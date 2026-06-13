#!/bin/bash
set -e

echo "========================================"
echo "  Запуск Ordis2 — Discord Bot + Admin"
echo "========================================"

# Запускаем Discord бота в фоне
echo "[1/2] Запуск Discord бота..."
cd /app
python bot.py &
BOT_PID=$!

# Ждём немного, чтобы бот успел инициализироваться
sleep 2

# Запускаем Flask/Gunicorn админ-панель
echo "[2/2] Запуск админ-панели..."
cd /app/admin
exec gunicorn app:app \
    --bind 0.0.0.0:5000 \
    --workers 2 \
    --timeout 120 \
    --access-logfile - \
    --error-logfile - \
    --capture-output

# Если Gunicorn упадёт — убиваем бота тоже
kill $BOT_PID 2>/dev/null