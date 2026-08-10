from __future__ import annotations

import logging
import subprocess
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


def probe_media_duration(file_path: str | Path) -> float:
    """Возвращает длительность медиафайла в секундах через ffprobe."""
    file_path = Path(file_path).resolve()
    cmd = [
        "ffprobe",
        "-v", "error",
        "-show_entries", "format=duration",
        "-of", "default=noprint_wrappers=1:nokey=1",
        str(file_path),
    ]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, check=True)
        return float(result.stdout.strip())
    except Exception as exc:
        logger.error("Ошибка при получении длительности файла %s: %s", file_path, exc)
        return 0.0


def trim_video_by_segments(
    input_video: Path,
    output_trimmed_video: Path,
    keep_segments: List[Dict[str, Any]]
) -> Path:
    """Вырезает паузы и склеивает оставшиеся сегменты с помощью FFmpeg filter_complex."""
    if not keep_segments:
        return input_video

    filter_chains = []
    concat_inputs = []

    for i, seg in enumerate(keep_segments):
        start = float(seg["start"])
        end = float(seg["end"])
        filter_chains.append(
            f"[0:v]trim=start={start}:end={end},setpts=PTS-STARTPTS[v{i}];"
            f"[0:a]atrim=start={start}:end={end},asetpts=PTS-STARTPTS[a{i}]"
        )
        concat_inputs.append(f"[v{i}][a{i}]")

    filter_complex = (
        ";".join(filter_chains) + ";" +
        "".join(concat_inputs) +
        f"concat=n={len(keep_segments)}:v=1:a=1[outv][outa]"
    )

    cmd = [
        "ffmpeg", "-y",
        "-i", str(input_video),
        "-filter_complex", filter_complex,
        "-map", "[outv]",
        "-map", "[outa]",
        "-c:v", "libx264",
        "-preset", "fast",
        "-crf", "18",
        "-c:a", "aac",
        str(output_trimmed_video)
    ]

    logger.info("Запуск пред-обрезки видео по %d сегментам...", len(keep_segments))
    result = subprocess.run(cmd, capture_output=True, text=True)

    if result.returncode != 0:
        logger.error("Ошибка FFmpeg при обрезке: %s", result.stderr)
        raise RuntimeError(f"FFmpeg trim failed: {result.stderr}")

    return output_trimmed_video


def render_final_video(
    input_video: str | Path,
    subtitles_path: str | Path,
    output_video: str | Path,
    preset_name: str = "milo",
    font_size: Optional[str] = None,
    v_offset: Optional[float | str] = None,
    h_align: Optional[str] = None,
    keep_segments: Optional[List[Dict[str, Any]]] = None,
    **kwargs,
) -> Path:
    """Рендерит итоговое видео с наложением tscaps субтитров через Headless Chrome (render_worker.js)."""
    input_path = Path(input_video).resolve()
    subtitles_json_path = Path(subtitles_path).resolve()
    output_path = Path(output_video).resolve()

    if not input_path.exists():
        raise FileNotFoundError(f"Исходное видео не найдено: {input_path}")
    if not subtitles_json_path.exists():
        raise FileNotFoundError(f"Файл транскрипта не найден: {subtitles_json_path}")

    output_path.parent.mkdir(parents=True, exist_ok=True)
    worker_script = Path(__file__).parent / "render_worker.js"

    if not worker_script.exists():
        raise FileNotFoundError(f"Скрипт рендеринга Node.js не найден по пути: {worker_script}")

    # Предварительная обрезка тишины, если передан список сегментов
    video_for_rendering = input_path
    source_duration = probe_media_duration(input_path)

    if keep_segments and len(keep_segments) > 0:
        is_full_video = (
            len(keep_segments) == 1 and
            abs(keep_segments[0].get("start", 0.0)) < 0.1 and
            abs(keep_segments[0].get("end", source_duration) - source_duration) < 0.2
        )
        if not is_full_video:
            trimmed_path = input_path.parent / f"{input_path.stem}_trimmed.mp4"
            video_for_rendering = trim_video_by_segments(input_path, trimmed_path, keep_segments)

    cmd = [
        "node",
        str(worker_script),
        "--input", str(video_for_rendering),
        "--transcript", str(subtitles_json_path),
        "--preset", preset_name,
        "--output", str(output_path),
    ]

    if font_size:
        cmd.extend(["--font-size", str(font_size)])
    if v_offset is not None:
        cmd.extend(["--v-offset", str(v_offset)])
    if h_align:
        cmd.extend(["--h-align", str(h_align)])

    logger.info("Запуск Node.js рендерера: %s", " ".join(cmd))
    result = subprocess.run(cmd, capture_output=True, text=True)

    if result.stdout.strip():
        logger.info("Node.js stdout:\n%s", result.stdout.strip())
    if result.stderr.strip():
        logger.warning("Node.js stderr:\n%s", result.stderr.strip())

    if result.returncode != 0:
        raise RuntimeError(f"Рендерер завершился с ошибкой (code {result.returncode}):\n{result.stderr}")

    if not output_path.exists() or output_path.stat().st_size == 0:
        raise RuntimeError(f"Итоговый файл не был создан: {output_path}")

    logger.info("Видео сгенерировано через Puppeteer. Размер: %d байт", output_path.stat().st_size)
    return output_path