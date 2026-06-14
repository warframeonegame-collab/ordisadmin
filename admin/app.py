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
    if 'user_id' in session:
        session['role'] = get_user_role(session['user_id'])

# При запуске мигрируем site_roles из хардкода в БД
try:
    db = Database()
    db.merge_site_roles(config.SITE_ROLES)
except Exception as e:
    logging.warning(f"Не удалось мигрировать site_roles в БД: {e}")

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
    
    return redirect(url_for('dashboard'))

@app.route('/logout')
def logout():
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
    
    # Получаем никнеймы из Discord
    discord_nicks = fetch_discord_members()
    
    members_list = []
    for uid, data in db.items():
        if search and search.lower() not in data.get('nickname', '').lower() and search not in uid:
            continue
        # Используем ник из Discord если в database его нет
        nickname = data.get('nickname') or discord_nicks.get(uid, '')
        # Получаем аватарку: Discord CDN не принимает avatar=None, нужен дефолтный хэш
        avatar_hash = data.get('avatar') or '0'
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
            'description': 'Заблокировать пользователя',
            'category': 'moderation',
            'requires_user': True,
            'variables': [
                {'name': 'type', 'label': 'Тип', 'type': 'select', 'options': ['--chat', '--voice'], 'required': True},
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

@app.route('/roles')
@login_required
@permission_required('roles_manage')
def roles_page():
    # Читаем site_roles из БД (site_roles.json) а не из хардкода
    db = Database()
    site_roles_data = db.get_site_roles()
    return render_template('roles.html', role=session.get('role', 'user'), 
                         site_roles=site_roles_data, role_names=config.ROLE_NAMES,
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

@app.route('/recruiter-rules')
@login_required
def recruiter_rules_page():
    # Проверяем permission recruiter_rules_view
    user_id = session.get('user_id')
    if not has_permission(user_id, 'recruiter_rules_view'):
        abort(403)
    return render_template('recruiter_rules.html', role=session.get('role', 'user'))

@app.route('/api/recruiter-rules/content', methods=['GET', 'POST'])
@login_required
def api_recruiter_rules_content():
    """GET: получить текст правил рекрутеров. POST: сохранить (admin+)."""
    rules_file = os.path.join(config.DATA_DIR, 'recruiter_rules.json')
    
    if request.method == 'GET':
        content = ''
        try:
            if os.path.exists(rules_file):
                with open(rules_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    content = data.get('content', '')
        except:
            pass
        return jsonify({'content': content})
    
    # POST: сохранить
    user_role = session.get('role', 'user')
    if user_role not in ('admin', 'cofounder', 'founder'):
        return jsonify({'error': 'Нет прав на редактирование'}), 403
    
    data = request.json
    content = data.get('content', '')
    
    try:
        with open(rules_file, 'w', encoding='utf-8') as f:
            json.dump({
                'content': content,
                'updated_by': session.get('username', 'Unknown'),
                'updated_at': datetime.now().isoformat()
            }, f, ensure_ascii=False, indent=2)
        
        logs_manager.log_site_action(
            action='Обновление правил рекрутеров',
            description=f'Пользователь {session.get("username")} обновил правила рекрутеров',
            user_id=session.get('user_id', ''),
            user_name=session.get('username', 'Unknown')
        )
        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

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
        'recruiter_rules_view': permissions.get('recruiter_rules_view', False),
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

# ==================== ERROR HANDLERS ====================

@app.errorhandler(403)
def forbidden(e):
    return render_template('error.html', code=403, message='Доступ запрещён'), 403

@app.errorhandler(404)
def not_found(e):
    return render_template('error.html', code=404, message='Страница не найдена'), 404

# ==================== MAIN ====================

if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=3000)