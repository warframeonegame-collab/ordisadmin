import os
import sys
import json
import logging
import requests
import secrets
from datetime import datetime, timedelta
from functools import wraps
admin_dir = os.path.dirname(__file__)
sys.path.insert(0, os.path.join(admin_dir, '..'))

from flask import Flask, render_template, request, redirect, url_for, session, jsonify, abort

# Загружаем admin/config.py через importlib, чтобы не путать с корневым config.py
import importlib.util as _importlib_util
cfg_spec = _importlib_util.spec_from_file_location("admin_config", os.path.join(admin_dir, 'config.py'))
admin_config = _importlib_util.module_from_spec(cfg_spec)
cfg_spec.loader.exec_module(admin_config)
config = admin_config

# Импортируем наш менеджер логов
from utils.logs_manager import LogsManager
logs_manager = LogsManager()

# Импортируем Database для сохранения site_roles
from utils.database import Database

app = Flask(__name__)
app.secret_key = config.SECRET_KEY

@app.before_request
def refresh_session_role():
    """Обновляет роль в сессии из БД при каждом запросе, чтобы изменения вступали в силу сразу"""
    try:
        if 'user_id' in session:
            session['role'] = get_user_role(session['user_id'])
    except Exception as e:
        logging.warning(f"Ошибка при обновлении роли сессии: {e}")

# При запуске мигрируем site_roles из хардкода в БД
try:
    db = Database()
    db.merge_site_roles(config.SITE_ROLES)
except Exception as e:
    logging.warning(f"Не удалось мигрировать site_roles в БД: {e}")

# ==================== SESSIONS ====================

SESSIONS_FILE = os.path.join(config.DATA_DIR, 'sessions.json')

def _load_sessions():
    try:
        if os.path.exists(SESSIONS_FILE):
            with open(SESSIONS_FILE, 'r', encoding='utf-8') as f:
                return json.load(f)
    except Exception:
        pass
    return []

def _save_sessions(sessions):
    os.makedirs(os.path.dirname(SESSIONS_FILE), exist_ok=True)
    with open(SESSIONS_FILE, 'w', encoding='utf-8') as f:
        json.dump(sessions, f, ensure_ascii=False, indent=2)

def _track_session(user_id, username):
    """Сохраняет/обновляет сессию пользователя."""
    sessions = _load_sessions()
    now = datetime.now().isoformat()
    
    # Ищем существующую сессию
    for s in sessions:
        if s.get('user_id') == str(user_id):
            s['last_active'] = now
            s['username'] = username
            _save_sessions(sessions)
            return
    
    # Новая сессия
    sessions.append({
        'user_id': str(user_id),
        'username': username,
        'login_time': now,
        'last_active': now,
    })
    _save_sessions(sessions)

def _remove_session(user_id):
    """Удаляет сессию при logout."""
    sessions = _load_sessions()
    sessions = [s for s in sessions if s.get('user_id') != str(user_id)]
    _save_sessions(sessions)

# ==================== HELPERS ====================

def get_user_entries(db):
    """Возвращает только пользовательские записи из БД (исключая системные ключи, начинающиеся с _)"""
    return {uid: data for uid, data in db.items() if not uid.startswith('_')}

# Используем единый Database класс (как и бот), чтобы не перезаписывать данные
_db_instance = None
def get_db():
    global _db_instance
    if _db_instance is None:
        _db_instance = Database()
    return _db_instance

def load_database():
    """Загружает database.json напрямую из файла (всегда свежие данные)"""
    db = get_db()
    db.refresh()
    return db.get_all_users()

def save_database(data):
    """Сохраняет database.json через единый Database"""
    db = get_db()
    db.data = data
    db.save_data()

def get_user_role(user_id):
    """Возвращает роль пользователя на сайте (читает напрямую из файла)"""
    user_id_str = str(user_id)
    
    # Читаем site_roles.json напрямую из файла (всегда актуальные данные)
    try:
        site_roles_file = os.path.join(config.DATA_DIR, 'site_roles.json')
        if os.path.exists(site_roles_file):
            with open(site_roles_file, 'r', encoding='utf-8') as f:
                site_roles = json.load(f)
            if user_id_str in site_roles:
                return site_roles[user_id_str]
    except Exception:
        pass
    
    # Фолбек на хардкод из config
    if user_id_str in config.SITE_ROLES:
        return config.SITE_ROLES[user_id_str]
    return 'user'

def check_discord_role(user_id, role_id):
    """Проверяет, есть ли у пользователя указанная Discord роль на сервере"""
    try:
        headers = {'Authorization': f'Bot {config.DISCORD_BOT_TOKEN}'}
        resp = requests.get(
            f'https://discord.com/api/guilds/{config.GUILD_ID}/members/{user_id}',
            headers=headers,
            timeout=5
        )
        if resp.status_code == 200:
            member_data = resp.json()
            roles = member_data.get('roles', [])
            return str(role_id) in roles
    except Exception as e:
        logging.warning(f"Не удалось проверить Discord роль пользователя {user_id}: {e}")
    return False

def has_permission(user_id, permission):
    """Проверяет, есть ли у пользователя право"""
    role = get_user_role(user_id)
    return config.ROLE_PERMISSIONS.get(role, {}).get(permission, False)

def login_required(f):
    """Декоратор: требует авторизацию"""
    @wraps(f)
    def decorated(*args, **kwargs):
        if 'user_id' not in session:
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated

def permission_required(permission):
    """Декоратор: требует конкретное право"""
    def decorator(f):
        @wraps(f)
        def decorated(*args, **kwargs):
            if 'user_id' not in session:
                return redirect(url_for('login'))
            if not has_permission(session['user_id'], permission):
                abort(403)
            return f(*args, **kwargs)
        return decorated
    return decorator

def fetch_discord_members():
    """Получает список участников Discord и возвращает словарь {id: nickname}"""
    result = {}
    try:
        headers = {'Authorization': f'Bot {config.DISCORD_BOT_TOKEN}'}
        members_resp = requests.get(
            f'https://discord.com/api/guilds/{config.GUILD_ID}/members',
            headers=headers,
            params={'limit': 1000},
            timeout=10
        )
        if members_resp.status_code == 200:
            for dm in members_resp.json():
                user_id = dm.get('user', {}).get('id')
                if user_id:
                    nick = dm.get('nick') or dm.get('user', {}).get('username', '')
                    result[user_id] = nick
    except Exception as e:
        logging.warning(f"Не удалось получить участников Discord: {e}")
    return result

def fetch_discord_members_with_avatars():
    """Получает участников Discord с никами и аватарками"""
    result = {}
    try:
        headers = {'Authorization': f'Bot {config.DISCORD_BOT_TOKEN}'}
        members_resp = requests.get(
            f'https://discord.com/api/guilds/{config.GUILD_ID}/members',
            headers=headers,
            params={'limit': 1000},
            timeout=10
        )
        if members_resp.status_code == 200:
            for dm in members_resp.json():
                user_id = dm.get('user', {}).get('id')
                if user_id:
                    user = dm.get('user', {})
                    nick = dm.get('nick') or user.get('username', '')
                    avatar = user.get('avatar', '') or '0'
                    result[user_id] = {'nickname': nick, 'avatar': avatar}
    except Exception as e:
        logging.warning(f"Не удалось получить участников Discord: {e}")
    return result

def fetch_discord_channels():
    """Получает список каналов Discord и возвращает словарь {id: name}"""
    result = {}
    try:
        headers = {'Authorization': f'Bot {config.DISCORD_BOT_TOKEN}'}
        resp = requests.get(
            f'https://discord.com/api/guilds/{config.GUILD_ID}/channels',
            headers=headers,
            timeout=10
        )
        if resp.status_code == 200:
            for ch in resp.json():
                result[ch['id']] = ch['name']
    except Exception as e:
        logging.warning(f"Не удалось получить каналы Discord: {e}")
    return result

def resolve_mentions(text, discord_nicks, discord_channels):
    """Заменяет Discord mentions на реальные имена/названия каналов"""
    import re
    if not text:
        return text
    # Замена упоминаний пользователей <@!ID> и <@ID>
    def replace_user_mention(match):
        user_id = match.group(1)
        name = discord_nicks.get(user_id, user_id)
        return f'@{name}'
    text = re.sub(r'<@!?(\d+)>', replace_user_mention, text)
    # Замена упоминаний каналов <#ID>
    def replace_channel_mention(match):
        ch_id = match.group(1)
        name = discord_channels.get(ch_id, ch_id)
        return f'#{name}'
    text = re.sub(r'<#(\d+)>', replace_channel_mention, text)
    return text

# ==================== AUTH ROUTES ====================

