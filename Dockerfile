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

# Запуск ботa в фоновом режиме, а FastAPI-сервера — на переднем плане
CMD ["sh", "-c", "python bot.py & uvicorn server:app --host 0.0.0.0 --port $PORT"]