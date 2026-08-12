from __future__ import annotations

import asyncio
import json
import logging
import os
import subprocess
import tempfile
import traceback
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

from aiogram import Bot, Dispatcher, types
from aiogram.exceptions import TelegramBadRequest, TelegramRetryAfter
from aiogram.filters import Command
from aiogram.types import ContentType, InlineKeyboardButton, InlineKeyboardMarkup, WebAppInfo
from dotenv import load_dotenv

import db
from llm_cutter import get_cut_plan
from preset_templates import PRESET_TEMPLATES
from transcriber import transcribe_audio

# Безопасный импорт video_processor с подробным логированием ошибки
try:
    import video_processor
except Exception as err:
    logging.error("КРИТИЧЕСКАЯ ОШИБКА: Не удалось импортировать video_processor в bot.py:\n%s", traceback.format_exc())
    video_processor = None

load_dotenv(dotenv_path=Path(__file__).with_name('.env'))

BOT_TOKEN = os.getenv("BOT_TOKEN") or "YOUR_BOT_TOKEN"
GROQ_API_KEY = os.getenv("GROQ_API_KEY")

# Гарантируем корректный HTTPS URL для Telegram WebApp
raw_webapp_url = os.getenv("WEBAPP_BASE_URL", "https://banger-cut.onrender.com").strip().rstrip("/")
if raw_webapp_url and not raw_webapp_url.startswith("http"):
    WEBAPP_BASE_URL = f"https://{raw_webapp_url}"
else:
    WEBAPP_BASE_URL = raw_webapp_url or "https://banger-cut.onrender.com"

TMP_ROOT = Path("tmp")
TMP_ROOT.mkdir(parents=True, exist_ok=True)

logger = logging.getLogger(__name__)

bot = Bot(token=BOT_TOKEN) if not BOT_TOKEN.startswith("YOUR_") else None
dp = Dispatcher()

# Очередь для фоновой обработки видео
video_queue: asyncio.Queue = asyncio.Queue()
_worker_task: Optional[asyncio.Task] = None


async def safe_edit_status(message: types.Message, text: str, reply_markup: Optional[InlineKeyboardMarkup] = None) -> None:
    """Безопасное обновление статусного сообщения с защитой от лимитов Telegram."""
    try:
        await message.edit_text(text, reply_markup=reply_markup, parse_mode="Markdown")
        await asyncio.sleep(0.5)
    except TelegramRetryAfter as e:
        await asyncio.sleep(e.retry_after)
        try:
            await message.edit_text(text, reply_markup=reply_markup, parse_mode="Markdown")
        except Exception:
            pass
    except Exception as exc:
        logger.warning("Не удалось обновить статусное сообщение: %s", exc)


def get_all_presets() -> Dict[str, Dict[str, str]]:
    presets = dict(PRESET_TEMPLATES)
    templates_dir = Path(__file__).parent / "templates"
    if templates_dir.exists():
        for folder in templates_dir.iterdir():
            if folder.is_dir() and not folder.name.startswith("."):
                preset_key = folder.name
                if preset_key not in presets:
                    presets[preset_key] = {"name": preset_key.replace("_", " ").title()}
    return presets


def _make_safe_filename(name: Optional[str]) -> str:
    raw_name = (name or "").strip()
    basename = Path(raw_name).name if raw_name else ""
    if not basename:
        basename = "video.mp4"
    if not basename.lower().endswith((".mp4", ".mov", ".mkv", ".avi", ".webm", ".3gp", ".m4v")):
        basename += ".mp4"
    return basename


