from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

DEFAULT_PRESET = "milo"


def _filter_and_align_words(
    words: List[Dict[str, Any]], 
    segments: List[Dict[str, float]]
) -> List[Dict[str, Any]]:
    """Фильтрует слова по отрезкам монтажа и пересчитывает их тайминги от 0.0 секунд."""
    kept_words = []
    cumulative_offset = 0.0
    sorted_segments = sorted(segments, key=lambda s: float(s["start"]))

    for segment in sorted_segments:
        seg_start = float(segment["start"])
        seg_end = float(segment["end"])
        seg_duration = seg_end - seg_start

        for word in words:
            w_start = float(word.get("start", 0.0))
            w_end = float(word.get("end", 0.0))
            w_text = str(word.get("word", "")).strip()

            if not w_text:
                continue

            # Проверяем попадание слова в текущий сегмент
            if w_end > seg_start and w_start < seg_end:
                adj_start = cumulative_offset + max(0.0, w_start - seg_start)
                adj_end = cumulative_offset + max(0.0, min(w_end, seg_end) - seg_start)
                if adj_end > adj_start:
                    kept_words.append({
                        "word": w_text,
                        "start": round(adj_start, 3),
                        "end": round(adj_end, 3),
                    })
        cumulative_offset += seg_duration

    return kept_words


def generate_tscaps_transcript(
    whisper_words: List[Dict[str, Any]],
    keep_segments: List[Dict[str, Any]],
    output_json_path: str,
    user_settings: Optional[Dict[str, Any]] = None,
) -> str:
    """Генерирует JSON-транскрипт с выровненными таймингами для движка tscaps."""
    filtered_words = _filter_and_align_words(whisper_words, keep_segments)
    
    out_file = Path(output_json_path)
    if out_file.suffix.lower() != ".json":
        out_file = out_file.with_suffix(".json")
    out_file.parent.mkdir(parents=True, exist_ok=True)

    transcript_data = {
        "words": filtered_words
    }

    with open(out_file, "w", encoding="utf-8") as f:
        json.dump(transcript_data, f, ensure_ascii=False, indent=2)

    logger.info("Успешно сгенерирован JSON-транскрипт tscaps: %s (слов: %d)", out_file, len(filtered_words))
    return str(out_file)


# Совместимость со старым API
def generate_pycaps_subtitles(*args, **kwargs) -> str:
    return generate_tscaps_transcript(*args, **kwargs)

def render_subtitles(*args, **kwargs) -> str:
    return generate_tscaps_transcript(*args, **kwargs)