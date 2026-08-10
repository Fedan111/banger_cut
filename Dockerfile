FROM python:3.10-slim

# Установка системных зависимостей и FFmpeg
RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Копирование и установка зависимостей
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Копирование исходного кода проекта
COPY . .

# Создание папки для временных файлов
RUN mkdir -p tmp

# Запуск FastAPI-сервера и Telegram-бота
CMD uvicorn server:app --host 0.0.0.0 --port $PORT & python bot.py