def build_settings_keyboard(chat_id: Union[int, str]) -> InlineKeyboardMarkup:
    settings = db.get_user_settings(int(chat_id))
    current_preset = settings.get("preset", "milo")
    current_v_offset = float(settings.get("v_offset", 0.8))
    current_h_align = settings.get("h_align", "center")
    current_font_size = settings.get("font_size", "4.8cqh")
    all_presets = get_all_presets()

    rows: List[List[InlineKeyboardButton]] = []

    preset_buttons: List[InlineKeyboardButton] = []
    for preset_key, tmpl in all_presets.items():
        prefix = "✅ " if current_preset == preset_key else ""
        label = f"{prefix}{tmpl.get('name', preset_key)}"
        preset_buttons.append(InlineKeyboardButton(text=label, callback_data=f"preset:{preset_key}"))
    rows.extend([preset_buttons[i : i + 2] for i in range(0, len(preset_buttons), 2)])

    rows.append([InlineKeyboardButton(text="--- Позиция по вертикали ---", callback_data="noop")])
    pos_options = [("⬆️ Сверху", 0.2), ("🎯 По центру", 0.5), ("⬇️ Снизу", 0.8)]
    rows.append([
        InlineKeyboardButton(
            text=f"{'✅ ' if abs(current_v_offset - val) < 0.05 else ''}{text}",
            callback_data=f"pos:{val}"
        ) for text, val in pos_options
    ])

    rows.append([InlineKeyboardButton(text="--- Выравнивание по горизонтали ---", callback_data="noop")])
    halign_options = [("⬅️ Слева", "left"), ("⏺️ По центру", "center"), ("➡️ Справа", "right")]
    rows.append([
        InlineKeyboardButton(
            text=f"{'✅ ' if current_h_align == val else ''}{text}",
            callback_data=f"halign:{val}"
        ) for text, val in halign_options
    ])

    rows.append([InlineKeyboardButton(text="--- Размер шрифта ---", callback_data="noop")])
    size_options = [("🔍 Мелкий", "2.8cqh"), ("🔤 Средний", "4.8cqh"), ("💥 Крупный", "6.8cqh")]
    rows.append([
        InlineKeyboardButton(
            text=f"{'✅ ' if current_font_size == val else ''}{text}",
            callback_data=f"size:{val}"
        ) for text, val in size_options
    ])

    return InlineKeyboardMarkup(inline_keyboard=rows)


@dp.message(Command(commands=["start"]))
async def start_handler(message: types.Message) -> None:
    await message.answer(
        "Привет! Отправь мне видео, и я смонтирую ролик со стильными субтитрами.\n"
        "Настроить стиль, позицию и размер можно через команду /settings."
    )


@dp.message(Command(commands=["settings"]))
async def settings_handler(message: types.Message) -> None:
    keyboard = build_settings_keyboard(message.from_user.id)
    settings = db.get_user_settings(message.from_user.id)
    current_key = settings.get("preset", "milo")
    preset_label = get_all_presets().get(current_key, {}).get("name", current_key)
    
    await message.answer(
        f"⚙️ **Текущие настройки:**\n"
        f"• Стиль: `{preset_label}`\n"
        f"• Размер: `{settings.get('font_size', '4.8cqh')}`\n\n"
        f"Выберите параметры для изменения:",
        reply_markup=keyboard,
        parse_mode="Markdown",
    )


@dp.callback_query(lambda callback: callback.data == "noop")
async def noop_callback(callback: types.CallbackQuery) -> None:
    await callback.answer()


@dp.callback_query(lambda callback: callback.data and callback.data.startswith(("preset:", "pos:", "halign:", "size:")))
async def settings_callback_handler(callback: types.CallbackQuery) -> None:
    data = callback.data
    user_id = callback.from_user.id

    if data.startswith("preset:"):
        key = data.split(":", 1)[1]
        db.update_user_settings(user_id, {"preset": key})
    elif data.startswith("pos:"):
        db.update_user_settings(user_id, {"v_offset": float(data.split(":", 1)[1])})
    elif data.startswith("halign:"):
        db.update_user_settings(user_id, {"h_align": data.split(":", 1)[1]})
    elif data.startswith("size:"):
        db.update_user_settings(user_id, {"font_size": data.split(":", 1)[1]})

    try:
        await callback.message.edit_reply_markup(reply_markup=build_settings_keyboard(user_id))
    except TelegramBadRequest:
        pass
    await callback.answer("Настройки обновлены!")


