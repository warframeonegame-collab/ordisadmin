"""Скрипт миграции данных из JSON-файлов в PostgreSQL.

Использование:
    python migrate_json_to_postgres.py

Перед запуском убедитесь, что в .env задан PG_DSN, а PostgreSQL сервер доступен.
"""

import json
import os
import sys
import logging

sys.path.insert(0, os.path.dirname(__file__))
import config

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)


def load_json(path, default=None):
    if default is None:
        default = {}
    if not os.path.exists(path):
        logger.warning(f"Файл не найден: {path}")
        return default
    try:
        with open(path, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception as e:
        logger.error(f"Ошибка чтения {path}: {e}")
        return default


def main():
    if not config.PG_DSN:
        logger.error("PG_DSN не задан в .env.")
        sys.exit(1)

    DATA_DIR = config.DATA_DIR
    logger.info(f"DATA_DIR: {DATA_DIR}")

    from utils.postgres_db import Database
    db = Database()
    if not db.enabled:
        logger.error("Не удалось подключиться к PostgreSQL")
        sys.exit(1)
    logger.info("Подключение к PostgreSQL установлено")

    conn = db.conn

    # 1. Пользователи (database.json)
    database_json = load_json(os.path.join(DATA_DIR, 'database.json'), {})
    logger.info(f"Миграция пользователей: {len(database_json)} записей")
    for uid, data in database_json.items():
        try:
            db.get_user(uid)
            db.update_user(uid, **{k: v for k, v in data.items() if k != 'user_id'})
        except Exception as e:
            logger.error(f"Ошибка миграции пользователя {uid}: {e}")

    # 2. Роли на сайте (site_roles.json)
    site_roles = load_json(os.path.join(DATA_DIR, 'site_roles.json'), {})
    logger.info(f"Миграция site_roles: {len(site_roles)} записей")
    db.merge_site_roles(site_roles)

    # 4. Логи (logs.json)
    logs = load_json(os.path.join(DATA_DIR, 'logs.json'), [])
    logger.info(f"Миграция logs: {len(logs) if isinstance(logs, list) else 0} записей")
    if isinstance(logs, list):
        for log in logs:
            try:
                with conn.cursor() as c:
                    c.execute(
                        "INSERT INTO logs (timestamp, type, title, description, author_id, author_name, color, fields, source, attachments) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                        (log.get('timestamp'), log.get('type'), log.get('title'), log.get('description'),
                         str(log.get('author_id', '')), log.get('author_name', ''), int(log.get('color', 0)),
                         json.dumps(log.get('fields', []), ensure_ascii=False), log.get('source', 'discord'),
                         json.dumps(log.get('attachments', []), ensure_ascii=False)),
                    )
            except Exception as e:
                logger.error(f"Ошибка миграции log: {e}")

    # 5. Presence cache (presence_cache.json)
    presence = load_json(os.path.join(DATA_DIR, 'presence_cache.json'), {})
    logger.info(f"Миграция presence_cache: {len(presence)} записей")
    for uid, data in presence.items():
        try:
            with conn.cursor() as c:
                c.execute(
                    "INSERT INTO presence_cache (user_id, status, last_seen, roles, nickname) VALUES (%s,%s,%s,%s,%s) ON CONFLICT (user_id) DO UPDATE SET status=EXCLUDED.status, last_seen=EXCLUDED.last_seen, roles=EXCLUDED.roles, nickname=EXCLUDED.nickname",
                    (str(uid), data.get('status'), data.get('last_seen'),
                     json.dumps(data.get('roles', []), ensure_ascii=False), data.get('nickname')),
                )
        except Exception as e:
            logger.error(f"Ошибка миграции presence_cache {uid}: {e}")

    # 6. Сессии (sessions.json)
    sessions = load_json(os.path.join(DATA_DIR, 'sessions.json'), [])
    logger.info(f"Миграция sessions: {len(sessions) if isinstance(sessions, list) else 0} записей")
    if isinstance(sessions, list):
        for s in sessions:
            try:
                with conn.cursor() as c:
                    c.execute(
                        "INSERT INTO sessions (user_id, username, login_time, last_active) VALUES (%s,%s,%s,%s) ON CONFLICT (user_id) DO UPDATE SET username=EXCLUDED.username, login_time=EXCLUDED.login_time, last_active=EXCLUDED.last_active",
                        (str(s.get('user_id')), s.get('username'), s.get('login_time'), s.get('last_active')),
                    )
            except Exception as e:
                logger.error(f"Ошибка миграции session: {e}")


    antileak = load_json(os.path.join(DATA_DIR, 'antileak_alerts.json'), [])
    logger.info(f"Миграция antileak_alerts: {len(antileak) if isinstance(antileak, list) else 0} записей")
    if isinstance(antileak, list):
        for a in antileak:
            try:
                with conn.cursor() as c:
                    c.execute(
                        "INSERT INTO antileak_alerts (id, user_id, username, user_avatar, action_type, action_count, threshold, details, saved_roles, victim_ids, timestamp, status, resolved_by, resolved_at, guild_id) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) ON CONFLICT (id) DO NOTHING",
                        (a.get('id'), str(a.get('user_id', '')), a.get('username'), a.get('user_avatar'),
                         a.get('action_type'), int(a.get('action_count', 0)), int(a.get('threshold', 0)),
                         json.dumps(a.get('details'), ensure_ascii=False) if a.get('details') else None,
                         json.dumps(a.get('saved_roles', []), ensure_ascii=False),
                         json.dumps(a.get('victim_ids', []), ensure_ascii=False),
                         a.get('timestamp'), a.get('status'), a.get('resolved_by'),
                         a.get('resolved_at'), a.get('guild_id')),
                    )
            except Exception as e:
                logger.error(f"Ошибка миграции antileak_alert: {e}")

    # 8. Разделы правил (rules_sections.json)
    rules_sections = load_json(os.path.join(DATA_DIR, 'rules_sections.json'), [])
    logger.info(f"Миграция rules_sections: {len(rules_sections) if isinstance(rules_sections, list) else 0} записей")
    if isinstance(rules_sections, list):
        for s in rules_sections:
            try:
                with conn.cursor() as c:
                    c.execute(
                        "INSERT INTO rules_sections (id, title, content, updated_at) VALUES (%s,%s,%s,%s) ON CONFLICT (id) DO UPDATE SET title=EXCLUDED.title, content=EXCLUDED.content, updated_at=EXCLUDED.updated_at",
                        (s.get('id'), s.get('title'), s.get('content'), s.get('updated_at')),
                    )
            except Exception as e:
                logger.error(f"Ошибка миграции rules_section: {e}")

    # 9. Связи правил (rules_connections.json)
    rules_connections = load_json(os.path.join(DATA_DIR, 'rules_connections.json'), [])
    logger.info(f"Миграция rules_connections")
    try:
        with conn.cursor() as c:
            c.execute("DELETE FROM rules_connections")
            c.execute("INSERT INTO rules_connections (data) VALUES (%s)",
                      (json.dumps(rules_connections, ensure_ascii=False),))
    except Exception as e:
        logger.error(f"Ошибка миграции rules_connections: {e}")

    # 10. Отложенные команды (pending_commands.json)
    pending = load_json(os.path.join(DATA_DIR, 'pending_commands.json'), [])
    logger.info(f"Миграция pending_commands: {len(pending) if isinstance(pending, list) else 0} записей")
    if isinstance(pending, list):
        for p in pending:
            try:
                with conn.cursor() as c:
                    c.execute(
                        "INSERT INTO pending_commands (command, channel_id, executor, executor_id, timestamp) VALUES (%s,%s,%s,%s,%s)",
                        (p.get('command'), str(p.get('channel_id', '')), p.get('executor'),
                         str(p.get('executor_id', '')), p.get('timestamp')),
                    )
            except Exception as e:
                logger.error(f"Ошибка миграции pending_command: {e}")
    logger.info("Миграция завершена!")
    db.close()


if __name__ == '__main__':
    main()

