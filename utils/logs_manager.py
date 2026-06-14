import json
import os
from datetime import datetime
from typing import Optional, List, Dict, Any
import config

LOGS_FILE = os.path.join(config.DATA_DIR, 'logs.json')

class LogsManager:
    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def _ensure_file(self):
        directory = os.path.dirname(LOGS_FILE)
        if directory and not os.path.exists(directory):
            os.makedirs(directory)
        if not os.path.exists(LOGS_FILE):
            with open(LOGS_FILE, 'w', encoding='utf-8') as f:
                json.dump([], f)

    def _load_logs(self) -> List[Dict]:
        self._ensure_file()
        try:
            with open(LOGS_FILE, 'r', encoding='utf-8') as f:
                return json.load(f)
        except (json.JSONDecodeError, FileNotFoundError):
            return []

    def _save_logs(self, logs: List[Dict]):
        self._ensure_file()
        with open(LOGS_FILE, 'w', encoding='utf-8') as f:
            json.dump(logs, f, indent=2, ensure_ascii=False)

    def add_log(self, log_type: str, title: str, description: str, 
                author_id: str = '', author_name: str = '', 
                color: int = 0, fields: Optional[List[Dict]] = None,
                source: str = 'discord', attachments: Optional[List[str]] = None):
        """Добавляет запись в локальный файл логов"""
        logs = self._load_logs()
        log_entry = {
            'id': str(len(logs) + 1),
            'timestamp': datetime.utcnow().isoformat(),
            'type': log_type,
            'title': title,
            'description': description,
            'author_id': author_id,
            'author_name': author_name,
            'color': color,
            'fields': fields or [],
            'source': source,
            'attachments': attachments or [],
        }
        logs.append(log_entry)
        
        # Ограничиваем размер файла (храним максимум 10000 записей)
        if len(logs) > 10000:
            logs = logs[-10000:]
        
        self._save_logs(logs)
        return log_entry

    def get_logs(self, page: int = 1, per_page: int = 50,
                 log_type: str = 'all', user_filter: str = '',
                 date_from: str = '', date_to: str = '') -> Dict[str, Any]:
        """Получает логи с фильтрацией и пагинацией"""
        logs = self._load_logs()
        
        # Фильтрация по типу
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
            logs = [
                log for log in logs
                if any(kw in log.get('title', '').lower() for kw in keywords)
            ]
        
        # Фильтрация по пользователю
        if user_filter:
            user_filter_lower = user_filter.lower()
            logs = [
                log for log in logs
                if user_filter in log.get('author_id', '') 
                or user_filter_lower in log.get('author_name', '').lower()
            ]
        
        # Фильтрация по дате
        if date_from or date_to:
            filtered = []
            for log in logs:
                try:
                    log_date = datetime.fromisoformat(log.get('timestamp', ''))
                    if date_from:
                        from_date = datetime.fromisoformat(date_from + 'T00:00:00')
                        if log_date < from_date:
                            continue
                    if date_to:
                        to_date = datetime.fromisoformat(date_to + 'T23:59:59')
                        if log_date > to_date:
                            continue
                    filtered.append(log)
                except (ValueError, TypeError):
                    filtered.append(log)
            logs = filtered
        
        # Сортировка по времени (новые сверху)
        logs.sort(key=lambda x: x.get('timestamp', ''), reverse=True)
        
        total = len(logs)
        total_pages = max(1, (total + per_page - 1) // per_page)
        page = max(1, min(page, total_pages))
        
        start = (page - 1) * per_page
        end = start + per_page
        page_logs = logs[start:end]
        
        return {
            'logs': page_logs,
            'page': page,
            'per_page': per_page,
            'total': total,
            'total_pages': total_pages,
        }

    def log_site_action(self, action: str, description: str, 
                        user_id: str = '', user_name: str = ''):
        """Логирует действие на сайте"""
        return self.add_log(
            log_type='site',
            title=f'Действие на сайте: {action}',
            description=description,
            author_id=user_id,
            author_name=user_name,
            color=0x9b59b6,
            source='site'
        )