import asyncio
import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, Dict

from aiogram import types
from fastapi import FastAPI, HTTPException, BackgroundTasks, Response
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

import db
from bot import bot, dp, process_queue_worker

try:
    import video_processor
except ImportError:
    video_processor = None

logging.basicConfig(level=logging.INFO)

BOT_TOKEN = os.getenv("BOT_TOKEN")
RENDER_EXTERNAL_URL = os.getenv("RENDER_EXTERNAL_URL")

WEBHOOK_PATH = f"/webhook/{BOT_TOKEN}"
WEBHOOK_URL = f"{RENDER_EXTERNAL_URL}{WEBHOOK_PATH}"

BASE_DIR = Path(__file__).parent


@asynccontextmanager
async def lifespan(app: FastAPI):
    logging.info(f"Регистрация вебхука на URL: {WEBHOOK_URL}")
    await bot.set_webhook(url=WEBHOOK_URL, drop_pending_updates=True)

    worker_task = asyncio.create_task(process_queue_worker())

    yield

    worker_task.cancel()


app = FastAPI(lifespan=lifespan)

WEB_DIR = BASE_DIR / "web"
if WEB_DIR.exists():
    app.mount("/static", StaticFiles(directory=WEB_DIR), name="static")


class UpdateSessionRequest(BaseModel):
    words: list[Dict[str, Any]]
    keep_segments: list[Dict[str, Any]]


@app.get("/")
@app.head("/")
async def root():
    return {"status": "ok", "bot": "Banger Cut"}


@app.get("/favicon.ico", include_in_schema=False)
async def favicon():
    return Response(status_code=204)


@app.get("/editor", response_class=HTMLResponse)
async def serve_editor():
    """Отдаёт Telegram Mini App."""
    html_path = WEB_DIR / "index.html"
    if html_path.exists():
        return FileResponse(html_path)
    return HTMLResponse("<h3>Ошибка: Файл web/index.html не найден на сервере.</h3>", status_code=404)


@app.get("/api/session/{session_id}")
async def get_session_api(session_id: str):
    """Возвращает данные сессии из Supabase для Mini App."""
    try:
        session = db.get_session(session_id) if hasattr(db, "get_session") else None
        if not session and hasattr(db, "supabase"):
            res = db.supabase.table("sessions").select("*").eq("id", session_id).execute()
            if res.data:
                session = res.data[0]

        if not session:
            raise HTTPException(status_code=404, detail="Сессия не найдена")

        return {
            "status": "ok",
            "session": session
        }
    except Exception as e:
        logging.error("Ошибка при получении сессии %s: %s", session_id, e)
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/session/{session_id}/video")
async def get_session_video(session_id: str):
    """Отдаёт видеофайл сессии для воспроизведения в Mini App."""
    try:
        session = db.get_session(session_id) if hasattr(db, "get_session") else None
        if not session and hasattr(db, "supabase"):
            res = db.supabase.table("sessions").select("*").eq("id", session_id).execute()
            if res.data:
                session = res.data[0]

        if not session or not session.get("input_path"):
            raise HTTPException(status_code=404, detail="Запись сессии не найдена")

        video_path = Path(session["input_path"])
        if not video_path.exists():
            raise HTTPException(status_code=404, detail="Файл видео не найден на сервере")

        return FileResponse(video_path, media_type="video/mp4")
    except Exception as e:
        logging.error("Ошибка при получении видео для сессии %s: %s", session_id, e)
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/session/{session_id}")
async def update_session_api(session_id: str, payload: UpdateSessionRequest, background_tasks: BackgroundTasks):
    """Сохраняет отредактированный транскрипт в Supabase и передает рендеринг в BackgroundTasks."""
    try:
        update_data = {
            "transcript": payload.words,
            "keep_segments": payload.keep_segments,
            "status": "edited"
        }

        if hasattr(db, "update_session"):
            db.update_session(session_id, update_data)
        elif hasattr(db, "supabase"):
            db.supabase.table("sessions").update(update_data).eq("id", session_id).execute()

        # Надежный запуск обработки видео в фоне через FastAPI BackgroundTasks
        if video_processor and hasattr(video_processor, "render_final_video_task"):
            background_tasks.add_task(video_processor.render_final_video_task, session_id)
            logging.info("Фоновая задача рендеринга для сессии %s добавлена в очередь.", session_id)
        else:
            logging.warning("Модуль video_processor или функция render_final_video_task не найдены.")

        return {"status": "ok", "message": "Сессия успешно обновлена, запущен рендеринг"}
    except Exception as e:
        logging.error("Ошибка при обновлении сессии %s: %s", session_id, e)
        raise HTTPException(status_code=500, detail=str(e))


@app.post(WEBHOOK_PATH)
async def bot_webhook(update: dict):
    telegram_update = types.Update(**update)
    await dp.feed_webhook_update(bot, telegram_update)
    return {"status": "ok"}