@app.route('/')
def index():
    if 'user_id' in session:
        return redirect(url_for('dashboard'))
    return redirect(url_for('login'))

@app.route('/login')
def login():
    if 'user_id' in session:
        return redirect(url_for('dashboard'))
    
    params = {
        'client_id': config.DISCORD_CLIENT_ID,
        'redirect_uri': config.DISCORD_REDIRECT_URI,
        'response_type': 'code',
        'scope': 'identify guilds',
    }
    discord_auth_url = f"https://discord.com/api/oauth2/authorize?{'&'.join(f'{k}={v}' for k, v in params.items())}"
    return render_template('login.html', discord_auth_url=discord_auth_url)

@app.route('/callback')
def callback():
    code = request.args.get('code')
    if not code:
        return redirect(url_for('login'))
    
    # Обмен кода на токен
    data = {
        'grant_type': 'authorization_code',
        'code': code,
        'redirect_uri': config.DISCORD_REDIRECT_URI,
    }
    headers = {
        'Content-Type': 'application/x-www-form-urlencoded',
    }
    
    resp = requests.post('https://discord.com/api/oauth2/token', data=data, headers=headers, auth=(
        config.DISCORD_CLIENT_ID, config.DISCORD_CLIENT_SECRET
    ))
    
    if resp.status_code != 200:
        return redirect(url_for('login'))
    
    token_data = resp.json()
    access_token = token_data.get('access_token')
    
    # Получаем информацию о пользователе
    headers = {'Authorization': f'Bearer {access_token}'}
    user_resp = requests.get('https://discord.com/api/users/@me', headers=headers)
    
    if user_resp.status_code != 200:
        return redirect(url_for('login'))
    
    user_info = user_resp.json()
    user_id = user_info['id']
    session['user_id'] = user_id
    session['username'] = user_info['username']
    session['avatar'] = user_info.get('avatar', '')
    session['discriminator'] = user_info.get('discriminator', '0')
    
    # Определяем роль: только из SITE_ROLES (без автовыдачи по Discord роли)
    user_role = get_user_role(user_id)
    session['role'] = user_role
    
    # Логируем авторизацию
    logs_manager.log_site_action(
        action='Авторизация',
        description=f'Пользователь {user_info["username"]} авторизовался на сайте (роль: {user_role})',
        user_id=user_id,
        user_name=user_info['username']
    )
    
    # Трекаем сессию
    _track_session(user_id, user_info['username'])
    
    return redirect(url_for('dashboard'))

@app.route('/logout')
def logout():
    _remove_session(session.get('user_id', ''))
    session.clear()
    return redirect(url_for('login'))

# ==================== MAIN ROUTES ====================

@app.route('/dashboard')
@login_required
def dashboard():
    db = load_database()
    total_members = len(db)
    # Безопасное преобразование xp в int, так как в базе могут быть строки
    total_xp = sum(int(u.get('xp', 0)) if u.get('xp') is not None else 0 for u in db.values())
    total_warns = sum(len(u.get('warns', [])) for u in db.values())
    banned_count = sum(1 for u in db.values() if u.get('banned', False))
    
    # Бот статус
    bot_online = False
    try:
        headers = {'Authorization': f'Bot {config.DISCORD_BOT_TOKEN}'}
        resp = requests.get('https://discord.com/api/users/@me', headers=headers, timeout=5)
        bot_online = resp.status_code == 200
    except Exception:
        pass
    
    stats = {
        'total_members': total_members,
        'total_xp': total_xp,
        'total_warns': total_warns,
        'banned_count': banned_count,
        'bot_online': bot_online,
    }
    
    return render_template('dashboard.html', stats=stats, role=session.get('role', 'user'),
                         invite_url=config.INVITE_URL)

@app.route('/members')
@login_required
@permission_required('members_view_all')
def members():
    db = load_database()
    search = request.args.get('search', '').strip()
    sort_by = request.args.get('sort', 'level')
    order = request.args.get('order', 'desc')
    
    # Получаем никнеймы и аватарки из Discord
    discord_data = fetch_discord_members_with_avatars()
    
    members_list = []
    for uid, data in db.items():
        if search and search.lower() not in data.get('nickname', '').lower() and search not in uid:
            continue
        # Используем ник из Discord если в database его нет
        nickname = data.get('nickname') or discord_data.get(uid, {}).get('nickname', '')
        # Получаем аватарку из Discord API или из БД
        avatar_hash = discord_data.get(uid, {}).get('avatar') or data.get('avatar') or '0'
        avatar_url = f'https://cdn.discordapp.com/avatars/{uid}/{avatar_hash}.png?size=64' if avatar_hash != '0' else f'https://cdn.discordapp.com/embed/avatars/0.png'
        members_list.append({
            'id': uid,
            'nickname': nickname,
            'avatar_url': avatar_url,
            'level': data.get('level', 1),
            'xp': data.get('xp', 0),
            'position': data.get('position', ''),
            'subdivision': data.get('subdivision', ''),
            'warns': len(data.get('warns', [])),
            'banned': data.get('banned', False),
            'joined_at': data.get('joined_at', ''),
        })
    
    # Сортировка с безопасным приведением типов
    reverse = (order == 'desc')
    if sort_by in ['level', 'xp', 'warns']:
        members_list.sort(key=lambda x: int(x.get(sort_by, 0)) if isinstance(x.get(sort_by, 0), (int, float, str)) and str(x.get(sort_by, 0)).lstrip('-').isdigit() else 0, reverse=reverse)
    else:
        members_list.sort(key=lambda x: str(x.get(sort_by, '') or '').lower(), reverse=reverse)
    
    return render_template('members.html', members=members_list, search=search, 
                         sort_by=sort_by, order=order, role=session.get('role', 'user'))

@app.route('/member/<user_id>')
@login_required
def member_detail(user_id):
    db = load_database()
    user_data = db.get(str(user_id))
    if not user_data:
        abort(404)
    
    # Проверяем права: обычные пользователи могут смотреть только свой профиль
    if not has_permission(session['user_id'], 'members_view_all') and str(session['user_id']) != str(user_id):
        abort(403)
    
    # Получаем ник из Discord если его нет в базе
    discord_nicks = fetch_discord_members()
    nickname = user_data.get('nickname') or discord_nicks.get(str(user_id), '')
    user_data['nickname'] = nickname
    
    return render_template('member.html', member_id=user_id, member=user_data, 
                         role=session.get('role', 'user'))

@app.route('/leaderboard')
@login_required
def leaderboard():
    return render_template('leaderboard.html', role=session.get('role', 'user'))

@app.route('/logs')
@login_required
@permission_required('logs_view')
def logs():
    page = request.args.get('page', 1, type=int)
    per_page = 50
    log_type = request.args.get('type', 'all')
    date_from = request.args.get('date_from', '')
    date_to = request.args.get('date_to', '')
    user_filter = request.args.get('user_id', '')
    
    return render_template('logs.html', page=page, log_type=log_type,
                         date_from=date_from, date_to=date_to, 
                         user_filter=user_filter, role=session.get('role', 'user'))

