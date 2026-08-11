from __future__ import annotations

import json
import logging
import os
import subprocess
import tempfile
from pathlib import Path
from typing import Any, Dict, List

from groq import Groq

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)


def _extract_audio(video_path: str, output_wav_path: str) -> None:
    command = [
        "ffmpeg",
        "-y",
        "-i",
        video_path,
        "-vn",
        "-acodec",
        "pcm_s16le",
        "-ar",
        "16000",
        "-ac",
        "1",
        output_wav_path,
    ]
    logger.info("Извлечение аудио из %s в %s", video_path, output_wav_path)
    result = subprocess.run(command, capture_output=True, text=True)
    if result.returncode != 0:
        logger.error("Ошибка FFmpeg при извлечении аудио: %s", result.stderr.strip())
        raise RuntimeError("Ошибка извлечения аудио")


def transcribe_audio(video_path: str) -> Dict[str, Any]:
    video_file = Path(video_path)
    if not video_file.exists():
        logger.error("Файл не найден: %s", video_path)
        raise FileNotFoundError(video_path)

    groq_api_key = os.getenv("GROQ_API_KEY")

    # 1. Обработка через Groq API (0% CPU / RAM сервера)
    if groq_api_key and not groq_api_key.startswith("YOUR_"):
        logger.info("Запуск распознавания через Groq API (whisper-large-v3-turbo)...")
        with tempfile.TemporaryDirectory(prefix="audio_extract_") as tmpdir:
            wav_path = Path(tmpdir) / "audio.wav"
            _extract_audio(str(video_file), str(wav_path))

            client = Groq(api_key=groq_api_key)
            with open(wav_path, "rb") as f:
                transcription = client.audio.transcriptions.create(
                    file=(wav_path.name, f.read()),
                    model="whisper-large-v3-turbo",
                    response_format="verbose_json",
                    timestamp_granularities=["word"],
                )

            words: List[Dict[str, Any]] = []
            raw_words = getattr(transcription, "words", []) or []
            for w in raw_words:
                word_txt = w.get("word") if isinstance(w, dict) else getattr(w, "word", "")
                w_start = w.get("start") if isinstance(w, dict) else getattr(w, "start", 0.0)
                w_end = w.get("end") if isinstance(w, dict) else getattr(w, "end", 0.0)
                if word_txt:
                    words.append({
                        "word": str(word_txt).strip(),
                        "start": float(w_start),
                        "end": float(w_end),
                    })

            full_text = getattr(transcription, "text", "") or " ".join(item["word"] for item in words)
            return {"full_text": full_text, "words": words}

    # 2. Локальная обработка через faster-whisper (tiny)
    logger.info("Groq API недоступен. Загрузка локальной модели 'tiny'...")
    try:
        from faster_whisper import WhisperModel
    except ImportError:
        raise RuntimeError("Пакет faster-whisper не установлен.")

    model = WhisperModel("tiny", device="cpu", compute_type="int8")

    with tempfile.TemporaryDirectory(prefix="whisper_transcribe_") as tmpdir:
        wav_path = Path(tmpdir) / "audio.wav"
        _extract_audio(str(video_file), str(wav_path))

        segments, _ = model.transcribe(str(wav_path), word_timestamps=True)
        words = []
        for segment in segments:
            for word_obj in getattr(segment, "words", []) or []:
                word = getattr(word_obj, "word", None)
                if word:
                    words.append({
                        "word": str(word).strip(),
                        "start": float(getattr(word_obj, "start", 0.0)),
                        "end": float(getattr(word_obj, "end", 0.0)),
                    })

        full_text = " ".join(item["word"] for item in words)
        return {"full_text": full_text, "words": words}