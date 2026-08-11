import asyncio
import logging
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI
from aiogram import types

from bot import bot, dp, process_queue_worker

logging.basicConfig(level=logging.INFO)

BOT_TOKEN = os.getenv("BOT_TOKEN")
RENDER_EXTERNAL_URL = os.getenv("RENDER_EXTERNAL_URL")

WEBHOOK_PATH = f"/webhook/{BOT_TOKEN}"
WEBHOOK_URL = f"{RENDER_EXTERNAL_URL}{WEBHOOK_PATH}"


@asynccontextmanager
async def lifespan(app: FastAPI):
    logging.info(f"Регистрация вебхука на URL: {WEBHOOK_URL}")
    await bot.set_webhook(url=WEBHOOK_URL, drop_pending_updates=True)

    # Запуск фонового воркера очереди
    worker_task = asyncio.create_task(process_queue_worker())

    yield

    # Отмена воркера при завершении работы (без delete_webhook)
    worker_task.cancel()


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