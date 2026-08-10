from __future__ import annotations

import json
import logging
import os
import tempfile
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

from aiogram import Bot, Dispatcher, types
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import Command
from aiogram.types import ContentType, FSInputFile, InlineKeyboardButton, InlineKeyboardMarkup, WebAppInfo
from dotenv import load_dotenv

import db
from llm_cutter import get_cut_plan
from preset_templates import PRESET_TEMPLATES
from subtitle_generator import generate_tscaps_transcript
from transcriber import transcribe_audio
from video_processor import probe_media_duration, render_final_video

load_dotenv(dotenv_path=Path(__file__).with_name('.env'))

BOT_TOKEN = os.getenv("BOT_TOKEN") or "YOUR_BOT_TOKEN"
GROQ_API_KEY = os.getenv("GROQ_API_KEY")
WEBAPP_BASE_URL = os.getenv("WEBAPP_BASE_URL", "")
TMP_ROOT = Path("tmp")

TMP_ROOT.mkdir(parents=True, exist_ok=True)

logger = logging.getLogger(__name__)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)

bot = Bot(token=BOT_TOKEN) if not BOT_TOKEN.startswith("YOUR_") else None
dp = Dispatcher()


def get_all_presets() -> Dict[str, Dict[str, str]]:
    """Собирает список пресетов из PRESET_TEMPLATES и сканирует папку templates/."""
    presets = dict(PRESET_TEMPLATES)
    templates_dir = Path(__file__).parent / "templates"

    if templates_dir.exists():
        for folder in templates_dir.iterdir():
            if folder.is_dir() and not folder.name.startswith("."):
                preset_key = folder.name
                if preset_key not in presets:
                    title = preset_key.replace("_", " ").title()
                    presets[preset_key] = {"name": title}

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

    # Секция 1: Пресеты (по 2 в ряд)
    preset_buttons: List[InlineKeyboardButton] = []
    for preset_key, tmpl in all_presets.items():
        is_active = current_preset == preset_key
        prefix = "✅ " if is_active else ""
        label = f"{prefix}{tmpl.get('name', preset_key)}"
        preset_buttons.append(
            InlineKeyboardButton(text=label, callback_data=f"preset:{preset_key}")
        )
    rows.extend([preset_buttons[i : i + 2] for i in range(0, len(preset_buttons), 2)])

    # Секция 2: Позиция по вертикали
    rows.append([InlineKeyboardButton(text="--- Позиция по вертикали ---", callback_data="noop")])
    pos_options = [
        ("⬆️ Сверху", 0.2),
        ("🎯 По центру", 0.5),
        ("⬇️ Снизу", 0.8),
    ]
    pos_row = []
    for text, val in pos_options:
        is_active = abs(current_v_offset - val) < 0.05
        prefix = "✅ " if is_active else ""
        pos_row.append(InlineKeyboardButton(text=f"{prefix}{text}", callback_data=f"pos:{val}"))
    rows.append(pos_row)

    # Секция 3: Позиция по горизонтали
    rows.append([InlineKeyboardButton(text="--- Выравнивание по горизонтали ---", callback_data="noop")])
    halign_options = [
        ("⬅️ Слева", "left"),
        ("⏺️ По центру", "center"),
        ("➡️ Справа", "right"),
    ]
    halign_row = []
    for text, val in halign_options:
        is_active = current_h_align == val
        prefix = "✅ " if is_active else ""
        halign_row.append(InlineKeyboardButton(text=f"{prefix}{text}", callback_data=f"halign:{val}"))
    rows.append(halign_row)

    # Секция 4: Размер шрифта
    rows.append([InlineKeyboardButton(text="--- Размер шрифта ---", callback_data="noop")])
    size_options = [
        ("🔍 Мелкий", "2.8cqh"),
        ("🔤 Средний", "4.8cqh"),
        ("💥 Крупный", "6.8cqh"),
    ]
    size_row = []
    for text, val in size_options:
        is_active = current_font_size == val
        prefix = "✅ " if is_active else ""
        size_row.append(InlineKeyboardButton(text=f"{prefix}{text}", callback_data=f"size:{val}"))
    rows.append(size_row)

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
    all_presets = get_all_presets()
    preset_label = all_presets.get(current_key, {}).get("name", current_key)
    
    v_offset = float(settings.get("v_offset", 0.8))
    v_pos_label = "Сверху" if v_offset < 0.35 else ("По центру" if v_offset < 0.65 else "Снизу")
    
    h_align = settings.get("h_align", "center")
    h_pos_label = "Слева" if h_align == "left" else ("Справа" if h_align == "right" else "По центру")
    
    font_size = settings.get("font_size", "4.8cqh")

    await message.answer(
        f"⚙️ **Текущие настройки:**\n"
        f"• Стиль: `{preset_label}`\n"
        f"• Вертикаль: `{v_pos_label}`\n"
        f"• Горизонталь: `{h_pos_label}`\n"
        f"• Размер: `{font_size}`\n\n"
        f"Нажмите на параметры ниже, чтобы изменить их:",
        reply_markup=keyboard,
        parse_mode="Markdown",
    )


@dp.callback_query(lambda callback: callback.data == "noop")
async def noop_callback(callback: types.CallbackQuery) -> None:
    await callback.answer()


