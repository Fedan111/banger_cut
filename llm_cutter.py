import json
import logging
from typing import Any, Dict, List

try:
    from groq import Groq
except ImportError:  # pragma: no cover
    Groq = None

logger = logging.getLogger(__name__)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)

SYSTEM_PROMPT = (
    "Ты — профессиональный видеомонтажер. Твоя задача — удалить паузы, повторы, оговорки и мусор, "
    "оставив только лучшие и логичные фрагменты речи. Верни только JSON-массив объектов вида "
    "[{\"start\": float, \"end\": float}]."
)


def _ensure_client(api_key: str) -> Any:
    if Groq is None:
        logger.error("groq SDK is not installed. Install it with `pip install groq`.")
        raise RuntimeError("groq SDK is required")
    return Groq(api_key=api_key)


def _normalize_whisper_data(whisper_data: Dict[str, Any]) -> Dict[str, Any]:
    if not isinstance(whisper_data, dict):
        raise ValueError("whisper_data must be a dict")
    words = whisper_data.get("words") or []
    if not isinstance(words, list):
        raise ValueError("whisper_data['words'] must be a list")

    normalized = []
    for item in words:
        if not isinstance(item, dict):
            continue
        normalized.append(
            {
                "word": str(item.get("word", "")).strip(),
                "start": float(item.get("start", 0.0)),
                "end": float(item.get("end", 0.0)),
            }
        )
    return {"words": normalized}


def _validate_segments(raw_segments: Any) -> List[Dict[str, float]]:
    if not isinstance(raw_segments, list):
        raise ValueError("Expected a JSON array of segments")

    validated: List[Dict[str, float]] = []
    for segment in raw_segments:
        if not isinstance(segment, dict):
            continue
        start = float(segment.get("start", 0.0))
        end = float(segment.get("end", 0.0))
        if end > start:
            validated.append({"start": start, "end": end})
    return validated


def get_cut_plan(whisper_data: Dict[str, Any], api_key: str) -> List[Dict[str, float]]:
    """Ask Groq to return clean keep segments from the whisper word timestamps."""
    normalized_data = _normalize_whisper_data(whisper_data)
    client = _ensure_client(api_key)

    prompt = (
        "Проанализируй следующие слова с таймкодами и верни только JSON-массив отрезков. "
        "Удали паузы, повторы, мусор и слабые фрагменты.\n"
        f"{json.dumps(normalized_data, ensure_ascii=False, indent=2)}"
    )

    logger.info("Requesting cut plan from Groq")
    response = client.chat.completions.create(
        model="llama-3.3-70b-versatile",
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": prompt},
        ],
        temperature=0.1,
    )

    content = response.choices[0].message.content
    if not content:
        raise ValueError("Groq returned an empty response")

    try:
        parsed = json.loads(content)
    except json.JSONDecodeError as exc:
        logger.error("Failed to decode Groq JSON response: %s", content)
        raise ValueError("Groq returned invalid JSON") from exc

    segments = _validate_segments(parsed)
    logger.info("Received %d validated keep segments", len(segments))
    return segments