@app.route('/commands')
@login_required
@permission_required('commands_use')
def commands_page():
    # Команды модерации (для всех с commands_use)
    moderation_commands = [
        {
            'name': 'warn',
            'description': 'Выдать предупреждение',
            'category': 'moderation',
            'requires_user': True,
            'variables': [
                {'name': 'reason', 'label': 'Причина', 'type': 'text', 'required': True}
            ]
        },
        {
            'name': 'mute',
            'description': 'Заблокировать пользователя (можно указать время: 30m, 1h, 2d)',
            'category': 'moderation',
            'requires_user': True,
            'variables': [
                {'name': 'type', 'label': 'Тип', 'type': 'select', 'options': ['--chat', '--voice'], 'required': True},
                {'name': 'duration', 'label': 'Время (например 30m, 1h, 2d)', 'type': 'text', 'required': False},
                {'name': 'reason', 'label': 'Причина', 'type': 'text', 'required': False}
            ]
        },
        {
            'name': 'unmute',
            'description': 'Снять блокировку',
            'category': 'moderation',
            'requires_user': True,
            'variables': []
        },
        {
            'name': 'unwarn',
            'description': 'Снять одно предупреждение',
            'category': 'moderation',
            'requires_user': True,
            'variables': [
                {'name': 'reason', 'label': 'Причина снятия', 'type': 'text', 'required': True}
            ]
        },
        {
            'name': 'ban',
            'description': 'Выдать штрафную роль',
            'category': 'moderation',
            'requires_user': True,
            'variables': [
                {'name': 'reason', 'label': 'Причина', 'type': 'text', 'required': False}
            ]
        },
        {
            'name': 'unban',
            'description': 'Снять штрафную роль',
            'category': 'moderation',
            'requires_user': True,
            'variables': []
        },
        {
            'name': 'clear',
            'description': 'Очистить сообщения',
            'category': 'moderation',
            'requires_user': False,
            'requires_channel': True,
            'variables': [
                {'name': 'period', 'label': 'Период (1m, 5h, 1d)', 'type': 'text', 'required': False},
                {'name': 'user', 'label': 'Пользователь (опционально)', 'type': 'user', 'required': False}
            ]
        },
        {
            'name': 'setsubdivision',
            'description': 'Установить подразделение',
            'category': 'admin',
            'requires_user': True,
            'variables': [
                {'name': 'subdivision', 'label': 'Подразделение', 'type': 'text', 'required': True}
            ]
        },
    ]
    
    commands_list = moderation_commands
    
    # Системные команды (только для основателя и со-основателя)
    system_commands = []
    user_role = session.get('role', 'user')
    if user_role in ['founder', 'cofounder']:
        system_commands = [
            {
                'name': 'wf',
                'description': 'Обновить статус Warframe',
                'category': 'system',
                'requires_user': False,
                'variables': []
            },
            {
                'name': 'updatetable',
                'description': 'Обновить таблицу лидеров',
                'category': 'system',
                'requires_user': False,
                'variables': []
            },
        ]
    
    # Команда «Сообщение бота в ЛС» — для всех с commands_use
    commands_list.append({
        'name': 'botmsg',
        'description': 'Отправить сообщение от имени бота в ЛС',
        'category': 'bot',
        'requires_user': True,
        'is_botmsg': True,
        'variables': [
            {'name': 'message', 'label': 'Текст сообщения', 'type': 'textarea', 'required': True}
        ]
    })
    
    # Получаем список каналов
    channels = []
    try:
        headers = {'Authorization': f'Bot {config.DISCORD_BOT_TOKEN}'}
        resp = requests.get(f'https://discord.com/api/guilds/{config.GUILD_ID}/channels', headers=headers, timeout=10)
        if resp.status_code == 200:
            for ch in resp.json():
                if ch.get('type') == 0:  # Text channels
                    channels.append({'id': ch['id'], 'name': ch['name']})
    except Exception:
        pass
    
    return render_template('commands.html', commands=commands_list, channels=channels, role=session.get('role', 'user'))

@app.route('/questionnaires')
@login_required
def questionnaires():
    user_id = session.get('user_id')
    role = get_user_role(user_id)
    # Доступ: admin+, или рекрутер с правом questionnaires_view
    if not has_permission(user_id, 'questionnaires_view') and not has_permission(user_id, 'logs_view'):
        abort(403)
    return render_template('questionnaires.html', role=session.get('role', 'user'))

@app.route('/timers')
@login_required
def timers():
    return render_template('timers.html', role=session.get('role', 'user'))

@app.route('/announcements')
@login_required
def announcements_page():
    return render_template('announcements.html', role=session.get('role', 'user'))

@app.route('/roles')
@login_required
@permission_required('roles_manage')
def roles_page():
    # Читаем site_roles из БД (site_roles.json) а не из хардкода
    db = Database()
    site_roles_data = db.get_site_roles()
    # Фильтруем: оставляем только записи, где значение — строка (роль)
    filtered_roles = {k: v for k, v in site_roles_data.items() if isinstance(v, str)}
    return render_template('roles.html', role=session.get('role', 'user'), 
                         site_roles=filtered_roles, role_names=config.ROLE_NAMES,
                         role_permissions=config.ROLE_PERMISSIONS)

@app.route('/settings')
@login_required
@permission_required('settings_manage')
def settings_page():
    return render_template('settings.html', role=session.get('role', 'user'))

@app.route('/rules')
@login_required
def rules_page():
    return render_template('rules.html', role=session.get('role', 'user'))

@app.route('/sessions')
@login_required
@permission_required('settings_manage')
def sessions_page():
    """Список активных сессий (только для основателя)"""
    return render_template('sessions.html', role=session.get('role', 'user'))

@app.route('/api/sessions')
@login_required
@permission_required('settings_manage')
def api_sessions():
    """Получить список сессий"""
    return jsonify({'sessions': _load_sessions()})

@app.route('/api/sessions/terminate', methods=['POST'])
@login_required
@permission_required('settings_manage')
def api_sessions_terminate():
    """Завершить сессию"""
    data = request.json
    user_id = data.get('user_id')
    if not user_id:
        return jsonify({'error': 'user_id required'}), 400
    _remove_session(user_id)
    return jsonify({'success': True})

@app.route('/api/stats/inactive')
@login_required
@permission_required('members_view_all')
def api_stats_inactive():
    """Неактивные участники (не заходили >N дней)"""
    db = load_database()
    discord_nicks = fetch_discord_members()
    sessions = _load_sessions()
    
    # Маппинг: user_id → last_active из сессий сайта
    session_map = {s['user_id']: s.get('last_active') for s in sessions}
    
    # Загружаем presence_cache из бота (активность в Discord)
    presence_cache_file = os.path.join(config.DATA_DIR, 'presence_cache.json')
    presence_cache = {}
    try:
        if os.path.exists(presence_cache_file):
            with open(presence_cache_file, 'r', encoding='utf-8') as f:
                presence_cache = json.load(f)
    except Exception as e:
        logging.warning(f"Не удалось загрузить presence_cache: {e}")
    
    now = datetime.now()
    inactive_days = 14  # по умолчанию 14 дней
    inactive = []
    
    for uid, data in db.items():
        if uid.startswith('_'):
            continue
        
        # 1. Проверяем последнюю активность на сайте (сессии)
        last_active_str = session_map.get(uid)
        last_active_dt = None
        
        if last_active_str:
            try:
                last_active_dt = datetime.fromisoformat(last_active_str)
            except Exception:
                pass
        
        # 2. Проверяем presence_cache — если участник онлайн или был недавно в Discord
        presence_data = presence_cache.get(uid, {})
        presence_status = presence_data.get('status', 'offline')
        presence_last_seen = presence_data.get('last_seen')
        
        # Если участник онлайн/idle/dnd — он точно активен
        if presence_status in ('online', 'idle', 'dnd'):
            continue  # Активен — пропускаем
        
        # Если есть last_seen из presence_cache и он свежее, чем из сессий
        if presence_last_seen:
            try:
                presence_dt = datetime.fromisoformat(presence_last_seen)
                if last_active_dt is None or presence_dt > last_active_dt:
                    last_active_dt = presence_dt
                    last_active_str = presence_last_seen
            except Exception:
                pass
        
        if last_active_dt:
            days_ago = (now - last_active_dt).days
            if days_ago >= inactive_days:
                nickname = data.get('nickname') or discord_nicks.get(uid, uid[:8])
                inactive.append({
                    'user_id': uid,
                    'nickname': nickname,
                    'last_active': last_active_str,
                    'days_ago': days_ago,
                })
        else:
            # Нет данных об активности нигде — считаем неактивным
            nickname = data.get('nickname') or discord_nicks.get(uid, uid[:8])
            inactive.append({
                'user_id': uid,
                'nickname': nickname,
                'last_active': None,
                'days_ago': None,
            })
    
    inactive.sort(key=lambda x: x.get('days_ago') or 999, reverse=True)
    return jsonify({'inactive': inactive[:20], 'threshold': inactive_days})

@app.route('/api/member/<user_id>/activity')
@login_required
@permission_required('members_view_all')
def api_member_activity(user_id):
    """История действий участника (из логов)"""
    try:
        result = logs_manager.get_logs(
            page=1,
            per_page=100,
            log_type='all',
            user_filter=str(user_id),
            date_from='',
            date_to=''
        )
        return jsonify({'activity': result.get('logs', [])})
    except Exception as e:
        return jsonify({'activity': [], 'error': str(e)}), 500

# ==================== HIERARCHY CONNECTIONS API ====================

HIERARCHY_FILE = os.path.join(config.DATA_DIR, 'hierarchy.json')
CONNECTIONS_FILE = os.path.join(config.DATA_DIR, 'rules_connections.json')

def load_hierarchy():
    """Загружает иерархию из JSON-файла"""
    try:
        if os.path.exists(HIERARCHY_FILE):
            with open(HIERARCHY_FILE, 'r', encoding='utf-8') as f:
                return json.load(f)
    except Exception:
        pass
    return {"tiers": [], "extra_lines": []}