@dp.callback_query(lambda callback: callback.data and callback.data.startswith("preset:"))
async def preset_callback(callback: types.CallbackQuery) -> None:
    preset_key = callback.data.split(":", 1)[1]
    all_presets = get_all_presets()

    if preset_key not in all_presets:
        await callback.answer("Неизвестный пресет")
        return

    db.update_user_settings(callback.from_user.id, {"preset": preset_key})
    preset_title = all_presets[preset_key].get("name", preset_key)

    try:
        await callback.message.edit_reply_markup(
            reply_markup=build_settings_keyboard(callback.from_user.id)
        )
    except TelegramBadRequest as exc:
        if "message is not modified" in str(exc):
            pass
        else:
            raise

    await callback.answer(f"Стиль изменен на: {preset_title}")


@dp.callback_query(lambda callback: callback.data and callback.data.startswith("pos:"))
async def position_callback(callback: types.CallbackQuery) -> None:
    val_str = callback.data.split(":", 1)[1]
    try:
        v_offset = float(val_str)
    except ValueError:
        await callback.answer("Неверное значение позиции")
        return

    db.update_user_settings(callback.from_user.id, {"v_offset": v_offset})
    
    try:
        await callback.message.edit_reply_markup(
            reply_markup=build_settings_keyboard(callback.from_user.id)
        )
    except TelegramBadRequest as exc:
        if "message is not modified" in str(exc):
            pass
        else:
            raise

    pos_name = "Сверху" if v_offset < 0.35 else ("По центру" if v_offset < 0.65 else "Снизу")
    await callback.answer(f"Вертикальная позиция: {pos_name}")


@dp.callback_query(lambda callback: callback.data and callback.data.startswith("halign:"))
async def halign_callback(callback: types.CallbackQuery) -> None:
    h_align = callback.data.split(":", 1)[1]
    if h_align not in ["left", "center", "right"]:
        await callback.answer("Неверное значение выравнивания")
        return

    db.update_user_settings(callback.from_user.id, {"h_align": h_align})

    try:
        await callback.message.edit_reply_markup(
            reply_markup=build_settings_keyboard(callback.from_user.id)
        )
    except TelegramBadRequest as exc:
        if "message is not modified" in str(exc):
            pass
        else:
            raise

    label = "Слева" if h_align == "left" else ("Справа" if h_align == "right" else "По центру")
    await callback.answer(f"Горизонтальное выравнивание: {label}")


@dp.callback_query(lambda callback: callback.data and callback.data.startswith("size:"))
async def size_callback(callback: types.CallbackQuery) -> None:
    font_size = callback.data.split(":", 1)[1]

    db.update_user_settings(callback.from_user.id, {"font_size": font_size})
    
    try:
        await callback.message.edit_reply_markup(
            reply_markup=build_settings_keyboard(callback.from_user.id)
        )
    except TelegramBadRequest as exc:
        if "message is not modified" in str(exc):
            pass
        else:
            raise

    await callback.answer(f"Размер шрифта установлен: {font_size}")


@dp.message(lambda message: message.content_type in [ContentType.VIDEO, ContentType.VIDEO_NOTE, ContentType.DOCUMENT])
async def video_handler(message: types.Message) -> None:
    if message.content_type == ContentType.DOCUMENT:
        if not message.document.mime_type or not message.document.mime_type.startswith("video/"):
            await message.answer("Пожалуйста, отправьте видеофайл.")
            return

    session_dir = Path(tempfile.mkdtemp(prefix="upload_", dir=TMP_ROOT))
    try:
        file_meta = message.video or message.video_note or message.document
        filename = _make_safe_filename(getattr(file_meta, "file_name", None) or "video.mp4")
        input_path = session_dir / filename

        status_msg = await message.answer("1/2 🎙️ Распознаем речь (Whisper STT)...")
        await message.bot.download(file_meta.file_id, destination=input_path)

        source_duration = probe_media_duration(input_path)
        whisper_data = transcribe_audio(str(input_path))
        words = whisper_data.get("words", [])

        await status_msg.edit_text("2/2 ✂️ Формируем монтажный план...")
        keep_segments: List[Dict[str, Any]] = []
        if GROQ_API_KEY and not GROQ_API_KEY.startswith("YOUR_"):
            try:
                keep_segments = get_cut_plan(whisper_data, GROQ_API_KEY)
            except Exception as exc:
                logger.warning("Ошибка генерации плана обрезки: %s", exc)

        if not keep_segments:
            keep_segments = [{"start": 0.0, "end": max(1.0, source_duration)}]

        # Создаем сессию в Supabase для Mini App
        session_id = db.create_session(
            chat_id=message.from_user.id,
            input_path=str(input_path),
            session_dir=str(session_dir),
            transcript=words,
            keep_segments=keep_segments
        )

        webapp_url = f"{WEBAPP_BASE_URL}/editor?session_id={session_id}"

        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="✏️ Открыть редактор субтитров", web_app=WebAppInfo(url=webapp_url))]
        ])

        await status_msg.edit_text(
            "✅ Видео обработано! Нажмите кнопку ниже, чтобы отредактировать текст, стили и тайминги в Mini App:",
            reply_markup=keyboard
        )

    except Exception as exc:
        logger.exception("Ошибка при обработке видео: %s", exc)
        await message.answer(f"Произошла ошибка при обработке: {exc}")


if __name__ == "__main__":
    if bot is None:
        logger.error("BOT_TOKEN не настроен в .env файле.")
        raise SystemExit(1)
    dp.run_polling(bot)