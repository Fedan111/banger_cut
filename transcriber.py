import json
import logging
import subprocess
import tempfile
from pathlib import Path
from typing import Any, Dict, List

try:
    from faster_whisper import WhisperModel
except ImportError:  # pragma: no cover
    WhisperModel = None

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

_MODEL = None


def _ensure_model() -> Any:
    global _MODEL
    if WhisperModel is None:
        logger.error("faster-whisper is not installed. Install it with `pip install faster-whisper`.")
        raise RuntimeError("faster-whisper package is required")

    if _MODEL is None:
        logger.info("Loading Whisper model 'small' on device auto...")
        _MODEL = WhisperModel("small", device="auto", compute_type="default")
    return _MODEL


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
    logger.info("Extracting audio from %s to %s", video_path, output_wav_path)
    result = subprocess.run(command, capture_output=True, text=True)
    if result.returncode != 0:
        logger.error("ffmpeg audio extraction failed: %s", result.stderr.strip())
        raise RuntimeError("Audio extraction failed")
    logger.info("Audio extracted successfully")


def get_word_timestamps(video_path: str) -> List[Dict[str, Any]]:
    """Return word-level timestamps for the given video file."""
    video_file = Path(video_path)
    if not video_file.exists():
        logger.error("Input file does not exist: %s", video_path)
        raise FileNotFoundError(video_path)

    model = _ensure_model()

    with tempfile.TemporaryDirectory(prefix="whisper_transcribe_") as tmpdir:
        wav_path = Path(tmpdir) / "audio.wav"
        _extract_audio(str(video_file), str(wav_path))

        logger.info("Starting transcription for %s", wav_path)
        segments, info = model.transcribe(str(wav_path), word_timestamps=True, task="transcribe", language=None)
        segments_list = list(segments)
        logger.info(
            "Transcription complete: language=%s, duration=%.2fs, segments=%d",
            info.language,
            info.duration,
            len(segments_list),
        )

        words: List[Dict[str, Any]] = []
        for segment in segments_list:
            for word_obj in getattr(segment, "words", []) or []:
                word = getattr(word_obj, "word", None) or getattr(word_obj, "text", None)
                if word is None:
                    continue
                words.append(
                    {
                        "word": str(word).strip(),
                        "start": float(getattr(word_obj, "start", 0.0)),
                        "end": float(getattr(word_obj, "end", 0.0)),
                    }
                )

        logger.info("Collected %d words from transcription", len(words))
        return words


def transcribe_audio(video_path: str) -> Dict[str, Any]:
    words = get_word_timestamps(video_path)
    full_text = " ".join(item["word"] for item in words if item.get("word"))
    return {"full_text": full_text, "words": words}


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Transcribe video audio with faster-whisper and word-level timestamps.")
    parser.add_argument("video_path", help="Path to the input video file")
    parser.add_argument("--output", help="Optional path to write JSON output")
    args = parser.parse_args()

    try:
        result = transcribe_audio(args.video_path)
        if args.output:
            output_file = Path(args.output)
            output_file.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
            logger.info("Saved transcription JSON to %s", output_file)
        else:
            print(json.dumps(result, ensure_ascii=False, indent=2))
    except Exception as exc:
        logger.exception("Transcription failed: %s", exc)
        raise
