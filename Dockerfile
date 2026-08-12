FROM python:3.10-slim

# Установка FFmpeg, Node.js, Chromium и системных библиотек для Puppeteer
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    ffmpeg \
    nodejs \
    npm \
    chromium \
    libnss3 \
    libatk1.0-0 \
    libatk-bridge2.0-0 \
    libcups2 \
    libdrm2 \
    libxkbcommon0 \
    libxcomposite1 \
    libxdamage1 \
    libxrandr2 \
    libgbm1 \
    libasound2 \
    fonts-freefont-ttf \
    && rm -rf /var/lib/apt/lists/*

# Настройка Puppeteer для использования системного Chromium
ENV PUPPETEER_SKIP_CHROMIUM_DOWNLOAD=true \
    PUPPETEER_EXECUTABLE_PATH=/usr/bin/chromium

WORKDIR /app

# Копирование и установка Python и Node.js зависимостей
COPY requirements.txt package*.json ./
RUN pip install --no-cache-dir -r requirements.txt && \
    if [ -f package.json ]; then npm install; fi

# Копирование исходного кода проекта
COPY . .

# Создание папки для временных файлов
RUN mkdir -p tmp

# Запуск бота в фоновом режиме, а FastAPI-сервера — на переднем плане
CMD ["sh", "-c", "python bot.py & uvicorn server:app --host 0.0.0.0 --port $PORT"]