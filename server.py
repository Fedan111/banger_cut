import os
import json
import logging
import asyncio
from pathlib import Path
from fastapi import FastAPI, HTTPException, Request
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse, FileResponse, JSONResponse
from pydantic import BaseModel, Field
from aiogram.types import Update

from bot import bot, dp, TMP_ROOT, ensure_worker_running
from video_processor import render_final_video
import db

logger = logging.getLogger(__name__)

app = FastAPI()

WEB_DIR = Path(__file__).parent / "web"
WEB_DIR.mkdir(exist_ok=True)

app.mount("/static", StaticFiles(directory=str(WEB_DIR)), name="static")
app.mount("/tmp_media", StaticFiles(directory=str(TMP_ROOT)), name="tmp_media")


@app.on_event("startup")
async def startup_event():
    ensure_worker_running()
    logger.info("FastAPI запущен, фоновый воркер очереди видео активирован.")


class RenderRequest(BaseModel):
    session_id: str | None = None
    transcript: list[dict] = Field(default_factory=list)
    preset: str = "milo"
    font_size: str = "medium"
    v_offset: float = 0.0
    h_align: str = "center"


@app.get("/")
@app.head("/")
async def health_check():
    return {"status": "ok", "service": "banger-cut"}


@app.post("/webhook/{token}")
async def telegram_webhook(token: str, request: Request):
    try:
        data = await request.json()
        telegram_update = Update(**data)
        await dp.feed_update(bot, telegram_update)
        return {"status": "ok"}
    except Exception as exc:
        logger.exception("Ошибка при обработке вебхука Telegram:")
        return JSONResponse(status_code=500, content={"error": str(exc)})


@app.get("/editor", response_class=HTMLResponse)
async def get_editor_page():
    index_file = WEB_DIR / "index.html"
    if not index_file.exists():
        raise HTTPException(status_code=404, detail="Index file not found")
    return FileResponse(index_file)


@app.get("/api/session/{session_id}")
async def get_session_data(session_id: str):
    session = db.get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    
    session_dir = Path(session["session_dir"])
    input_path = Path(session["input_path"])
    video_url = f"/tmp_media/{session_dir.name}/{input_path.name}"
    
    user_settings = db.get_user_settings(session["chat_id"])
    
    return {
        "session_id": session["id"],
        "video_url": video_url,
        "transcript": session["transcript"],
        "user_settings": user_settings
    }


async def _execute_render(session_id: str, data: RenderRequest):
    session = db.get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    db.update_session_status(session_id, "rendering")
    if data.transcript:
        db.update_session_transcript(session_id, data.transcript)

    chat_id = session["chat_id"]
    session_dir = Path(session["session_dir"])
    input_path = Path(session["input_path"])
    keep_segments = session.get("keep_segments", [])

    transcript_data = data.transcript or session.get("transcript", [])
    updated_transcript_path = session_dir / "updated_transcript.json"
    updated_transcript_path.write_text(json.dumps(transcript_data, ensure_ascii=False), encoding="utf-8")

    output_path = session_dir / f"{input_path.stem}_final.mp4"

    try:
        await asyncio.to_thread(
            render_final_video,
            input_video=input_path,
            subtitles_path=updated_transcript_path,
            output_video=output_path,
            preset_name=data.preset,
            font_size=data.font_size,
            v_offset=data.v_offset,
            h_align=data.h_align,
            keep_segments=keep_segments,
        )

        db.update_session_status(session_id, "done")

        from aiogram.types import FSInputFile
        await bot.send_video(
            chat_id=chat_id,
            video=FSInputFile(output_path),
            caption="✨ Готово! Отредактировано и зарендерено через Mini App."
        )

        return {"status": "ok"}
    except Exception as exc:
        logger.exception("Детальная ошибка во время рендеринга:")
        db.update_session_status(session_id, "error")
        raise HTTPException(status_code=500, detail=f"Ошибка рендеринга: {exc}")


@app.post("/api/render")
async def start_render(data: RenderRequest):
    if not data.session_id:
        raise HTTPException(status_code=400, detail="session_id обязателен")
    return await _execute_render(data.session_id, data)


@app.post("/api/session/{session_id}")
async def render_by_session_id(session_id: str, data: RenderRequest):
    return await _execute_render(session_id, data)