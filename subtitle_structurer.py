import json
import logging
import os
from typing import Any, Dict, List, Optional

try:
    from groq import Groq
except ImportError:  # pragma: no cover
    Groq = None

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")

DEFAULT_MODEL = "llama-3.3-70b-versatile"


def _normalize_whisper_data(whisper_data: Any) -> List[Dict[str, Any]]:
    if isinstance(whisper_data, dict):
        words = whisper_data.get("words") or whisper_data.get("segments") or []
    else:
        words = whisper_data

    if not isinstance(words, list):
        raise ValueError("whisper_data must contain a list of words")

    normalized: List[Dict[str, Any]] = []
    for index, item in enumerate(words):
        if not isinstance(item, dict):
            continue
        word = str(item.get("word", item.get("text", ""))).strip()
        if not word:
            continue
        start = float(item.get("start", 0.0))
        end_value = item.get("end")
        if end_value is None:
            end_value = item.get("timestamp")
        if end_value is None:
            end_value = start + 0.35
        end = float(end_value)
        if end < start:
            end = start + 0.35
        normalized.append({"index": index, "word": word, "start": start, "end": end})
    return normalized


def _build_lines_from_indices(words: List[Dict[str, Any]], word_indices: List[int], block_type: str) -> List[str]:
    selected_words = [
        words[index] for index in word_indices if isinstance(index, int) and 0 <= index < len(words)
    ]
    if not selected_words:
        return []

    if block_type == "single_word" or len(selected_words) == 1:
        return [selected_words[0]["word"]]

    max_chars = 14
    lines: List[str] = []
    current_line: List[str] = []
    for word in selected_words:
        candidate = " ".join(current_line + [word["word"]])
        if not current_line:
            current_line = [word["word"]]
            continue
        if len(candidate) <= max_chars and len(current_line) < 2:
            current_line.append(word["word"])
            continue
        lines.append(" ".join(current_line))
        current_line = [word["word"]]
        if len(lines) >= 2:
            break

    if current_line:
        lines.append(" ".join(current_line))

    return [line for line in lines if line][:2]


def _build_deterministic_blocks(words: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    if not words:
        return []

    blocks: List[Dict[str, Any]] = []
    current_indices: List[int] = []

    def flush_current() -> None:
        if not current_indices:
            return
        selected_words = [
            words[index] for index in current_indices if isinstance(index, int) and 0 <= index < len(words)
        ]
        if not selected_words:
            return
        if len(selected_words) == 1:
            block_type = "single_word"
        else:
            block_type = "standard"
        blocks.append(
            {
                "type": block_type,
                "word_indices": [word["index"] for word in selected_words],
                "lines": _build_lines_from_indices(words, [word["index"] for word in selected_words], block_type),
                "start": selected_words[0]["start"],
                "end": selected_words[-1]["end"],
            }
        )

    for word in words:
        if len(word["word"]) > 8:
            if current_indices:
                flush_current()
                current_indices = []
            blocks.append(
                {
                    "type": "single_word",
                    "word_indices": [word["index"]],
                    "lines": [word["word"]],
                    "start": word["start"],
                    "end": word["end"],
                }
            )
            continue

        if len(current_indices) >= 4:
            flush_current()
            current_indices = []

        current_indices.append(word["index"])

    if current_indices:
        flush_current()

    return blocks


def _validate_block_coverage(blocks: List[Dict[str, Any]], words: List[Dict[str, Any]]) -> bool:
    if not blocks:
        return not words

    collected_indices: List[int] = []
    for block in blocks:
        indices = block.get("word_indices") or []
        if not isinstance(indices, list):
            return False
        for idx in indices:
            if not isinstance(idx, int):
                return False
            collected_indices.append(idx)

    expected_indices = [word["index"] for word in words]
    return collected_indices == expected_indices


def structure_subtitles_from_whisper(
    whisper_data: Any,
    api_key: Optional[str] = None,
    model: str = DEFAULT_MODEL,
) -> List[Dict[str, Any]]:
    """Create subtitle blocks from Whisper words. Falls back to a deterministic heuristic when Groq is unavailable."""
    words = _normalize_whisper_data(whisper_data)
    if not words:
        return []

    api_key = api_key or os.getenv("GROQ_API_KEY")
    if api_key and Groq is not None:
        try:
            client = Groq(api_key=api_key)
            prompt = (
                "Ты — специалист по субтитрам. На основе слов Whisper с таймкодами разбей текст на блоки для ASS. "
                "Правила: первый блок должен быть типа 'hook' и содержать 3-4 строки; остальные блоки должны чередовать ритм речи. "
                "10-20% всех блоков ДОЛЖНЫ быть типа 'single_word' (ровно 1 слово в блоке, 1 строка). "
                "Запрещено генерировать только 2-3 строчные блоки подряд; чередуй single_word, standard и hook. "
                "Ограничение: максимум 10 символов на одну строку. Если слово длинное, оно должно идти отдельной строкой. "
                "Верни только JSON-массив в формате [{\"type\":\"hook\",\"word_indices\":[...],\"lines\":[...]}, ...]. "
                f"Слова: {json.dumps(words, ensure_ascii=False, indent=2)}"
            )
            response = client.chat.completions.create(
                model=model,
                messages=[
                    {"role": "system", "content": "Ты создаёшь структуру субтитров для коротких видео."},
                    {"role": "user", "content": prompt},
                ],
                temperature=0.1,
            )
            content = response.choices[0].message.content
            if content:
                parsed = json.loads(content)
                if isinstance(parsed, list):
                    normalized_blocks: List[Dict[str, Any]] = []
                    for block in parsed:
                        if not isinstance(block, dict):
                            continue
                        word_indices = block.get("word_indices") or []
                        if not isinstance(word_indices, list):
                            continue
                        lines = block.get("lines") or []
                        if not isinstance(lines, list):
                            lines = []
                        normalized_blocks.append(
                            {
                                "type": block.get("type", "standard"),
                                "word_indices": [int(idx) for idx in word_indices if isinstance(idx, int)],
                                "lines": [str(line) for line in lines if str(line).strip()],
                                "start": float(block.get("start", 0.0)),
                                "end": float(block.get("end", 0.0)),
                            }
                        )
                    if normalized_blocks:
                        return normalized_blocks
        except Exception as exc:  # pragma: no cover - network/API fallback
            logger.warning("Groq subtitle structuring failed, using heuristic fallback: %s", exc)

    heuristic_blocks = []
    for block in _fallback_blocks(words):
        block_type = block.get("type", "standard")
        word_indices = block.get("word_indices") or []
        lines = _build_lines_from_indices(words, word_indices, block_type)
        heuristic_blocks.append({**block, "lines": lines})
    return heuristic_blocks
