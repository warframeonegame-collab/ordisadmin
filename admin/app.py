import os
import sys
import json
import logging
import requests
import secrets
from datetime import datetime, timedelta
from functools import wraps
from flask import Flask, render_template, request, redirect, url_for, session, jsonify, abort
import config

app = Flask(__name__)
app.secret_key = config.SECRET_KEY

# ==================== HELPERS ====================

def load_database():
    """Загружает database.json"""
    try:
        with open(config.DATABASE_PATH, 'r', encoding='utf-8') as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}

def save_database(data):
    """Сохраняет database.json"""
    with open(config.DATABASE_PATH, 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=4, ensure_ascii=False)

def get_user_role(user_id):
    """Возвращает роль пользователя на сайте"""
    user_id_str = str(user_id)
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
    session['user_id'] = user_info['id']
    session['username'] = user_info['username']
    session['avatar'] = user_info.get('avatar', '')
    session['discriminator'] = user_info.get('discriminator', '0')
    
    # Определяем роль: сначала проверяем SITE_ROLES, затем Discord роль рекрутера
    user_role = get_user_role(user_info['id'])
    if user_role == 'user':
        # Если нет явной роли в SITE_ROLES, проверяем Discord роль рекрутера
        if check_discord_role(user_info['id'], config.RECRUITER_DISCORD_ROLE_ID):
            user_role = 'recruiter'
    session['role'] = user_role
    
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
    
    return render_template('dashboard.html', stats=stats, role=session.get('role', 'user'))

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
        members_list.append({
            'id': uid,
            'nickname': nickname,
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
    
    return render_template('logs.html', page=page, log_type=log_type,
                         date_from=date_from, date_to=date_to, role=session.get('role', 'user'))

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
    return render_template('roles.html', role=session.get('role', 'user'), 
                         site_roles=config.SITE_ROLES, role_names=config.ROLE_NAMES,
                         role_permissions=config.ROLE_PERMISSIONS)

@app.route('/settings')
@login_required
@permission_required('settings_manage')
def settings_page():
    return render_template('settings.html', role=session.get('role', 'user'))

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
    
    # Только founder может менять роли
    if session.get('role') != 'founder' and new_role in ('founder', 'cofounder'):
        return jsonify({'error': 'Insufficient permissions'}), 403
    
    config.SITE_ROLES[str(user_id)] = new_role
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
    }
    
    config.ROLE_NAMES[role_name] = role_display
    
    return jsonify({'success': True})

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
    """Получает логи из Discord канала логов через Bot API"""
    page = request.args.get('page', 1, type=int)
    per_page = request.args.get('per_page', 50, type=int)
    log_type = request.args.get('type', 'all')
    user_filter = request.args.get('user_id', '').strip()
    limit = min(per_page, 100)
    
    try:
        # Получаем никнеймы участников Discord для отображения имён вместо ID
        discord_nicks = fetch_discord_members()
        # Получаем каналы для замены упоминаний каналов
        discord_channels = fetch_discord_channels()
        
        headers = {'Authorization': f'Bot {config.DISCORD_BOT_TOKEN}'}
        
        # Получаем название канала логов
        channel_name = config.LOG_CHANNEL_ID
        try:
            ch_resp = requests.get(
                f'https://discord.com/api/channels/{config.LOG_CHANNEL_ID}',
                headers=headers,
                timeout=5
            )
            if ch_resp.status_code == 200:
                channel_name = ch_resp.json().get('name', config.LOG_CHANNEL_ID)
        except:
            pass
        
        # Получаем сообщения из канала логов
        params = {'limit': limit}
        
        resp = requests.get(
            f'https://discord.com/api/channels/{config.LOG_CHANNEL_ID}/messages',
            headers=headers,
            params=params,
            timeout=10
        )
        
        if resp.status_code == 200:
            messages = resp.json()
            logs_data = []
            
            for msg in messages:
                content = msg.get('content', '')
                embeds = msg.get('embeds', [])
                timestamp = msg.get('timestamp', '')
                author = msg.get('author', {})
                author_id = author.get('id', '')
                author_username = author.get('username', 'System')
                
                # Получаем никнейм на сервере
                author_nickname = discord_nicks.get(author_id, author_username)
                
                log_entry = {
                    'id': msg.get('id'),
                    'timestamp': timestamp,
                    'author': author_username,
                    'author_nickname': author_nickname,
                    'author_id': author_id,
                    'channel_name': channel_name,
                    'channel_id': config.LOG_CHANNEL_ID,
                    'content': content,
                    'embeds': []
                }
                
                for embed in embeds:
                    # Заменяем Discord mentions на имена/названия каналов
                    resolved_desc = resolve_mentions(
                        embed.get('description', ''), discord_nicks, discord_channels
                    )
                    resolved_fields = []
                    for field in embed.get('fields', []):
                        resolved_fields.append({
                            'name': resolve_mentions(field.get('name', ''), discord_nicks, discord_channels),
                            'value': resolve_mentions(field.get('value', ''), discord_nicks, discord_channels),
                            'inline': field.get('inline', False),
                        })
                    embed_data = {
                        'title': embed.get('title', ''),
                        'description': resolved_desc,
                        'color': embed.get('color', 0),
                        'fields': resolved_fields,
                        'footer': embed.get('footer', {}).get('text', ''),
                    }
                    log_entry['embeds'].append(embed_data)
                
                # Фильтр по типу события
                if log_type != 'all':
                    title = ''
                    if embeds:
                        title = embeds[0].get('title', '')
                    title_lower = title.lower()
                    if log_type == 'command' and 'команда' not in title_lower:
                        continue
                    elif log_type == 'delete' and 'удалено' not in title_lower:
                        continue
                    elif log_type == 'edit' and 'отредактировано' not in title_lower:
                        continue
                    elif log_type == 'join' and 'новый участник' not in title_lower and 'подключение' not in title_lower:
                        continue
                    elif log_type == 'leave' and 'покинул' not in title_lower and 'отключение' not in title_lower:
                        continue
                    elif log_type == 'ban' and 'бан' not in title_lower and 'разбан' not in title_lower:
                        continue
                    elif log_type == 'role' and 'рол' not in title_lower:
                        continue
                    elif log_type == 'voice' and 'голосов' not in title_lower:
                        continue
                    elif log_type == 'recruitment' and 'анкет' not in title_lower and 'рекрут' not in title_lower:
                        continue
                
                # Фильтр по пользователю
                if user_filter:
                    if user_filter not in author_id and user_filter.lower() not in author_username.lower() and user_filter.lower() not in author_nickname.lower():
                        continue
                
                logs_data.append(log_entry)
            
            return jsonify({
                'logs': logs_data,
                'page': page,
                'total': len(logs_data),
                'channel_name': channel_name
            })
        else:
            return jsonify({'error': f'Discord API error: {resp.status_code}', 'logs': []}), 500
            
    except Exception as e:
        logging.error(f"Ошибка при получении логов: {e}")
        return jsonify({'error': str(e), 'logs': []}), 500

@app.route('/api/questionnaires')
@login_required
@permission_required('questionnaires_view')
def api_questionnaires():
    """Получает все анкеты рекрутинга из database.json"""
    db = load_database()
    discord_nicks = fetch_discord_members()
    
    questionnaires = []
    for uid, data in db.items():
        q = data.get('questionnaire')
        if q:
            nickname = data.get('nickname') or discord_nicks.get(uid, '')
            q_with_nickname = dict(q)
            q_with_nickname['nickname'] = nickname
            questionnaires.append(q_with_nickname)
    
    # Сортируем по дате заполнения (новые сверху)
    questionnaires.sort(key=lambda x: x.get('filled_at', ''), reverse=True)
    
    return jsonify(questionnaires)

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
