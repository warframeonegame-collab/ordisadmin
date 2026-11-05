# config.py

import os

from dotenv import load_dotenv
# 🔑 Базовые настройки

PREFIX = "."  # Префикс команд

# 🔄 Каналы
VERIFICATION_CHANNEL_ID = 1255217613643059270  # Канал верификации
WELCOME_CHANNEL_ID = 1255217613643059270   # Канал приветствия
LEADERBOARD_CHANNEL_ID = 1510310805353009183  # Канал таблицы лидеров
LOG_CHANNEL_ID = 1255221212519596184       # Канал логов
RECRUITMENT_CHANNEL_ID = 1515249442398142514  # Канал анкет рекрутинга

# 🎯 Роли
GUEST_ROLE_ID = 1510307677409120256        # Роль "Гость"
MEMBER_ROLE_ID = 1493217622123352134         # Роль "Участник клана"
SUBDIVISION_ROLE_ID = 1493218079528976414  # ID роли, которая может назначать подразделение

# 📊 Система уровней
load_dotenv()
# Путь к БД: корень проекта /data
PROJECT_ROOT = os.path.dirname(__file__)
DATA_DIR = os.getenv('DATA_DIR', os.path.join(PROJECT_ROOT, 'data'))
# PostgreSQL (если задан — используется вместо JSON-файлов)
PG_DSN = os.getenv('PG_DSN', '')
# Оставляем пути к JSON-файлам для обратной совместимости / миграции
DB_FILE = os.path.join(DATA_DIR, 'database.json')
XP_PER_MESSAGE = 5  # Опыт за сообщение
XP_PER_VOICE = 5  # Опыт за нахождение в голосовом канале (каждые 60 сек)
VOICE_XP_INTERVAL = 60  # Интервал начисления опыта в голосовом канале (сек)
LEVEL_MULTIPLIER = 100  # Множитель уровня

# 🎯 Тиры профиля
TIER_ROLES = {
    1492100129342357534: "🚫 Outside Tier",  # Outside Tier
    1493218079528976414: "🏅 1 Tier",        # 1 Tier
    1493217898548822056: "🎯 2 Tier",        # 2 Tier
    1493217622123352134: "🎖 3 Tier",         # 3 Tier
    1514368368180859090: "🎖 4 Tier"         # 4 Tier (штрафной ранг)
}

# 📋 Ограничения
NICKNAME_MAX_LENGTH = 24  # Максимальная длина ника


# 📅 Временные настройки
MESSAGE_DELETE_DELAY = 60  # Время удаления сообщений (сек)
HELP_MESSAGE_DELAY = 60    # Время удаления сообщения помощи

# 🔔 Эмодзи
EMOJIS = {
    "SUCCESS": "✅",
    "ERROR": "❌",
    "INFO": "🔍"
}

# 🛡️ Антилив v3 — risk-score engine (event-driven)
ANTILEAK_ENABLED = True
ANTILEAK_WINDOW_SHORT = 180        # Окно «всплеска» ( сек) — для мгновенных рейдов
ANTILEAK_WINDOW_LONG = 3600        # Почасовое окно — ловит «плавные» атаки (N действ/час)
ANTILEAK_GRACE_SECONDS = 30        # После старта бота — только лог, без реакций (антиспам при рестартах)
ANTILEAK_ALERT_COOLDOWN = 300      # Не создавать новый алерт на того же пользователя чаще, чем раз в N сек
ANTILEAK_ESCALATION_BYPASS = True  # Более высокий уровень эскалации обходит кулдаун алерта
ANTILEAK_TRUSTED_IDS = []          # Доп. доверенные ID (founder/cofounder берутся из site_roles автоматически)

# Вес действий (risk-score)
ANTILEAK_WEIGHTS = {
    'member_ban_add':          40,
    'member_kick':             35,
    'channel_delete':          30,
    'guild_role_delete':       25,
    'guild_update':            25,
    'message_bulk_delete':     20,
    'webhook_delete':          15,
    'channel_overwrite_update': 10,
    'member_role_update':      12,
    'channel_create':          5,
    'bot_add':                 50,
    'owner_transfer':          100,
}
# Критические действия: одно событие сразу = максимальная эскалация
ANTILEAK_CRITICAL_SINGLE = ('owner_transfer', 'bot_add')

# Уровни эскалации: (порог score, окно короткое ИЛИ длинное)
#   warn    — алерт + ЛС, роли не трогаем
#   strip   — снятие опасных ролей (manage-права, tier-роли)
#   lockdown — снятие ВСЕХ ролей + блокировка каналов (send_messages=False) + slowmode
ANTILEAK_LEVELS = [
    ('warn',     35),
    ('strip',    70),
    ('lockdown', 100),
]

# 🎨 UX-улучшения (v2)
GUILD_ID = 1255216389296492564   # Сервер для мгновенной синхронизации slash-команд
XP_COOLDOWN_SECONDS = 30         # Кулдаун XP за сообщения (анти-спам прокачки)
LEVEL_ROLE_REWARDS = {           # Роли-награды за уровень (создаются автоматически при выдаче)
    5: "Уровень 5+",
    10: "Уровень 10+",
    15: "Уровень 15+",
    20: "Уровень 20+",
}
LEADERBOARD_CARD_PATH = os.path.join(DATA_DIR, 'leaderboard_card.png')  # PNG-карточка топ-10
PROFILE_CARD_PATH = os.path.join(DATA_DIR, 'profile_card.png')          # PNG-карточка профиля
