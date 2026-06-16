import os
from dotenv import load_dotenv

# .env лежит в корне проекта (/app/.env), а не в admin/
dotenv_path = os.path.join(os.path.dirname(__file__), '..', '.env')
load_dotenv(dotenv_path)

# ==================== DISCORD OAUTH2 ====================
DISCORD_CLIENT_ID = os.getenv('DISCORD_CLIENT_ID', '')
DISCORD_CLIENT_SECRET = os.getenv('DISCORD_CLIENT_SECRET', '')
DISCORD_REDIRECT_URI = os.getenv('DISCORD_REDIRECT_URI', 'https://ordis.bothost.tech/callback')
DISCORD_BOT_TOKEN = os.getenv('DISCORD_TOKEN', '')

# ==================== FLASK ====================
SECRET_KEY = os.getenv('FLASK_SECRET_KEY', 'arasaka-plaza-admin-secret-key-change-me')
# Путь к БД: корень проекта /data
# На хостинге: /app/data, локально: e:\bots DS\Ordis2\data
PROJECT_ROOT = os.path.dirname(os.path.dirname(__file__))
DATA_DIR = os.getenv('DATA_DIR', os.path.join(PROJECT_ROOT, 'data'))
DATABASE_PATH = os.path.join(DATA_DIR, 'database.json')
LOGS_PATH = os.path.join(DATA_DIR, 'logs.json')

# ==================== DISCORD SERVER ====================
GUILD_ID = os.getenv('GUILD_ID', '1255216389296492564')  # ID сервера Arasaka Plaza
LOG_CHANNEL_ID = '1255221212519596184'  # Канал для отправки команд

# Discord роль, которая автоматически даёт роль "Рекрутер" на сайте
RECRUITER_DISCORD_ROLE_ID = '1513958773331464285'

# ==================== ПРИГЛАШЕНИЕ НА СЕРВЕР ====================
INVITE_URL = "https://discord.gg/Whsgd3fJmS"  # Ссылка приглашения на сервер

# ==================== РОЛИ НА САЙТЕ ====================
# Discord ID → роль на сайте
# Эти роли мигрируются в БД при первом запуске, можно оставить хардкод как дефолт
SITE_ROLES = {
    '436827887165898752': 'founder',      # Основатель (Weelh)
    '748069725698785381': 'cofounder',    # Со-основатель
}

# ==================== ПРАВА РОЛЕЙ ====================
ROLE_PERMISSIONS = {
    'recruiter': {
        'dashboard': True,
        'members_view_own': True,
        'members_view_all': False,
        'members_edit': False,
        'logs_view': False,
        'commands_use': False,
        'timers_view': True,
        'roles_manage': False,
        'settings_manage': False,
        'questionnaires_view': True,
        'rules_edit': False,
    },
    'user': {
        'dashboard': True,
        'members_view_own': True,
        'members_view_all': False,
        'members_edit': False,
        'logs_view': False,
        'commands_use': False,
        'timers_view': True,
        'roles_manage': False,
        'settings_manage': False,
        'rules_edit': False,
    },
    'admin': {
        'dashboard': True,
        'members_view_own': True,
        'members_view_all': True,
        'members_edit': True,
        'logs_view': True,
        'commands_use': True,
        'timers_view': True,
        'roles_manage': False,
        'settings_manage': False,
        'questionnaires_view': True,
        'rules_edit': True,
    },
    'cofounder': {
        'dashboard': True,
        'members_view_own': True,
        'members_view_all': True,
        'members_edit': True,
        'logs_view': True,
        'commands_use': True,
        'timers_view': True,
        'roles_manage': True,
        'settings_manage': False,
        'questionnaires_view': True,
        'rules_edit': True,
    },
    'founder': {
        'dashboard': True,
        'members_view_own': True,
        'members_view_all': True,
        'members_edit': True,
        'logs_view': True,
        'commands_use': True,
        'timers_view': True,
        'roles_manage': True,
        'settings_manage': True,
        'questionnaires_view': True,
        'rules_edit': True,
    },
}

# ==================== НАЗВАНИЯ РОЛЕЙ ====================
ROLE_NAMES = {
    'user': 'Пользователь',
    'recruiter': 'Рекрутер',
    'admin': 'Администрация',
    'cofounder': 'Со-основатель',
    'founder': 'Основатель',
}

# ==================== УВЕДОМЛЕНИЯ ====================
BARO_NOTIFY_MINUTES = 30  # За сколько минут до прибытия Баро отправлять уведомление

# ==================== КАНАЛ ОБЪЯВЛЕНИЙ ====================
ANNOUNCEMENT_CHANNEL_ID = '1257267587432058993'

# ==================== WARFRAME API ====================
WARFRAME_API = "https://api.warframestat.us/pc/"
