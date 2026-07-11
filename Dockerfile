FROM python:3.11-slim

WORKDIR /app

# Установка системных зависимостей (для сборки discord.py, httpx и Playwright)
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    libffi-dev \
    musl-dev \
    # Зависимости для Playwright/Chromium
    libnss3 \
    libnspr4 \
    libatk1.0-0 \
    libatk-bridge2.0-0 \
    libcups2 \
    libdrm2 \
    libdbus-1-3 \
    libxkbcommon0 \
    libatspi2.0-0 \
    libxcomposite1 \
    libxdamage1 \
    libxfixes3 \
    libxrandr2 \
    libgbm1 \
    libpango-1.0-0 \
    libcairo2 \
    libasound2 \
    libxshmfence1 \
    && rm -rf /var/lib/apt/lists/*

# Копируем и устанавливаем Python-зависимости
COPY requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir --default-timeout=120 -r /app/requirements.txt

# Устанавливаем браузеры Playwright
RUN playwright install --with-deps chromium

# Копируем весь исходный код
COPY . /app

# Делаем entrypoint исполняемым
RUN chmod +x /app/start.sh

# Создаём папку для данных и пустой database.json
RUN mkdir -p /app/data && echo '{}' > /app/data/database.json

# Открываем порт для админ-панели
EXPOSE 3000

# Запускаем и бота, и админ-панель
CMD ["/bin/bash", "/app/start.sh"]