def save_hierarchy(data):
    """Сохраняет иерархию в JSON-файл"""
    os.makedirs(os.path.dirname(HIERARCHY_FILE), exist_ok=True)
    with open(HIERARCHY_FILE, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

def load_connections():
    """Загружает связи из JSON-файла"""
    try:
        if os.path.exists(CONNECTIONS_FILE):
            with open(CONNECTIONS_FILE, 'r', encoding='utf-8') as f:
                data = json.load(f)
                return data.get('connections', [])
    except Exception:
        pass
    return []

def save_connections(connections):
    """Сохраняет связи в JSON-файл"""
    os.makedirs(os.path.dirname(CONNECTIONS_FILE), exist_ok=True)
    with open(CONNECTIONS_FILE, 'w', encoding='utf-8') as f:
        json.dump({'connections': connections}, f, ensure_ascii=False, indent=2)

@app.route('/api/rules/hierarchy', methods=['GET'])
@login_required
def api_rules_hierarchy_get():
    """Получить данные иерархии"""
    return jsonify(load_hierarchy())

@app.route('/api/rules/hierarchy', methods=['POST'])
@login_required
def api_rules_hierarchy_save():
    """Сохранить данные иерархии (только основатель)"""
    if session.get('role') != 'founder':
        return jsonify({'error': 'Только основатель может редактировать иерархию'}), 403
    
    data = request.json
    if not data:
        return jsonify({'error': 'Данные обязательны'}), 400
    
    save_hierarchy(data)
    
    logs_manager.log_site_action(
        action='Обновление иерархии',
        description='Обновлены названия ролей в иерархии',
        user_id=session.get('user_id', ''),
        user_name=session.get('username', 'Unknown')
    )
    
    return jsonify({'success': True})

@app.route('/api/rules/connections', methods=['GET'])
@login_required
def api_rules_connections_get():
    """Получить связи между ролями"""
    return jsonify({'connections': load_connections()})

@app.route('/api/rules/connections', methods=['POST'])
@login_required
def api_rules_connections_save():
    """Сохранить связи между ролями (только основатель)"""
    if session.get('role') != 'founder':
        return jsonify({'error': 'Только основатель может редактировать связи'}), 403
    
    data = request.json
    if not data or 'connections' not in data:
        return jsonify({'error': 'Данные connections обязательны'}), 400
    
    save_connections(data['connections'])
    
    logs_manager.log_site_action(
        action='Обновление связей иерархии',
        description=f'Обновлены связи между ролями: {json.dumps(data["connections"], ensure_ascii=False)}',
        user_id=session.get('user_id', ''),
        user_name=session.get('username', 'Unknown')
    )
    
    return jsonify({'success': True})

# ==================== LEGEND NAMES API ====================

LEGEND_NAMES_FILE = os.path.join(config.DATA_DIR, 'rules_legend_names.json')

def load_legend_names():
    """Загружает названия ролей для легенды"""
    default = ['Вестник Лотос.', 'Наблюдатель.', 'Высшие Тэнно.', 'Хранитель Додзё', 'Рекрутер', 'Архитектор Додзё', 'Вестник Орокин', 'Посвященный Тэнно', 'Отреченный.']
    try:
        if os.path.exists(LEGEND_NAMES_FILE):
            with open(LEGEND_NAMES_FILE, 'r', encoding='utf-8') as f:
                data = json.load(f)
                if isinstance(data, list) and len(data) >= len(default):
                    return data
    except Exception:
        pass
    return default

def save_legend_names(names):
    """Сохраняет названия ролей для легенды"""
    os.makedirs(os.path.dirname(LEGEND_NAMES_FILE), exist_ok=True)
    with open(LEGEND_NAMES_FILE, 'w', encoding='utf-8') as f:
        json.dump(names, f, ensure_ascii=False, indent=2)

@app.route('/api/rules/legend-names', methods=['GET'])
@login_required
def api_rules_legend_names_get():
    """Получить названия ролей для легенды"""
    return jsonify({'names': load_legend_names()})

@app.route('/api/rules/legend-names', methods=['POST'])
@login_required
def api_rules_legend_names_save():
    """Сохранить названия ролей для легенды (только основатель)"""
    if session.get('role') != 'founder':
        return jsonify({'error': 'Только основатель может редактировать названия'}), 403
    
    data = request.json
    if not data or 'names' not in data:
        return jsonify({'error': 'Данные names обязательны'}), 400
    
    save_legend_names(data['names'])
    
    logs_manager.log_site_action(
        action='Обновление названий ролей',
        description='Обновлены названия ролей в легенде',
        user_id=session.get('user_id', ''),
        user_name=session.get('username', 'Unknown')
    )
    
    return jsonify({'success': True})

# ==================== RULES SECTIONS API ====================

RULES_SECTIONS_FILE = os.path.join(config.DATA_DIR, 'rules_sections.json')

def load_rules_sections():
    """Загружает разделы правил из JSON-файла"""
    try:
        if os.path.exists(RULES_SECTIONS_FILE):
            with open(RULES_SECTIONS_FILE, 'r', encoding='utf-8') as f:
                return json.load(f)
    except Exception:
        pass
    return []

def save_rules_sections(sections):
    """Сохраняет разделы правил в JSON-файл"""
    os.makedirs(os.path.dirname(RULES_SECTIONS_FILE), exist_ok=True)
    with open(RULES_SECTIONS_FILE, 'w', encoding='utf-8') as f:
        json.dump(sections, f, ensure_ascii=False, indent=2)

RULES_INACTIVITY_FILE = os.path.join(config.DATA_DIR, 'rules_inactivity.json')

def load_inactivity():
    """Загружает сроки неактивности"""
    default = {'outside': 'Отсутствует', 'first': '30 дней', 'second': '20 дней', 'third': '14 дней'}
    try:
        if os.path.exists(RULES_INACTIVITY_FILE):
            with open(RULES_INACTIVITY_FILE, 'r', encoding='utf-8') as f:
                data = json.load(f)
                return {**default, **data}
    except Exception:
        pass
    return default

def save_inactivity(data):
    """Сохраняет сроки неактивности"""
    os.makedirs(os.path.dirname(RULES_INACTIVITY_FILE), exist_ok=True)
    with open(RULES_INACTIVITY_FILE, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

@app.route('/api/rules/inactivity', methods=['GET'])
@login_required
def api_rules_inactivity_get():
    """Получить сроки неактивности"""
    return jsonify(load_inactivity())

@app.route('/api/rules/inactivity', methods=['POST'])
@login_required
def api_rules_inactivity_save():
    """Сохранить сроки неактивности"""
    if not has_permission(session.get('user_id'), 'rules_edit'):
        return jsonify({'error': 'Нет прав на редактирование'}), 403
    
    data = request.json
    if not data:
        return jsonify({'error': 'Данные обязательны'}), 400
    
    save_inactivity(data)
    
    logs_manager.log_site_action(
        action='Обновление сроков неактивности',
        description=f'Обновлены сроки неактивности: {json.dumps(data, ensure_ascii=False)}',
        user_id=session.get('user_id', ''),
        user_name=session.get('username', 'Unknown')
    )
    
    return jsonify({'success': True})

@app.route('/api/rules/sections', methods=['GET'])
@login_required
def api_rules_sections_get():
    """Получить все разделы правил"""
    sections = load_rules_sections()
    return jsonify({'sections': sections})

@app.route('/api/rules/sections', methods=['POST'])
@login_required
def api_rules_sections_create():
    """Создать новый раздел правил"""
    if not has_permission(session.get('user_id'), 'rules_edit'):
        return jsonify({'error': 'Нет прав на редактирование правил'}), 403
    
    data = request.json
    title = data.get('title', '').strip()
    content = data.get('content', '')
    
    if not title:
        return jsonify({'error': 'Название раздела обязательно'}), 400
    
    sections = load_rules_sections()
    section_id = str(len(sections) + 1)
    
    sections.append({
        'id': section_id,
        'title': title,
        'content': content,
        'created_at': datetime.now().isoformat(),
        'updated_at': datetime.now().isoformat()
    })
    
    save_rules_sections(sections)
    
    logs_manager.log_site_action(
        action='Создание раздела правил',
        description=f'Создан раздел правил: {title}',
        user_id=session.get('user_id', ''),
        user_name=session.get('username', 'Unknown')
    )
    
    return jsonify({'success': True, 'id': section_id})

@app.route('/api/rules/sections/<section_id>', methods=['GET'])
@login_required
def api_rules_sections_get_one(section_id):
    """Получить один раздел правил"""
    sections = load_rules_sections()
    for s in sections:
        if s['id'] == section_id:
            return jsonify(s)
    return jsonify({'error': 'Раздел не найден'}), 404

@app.route('/api/rules/sections/<section_id>', methods=['POST'])
@login_required
def api_rules_sections_update(section_id):
    """Обновить раздел правил"""
    if not has_permission(session.get('user_id'), 'rules_edit'):
        return jsonify({'error': 'Нет прав на редактирование правил'}), 403
    
    data = request.json
    title = data.get('title', '').strip()
    content = data.get('content', '')
    
    if not title:
        return jsonify({'error': 'Название раздела обязательно'}), 400
    
    sections = load_rules_sections()
    for s in sections:
        if s['id'] == section_id:
            s['title'] = title
            s['content'] = content
            s['updated_at'] = datetime.now().isoformat()
            save_rules_sections(sections)
            
            logs_manager.log_site_action(
                action='Обновление раздела правил',
                description=f'Обновлён раздел правил: {title}',
                user_id=session.get('user_id', ''),
                user_name=session.get('username', 'Unknown')
            )
            
            return jsonify({'success': True})
    
    return jsonify({'error': 'Раздел не найден'}), 404

@app.route('/api/rules/sections/<section_id>', methods=['DELETE'])
@login_required
def api_rules_sections_delete(section_id):
    """Удалить раздел правил"""
    if not has_permission(session.get('user_id'), 'rules_edit'):
        return jsonify({'error': 'Нет прав на редактирование правил'}), 403
    
    sections = load_rules_sections()
    for i, s in enumerate(sections):
        if s['id'] == section_id:
            removed = sections.pop(i)
            save_rules_sections(sections)
            
            logs_manager.log_site_action(
                action='Удаление раздела правил',
                description=f'Удалён раздел правил: {removed["title"]}',
                user_id=session.get('user_id', ''),
                user_name=session.get('username', 'Unknown')
            )
            
            return jsonify({'success': True})
    
    return jsonify({'error': 'Раздел не найден'}), 404

# ==================== API ROUTES ====================

@app.route('/api/members')
@login_required
@permission_required('members_view_all')
def api_members():
    db = load_database()
    
    # Получаем информацию о пользователях из Discord
    discord_nicks = fetch_discord_members()
    
    # Обновляем никнеймы в базе
    for uid in db:
        if uid in discord_nicks:
            if not db[uid].get('nickname'):
                db[uid]['nickname'] = discord_nicks[uid]
    
    return jsonify(db)

@app.route('/api/members/<user_id>')
@login_required
def api_member(user_id):
    db = load_database()
    user_data = db.get(str(user_id))
    if not user_data:
        return jsonify({'error': 'User not found'}), 404
    return jsonify(user_data)

@app.route('/api/stats')
@login_required
def api_stats():
    db = load_database()
    return jsonify({
        'total_members': len(db),
        'total_xp': sum(int(u.get('xp', 0)) if u.get('xp') is not None else 0 for u in db.values()),
        'total_warns': sum(len(u.get('warns', [])) for u in db.values()),
        'banned_count': sum(1 for u in db.values() if u.get('banned', False)),
    })

@app.route('/api/stats/charts')
@login_required
def api_stats_charts():
    """Данные для графиков на Dashboard"""
    db = load_database()
    discord_nicks = fetch_discord_members()
    
    # Топ участников по XP
    members = []
    for uid, data in db.items():
        if uid.startswith('_'):
            continue
        nickname = data.get('nickname') or discord_nicks.get(uid, uid[:8])
        members.append({
            'nickname': nickname,
            'level': int(data.get('level', 1)) if data.get('level') is not None else 1,
            'xp': int(data.get('xp', 0)) if data.get('xp') is not None else 0,
        })
    members.sort(key=lambda x: (x['level'], x['xp']), reverse=True)
    
    # Распределение по тирам (учитываем TIER_ROLES из config.py)
    tiers = {}
    # Маппинг ключевых слов -> отображаемое название тира на основе TIER_ROLES
    tier_keywords = {
        'outside tier': 'Outside Tier',
        '1 tier': '1 Tier',
        '2 tier': '2 Tier',
        '3 tier': '3 Tier',
        '4 tier': '4 Tier',
    }
    # Также строим обратный маппинг из значений TIER_ROLES (с эмодзи)
    tier_value_to_name = {}
    for role_id, role_value in config.TIER_ROLES.items():
        # role_value выглядит как "🚫 Outside Tier", "🏅 1 Tier" и т.д.
        lower_val = role_value.lower().strip()
        for kw, name in tier_keywords.items():
            if kw in lower_val:
                tier_value_to_name[role_value] = name
                break
    
    for uid, data in db.items():
        if uid.startswith('_'):
            continue
        position = (data.get('position') or '').strip()
        if position:
            matched = False
            # Сначала пробуем точное совпадение со значениями TIER_ROLES (с эмодзи)
            if position in tier_value_to_name:
                name = tier_value_to_name[position]
                tiers[name] = tiers.get(name, 0) + 1
                matched = True
            # Затем пробуем поиск по ключевым словам в lower-case
            if not matched:
                lower_pos = position.lower()
                for kw, name in tier_keywords.items():
                    if kw in lower_pos:
                        tiers[name] = tiers.get(name, 0) + 1
                        matched = True
                        break
            if not matched:
                tiers['Другое'] = tiers.get('Другое', 0) + 1
        else:
            tiers['Без тира'] = tiers.get('Без тира', 0) + 1
    
    return jsonify({
        'members': members[:50],
        'tiers': tiers,
    })

@app.route('/api/server/stats')
@login_required
def api_server_stats():
    """Возвращает статистику сервера Discord (онлайн, старший состав)"""
    # Используем кэш presence из бота
    presence_cache_file = os.path.join(config.DATA_DIR, 'presence_cache.json')
    presence_cache = {}
    
    try:
        if os.path.exists(presence_cache_file):
            with open(presence_cache_file, 'r', encoding='utf-8') as f:
                presence_cache = json.load(f)
    except Exception as e:
        logging.warning(f"Не удалось загрузить кэш presence: {e}")
    
    # Роли старшего состава (Outside Tier + 1 Tier)
    SENIOR_ROLE_IDS = ['1492100129342357534', '1493218079528976414']
    
    # Подсчёт онлайн
    online_now = 0
    senior_online_count = 0
    for user_id, data in presence_cache.items():
        status = data.get('status', 'offline')
        if status in ('online', 'idle', 'dnd'):
            online_now += 1
            roles = data.get('roles', [])
            if any(rid in SENIOR_ROLE_IDS for rid in roles):
                senior_online_count += 1
    
    # Получаем данные из БД
    db = load_database()
    total_in_db = len(db)
    
    # Считаем старший состав по наличию тиров в БД
    senior_total = 0
    for uid, data in db.items():
        position = data.get('position', '')
        if position and ('outside' in position.lower() or '1 tier' in position.lower() or 'outside tier' in position.lower()):
            senior_total += 1
    
    return jsonify({
        'total_members': total_in_db,
        'online_now': online_now,
        'senior_online': senior_online_count,
        'senior_total': senior_total,
        'invite_url': config.INVITE_URL,
    })

@app.route('/api/warframe/timers')
@login_required
def api_warframe_timers():
    try:
        resp = requests.get(config.WARFRAME_API, headers={"User-Agent": "ArasakaPlaza/1.0"}, timeout=10)
        if resp.status_code == 200:
            data = resp.json()
            # Преобразуем данные в удобный формат для timers.html
            # Warframe API возвращает voidTrader (ед.ч.), не voidTraders
            return jsonify(data)
    except Exception as e:
        pass
    return jsonify({'error': 'Failed to fetch Warframe data'}), 500

@app.route('/api/warframe/baro')
@login_required
def api_baro():
    try:
        resp = requests.get(config.WARFRAME_API, headers={"User-Agent": "ArasakaPlaza/1.0"}, timeout=10)
        if resp.status_code == 200:
            data = resp.json()
            baro = data.get('voidTrader', {}) or {}
            return jsonify(baro)
    except Exception:
        pass
    return jsonify({'error': 'Failed to fetch Baro data'}), 500

@app.route('/api/bot/status')
@login_required
def api_bot_status():
    try:
        headers = {'Authorization': f'Bot {config.DISCORD_BOT_TOKEN}'}
        resp = requests.get('https://discord.com/api/users/@me', headers=headers, timeout=5)
        if resp.status_code == 200:
            return jsonify({'online': True, 'user': resp.json()})
    except Exception:
        pass
    return jsonify({'online': False})

@app.route('/api/roles/update', methods=['POST'])
@login_required
@permission_required('roles_manage')
def api_roles_update():
    data = request.json
    user_id = data.get('user_id')
    new_role = data.get('role')
    
    if not user_id or new_role not in config.ROLE_NAMES:
        return jsonify({'error': 'Invalid data'}), 400
    
    # Только founder может менять роли на founder/cofounder
    if session.get('role') != 'founder' and new_role in ('founder', 'cofounder'):
        return jsonify({'error': 'Insufficient permissions'}), 403
    
    # Сохраняем роль в БД (персистентно)
    try:
        db = Database()
        if new_role == 'user':
            db.remove_site_role(user_id)
        else:
            db.set_site_role(user_id, new_role)
    except Exception as e:
        logging.error(f"Не удалось сохранить роль в БД: {e}")
    
    # Также сохраняем в config.SITE_ROLES для текущей сессии
    config.SITE_ROLES[str(user_id)] = new_role
    
    # Логируем изменение роли на сайте
    logs_manager.log_site_action(
        action='Изменение роли пользователя',
        description=f'Пользователь {user_id} получил роль {new_role}',
        user_id=session.get('user_id', ''),
        user_name=session.get('username', 'Unknown')
    )
    
    return jsonify({'success': True})

@app.route('/api/roles/permissions', methods=['POST'])
@login_required
def api_roles_permissions():
    """Обновить права роли (только для founder)"""
    if session.get('role') != 'founder':
        return jsonify({'error': 'Insufficient permissions'}), 403
    
    data = request.json
    role_name = data.get('role')
    permissions = data.get('permissions', {})
    
    if not role_name:
        return jsonify({'error': 'Role name required'}), 400
    
    if role_name not in config.ROLE_PERMISSIONS:
        return jsonify({'error': 'Role not found'}), 404
    
    # Обновляем права
    for perm, value in permissions.items():
        config.ROLE_PERMISSIONS[role_name][perm] = bool(value)
    
    return jsonify({'success': True})

@app.route('/api/permissions/check', methods=['POST'])
@login_required
def api_permissions_check():
    """Проверяет, есть ли у текущего пользователя указанное право"""
    data = request.json
    permission = data.get('permission', '')
    user_id = session.get('user_id')
    if not permission:
        return jsonify({'has_permission': False}), 400
    result = has_permission(user_id, permission)
    return jsonify({'has_permission': result})

@app.route('/api/roles/delete', methods=['POST'])
@login_required
def api_roles_delete():
    """Удалить роль (только для founder)"""
    if session.get('role') != 'founder':
        return jsonify({'error': 'Только основатель может удалять роли'}), 403
    
    data = request.json
    role_name = data.get('role_name', '').strip().lower()
    
    if not role_name:
        return jsonify({'error': 'Role name required'}), 400
    
    if role_name not in config.ROLE_PERMISSIONS:
        return jsonify({'error': 'Role not found'}), 404
    
    # Нельзя удалить базовые роли и founder
    if role_name in ('user', 'founder', 'cofounder', 'admin', 'recruiter'):
        return jsonify({'error': 'Нельзя удалить базовую роль'}), 400
    
    # Удаляем роль
    del config.ROLE_PERMISSIONS[role_name]
    del config.ROLE_NAMES[role_name]
    
    # Сбрасываем пользователей с этой ролью на 'user'
    try:
        db = Database()
        site_roles = db.get_site_roles()
        for uid, role in list(site_roles.items()):
            if role == role_name:
                db.remove_site_role(uid)
    except Exception as e:
        logging.error(f"Не удалось сбросить роли пользователей: {e}")
    
    logs_manager.log_site_action(
        action='Удаление роли',
        description=f'Пользователь {session.get("username")} удалил роль {role_name}',
        user_id=session.get('user_id', ''),
        user_name=session.get('username', 'Unknown')
    )
    return jsonify({'success': True})

@app.route('/api/roles/create', methods=['POST'])
@login_required
def api_roles_create():
    """Создать новую роль (только для founder)"""
    if session.get('role') != 'founder':
        return jsonify({'error': 'Insufficient permissions'}), 403
    
    data = request.json
    role_name = data.get('role_name', '').strip().lower()
    role_display = data.get('role_display', '').strip()
    permissions = data.get('permissions', {})
    
    if not role_name or not role_display:
        return jsonify({'error': 'Role name and display name required'}), 400
    
    if role_name in config.ROLE_PERMISSIONS:
        return jsonify({'error': 'Role already exists'}), 400
    
    # Создаём роль с правами
    config.ROLE_PERMISSIONS[role_name] = {
        'dashboard': permissions.get('dashboard', True),
        'members_view_own': permissions.get('members_view_own', True),
        'members_view_all': permissions.get('members_view_all', False),
        'members_edit': permissions.get('members_edit', False),
        'logs_view': permissions.get('logs_view', False),
        'commands_use': permissions.get('commands_use', False),
        'timers_view': permissions.get('timers_view', True),
        'roles_manage': permissions.get('roles_manage', False),
        'settings_manage': permissions.get('settings_manage', False),
        'questionnaires_view': permissions.get('questionnaires_view', False),
        'rules_edit': permissions.get('rules_edit', False),
    }
    
    config.ROLE_NAMES[role_name] = role_display
    
    return jsonify({'success': True})

@app.route('/api/members/add', methods=['POST'])
@login_required
def api_member_add():
    """Ручное добавление пользователя по Discord ID (только founder/cofounder)"""
    user_role = session.get('role', 'user')
    if user_role not in ('founder', 'cofounder'):
        return jsonify({'error': 'Insufficient permissions'}), 403
    
    data = request.json
    user_id = str(data.get('user_id', '')).strip()
    
    if not user_id or not user_id.isdigit():
        return jsonify({'error': 'Введите корректный Discord ID (только цифры)'}), 400
    
    db = load_database()
    if user_id in db:
        return jsonify({'error': 'Пользователь уже есть в базе данных'}), 400
    
    # Пытаемся получить информацию из Discord
    nickname = ''
    try:
        headers = {'Authorization': f'Bot {config.DISCORD_BOT_TOKEN}'}
        resp = requests.get(
            f'https://discord.com/api/guilds/{config.GUILD_ID}/members/{user_id}',
            headers=headers,
            timeout=10
        )
        if resp.status_code == 200:
            member_data = resp.json()
            nickname = member_data.get('nick') or member_data.get('user', {}).get('username', '')
    except Exception as e:
        logging.warning(f"Не удалось получить данные участника {user_id} из Discord: {e}")
    
    # Создаём запись в БД
    from datetime import datetime
    new_user = {
        'nickname': nickname,
        'level': 1,
        'xp': 0,
        'position': '',
        'subdivision': '',
        'warns': [],
        'banned': False,
        'joined_at': datetime.now().strftime('%d.%m.%Y'),
    }
    
    db[user_id] = new_user
    save_database(db)
    
    # Логируем
    logs_manager.log_site_action(
        action='Добавление участника',
        description=f'Добавлен участник {user_id} ({nickname}) вручную',
        user_id=session.get('user_id', ''),
        user_name=session.get('username', 'Unknown')
    )
    
    return jsonify({'success': True, 'message': f'Участник {user_id} добавлен', 'nickname': nickname})

@app.route('/api/members/update', methods=['POST'])
@login_required
@permission_required('members_edit')
def api_member_update():
    data = request.json
    user_id = data.get('user_id')
    
    if not user_id:
        return jsonify({'error': 'User ID required'}), 400
    
    db = load_database()
    if str(user_id) not in db:
        return jsonify({'error': 'User not found'}), 404
    
    allowed_fields = ['nickname', 'position', 'subdivision', 'level', 'xp']
    update_data = {k: v for k, v in data.items() if k in allowed_fields and k != 'user_id'}
    
    # Логируем изменения
    changed_fields = ', '.join([f'{k}={v}' for k, v in update_data.items() if db[str(user_id)].get(k) != v])
    if changed_fields:
        logs_manager.log_site_action(
            action='Редактирование участника',
            description=f'Изменены поля у {user_id}: {changed_fields}',
            user_id=session.get('user_id', ''),
            user_name=session.get('username', 'Unknown')
        )
    
    db[str(user_id)].update(update_data)
    save_database(db)
    
    # Синхронизация ника с Discord сервером
    nickname = update_data.get('nickname')
    if nickname:
        try:
            headers = {'Authorization': f'Bot {config.DISCORD_BOT_TOKEN}', 'Content-Type': 'application/json'}
            discord_resp = requests.patch(
                f'https://discord.com/api/guilds/{config.GUILD_ID}/members/{user_id}',
                headers=headers,
                json={'nick': nickname[:32]},  # Максимум 32 символа для ника
                timeout=10
            )
            if discord_resp.status_code == 200 or discord_resp.status_code == 204:
                logging.info(f"Участник {user_id}: ник изменён на '{nickname}' через API")
            else:
                logging.warning(f"Не удалось изменить ник {user_id}: {discord_resp.status_code} - {discord_resp.text}")
        except Exception as e:
            logging.warning(f"Ошибка при смене ника через Discord API: {e}")
    
    return jsonify({'success': True})

@app.route('/api/execute', methods=['POST'])
@login_required
@permission_required('commands_use')
def api_execute_command():
    """Записывает команду для выполнения ботом"""
    data = request.json
    command = data.get('command', '').strip()
    channel_id = data.get('channel_id')
    
    if not command:
        return jsonify({'error': 'Command required'}), 400
    
    # Добавляем подпись кто выполнил
    username = session.get('username', 'Unknown')
    
    # Логируем выполнение команды
    logs_manager.log_site_action(
        action='Выполнение команды',
        description=f'Команда: {command}',
        user_id=session.get('user_id', ''),
        user_name=username
    )
    
    # Записываем команду в файл для бота
    pending_file = os.path.join(os.path.dirname(__file__), '..', 'pending_commands.json')
    pending_commands = []
    
    if os.path.exists(pending_file):
        try:
            with open(pending_file, 'r', encoding='utf-8') as f:
                pending_commands = json.load(f)
        except:
            pending_commands = []
    
    pending_commands.append({
        'command': command,
        'channel_id': channel_id or config.LOG_CHANNEL_ID,
        'executor': username,
        'executor_id': session.get('user_id', ''),
        'timestamp': datetime.now().isoformat()
    })
    
    with open(pending_file, 'w', encoding='utf-8') as f:
        json.dump(pending_commands, f, indent=2, ensure_ascii=False)
    
    return jsonify({'success': True, 'message': 'Команда отправлена боту на выполнение'})

@app.route('/api/logs')
@login_required
@permission_required('logs_view')
def api_logs():
    """Получает логи из локального logs.json с фильтрацией и пагинацией"""
    page = request.args.get('page', 1, type=int)
    per_page = request.args.get('per_page', 50, type=int)
    log_type = request.args.get('type', 'all')
    user_filter = request.args.get('user_id', '').strip()
    date_from = request.args.get('date_from', '').strip()
    date_to = request.args.get('date_to', '').strip()
    
    try:
        # Получаем логи из локального хранилища
        result = logs_manager.get_logs(
            page=page,
            per_page=per_page,
            log_type=log_type,
            user_filter=user_filter,
            date_from=date_from,
            date_to=date_to
        )
        
        # Обогащаем данные для отображения
        discord_nicks = fetch_discord_members()
        discord_channels = fetch_discord_channels()
        
        for log_entry in result['logs']:
            # Если source = 'site', то у нас уже есть author_name
            # Если source = 'discord', можем попробовать заменить ID на ник
            if log_entry['source'] == 'discord':
                if log_entry['author_id'] and log_entry['author_id'] in discord_nicks:
                    log_entry['author_name'] = discord_nicks[log_entry['author_id']]
        
        return jsonify({
            'logs': result['logs'],
            'page': result['page'],
            'per_page': result['per_page'],
            'total': result['total'],
            'total_pages': result['total_pages'],
            'channel_name': 'Локальные логи',
        })
        
    except Exception as e:
        logging.error(f"Ошибка при получении логов: {e}")
        return jsonify({'error': str(e), 'logs': [], 'page': 1, 'total_pages': 0, 'total': 0}), 500

@app.route('/api/logs/action', methods=['POST'])
@login_required
def api_log_action():
    """Логирует действие на сайте"""
    data = request.json
    action = data.get('action', 'Действие')
    description = data.get('description', '')
    
    logs_manager.log_site_action(
        action=action,
        description=description,
        user_id=session.get('user_id', ''),
        user_name=session.get('username', 'Unknown')
    )
    
    return jsonify({'success': True})

@app.route('/api/questionnaires')
@login_required
def api_questionnaires():
    """Получает анкеты рекрутинга из database.json с пагинацией"""
    user_id = session.get('user_id')
    if not has_permission(user_id, 'questionnaires_view') and not has_permission(user_id, 'logs_view'):
        return jsonify({'error': 'Forbidden'}), 403
    
    page = request.args.get('page', 1, type=int)
    per_page = 10
    
    db = load_database()
    discord_nicks = fetch_discord_members()
    
    questionnaires = []
    for uid, data in list(db.items()):
        # Пропускаем системные ключи (начинаются с _)
        if uid.startswith('_'):
            continue
        q = data.get('questionnaire')
        if q and isinstance(q, dict):
            nickname = data.get('nickname') or discord_nicks.get(uid, '')
            # Копируем анкету, добавляем ник и ID
            q_copy = {}
            for k, v in q.items():
                q_copy[k] = str(v) if v is not None else ''
            q_copy['nickname'] = nickname or ''
            q_copy['user_id'] = uid
            questionnaires.append(q_copy)
        elif q and isinstance(q, str):
            # На случай если анкета — строка JSON
            try:
                q_parsed = json.loads(q)
                nickname = data.get('nickname') or discord_nicks.get(uid, '')
                q_parsed['nickname'] = nickname or ''
                q_parsed['user_id'] = uid
                questionnaires.append(q_parsed)
            except:
                pass
    
    # Сортируем по дате заполнения (новые сверху)
    questionnaires.sort(key=lambda x: x.get('filled_at', ''), reverse=True)
    
    total = len(questionnaires)
    total_pages = max(1, (total + per_page - 1) // per_page)
    start = (page - 1) * per_page
    end = start + per_page
    
    return jsonify({
        'questionnaires': questionnaires[start:end],
        'page': page,
        'per_page': per_page,
        'total': total,
        'total_pages': total_pages,
    })

@app.route('/api/leaderboard')
@login_required
def api_leaderboard():
    """Возвращает таблицу лидеров для отображения на сайте"""
    db = load_database()
    discord_nicks = fetch_discord_members()
    
    users = []
    for uid, data in db.items():
        nickname = data.get('nickname') or discord_nicks.get(uid, 'Неизвестно')
        users.append({
            'id': uid,
            'nickname': nickname,
            'level': int(data.get('level', 1)) if data.get('level') is not None else 1,
            'xp': int(data.get('xp', 0)) if data.get('xp') is not None else 0,
            'position': data.get('position', ''),
            'subdivision': data.get('subdivision', ''),
        })
    
    # Сортируем по уровню (по убыванию), затем по опыту
    users.sort(key=lambda x: (x['level'], x['xp']), reverse=True)
    
    return jsonify(users[:100])  # Топ-100

# ==================== ANNOUNCEMENTS API ====================

@app.route('/api/announcements')
@login_required
def api_announcements_get():
    """Загружает объявления из канала объявлений Discord"""
    try:
        headers = {'Authorization': f'Bot {config.DISCORD_BOT_TOKEN}'}
        channel_id = config.ANNOUNCEMENT_CHANNEL_ID
        
        # Получаем последние 50 сообщений из канала
        resp = requests.get(
            f'https://discord.com/api/channels/{channel_id}/messages',
            headers=headers,
            params={'limit': 50},
            timeout=10
        )
        
        if resp.status_code != 200:
            return jsonify({'error': 'Не удалось загрузить объявления', 'announcements': []}), 500
        
        messages = resp.json()
        # Получаем pinned messages
        pinned_resp = requests.get(
            f'https://discord.com/api/channels/{channel_id}/pins',
            headers=headers,
            timeout=10
        )
        pinned_ids = set()
        if pinned_resp.status_code == 200:
            for pm in pinned_resp.json():
                pinned_ids.add(pm['id'])
        
        announcements = []
        for msg in messages:
            author = msg.get('author', {})
            content = msg.get('content', '')
            # Пропускаем пустые и embed-only сообщения
            if not content.strip() and not msg.get('embeds'):
                continue
            
            # Извлекаем заголовок (первая строка с **жирным** или до первого переноса)
            title = ''
            text = content
            lines = content.strip().split('\n', 1)
            if lines and lines[0].startswith('**') and lines[0].endswith('**'):
                title = lines[0].strip('*')
                text = lines[1] if len(lines) > 1 else ''
            elif lines and '**' in lines[0]:
                # Первая строка может содержать заголовок без маркдауна
                title = lines[0].strip()
                text = lines[1] if len(lines) > 1 else ''
            
            announcements.append({
                'id': msg['id'],
                'message_id': msg['id'],
                'title': title,
                'content': text or content,
                'author_id': author.get('id', ''),
                'author_name': author.get('username', 'Unknown'),
                'author_avatar': author.get('avatar', ''),
                'timestamp': msg.get('timestamp', ''),
                'pinned': msg['id'] in pinned_ids,
                'has_embeds': len(msg.get('embeds', [])) > 0,
                'embeds': [{'title': e.get('title', ''), 'description': e.get('description', '')} for e in msg.get('embeds', [])[:3]],
            })
        
        return jsonify({'announcements': announcements})
    except Exception as e:
        logging.error(f"[Announcements] Ошибка: {e}")
        return jsonify({'error': str(e), 'announcements': []}), 500

@app.route('/api/announcements/post', methods=['POST'])
@login_required
def api_announcements_post():
    """Публикует объявление в канал объявлений"""
    # Проверяем права: admin+
    user_role = session.get('role', 'user')
    if user_role not in ('admin', 'cofounder', 'founder'):
        return jsonify({'error': 'Только администрация может публиковать объявления'}), 403
    
    data = request.json
    title = data.get('title', '').strip()
    content = data.get('content', '').strip()
    pin = data.get('pin', True)
    
    if not content:
        return jsonify({'error': 'Введите текст объявления'}), 400
    
    # Формируем сообщение для Discord
    message = ''
    if title:
        message += f'**{title}**\n\n'
    message += content
    
    # Добавляем подпись
    username = session.get('username', 'Unknown')
    message += f'\n\n— {username}'
    
    try:
        headers = {
            'Authorization': f'Bot {config.DISCORD_BOT_TOKEN}',
            'Content-Type': 'application/json',
        }
        channel_id = config.ANNOUNCEMENT_CHANNEL_ID
        
        resp = requests.post(
            f'https://discord.com/api/channels/{channel_id}/messages',
            headers=headers,
            json={'content': message},
            timeout=10
        )
        
        if resp.status_code != 200:
            error_data = resp.json()
            return jsonify({'error': f'Discord API error: {error_data.get("message", resp.text)}'}), 500
        
        msg_data = resp.json()
        message_id = msg_data.get('id')
        
        # Если нужно закрепить
        if pin and message_id:
            try:
                requests.put(
                    f'https://discord.com/api/channels/{channel_id}/pins/{message_id}',
                    headers=headers,
                    timeout=5
                )
            except Exception as e:
                logging.warning(f"[Announcements] Не удалось закрепить: {e}")
        
        # Логируем
        logs_manager.log_site_action(
            action='Публикация объявления',
            description=f'Пользователь {username} опубликовал объявление' + (f' "{title[:50]}"' if title else ''),
            user_id=session.get('user_id', ''),
            user_name=username
        )
        
        return jsonify({'success': True, 'message_id': message_id})
    except Exception as e:
        logging.error(f"[Announcements] Ошибка публикации: {e}")
        return jsonify({'error': str(e)}), 500

# ==================== GLOBAL SEARCH API ====================

@app.route('/api/search')
@login_required
def api_search():
    """Глобальный поиск по участникам, логам и анкетам"""
    query = request.args.get('q', '').strip().lower()
    if len(query) < 2:
        return jsonify({'results': []})
    
    results = []
    
    # Поиск по участникам
    try:
        db = load_database()
        discord_nicks = fetch_discord_members()
        
        for uid, data in db.items():
            if uid.startswith('_'):
                continue
            nickname = data.get('nickname') or discord_nicks.get(uid, '')
            if query in nickname.lower() or query in uid:
                results.append({
                    'type': 'member',
                    'title': nickname or uid,
                    'subtitle': f'Уровень {data.get("level", 1)} • {uid}',
                    'url': f'/member/{uid}'
                })
    except Exception:
        pass
    
    # Поиск по логам
    try:
        logs_result = logs_manager.get_logs(page=1, per_page=100)
        for log in logs_result.get('logs', []):
            desc = log.get('description', '').lower()
            author = log.get('author_name', '').lower()
            action = log.get('action', '').lower()
            if query in desc or query in author or query in action:
                results.append({
                    'type': 'log',
                    'title': log.get('action', 'Действие'),
                    'subtitle': log.get('description', '')[:80],
                    'url': '/logs'
                })
    except Exception:
        pass
    
    # Ограничиваем результаты
    return jsonify({'results': results[:15]})

# ==================== ANTILEAK PAGE ====================

@app.route('/antileak')
@login_required
@permission_required('antileak_view')
def antileak_page():
    return render_template('antileak.html', role=session.get('role', 'user'))

@app.route('/api/antileak/alerts')
@login_required
@permission_required('antileak_view')
def api_antileak_alerts():
    """Получить все алерты антилива"""
    try:
        alerts_file = os.path.join(config.DATA_DIR, 'antileak_alerts.json')
        if os.path.exists(alerts_file):
            with open(alerts_file, 'r', encoding='utf-8') as f:
                alerts = json.load(f)
        else:
            alerts = []
        
        # Обогащаем данные — подтягиваем ники из Discord
        discord_nicks = fetch_discord_members()
        for alert in alerts:
            uid = alert.get('user_id', '')
            if uid in discord_nicks:
                alert['username'] = discord_nicks[uid]
        
        return jsonify({'alerts': alerts})
    except Exception as e:
        logging.error(f"Ошибка загрузки алертов антилива: {e}")
        return jsonify({'alerts': [], 'error': str(e)}), 500

@app.route('/api/antileak/resolve', methods=['POST'])
@login_required
@permission_required('antileak_view')
def api_antileak_resolve():
    """Подтвердить или отклонить алерт антилива (восстановить роли)"""
    data = request.json
    alert_id = data.get('alert_id')
    action = data.get('action')  # 'confirm' или 'reject'
    
    if not alert_id or action not in ('confirm', 'reject'):
        return jsonify({'error': 'Неверные параметры'}), 400
    
    alerts_file = os.path.join(config.DATA_DIR, 'antileak_alerts.json')
    try:
        with open(alerts_file, 'r', encoding='utf-8') as f:
            alerts = json.load(f)
        
        target_alert = None
        for a in alerts:
            if a['id'] == alert_id:
                target_alert = a
                break
        
        if not target_alert:
            return jsonify({'error': 'Алерт не найден'}), 404
        
        if target_alert['status'] != 'pending':
            return jsonify({'error': 'Алерт уже обработан'}), 400
        
        # Обновляем статус
        target_alert['status'] = 'confirmed' if action == 'confirm' else 'rejected'
        target_alert['resolved_by'] = session.get('username', 'Unknown')
        target_alert['resolved_at'] = datetime.now().isoformat()
        
        with open(alerts_file, 'w', encoding='utf-8') as f:
            json.dump(alerts, f, ensure_ascii=False, indent=2)
        
        # Если отклонено — восстанавливаем роли через Discord API
        if action == 'reject':
            user_id = target_alert.get('user_id')
            saved_roles = target_alert.get('saved_roles', [])
            guild_id = config.GUILD_ID
            
            if user_id and saved_roles:
                try:
                    headers = {
                        'Authorization': f'Bot {config.DISCORD_BOT_TOKEN}',
                        'Content-Type': 'application/json'
                    }
                    # Добавляем роли обратно
                    resp = requests.put(
                        f'https://discord.com/api/guilds/{guild_id}/members/{user_id}/roles',
                        headers=headers,
                        json={'roles': [str(r) for r in saved_roles]},
                        timeout=10
                    )
                    if resp.status_code in (200, 204):
                        logging.info(f"[AntiLeak] Роли восстановлены для {user_id} (отклонено основателем)")
                    else:
                        logging.warning(f"[AntiLeak] Ошибка восстановления ролей для {user_id}: {resp.status_code}")
                except Exception as e:
                    logging.error(f"[AntiLeak] Ошибка восстановления ролей: {e}")
        
        # Логируем
        logs_manager.log_site_action(
            action='🛡️ Антилив — Решение',
            description=(
                f'Основатель {session.get("username")} '
                f'{"подтвердил" if action == "confirm" else "отклонил"} '
                f'алерт #{alert_id} (пользователь {target_alert.get("username")})'
            ),
            user_id=session.get('user_id', ''),
            user_name=session.get('username', 'Unknown')
        )
        
        return jsonify({
            'success': True,
            'status': target_alert['status'],
            'message': 'Алерт подтверждён' if action == 'confirm' else 'Алерт отклонён, роли восстановлены'
        })
        
    except Exception as e:
        logging.error(f"Ошибка resolve антилив: {e}")
        return jsonify({'error': str(e)}), 500

# ==================== ERROR HANDLERS ====================

@app.errorhandler(403)
def forbidden(e):
    return render_template('error.html', code=403, message='Доступ запрещён'), 403

@app.errorhandler(404)
def not_found(e):
    return render_template('error.html', code=404, message='Страница не найдена'), 404

@app.errorhandler(500)
def internal_error(e):
    logging.error(f"Internal Server Error: {e}")
    return render_template('error.html', code=500, message='Внутренняя ошибка сервера'), 500

# ==================== MAIN ====================

if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=3000)