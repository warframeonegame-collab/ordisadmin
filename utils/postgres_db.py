"""PostgreSQL менеджер базы данных для бота Ordis.

Заменяет JSON-хранилище (utils/database.py) на PostgreSQL.
Интерфейс совместим со старым классом Database. Все методы синхронные (psycopg2).
"""

import json
import logging
from datetime import datetime, timezone
from typing import Dict

import psycopg2
import psycopg2.extras
import config

logger = logging.getLogger(__name__)


class Database:
    """Синглтон-менеджер PostgreSQL базы данных."""

    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        if self._initialized:
            return
        self._initialized = True
        self.conn = None
        self.pg_dsn = config.PG_DSN
        self.enabled = bool(self.pg_dsn)
        if self.enabled:
            self._connect()
            self._create_tables()
        self._site_roles_cache: Dict[str, str] = {}
        self._site_roles_loaded = False

    # ------------------------------------------------------------------ #
    def _connect(self):
        try:
            self.conn = psycopg2.connect(self.pg_dsn)
            self.conn.autocommit = True
            logger.info("✅ Подключение к PostgreSQL установлено")
        except Exception as e:
            logger.error(f"❌ Не удалось подключиться к PostgreSQL: {e}")
            self.enabled = False
            self.conn = None

    def _create_tables(self):
        if not self.enabled or self.conn is None:
            return
        commands = [
            """
            CREATE TABLE IF NOT EXISTS users (
                user_id BIGINT PRIMARY KEY,
                nickname TEXT DEFAULT '', position TEXT, subdivision TEXT,
                joined_at TEXT, xp BIGINT DEFAULT 0, description TEXT DEFAULT '',
                level INTEGER DEFAULT 1,
                achievements JSONB DEFAULT '{}'::JSONB,
                warns JSONB DEFAULT '[]'::JSONB,
                saved_roles JSONB DEFAULT '[]'::JSONB,
                banned BOOLEAN DEFAULT FALSE, ban_reason TEXT,
                saved_position TEXT, saved_subdivision TEXT, questionnaire JSONB,
                updated_at TIMESTAMPTZ DEFAULT NOW()
            )
            """,
            """
            CREATE TABLE IF NOT EXISTS site_roles (
                user_id TEXT PRIMARY KEY, role TEXT NOT NULL
            )
            """,
            """
            CREATE TABLE IF NOT EXISTS bot_errors (
                id SERIAL PRIMARY KEY, timestamp TIMESTAMPTZ,
                error_type TEXT, error_message TEXT, source TEXT,
                user_id TEXT, user_name TEXT,
                details JSONB DEFAULT '{}'::JSONB
            )
            """,
            """
            CREATE TABLE IF NOT EXISTS logs (
                id SERIAL PRIMARY KEY, timestamp TIMESTAMPTZ, type TEXT,
                title TEXT, description TEXT, author_id TEXT, author_name TEXT,
                color INTEGER DEFAULT 0, fields JSONB DEFAULT '[]'::JSONB,
                source TEXT DEFAULT 'discord',
                attachments JSONB DEFAULT '[]'::JSONB
            )
            """,
            """
            CREATE TABLE IF NOT EXISTS presence_cache (
                user_id TEXT PRIMARY KEY, status TEXT, last_seen TIMESTAMPTZ,
                roles JSONB DEFAULT '[]'::JSONB, nickname TEXT
            )
            """,
            """
            CREATE TABLE IF NOT EXISTS sessions (
                user_id TEXT PRIMARY KEY, username TEXT,
                login_time TIMESTAMPTZ, last_active TIMESTAMPTZ
            )
            """,
            """
            CREATE TABLE IF NOT EXISTS antileak_alerts (
                id TEXT PRIMARY KEY, user_id TEXT, username TEXT, user_avatar TEXT,
                action_type TEXT, action_count INTEGER DEFAULT 0, threshold INTEGER DEFAULT 0,
                details JSONB, saved_roles JSONB DEFAULT '[]'::JSONB,
                victim_ids JSONB DEFAULT '[]'::JSONB, timestamp TIMESTAMPTZ,
                status TEXT, resolved_by TEXT, resolved_at TIMESTAMPTZ, guild_id TEXT
            )
            """,
            """
            CREATE TABLE IF NOT EXISTS rules_sections (
                id TEXT PRIMARY KEY, title TEXT, content TEXT, updated_at TIMESTAMPTZ
            )
            """,
            """
            CREATE TABLE IF NOT EXISTS rules_connections (
                id SERIAL PRIMARY KEY, data JSONB DEFAULT '[]'::JSONB
            )
            """,
            """
            CREATE TABLE IF NOT EXISTS pending_commands (
                id SERIAL PRIMARY KEY, command TEXT, channel_id TEXT,
                executor TEXT, executor_id TEXT, timestamp TIMESTAMPTZ
            )
            """,
            """
            CREATE TABLE IF NOT EXISTS antileak_actions (
                id SERIAL PRIMARY KEY, alert_id TEXT, action TEXT,
                payload JSONB, status TEXT DEFAULT 'pending',
                created_by TEXT, created_at TIMESTAMPTZ, executed_at TIMESTAMPTZ
            )
            """,
            """
            CREATE TABLE IF NOT EXISTS antileak_state (
                key TEXT PRIMARY KEY, value JSONB
            )
            """,
        ]
        with self.conn.cursor() as cur:
            for cmd in commands:
                cur.execute(cmd)
        # Аддитивная миграция: колонка для запланированных авто-размутов
        with self.conn.cursor() as cur:
            cur.execute(
                "ALTER TABLE users ADD COLUMN IF NOT EXISTS "
                "scheduled_unmutes JSONB DEFAULT '[]'::JSONB"
            )
        v3 = [
            # Антилив v3: уровень эскалации и итоговый score алерта
            "ALTER TABLE antileak_alerts ADD COLUMN IF NOT EXISTS response_level TEXT",
            "ALTER TABLE antileak_alerts ADD COLUMN IF NOT EXISTS score INTEGER DEFAULT 0",
        ]
        with self.conn.cursor() as cur:
            for cmd in v3:
                cur.execute(cmd)
        logger.info("✅ Таблицы PostgreSQL созданы/проверены")

    def close(self):
        if self.conn is not None:
            try:
                self.conn.close()
                logger.info("🔌 Соединение с PostgreSQL закрыто")
            except Exception as e:
                logger.error(f"Ошибка при закрытии соединения: {e}")
            self.conn = None

    # ------------------------------------------------------------------ #
    def _json_default(self, value):
        if value is None:
            return None
        if isinstance(value, (str, int, float, bool, list, dict)):
            return json.dumps(value, ensure_ascii=False)
        return json.dumps(value, default=str, ensure_ascii=False)

    def _json_load(self, value):
        if value is None:
            return None
        if isinstance(value, (dict, list)):
            return value
        if isinstance(value, str):
            try:
                return json.loads(value)
            except (json.JSONDecodeError, TypeError):
                return value
        return value

    # ------------------------------------------------------------------ #
    # Пользователи (было database.json)
    # ------------------------------------------------------------------ #
    def get_user(self, user_id, joined_at=None):
        if not self.enabled:
            return None
        user_id = str(user_id)
        with self.conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute("SELECT * FROM users WHERE user_id = %s::BIGINT", (user_id,))
            row = cur.fetchone()
        if row:
            data = dict(row)
            for field in ('achievements', 'warns', 'saved_roles', 'questionnaire',
                          'scheduled_unmutes'):
                data[field] = self._json_load(data.get(field))
            return data

        defaults = {
            'position': None, 'subdivision': None, 'achievements': {},
            'warns': [], 'saved_roles': [], 'banned': False,
            'ban_reason': None, 'saved_position': None, 'saved_subdivision': None,
            'description': '', 'questionnaire': None,
        }
        defaults['joined_at'] = joined_at if joined_at is not None else datetime.now().strftime('%d.%m.%Y')

        with self.conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO users (user_id, nickname, position, subdivision, joined_at,
                                   xp, description, level, achievements, warns, saved_roles,
                                   banned, ban_reason, saved_position, saved_subdivision,
                                   questionnaire)
                VALUES (%s::BIGINT, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (user_id) DO NOTHING
                """,
                (int(user_id), '', None, None, defaults['joined_at'], 0, '', 1,
                 self._json_default(defaults['achievements']),
                 self._json_default(defaults['warns']),
                 self._json_default(defaults['saved_roles']),
                 False, None, None, None,
                 self._json_default(defaults['questionnaire'])),
            )
        return self.get_user(user_id, joined_at)

    def update_user(self, user_id, **kwargs):
        if not self.enabled or not kwargs:
            return
        user_id = str(user_id)
        allowed = {'nickname', 'position', 'subdivision', 'joined_at', 'xp', 'description',
                   'level', 'achievements', 'warns', 'saved_roles', 'banned', 'ban_reason',
                   'saved_position', 'saved_subdivision', 'questionnaire', 'scheduled_unmutes'}
        set_parts, values = [], []
        for key, val in kwargs.items():
            if key not in allowed:
                continue
            if key in ('achievements', 'warns', 'saved_roles', 'questionnaire',
                       'scheduled_unmutes'):
                val = self._json_default(val)
            set_parts.append(f"{key} = %s")
            values.append(val)
        if not set_parts:
            return
        set_parts.append("updated_at = NOW()")
        values.append(int(user_id))
        sql = f"UPDATE users SET {', '.join(set_parts)} WHERE user_id = %s::BIGINT"
        with self.conn.cursor() as cur:
            cur.execute(sql, tuple(values))

    def add_xp(self, user_id, amount):
        if not self.enabled:
            return
        user_id = str(user_id)
        user = self.get_user(user_id)
        if user is None:
            return
        old_level = int(user.get('level') or 1)
        new_xp = int(user.get('xp') or 0) + int(amount)
        new_level = old_level
        current_level = old_level
        while True:
            need = config.LEVEL_MULTIPLIER * (current_level + 1) ** 2
            if new_xp >= need:
                current_level += 1
                new_level = current_level
            else:
                break
        self.update_user(user_id, xp=new_xp, level=new_level)
        return new_level > old_level

    def add_voice_xp(self, user_id, amount, minutes=1):
        """Единый read-modify-write для голосового XP.

        Начисляет XP/уровень (как add_xp) и инкрементирует achievements['voice_minutes'].
        Автоматически проставляет достижения 'voice10' (600 минут) и 'voice50' (3000 минут).
        Возвращает (level_up: bool, new_level: int, minutes_total: int).
        """
        if not self.enabled:
            return False, 1, 0
        user_id = str(user_id)
        user = self.get_user(user_id)
        if user is None:
            return False, 1, 0

        old_level = int(user.get('level') or 1)
        new_xp = int(user.get('xp') or 0) + int(amount)
        current_level = old_level
        while True:
            need = config.LEVEL_MULTIPLIER * (current_level + 1) ** 2
            if new_xp >= need:
                current_level += 1
            else:
                break

        achievements = user.get('achievements') or {}
        minutes_total = int(achievements.get('voice_minutes') or 0) + int(minutes)
        achievements['voice_minutes'] = minutes_total
        if minutes_total >= 600 and not achievements.get('voice10'):
            achievements['voice10'] = True
            logger.info(f"[VoiceXP] Достижение 'voice10' для {user_id} ({minutes_total} мин)")
        if minutes_total >= 3000 and not achievements.get('voice50'):
            achievements['voice50'] = True
            logger.info(f"[VoiceXP] Достижение 'voice50' для {user_id} ({minutes_total} мин)")

        self.update_user(user_id, xp=new_xp, level=current_level, achievements=achievements)
        return current_level > old_level, current_level, minutes_total

    def delete_user(self, user_id):
        if not self.enabled:
            return
        user_id = str(user_id)
        with self.conn.cursor() as cur:
            cur.execute("DELETE FROM users WHERE user_id = %s::BIGINT", (int(user_id),))

    def count_users(self):
        """Количество пользователей (SQL COUNT — не грузит таблицу в память)."""
        if not self.enabled:
            return 0
        with self.conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) FROM users")
            return cur.fetchone()[0]

    def get_top_users(self, limit=10):
        """Топ-N пользователей по уровню (SQL — без загрузки всей таблицы users).

        Возвращает список словарей: {'user_id', 'nickname', 'level', 'xp'}.
        """
        if not self.enabled:
            return []
        with self.conn.cursor() as cur:
            cur.execute(
                "SELECT user_id, nickname, level, xp FROM users "
                "ORDER BY level DESC, xp DESC LIMIT %s",
                (limit,),
            )
            rows = cur.fetchall()
        return [
            {'user_id': str(r[0]), 'nickname': r[1], 'level': r[2], 'xp': r[3]}
            for r in rows
        ]

    def get_all_users(self):
        if not self.enabled:
            return {}
        result = {}
        with self.conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute("SELECT * FROM users ORDER BY user_id")
            rows = cur.fetchall()
        for row in rows:
            data = dict(row)
            uid = str(data.pop('user_id'))
            for field in ('achievements', 'warns', 'saved_roles', 'questionnaire'):
                data[field] = self._json_load(data.get(field))
            result[uid] = data
        return result

    def refresh(self, user_id=None):
        if user_id:
            self.get_user(user_id)
        logger.info("Данные базы данных успешно обновлены (PostgreSQL)")


    # ------------------------------------------------------------------ #
    # Роли на сайте (было site_roles.json)
    # ------------------------------------------------------------------ #
    def _load_site_roles_cache(self):
        if self._site_roles_loaded:
            return
        self._site_roles_cache = {}
        if not self.enabled:
            self._site_roles_loaded = True
            return
        with self.conn.cursor() as cur:
            cur.execute("SELECT user_id, role FROM site_roles")
            for user_id, role in cur.fetchall():
                self._site_roles_cache[str(user_id)] = role
        self._site_roles_loaded = True

    def get_site_roles(self) -> dict:
        self._load_site_roles_cache()
        return dict(self._site_roles_cache)

    def set_site_role(self, user_id: str, role: str):
        user_id = str(user_id)
        if not self.enabled:
            self._site_roles_cache[user_id] = role
            return
        with self.conn.cursor() as cur:
            cur.execute(
                "INSERT INTO site_roles (user_id, role) VALUES (%s, %s) "
                "ON CONFLICT (user_id) DO UPDATE SET role = EXCLUDED.role",
                (user_id, role),
            )
        self._site_roles_cache[user_id] = role

    def remove_site_role(self, user_id: str):
        user_id = str(user_id)
        if not self.enabled:
            self._site_roles_cache.pop(user_id, None)
            return
        with self.conn.cursor() as cur:
            cur.execute("DELETE FROM site_roles WHERE user_id = %s", (user_id,))
        self._site_roles_cache.pop(user_id, None)

    def merge_site_roles(self, roles: dict):
        if not roles:
            return
        if not self.enabled:
            self._site_roles_cache.update({str(k): str(v) for k, v in roles.items()})
            return
        with self.conn.cursor() as cur:
            for user_id, role in roles.items():
                cur.execute(
                    "INSERT INTO site_roles (user_id, role) VALUES (%s, %s) "
                    "ON CONFLICT (user_id) DO UPDATE SET role = EXCLUDED.role",
                    (str(user_id), str(role)),
                )
        self._site_roles_cache.update({str(k): str(v) for k, v in roles.items()})

    # ------------------------------------------------------------------ #
    # Алерты антилива (было antileak_alerts.json)
    # ------------------------------------------------------------------ #
    @staticmethod
    def _dt_to_iso(value):
        """TIMESTAMPTZ → строка ISO (наивное UTC-время, как в старых JSON-файлах)."""
        if value is None:
            return None
        if isinstance(value, datetime):
            if value.tzinfo is not None:
                value = value.astimezone(timezone.utc).replace(tzinfo=None)
            return value.isoformat()
        return value

    def _alert_row_to_dict(self, row):
        data = dict(row)
        for field in ('details', 'saved_roles', 'victim_ids'):
            data[field] = self._json_load(data.get(field))
        for field in ('timestamp', 'resolved_at'):
            data[field] = self._dt_to_iso(data.get(field))
        return data

    def get_antileak_alerts(self):
        """Возвращает все алерты (новые сверху)."""
        if not self.enabled:
            return []
        with self.conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute("SELECT * FROM antileak_alerts ORDER BY timestamp DESC")
            return [self._alert_row_to_dict(r) for r in cur.fetchall()]

    def get_antileak_alert(self, alert_id):
        """Возвращает алерт по ID или None."""
        if not self.enabled:
            return None
        with self.conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute("SELECT * FROM antileak_alerts WHERE id = %s", (str(alert_id),))
            row = cur.fetchone()
        return self._alert_row_to_dict(row) if row else None

    def add_antileak_alert(self, alert_data):
        """Добавляет новый алерт (v3: с response_level и score)."""
        if not self.enabled:
            return
        with self.conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO antileak_alerts (id, user_id, username, user_avatar,
                    action_type, action_count, threshold, details, saved_roles,
                    victim_ids, timestamp, status, resolved_by, resolved_at, guild_id,
                    response_level, score)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (id) DO NOTHING
                """,
                (str(alert_data.get('id')),
                 str(alert_data.get('user_id') or ''),
                 alert_data.get('username'),
                 alert_data.get('user_avatar'),
                 alert_data.get('action_type'),
                 alert_data.get('action_count', 1),
                 alert_data.get('threshold', 0),
                 self._json_default(alert_data.get('details') or {}),
                 self._json_default(alert_data.get('saved_roles') or []),
                 self._json_default(alert_data.get('victim_ids') or []),
                 alert_data.get('timestamp') or datetime.utcnow().isoformat(),
                 alert_data.get('status') or 'pending',
                 alert_data.get('resolved_by'),
                 alert_data.get('resolved_at'),
                 str(alert_data.get('guild_id') or ''),
                 alert_data.get('response_level'),
                 alert_data.get('score', 0)),
            )

    # ------------------------------------------------------------------ #
    # Антилив v3: очередь действий бот ← сайт + состояние lockdown
    # ------------------------------------------------------------------ #
    def _action_row_to_dict(self, row):
        if row is None:
            return None
        data = dict(zip(
            ('id', 'alert_id', 'action', 'payload', 'status', 'created_by',
             'created_at', 'executed_at'), row))
        data['payload'] = self._json_load(data.get('payload'))
        for f in ('created_at', 'executed_at'):
            data[f] = self._dt_to_iso(data.get(f))
        return data

    def add_antileak_action(self, action, payload=None, created_by='site', alert_id=None):
        """Ставит действие в очередь исполнения ботом (reject/confirm/lockdown/unlock).
        Возвращает id записи."""
        if not self.enabled:
            return None
        with self.conn.cursor() as cur:
            cur.execute(
                "INSERT INTO antileak_actions (alert_id, action, payload, created_by, created_at) "
                "VALUES (%s, %s, %s, %s, NOW()) RETURNING id",
                (str(alert_id) if alert_id else None, str(action),
                 self._json_default(payload or {}), str(created_by)),
            )
            return cur.fetchone()[0]

    def get_pending_antileak_actions(self):
        """Список неисполненных действий из очереди (по возрасту)."""
        if not self.enabled:
            return []
        with self.conn.cursor() as cur:
            cur.execute(
                "SELECT id, alert_id, action, payload, status, created_by, created_at, executed_at "
                "FROM antileak_actions WHERE status = 'pending' ORDER BY id ASC LIMIT 25"
            )
            return [self._action_row_to_dict(r) for r in cur.fetchall()]

    def mark_antileak_action_done(self, action_id, success=True):
        if not self.enabled or action_id is None:
            return
        status = 'done' if success else 'failed'
        with self.conn.cursor() as cur:
            cur.execute(
                "UPDATE antileak_actions SET status = %s, executed_at = NOW() WHERE id = %s",
                (status, int(action_id)),
            )

    def get_antileak_state(self, key):
        """Значение из antileak_state (dict) или None."""
        if not self.enabled:
            return None
        with self.conn.cursor() as cur:
            cur.execute("SELECT value FROM antileak_state WHERE key = %s", (str(key),))
            row = cur.fetchone()
        if not row:
            return None
        try:
            return json.loads(row[0]) if isinstance(row[0], (str,)) else row[0]
        except Exception:
            return None

    def set_antileak_state(self, key, value):
        if not self.enabled:
            return
        with self.conn.cursor() as cur:
            cur.execute(
                "INSERT INTO antileak_state (key, value) VALUES (%s, %s) "
                "ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value",
                (str(key), self._json_default(value)),
            )

    def resolve_antileak_alert(self, alert_id, status, resolved_by):
        """Обновляет статус алерта. Возвращает обновлённый алерт или None."""
        if not self.enabled:
            return None
        with self.conn.cursor() as cur:
            cur.execute(
                "UPDATE antileak_alerts SET status = %s, resolved_by = %s, "
                "resolved_at = %s WHERE id = %s",
                (status, resolved_by, datetime.utcnow().isoformat(), str(alert_id)),
            )
        return self.get_antileak_alert(alert_id)

    # ------------------------------------------------------------------ #
    # Кэш presence (было presence_cache.json)
    # ------------------------------------------------------------------ #
    def get_presence_cache(self):
        """Возвращает кэш presence: {user_id: {status, last_seen, roles, nickname}}.

        last_seen — строка ISO (наивное UTC-время), как в старом JSON-файле.
        """
        if not self.enabled:
            return {}
        result = {}
        with self.conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute("SELECT * FROM presence_cache")
            rows = cur.fetchall()
        for row in rows:
            data = dict(row)
            uid = str(data.pop('user_id'))
            data['roles'] = self._json_load(data.get('roles')) or []
            data['last_seen'] = self._dt_to_iso(data.get('last_seen'))
            result[uid] = data
        return result

    def upsert_presence(self, user_id, status, last_seen, roles, nickname):
        """Создаёт или обновляет запись участника в кэше presence."""
        if not self.enabled:
            return
        with self.conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO presence_cache (user_id, status, last_seen, roles, nickname)
                VALUES (%s, %s, %s, %s, %s)
                ON CONFLICT (user_id) DO UPDATE SET
                    status = EXCLUDED.status,
                    last_seen = EXCLUDED.last_seen,
                    roles = EXCLUDED.roles,
                    nickname = EXCLUDED.nickname
                """,
                (str(user_id), status, last_seen,
                 self._json_default([str(r) for r in roles or []]),
                 nickname),
            )

    def upsert_presence_many(self, rows):
        """Пакетная запись кэша presence ОДНИМ запросом (без N отдельных INSERT).

        rows — итератор кортежей (user_id, status, last_seen, roles_list, nickname).
        """
        if not self.enabled or not rows:
            return
        from psycopg2.extras import execute_values
        prepared = [
            (str(uid), status, last_seen,
             self._json_default([str(r) for r in roles or []]),
             nickname)
            for uid, status, last_seen, roles, nickname in rows
        ]
        with self.conn.cursor() as cur:
            execute_values(
                cur,
                """
                INSERT INTO presence_cache (user_id, status, last_seen, roles, nickname)
                VALUES %s
                ON CONFLICT (user_id) DO UPDATE SET
                    status = EXCLUDED.status,
                    last_seen = EXCLUDED.last_seen,
                    roles = EXCLUDED.roles,
                    nickname = EXCLUDED.nickname
                """,
                prepared,
                template="(%s, %s, %s, %s, %s)",
            )

    def delete_presence(self, user_id):
        """Удаляет участника из кэша presence."""
        if not self.enabled:
            return
        with self.conn.cursor() as cur:
            cur.execute("DELETE FROM presence_cache WHERE user_id = %s", (str(user_id),))

    # ------------------------------------------------------------------ #
    # Ожидающие команды с сайта (было pending_commands.json)
    # ------------------------------------------------------------------ #
    def add_pending_command(self, command, channel_id, executor, executor_id,
                            timestamp=None):
        """Добавляет команду от веб-панели в очередь."""
        if not self.enabled:
            return
        with self.conn.cursor() as cur:
            cur.execute(
                "INSERT INTO pending_commands (command, channel_id, executor, "
                "executor_id, timestamp) VALUES (%s, %s, %s, %s, %s)",
                (command, str(channel_id), executor, executor_id,
                 timestamp or datetime.utcnow().isoformat()),
            )

    def pop_pending_commands(self):
        """Забирает все ожидающие команды (читает и очищает очередь атомарно)."""
        if not self.enabled:
            return []
        with self.conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute("DELETE FROM pending_commands RETURNING *")
            rows = cur.fetchall()
        return [dict(r) for r in rows]

    # ------------------------------------------------------------------ #

    @property
    def data(self):
        return self.get_all_users()

    @data.setter
    def data(self, value):
        logger.warning("Прямое присваивание db.data игнорируется (PostgreSQL). "
                       "Используйте update_user / get_all_users.")

    def save_data(self):
        pass
    def __del__(self):
        self.close()


# Глобальный экземпляр (Singleton)
db = Database()
