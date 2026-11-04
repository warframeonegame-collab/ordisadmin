"""Менеджер ошибок бота на PostgreSQL (заменяет bot_errors.json)."""

import json
import logging
from datetime import datetime
from typing import List, Dict, Optional
import config
from utils.postgres_db import db as pg_db

logger = logging.getLogger(__name__)


class BotErrorsManager:
    """Менеджер для хранения и получения логов ошибок бота в PostgreSQL."""

    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def add_error(
        self,
        error_type: str,
        error_message: str,
        source: str = '',
        user_id: str = '',
        user_name: str = '',
        details: Optional[Dict] = None,
    ):
        """Сохраняет ошибку бота в PostgreSQL."""
        if not pg_db.enabled:
            return None
        try:
            entry_id = None
            with pg_db.conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO bot_errors (timestamp, error_type, error_message, source,
                                            user_id, user_name, details)
                    VALUES (%s, %s, %s, %s, %s, %s, %s)
                    RETURNING id
                    """,
                    (
                        datetime.now().isoformat(),
                        error_type,
                        error_message,
                        source,
                        str(user_id),
                        user_name,
                        json.dumps(details or {}, ensure_ascii=False),
                    ),
                )
                row = cur.fetchone()
                if row:
                    entry_id = row[0]
            # Ограничиваем хранилище (максимум 5000 записей)
            self._enforce_limit()
            return {
                'id': str(entry_id) if entry_id else '',
                'timestamp': datetime.now().isoformat(),
                'error_type': error_type,
                'error_message': error_message,
                'source': source,
                'user_id': str(user_id),
                'user_name': user_name,
                'details': details or {},
            }
        except Exception as e:
            logger.error(f"Не удалось сохранить ошибку бота: {e}")
            return None

    def _enforce_limit(self):
        """Оставляет только последние 5000 записей."""
        if not pg_db.enabled:
            return
        try:
            with pg_db.conn.cursor() as cur:
                cur.execute(
                    """
                    DELETE FROM bot_errors
                    WHERE id NOT IN (
                        SELECT id FROM bot_errors ORDER BY id DESC LIMIT 5000
                    )
                    """
                )
        except Exception as e:
            logger.error(f"Ошибка при ограничении логов ошибок: {e}")

    def get_errors(
        self,
        page: int = 1,
        per_page: int = 50,
        error_type: str = 'all',
        date_from: str = '',
        date_to: str = '',
    ) -> Dict:
        """Получает ошибки с фильтрацией и пагинацией."""
        if not pg_db.enabled:
            return {'errors': [], 'page': page, 'per_page': per_page, 'total': 0, 'total_pages': 0}
        try:
            with pg_db.conn.cursor() as cur:
                # Базовый запрос с фильтрами
                where = ["1=1"]
                params: List = []
                if error_type != 'all':
                    where.append("error_type ILIKE %s")
                    params.append(f"%{error_type}%")
                if date_from:
                    where.append("timestamp >= %s")
                    params.append(date_from + 'T00:00:00')
                if date_to:
                    where.append("timestamp <= %s")
                    params.append(date_to + 'T23:59:59')
                where_sql = " AND ".join(where)

                # Общее количество
                cur.execute(f"SELECT COUNT(*) FROM bot_errors WHERE {where_sql}", tuple(params))
                total = cur.fetchone()[0]

                # Страница
                total_pages = max(1, (total + per_page - 1) // per_page)
                page = max(1, min(page, total_pages))
                offset = (page - 1) * per_page

                cur.execute(
                    f"""
                    SELECT id, timestamp, error_type, error_message, source,
                           user_id, user_name, details
                    FROM bot_errors
                    WHERE {where_sql}
                    ORDER BY id DESC
                    LIMIT %s OFFSET %s
                    """,
                    tuple(params + [per_page, offset]),
                )
                rows = cur.fetchall()

            errors = []
            for row in rows:
                errors.append({
                    'id': str(row[0]),
                    'timestamp': row[1].isoformat() if row[1] else '',
                    'error_type': row[2],
                    'error_message': row[3],
                    'source': row[4],
                    'user_id': row[5] or '',
                    'user_name': row[6] or '',
                    'details': row[7] if isinstance(row[7], dict) else (json.loads(row[7]) if row[7] else {}),
                })

            return {
                'errors': errors,
                'page': page,
                'per_page': per_page,
                'total': total,
                'total_pages': total_pages,
            }
        except Exception as e:
            logger.error(f"Ошибка при получении ошибок бота: {e}")
            return {'errors': [], 'page': page, 'per_page': per_page, 'total': 0, 'total_pages': 0}

    def clear_errors(self):
        """Очищает все сохранённые ошибки."""
        if not pg_db.enabled:
            return
        try:
            with pg_db.conn.cursor() as cur:
                cur.execute("DELETE FROM bot_errors")
        except Exception as e:
            logger.error(f"Ошибка при очистке логов ошибок: {e}")

    def get_stats(self) -> Dict:
        """Возвращает статистику по ошибкам."""
        if not pg_db.enabled:
            return {'total': 0, 'by_type': {}}
