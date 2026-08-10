import os
import logging
from contextlib import asynccontextmanager
from fastapi import FastAPI
from aiogram import Bot, Dispatcher, types

# Импортируйте вашего диспетчера/хэндлеры из старого файла (например, из bot.py),
# либо переносите логику сюда.

logging.basicConfig(level=logging.INFO)

BOT_TOKEN = os.getenv("BOT_TOKEN")
RENDER_EXTERNAL_URL = os.getenv("RENDER_EXTERNAL_URL")

WEBHOOK_PATH = f"/webhook/{BOT_TOKEN}"
WEBHOOK_URL = f"{RENDER_EXTERNAL_URL}{WEBHOOK_PATH}"

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()  # Или используйте ваш существующий dp

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Установка вебхука при старте
    await bot.set_webhook(url=WEBHOOK_URL, drop_pending_updates=True)
    yield
    # Удаление вебхука при остановке
    await bot.delete_webhook()

app = FastAPI(lifespan=lifespan)

# Корневой эндпоинт (Health Check для Render и проверка в браузере)
@app.get("/")
@app.head("/")
async def root():
    return {"status": "ok", "bot": "Banger Cut"}

# Эндпоинт приема обновлений от Telegram
@app.post(WEBHOOK_PATH)
async def bot_webhook(update: dict):
    telegram_update = types.Update(**update)
    await dp.feed_webhook_update(bot, telegram_update)
    return {"status": "ok"}