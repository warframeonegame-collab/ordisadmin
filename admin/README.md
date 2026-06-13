# Arasaka Plaza - Admin Panel

Админ-панель для бота Ordis2 (Warframe клан Arasaka Plaza)

## Установка

1. Установите зависимости:
```bash
cd admin
pip install -r requirements.txt
```

2. Настройте переменные окружения в файле `.env`:
```
DISCORD_CLIENT_ID=ваш_client_id
DISCORD_CLIENT_SECRET=ваш_client_secret
DISCORD_REDIRECT_URI=http://localhost:5000/callback
DISCORD_TOKEN=токен_бота
FLASK_SECRET_KEY=секретный_ключ
```

3. Поместите логотип в `admin/static/img/logo.png`

4. Запустите сервер:
```bash
python app.py
```

5. Откройте в браузере: http://localhost:5000

## Настройка Discord OAuth2

1. Перейдите в [Discord Developer Portal](https://discord.com/developers/applications)
2. Создайте приложение или выберите существующее
3. В разделе "OAuth2" добавьте Redirect URL: `http://localhost:5000/callback`
4. Скопируйте Client ID и Client Secret в `.env`

## Роли на сайте

| Роль | Описание | Права |
|------|----------|-------|
| Основатель | Полный доступ | Все права |
| Со-основатель | Доступ ко всему кроме настройек | Все права кроме settings |
| Администрация | Управление участниками | Members, Logs, Commands, Roles |
| Пользователь | Базовый доступ | Dashboard, Timers |

## Структура файлов

```
admin/
├── app.py              # Flask-приложение
├── config.py           # Настройки
├── requirements.txt    # Зависимости
├── README.md           # Документация
├── templates/          # HTML-шаблоны
│   ├── base.html
│   ├── login.html
│   ├── dashboard.html
│   ├── members.html
│   ├── member.html
│   ├── logs.html
│   ├── commands.html
│   ├── timers.html
│   ├── roles.html
│   ├── settings.html
│   └── error.html
└── static/
    ├── css/
    │   └── style.css   # Стили
    └── img/
        └── logo.png    # Логотип