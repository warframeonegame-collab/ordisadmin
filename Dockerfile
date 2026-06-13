FROM python:3.11-slim

WORKDIR /app

# Установка системных зависимостей (для сборки discord.py и httpx)
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    libffi-dev \
    musl-dev \
    && rm -rf /var/lib/apt/lists/*

# Копируем и устанавливаем Python-зависимости
COPY requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir --default-timeout=120 -r /app/requirements.txt

# Копируем весь исходный код
COPY . /app

# Делаем entrypoint исполняемым
RUN chmod +x /app/start.sh

# Создаём папку для данных и пустой bot.db
RUN mkdir -p /app/data && echo '{}' > /app/data/bot.db

# Volume для сохранения данных между перезапусками
VOLUME ["/app/data"]

# Открываем порт для админ-панели
EXPOSE 3000

# Запускаем и бота, и админ-панель
CMD ["/bin/bash", "/app/start.sh"]
