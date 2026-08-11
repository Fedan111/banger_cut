import asyncio
import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from aiogram import types

from bot import bot, dp, process_queue_worker

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

# Монтируем папку web для статических файлов (CSS/JS/изображения)
WEB_DIR = BASE_DIR / "web"
if WEB_DIR.exists():
    app.mount("/static", StaticFiles(directory=WEB_DIR), name="static")


@app.get("/")
@app.head("/")
async def root():
    return {"status": "ok", "bot": "Banger Cut"}


@app.get("/editor", response_class=HTMLResponse)
async def serve_editor():
    """Отдаёт Mini App из папки web/index.html."""
    html_path = WEB_DIR / "index.html"

    if html_path.exists():
        return FileResponse(html_path)

    return HTMLResponse("<h3>Ошибка: Файл web/index.html не найден на сервере.</h3>", status_code=404)


@app.post(WEBHOOK_PATH)
async def bot_webhook(update: dict):
    telegram_update = types.Update(**update)
    await dp.feed_webhook_update(bot, telegram_update)
    return {"status": "ok"}