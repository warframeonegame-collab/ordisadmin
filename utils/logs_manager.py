"""Менеджер логов на PostgreSQL (заменяет logs.json)."""

import json
import logging
from datetime import datetime
from typing import Optional, List, Dict, Any
import config
from utils.postgres_db import db as pg_db

logger = logging.getLogger(__name__)


class LogsManager:
    """Менеджер логов бота в PostgreSQL."""

    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def add_log(
        self,
        log_type: str,
        title: str,
        description: str,
        author_id: str = '',
        author_name: str = '',
        color: int = 0,
        fields: Optional[List[Dict]] = None,
        source: str = 'discord',
        attachments: Optional[List[str]] = None,
    ):
        if not pg_db.enabled:
            return None
        try:
            entry_id = None
            with pg_db.conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO logs (timestamp, type, title, description, author_id,
                                      author_name, color, fields, source, attachments)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    RETURNING id
                    """,
                    (
                        datetime.utcnow().isoformat(),
                        log_type,
                        title,
                        description,
                        str(author_id),
                        author_name,
                        int(color),
                        json.dumps(fields or [], ensure_ascii=False),
                        source,
                        json.dumps(attachments or [], ensure_ascii=False),
                    ),
                )
                row = cur.fetchone()
                if row:
                    entry_id = row[0]
            self._enforce_limit()
            return {
                'id': str(entry_id) if entry_id else '',
                'timestamp': datetime.utcnow().isoformat(),
                'type': log_type,
                'title': title,
                'description': description,
                'author_id': str(author_id),
                'author_name': author_name,
                'color': int(color),
                'fields': fields or [],
                'source': source,
                'attachments': attachments or [],
            }
        except Exception as e:
            logger.error(f"Не удалось сохранить лог: {e}")
            return None

    def _enforce_limit(self):
        if not pg_db.enabled:
            return
        try:
            with pg_db.conn.cursor() as cur:
                cur.execute(
                    """
                    DELETE FROM logs
                    WHERE id NOT IN (
                        SELECT id FROM logs ORDER BY id DESC LIMIT 10000
                    )
                    """
                )
        except Exception as e:
            logger.error(f"Ошибка при ограничении логов: {e}")

    def get_logs(
        self,
        page: int = 1,
        per_page: int = 50,
        log_type: str = 'all',
        user_filter: str = '',
        date_from: str = '',
        date_to: str = '',
    ) -> Dict[str, Any]:
        if not pg_db.enabled:
            return {'logs': [], 'page': page, 'per_page': per_page, 'total': 0, 'total_pages': 0}
        try:
            where = ["1=1"]
            params: List = []
            if log_type != 'all':
                type_map = {
                    'command': ['команда', 'command'],
                    'delete': ['удален', 'удалено', 'delete'],
                    'edit': ['отредактировано', 'edit', 'изменение'],
                    'join': ['новый участник', 'подключение', 'join'],
                    'leave': ['покинул', 'отключение', 'leave'],
                    'ban': ['бан', 'разбан', 'ban'],
                    'role': ['рол', 'role'],
                    'voice': ['голосов', 'voice'],
                    'recruitment': ['анкет', 'рекрут', 'recruitment'],
                    'channel': ['канал', 'категори', 'channel'],
                    'site': ['site', 'сайт'],
                }
                keywords = type_map.get(log_type, [log_type])
                or_conditions = ' OR '.join(['title ILIKE %s'] * len(keywords))
                where.append(f"({or_conditions})")
                params.extend([f"%{kw}%" for kw in keywords])
            if user_filter:
                where.append("(author_id = %s OR author_name ILIKE %s)")
                params.extend([user_filter, f"%{user_filter}%"])
            if date_from:
                where.append("timestamp >= %s")
                params.append(date_from + 'T00:00:00')
            if date_to:
                where.append("timestamp <= %s")
                params.append(date_to + 'T23:59:59')
            where_sql = " AND ".join(where)

            with pg_db.conn.cursor() as cur:
                cur.execute(f"SELECT COUNT(*) FROM logs WHERE {where_sql}", tuple(params))
                total = cur.fetchone()[0]
                total_pages = max(1, (total + per_page - 1) // per_page)
                page = max(1, min(page, total_pages))
                offset = (page - 1) * per_page
                cur.execute(
                    f"""
                    SELECT id, timestamp, type, title, description, author_id,
                           author_name, color, fields, source, attachments
                    FROM logs WHERE {where_sql}
                    ORDER BY id DESC LIMIT %s OFFSET %s
                    """,
                    tuple(params + [per_page, offset]),
                )
                rows = cur.fetchall()

            logs = []
            for row in rows:
                logs.append({
                    'id': str(row[0]),
                    'timestamp': row[1].isoformat() if row[1] else '',
                    'type': row[2],
                    'title': row[3],
                    'description': row[4],
                    'author_id': row[5] or '',
                    'author_name': row[6] or '',
                    'color': row[7] or 0,
                    'fields': row[8] if isinstance(row[8], list) else (json.loads(row[8]) if row[8] else []),
                    'source': row[9] or 'discord',
                    'attachments': row[10] if isinstance(row[10], list) else (json.loads(row[10]) if row[10] else []),
                })
            return {
                'logs': logs,
                'page': page,
                'per_page': per_page,
                'total': total,
                'total_pages': total_pages,
            }
        except Exception as e:
            logger.error(f"Ошибка при получении логов: {e}")
            return {'logs': [], 'page': page, 'per_page': per_page, 'total': 0, 'total_pages': 0}

    def log_site_action(
        self,
        action: str,
        description: str,
        user_id: str = '',
        user_name: str = '',
    ):
        return self.add_log(
            log_type='site',
            title=f'Действие на сайте: {action}',
            description=description,
            author_id=user_id,
            author_name=user_name,
            color=0x9b59b6,
            source='site',
        )
