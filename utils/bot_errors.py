import json
import os
from datetime import datetime
from typing import List, Dict, Optional
import config

BOT_ERRORS_FILE = os.path.join(config.DATA_DIR, 'bot_errors.json')


class BotErrorsManager:
    """Менеджер для хранения и получения логов ошибок бота."""

    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def _ensure_file(self):
        directory = os.path.dirname(BOT_ERRORS_FILE)
        if directory and not os.path.exists(directory):
            os.makedirs(directory)
        if not os.path.exists(BOT_ERRORS_FILE):
            with open(BOT_ERRORS_FILE, 'w', encoding='utf-8') as f:
                json.dump([], f)

    def _load_errors(self) -> List[Dict]:
        self._ensure_file()
        try:
            with open(BOT_ERRORS_FILE, 'r', encoding='utf-8') as f:
                return json.load(f)
        except (json.JSONDecodeError, FileNotFoundError):
            return []

    def _save_errors(self, errors: List[Dict]):
        self._ensure_file()
        with open(BOT_ERRORS_FILE, 'w', encoding='utf-8') as f:
            json.dump(errors, f, indent=2, ensure_ascii=False)

    def add_error(
        self,
        error_type: str,
        error_message: str,
        source: str = '',
        user_id: str = '',
        user_name: str = '',
        details: Optional[Dict] = None,
    ):
        """Сохраняет ошибку бота в локальный файл."""
        errors = self._load_errors()
        error_entry = {
            'id': str(len(errors) + 1),
            'timestamp': datetime.now().isoformat(),
            'error_type': error_type,
            'error_message': error_message,
            'source': source,
            'user_id': user_id,
            'user_name': user_name,
            'details': details or {},
        }
        errors.append(error_entry)

        # Ограничиваем хранилище (максимум 5000 записей)
        if len(errors) > 5000:
            errors = errors[-5000:]

        self._save_errors(errors)
        return error_entry

    def get_errors(
        self,
        page: int = 1,
        per_page: int = 50,
        error_type: str = 'all',
        date_from: str = '',
        date_to: str = '',
    ) -> Dict:
        """Получает ошибки с фильтрацией и пагинацией."""
        errors = self._load_errors()

        # Фильтрация по типу ошибки
        if error_type != 'all':
            errors = [
                e for e in errors
                if error_type.lower() in e.get('error_type', '').lower()
            ]

        # Фильтрация по дате
        if date_from or date_to:
            filtered = []
            for e in errors:
                try:
                    log_date = datetime.fromisoformat(e.get('timestamp', ''))
                    if date_from:
                        from_date = datetime.fromisoformat(date_from + 'T00:00:00')
                        if log_date < from_date:
                            continue
                    if date_to:
                        to_date = datetime.fromisoformat(date_to + 'T23:59:59')
                        if log_date > to_date:
                            continue
                    filtered.append(e)
                except (ValueError, TypeError):
                    filtered.append(e)
            errors = filtered

        # Сортировка по времени (новые сверху)
        errors.sort(key=lambda x: x.get('timestamp', ''), reverse=True)

        total = len(errors)
        total_pages = max(1, (total + per_page - 1) // per_page)
        page = max(1, min(page, total_pages))

        start = (page - 1) * per_page
        end = start + per_page
        page_errors = errors[start:end]

        return {
            'errors': page_errors,
            'page': page,
            'per_page': per_page,
            'total': total,
            'total_pages': total_pages,
        }

    def clear_errors(self):
        """Очищает все сохранённые ошибки."""
        self._save_errors([])

    def get_stats(self) -> Dict:
        """Возвращает статистику по ошибкам."""
        errors = self._load_errors()
        if not errors:
            return {'total': 0, 'by_type': {}}

        by_type = {}
        for e in errors:
            etype = e.get('error_type', 'unknown')
            by_type[etype] = by_type.get(etype, 0) + 1

        return {
            'total': len(errors),
            'by_type': dict(sorted(by_type.items(), key=lambda x: x[1], reverse=True)),
        }