async def _process_single_video(task: dict) -> None:
    message: types.Message = task["message"]
    status_msg: types.Message = task["status_msg"]

    session_dir = Path(tempfile.mkdtemp(prefix="upload_", dir=TMP_ROOT))
    try:
        file_meta = message.video or message.video_note or message.document
        filename = _make_safe_filename(getattr(file_meta, "file_name", None) or "video.mp4")
        raw_input_path = session_dir / filename

        await safe_edit_status(status_msg, "1/3 📥 Загружаем и оптимизируем видео...")
        await message.bot.download(file_meta.file_id, destination=raw_input_path)

        converted_mp4 = session_dir / "converted_input.mp4"
        conv_cmd = [
            "ffmpeg", "-y", "-threads", "1",
            "-i", str(raw_input_path),
            "-vcodec", "libx264",
            "-crf", "26",
            "-preset", "ultrafast",
            "-acodec", "aac",
            "-b:a", "128k",
            str(converted_mp4)
        ]
        
        logger.info("Запуск конвертации медиафайла %s в MP4...", raw_input_path.name)
        conv_res = await asyncio.to_thread(
            subprocess.run, conv_cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True
        )

        if converted_mp4.exists() and converted_mp4.stat().st_size > 0:
            input_path = converted_mp4
            logger.info("Успешно сконвертировано в MP4.")
        else:
            logger.warning("Конвертация не удалась, используем исходный файл: %s", conv_res.stderr)
            input_path = raw_input_path

        await safe_edit_status(status_msg, "2/3 🎙️ Распознаем речь (Whisper STT)...")

        source_duration = video_processor.probe_media_duration(input_path) if video_processor else 10.0
        
        whisper_data = await asyncio.to_thread(transcribe_audio, str(input_path))
        words = whisper_data.get("words", [])

        await safe_edit_status(status_msg, "2/3 ✂️ Формируем монтажный план...")
        keep_segments: List[Dict[str, Any]] = []
        if GROQ_API_KEY and not GROQ_API_KEY.startswith("YOUR_"):
            try:
                keep_segments = await asyncio.to_thread(get_cut_plan, whisper_data, GROQ_API_KEY)
            except Exception as exc:
                logger.warning("Ошибка генерации плана обрезки: %s", exc)

        if not keep_segments:
            keep_segments = [{"start": 0.0, "end": max(1.0, source_duration)}]

        session_id = db.create_session(
            chat_id=message.from_user.id,
            input_path=str(input_path),
            session_dir=str(session_dir),
            transcript=words,
            keep_segments=keep_segments,
        )

        await safe_edit_status(status_msg, "3/3 🎨 Подготавливаем редактор субтитров...")

        if video_processor and hasattr(video_processor, "generate_preview_draft"):
            try:
                preview_path = await asyncio.to_thread(video_processor.generate_preview_draft, session_id)
                if preview_path and Path(preview_path).exists():
                    update_data = {"preview_path": str(preview_path)}
                    if hasattr(db, "update_session"):
                        db.update_session(session_id, update_data)
                    elif hasattr(db, "supabase"):
                        db.supabase.table("sessions").update(update_data).eq("id", session_id).execute()
            except Exception as exc:
                logger.warning("Не удалось сгенерировать превью сессии %s: %s", session_id, exc)

        webapp_url = f"{WEBAPP_BASE_URL}/editor?session_id={session_id}"
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="✏️ Открыть редактор субтитров", web_app=WebAppInfo(url=webapp_url))]
        ])

        await safe_edit_status(
            status_msg,
            "✅ **Видео обработано!**\nНажмите кнопку ниже, чтобы отредактировать текст и стили в Mini App:",
            reply_markup=keyboard,
        )

    except Exception as exc:
        logger.exception("Ошибка обработки видео: %s", exc)
        await safe_edit_status(status_msg, f"❌ Произошла ошибка при обработке: {exc}")


async def process_queue_worker() -> None:
    """Обрабатывает входящие видео по очереди."""
    logger.info("⚡ Воркер обработки очереди видео запущен и готов к работе.")
    while True:
        task = await video_queue.get()
        try:
            logger.info("Воркер взял задачу из очереди...")
            await _process_single_video(task)
        except Exception as exc:
            logger.error("Ошибка в фоновом воркере: %s", exc)
        finally:
            video_queue.task_done()


def ensure_worker_running():
    """Гарантирует запуск фоновой задачи воркера в активном событийном цикле."""
    global _worker_task
    if _worker_task is None or _worker_task.done():
        logger.info("Запуск фоновой задачи process_queue_worker...")
        _worker_task = asyncio.create_task(process_queue_worker())


@dp.startup()
async def on_startup():
    ensure_worker_running()


@dp.message(lambda message: message.content_type in [ContentType.VIDEO, ContentType.VIDEO_NOTE, ContentType.DOCUMENT])
async def video_handler(message: types.Message) -> None:
    ensure_worker_running()

    if message.content_type == ContentType.DOCUMENT:
        if not message.document.mime_type or not message.document.mime_type.startswith("video/"):
            await message.answer("Пожалуйста, отправьте видеофайл.")
            return

    q_size = video_queue.qsize()
    status_msg = await message.answer(
        f"⏳ Видео добавлено в очередь (Ваша позиция: {q_size + 1}).\n"
        f"Пожалуйста, подождите..."
    )

    await video_queue.put({"message": message, "status_msg": status_msg})