import os
import logging
from contextlib import asynccontextmanager
from fastapi import FastAPI
from aiogram import types

from bot import bot, dp

logging.basicConfig(level=logging.INFO)

BOT_TOKEN = os.getenv("BOT_TOKEN")
RENDER_EXTERNAL_URL = os.getenv("RENDER_EXTERNAL_URL")

WEBHOOK_PATH = f"/webhook/{BOT_TOKEN}"
WEBHOOK_URL = f"{RENDER_EXTERNAL_URL}{WEBHOOK_PATH}"


@asynccontextmanager
async def lifespan(app: FastAPI):
    # При старте приложения принудительно устанавливаем вебхук в Telegram
    logging.info(f"Установка вебхука на URL: {WEBHOOK_URL}")
    await bot.set_webhook(url=WEBHOOK_URL, drop_pending_updates=True)
    yield
    # delete_webhook() убран, чтобы при ротации контейнеров адрес не сбрасывался в Telegram


app = FastAPI(lifespan=lifespan)


@app.get("/")
@app.head("/")
async def root():
    return {"status": "ok", "bot": "Banger Cut"}


@app.post(WEBHOOK_PATH)
async def bot_webhook(update: dict):
    telegram_update = types.Update(**update)
    await dp.feed_webhook_update(bot, telegram_update)
    return {"status": "ok"}