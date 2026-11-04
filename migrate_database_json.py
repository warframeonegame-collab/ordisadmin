# -*- coding: utf-8 -*-
"""Миграция database.json (пользователи) в PostgreSQL таблицу users."""
import sys, io, os, json
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
sys.path.insert(0, r"E:\bots DS\Ordis2")
os.chdir(r"E:\bots DS\Ordis2")

from dotenv import load_dotenv
load_dotenv()

from utils.database import Database

with open("data/database.json", encoding="utf-8") as f:
    data = json.load(f)

users = {uid: d for uid, d in data.items() if not uid.startswith('_')}
print(f"Пользователей в database.json: {len(users)}")

db = Database()
assert db.enabled, "PG не подключен"

ok, fail = 0, 0
for uid, fields in users.items():
    try:
        db.get_user(uid)  # создаёт запись с дефолтами, если её нет
        db.update_user(uid, **{k: v for k, v in fields.items() if k != 'user_id'})
        ok += 1
    except Exception as e:
        fail += 1
        print(f"  ОШИБКА {uid}: {e}")

print(f"Перенесено: {ok}, ошибок: {fail}")

# Верификация: построчная сверка
mismatch = 0
pg_users = db.get_all_users()
for uid, fields in users.items():
    row = pg_users.get(str(uid))
    if row is None:
        print(f"  НЕТ В PG: {uid}")
        mismatch += 1
        continue
    for k, v in fields.items():
        if k == 'user_id':
            continue
        pg_v = row.get(k)
        if k in ('achievements', 'warns', 'saved_roles', 'questionnaire'):
            # JSONB поля: сравниваем как объекты
            import json as _json
            if isinstance(pg_v, str):
                pg_v = _json.loads(pg_v)
        if pg_v != v:
            print(f"  РАСХОЖДЕНИЕ {uid}.{k}: json={v!r} pg={pg_v!r}")
            mismatch += 1

print(f"Сверка: {'ВСЁ СОВПАДАЕТ' if mismatch == 0 else f'{mismatch} расхождений'}")
print(f"Всего в PG users: {len(pg_users)}")
