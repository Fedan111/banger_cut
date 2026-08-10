import argparse
import json
import logging
import os
import subprocess
import tempfile
from pathlib import Path
from typing import Any, Dict, List

from llm_cutter import get_cut_plan
from subtitle_generator import generate_pycaps_subtitles
from transcriber import get_word_timestamps
from video_processor import probe_media_duration, render_final_video

logger = logging.getLogger(__name__)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)


def _get_fallback_cut_plan(video_path: str, words: List[Dict[str, Any]]) -> List[Dict[str, float]]:
    duration = probe_media_duration(Path(video_path))
    if not words:
        return [{"start": 0.0, "end": max(1.0, duration)}]
    start = min(float(w.get("start", 0.0)) for w in words)
    end = max(float(w.get("end", 0.0)) for w in words)
    return [{"start": start, "end": max(end, duration)}]


def process_video_pipeline(
    input_video_path: str, 
    groq_api_key: str | None = None, 
    preset_style: str = "garmash_yellow"
) -> str:
    """Запуск пайплайна: Whisper STT -> LLM Cutter -> PyCaps Render -> FFmpeg."""
    input_path = Path(input_video_path)
    if not input_path.exists():
        raise FileNotFoundError(f"Файл не найден: {input_path}")

    tmp_root = Path("tmp")
    work_dir = Path(tempfile.mkdtemp(prefix="pipeline_", dir=str(tmp_root)))
    
    subtitles_path = work_dir / f"{input_path.stem}_subs.json"
    output_path = work_dir / f"{input_path.stem}_final.mp4"

    logger.info("Шаг 1/4: Распознавание речи через Whisper STT")
    words = get_word_timestamps(str(input_path))

    logger.info("Шаг 2/4: Вычисление монтажных отрезков (LLM Cut Plan)")
    resolved_api_key = groq_api_key or os.getenv("GROQ_API_KEY")
    try:
        keep_segments = get_cut_plan({"words": words}, resolved_api_key or "dummy")
    except Exception as exc:
        logger.warning("Ошибка генерации монтажного плана: %s. Используется оригинальная длина.", exc)
        keep_segments = _get_fallback_cut_plan(str(input_path), words)

    if not keep_segments:
        keep_segments = _get_fallback_cut_plan(str(input_path), words)

    logger.info("Шаг 3/4: Генерация субтитров через PyCaps (Без LLM)")
    generate_pycaps_subtitles(
        whisper_words=words,
        keep_segments=keep_segments,
        output_path=str(subtitles_path),
        user_settings={"preset": preset_style}
    )

    logger.info("Шаг 4/4: Сборка итогового видео через FFmpeg")
    render_final_video(
        str(input_path), 
        keep_segments, 
        str(subtitles_path), 
        str(output_path)
    )

    logger.info("Монтаж успешно завершен: %s", output_path)
    return str(output_path)


def main() -> None:
    parser = argparse.ArgumentParser(description="Автоматический монтаж с PyCaps субтитрами")
    parser.add_argument("input_video", help="Путь к исходному видео")
    parser.add_argument("output_video", nargs="?", default=None, help="Путь для сохранения")
    parser.add_argument("--preset", default="garmash_yellow", help="Стиль субтитров PyCaps")
    args = parser.parse_args()

    result_path = process_video_pipeline(args.input_video, preset_style=args.preset)
    print(json.dumps({"status": "success", "output_video": result_path}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()