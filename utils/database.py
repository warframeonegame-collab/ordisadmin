import json
import os
from datetime import datetime
import config

class Database:
    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance.db_file = config.DB_FILE
            cls._instance.data = cls._instance.load_data()
            cls._instance._create_directory()
        return cls._instance

    def __init__(self):
        pass

    def _create_directory(self):
        """Создает директорию для файла БД, если её нет"""
        directory = os.path.dirname(self.db_file)
        if directory and not os.path.exists(directory):
            os.makedirs(directory)

    def load_data(self):
        """Загружает данные из JSON-файла и автоматически добавляет недостающие поля."""
        try:
            if os.path.exists(self.db_file):
                with open(self.db_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                
                DEFAULT_FIELDS = {
                    'position': None,
                    'subdivision': None,
                    'achievements': {},
                    'warns': [],
                    'saved_roles': [],
                    'banned': False,
                    'ban_reason': None,
                    'saved_position': None,
                    'saved_subdivision': None,
                    'description': "",
                    'questionnaire': None,
                }
                
                MIGRATIONS = {
                    'discription': 'description',
                }
                
                needs_save = False
                for user_id in data:
                    # Миграция старых ключей
                    for old_key, new_key in MIGRATIONS.items():
                        if old_key in data[user_id]:
                            data[user_id][new_key] = data[user_id].pop(old_key)
                            needs_save = True
                    
                    # Добавление недостающих полей
                    for key, default_value in DEFAULT_FIELDS.items():
                        if key not in data[user_id]:
                            data[user_id][key] = default_value
                            needs_save = True
                
                # Сохраняем обновлённую структуру, если были изменения
                if needs_save:
                    with open(self.db_file, 'w', encoding='utf-8') as f:
                        json.dump(data, f, indent=4, ensure_ascii=False)
                
                return data
            return {}
        except Exception as e:
            print(f"Ошибка при загрузке данных: {str(e)}")
            return {}

    def save_data(self):
        """Сохраняет данные в JSON-файл"""
        try:
            self._create_directory()
            with open(self.db_file, 'w', encoding='utf-8') as f:
                json.dump(self.data, f, indent=4, ensure_ascii=False)
        except Exception as e:
            print(f"Ошибка при сохранении данных: {str(e)}")

    def user_exists(self, user_id):
        """Проверяет существование пользователя"""
        return str(user_id) in self.data

    def get_user(self, user_id, joined_at=None):
        """Получает данные пользователя.
        joined_at — необязательная строка даты (DD.MM.YYYY), используется при первом создании записи."""
        try:
            user_id = str(user_id)
            if user_id not in self.data:
                # Если передана конкретная дата — используем её, иначе текущую
                date_str = joined_at if joined_at else datetime.now().strftime('%d.%m.%Y')
                self.data[str(user_id)] = {
                    'nickname': '',
                    'position': None,
                    'subdivision': None,
                    'joined_at': date_str,
                    'xp': 0,
                    'description': "",
                    'level': 1,
                    'achievements': {},
                    'warns': [],
                    'saved_roles': [],
                    'banned': False,
                    'ban_reason': None,
                    'saved_position': None,
                    'saved_subdivision': None,
                    'questionnaire': None,
                }
                self.save_data()
            return self.data[user_id]  # Явно возвращаем словарь
        except Exception as e:
            print(f"Ошибка при получении данных пользователя: {str(e)}")
            return {}  # Возвращаем пустой словарь, а не None

    def update_user(self, user_id, **kwargs):
        """Обновляет данные пользователя"""
        try:
            user = self.get_user(user_id)
            if 'xp' in kwargs and kwargs['xp'] < 0:
                raise ValueError("Опыт не может быть отрицательным")
            if 'level' in kwargs and kwargs['level'] < 1:
                raise ValueError("Уровень не может быть меньше 1")
            if "position" in kwargs:
                position = kwargs["position"]
                if position is None:
                    pass  # разрешаем установить None (будет в user.update)
                elif not isinstance(position, str):
                    raise TypeError("Позиция должна быть строкой")
                elif not position.strip():
                    # Пустая строка = сброс
                    kwargs["position"] = None
                elif len(position) > 100:
                    raise ValueError("Позиция слишком длинная (максимум 100 символов)")
            
            if "subdivision" in kwargs:
                subdivision = kwargs["subdivision"]
                if subdivision is None:
                    pass
                elif not isinstance(subdivision, str):
                    raise TypeError("Подразделение должно быть строкой")
                elif not subdivision.strip() or subdivision.strip().lower() == "remove":
                    kwargs["subdivision"] = None
                elif len(subdivision) > 100:
                    raise ValueError("Подразделение слишком длинное (максимум 100 символов)")
            
            user.update(kwargs)
            self.save_data()
        except Exception as e:
            print(f"Ошибка при обновлении данных пользователя: {str(e)}")

    def add_xp(self, user_id, amount):
        try:
            if amount < 0:
                raise ValueError("Количество опыта не может быть отрицательным")
            
            user = self.get_user(user_id)
            new_xp = user['xp'] + amount
            new_level = user['level']
            
            # Рассчитываем новый уровень
            while True:
                required_xp = config.LEVEL_MULTIPLIER * new_level ** 2
                if new_xp < required_xp:
                    break
                new_level += 1
            
            # Обновляем только необходимые поля
            self.update_user(user_id, 
                             xp=new_xp,
                             level=new_level)
        
            print(f"Добавлено {amount} XP пользователю {user_id}")
        except Exception as e:
            print(f"Ошибка при добавлении опыта: {str(e)}")



    def calculate_level(self, user):
        """Рассчитывает уровень пользователя"""
        try:
            current_level = user['level']
            while True:
                required_xp = config.LEVEL_MULTIPLIER * current_level ** 2
                if user['xp'] < required_xp:
                    break
                current_level += 1
            
            if current_level != user['level']:
                user['level'] = current_level
                print(f"Уровень повышен до {current_level}")
        except Exception as e:
            print(f"Ошибка при расчете уровня: {str(e)}")

    def refresh(self, user_id=None):
        """Перезагружает данные из файла. 
        Если указан user_id, перезагружает только данные конкретного пользователя"""
        try:
            self.data = self.load_data()
            if user_id:
                # Если указан конкретный пользователь, проверяем его существование
                if str(user_id) not in self.data:
                    # Если пользователя нет в базе, создаем пустую запись
                    self.get_user(user_id)  # Используем get_user для создания профиля
                print(f"Данные пользователя {user_id} успешно обновлены")
            else:
                print("Все данные базы данных успешно обновлены")
        except Exception as e:
            print(f"Ошибка при обновлении данных: {str(e)}")

    def delete_user(self, user_id):
        """Удаляет пользователя из базы"""
        try:
            user_id = str(user_id)
            if user_id in self.data:
                del self.data[user_id]
                self.save_data()
                print(f"Пользователь {user_id} удален")
        except Exception as e:
            print(f"Ошибка при удалении пользователя: {str(e)}")

    def get_all_users(self):
        """Возвращает всех пользователей"""
        return self.data

    def __del__(self):
        """Сохраняет данные при уничтожении объекта"""
        self.save_data()
