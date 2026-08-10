import os
import json
from pathlib import Path
from fastapi import FastAPI, HTTPException
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse, FileResponse
from pydantic import BaseModel

from bot import bot, TMP_ROOT
from video_processor import render_final_video
import db

app = FastAPI()

WEB_DIR = Path(__file__).parent / "web"
WEB_DIR.mkdir(exist_ok=True)

app.mount("/static", StaticFiles(directory=str(WEB_DIR)), name="static")
app.mount("/tmp_media", StaticFiles(directory=str(TMP_ROOT)), name="tmp_media")


class RenderRequest(BaseModel):
    session_id: str
    transcript: list[dict]
    preset: str
    font_size: str
    v_offset: float
    h_align: str


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
    
    # Формируем относительный URL для видео
    session_dir = Path(session["session_dir"])
    input_path = Path(session["input_path"])
    video_url = f"/tmp_media/{session_dir.name}/{input_path.name}"
    
    # Загружаем настройки пользователя
    user_settings = db.get_user_settings(session["chat_id"])
    
    return {
        "session_id": session["id"],
        "video_url": video_url,
        "transcript": session["transcript"],
        "user_settings": user_settings
    }


@app.post("/api/render")
async def start_render(data: RenderRequest):
    session = db.get_session(data.session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    db.update_session_status(data.session_id, "rendering")
    db.update_session_transcript(data.session_id, data.transcript)

    chat_id = session["chat_id"]
    session_dir = Path(session["session_dir"])
    input_path = Path(session["input_path"])
    keep_segments = session.get("keep_segments", [])

    updated_transcript_path = session_dir / "updated_transcript.json"
    updated_transcript_path.write_text(json.dumps(data.transcript, ensure_ascii=False), encoding="utf-8")

    output_path = session_dir / f"{input_path.stem}_final.mp4"

    # Запуск финального рендера
    render_final_video(
        input_video=input_path,
        subtitles_path=updated_transcript_path,
        output_video=output_path,
        preset_name=data.preset,
        font_size=data.font_size,
        v_offset=data.v_offset,
        h_align=data.h_align,
        keep_segments=keep_segments,
    )

    db.update_session_status(data.session_id, "done")

    # Отправка видео пользователю
    from aiogram.types import FSInputFile
    await bot.send_video(
        chat_id=chat_id,
        video=FSInputFile(output_path),
        caption="✨ Готово! Отредактировано и зарендерено через Mini App."
    )

    return {"status": "ok"}