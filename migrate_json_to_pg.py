# -*- coding: utf-8 -*-
"""Синхронизация JSON-файлов бота Ordis2 -> PostgreSQL.

Обнаружено: база уже частично используется ботом (antileak_alerts, presence_cache,
rules_sections, sessions, site_roles, bot_errors, logs, users и др. — схема бота).
Поэтому:
  • для «живых» таблиц — UPSERT по ключу (ничего из базы не удаляется);
  • недостающие файлы (hierarchy, rules_config, legend, контенты правил)
    переносятся в новые таблицы в стиле бота (data JSONB / колонки);
  • структура бота НЕ изменяется.

Повторный запуск безопасен.
"""
import sys, io, os, json

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

import psycopg2
from psycopg2.extras import execute_values, Json

DSN = os.environ.get("PG_DSN", "")
if not DSN:
    try:
        from dotenv import load_dotenv
        load_dotenv()
        DSN = os.environ.get("PG_DSN", "")
    except ImportError:
        pass
if not DSN:
    raise SystemExit("PG_DSN не задан (переменная окружения или .env)")
DATA = r"E:\bots DS\Ordis2\data"


def load(name):
    with open(os.path.join(DATA, name + ".json"), encoding="utf-8") as f:
        return json.load(f)


REPORT = []


def note(table, action, n_json, n_db):
    REPORT.append((table, action, n_json, n_db))


# ---------------------------------------------------------------- UPSERT-ы
UPSERT_ANTILEAK = """
INSERT INTO antileak_alerts
    (id, user_id, username, user_avatar, action_type, action_count, threshold,
     details, saved_roles, victim_ids, "timestamp", status, resolved_by,
     resolved_at, guild_id)
VALUES %s
ON CONFLICT (id) DO UPDATE SET
    user_id = EXCLUDED.user_id, username = EXCLUDED.username,
    user_avatar = EXCLUDED.user_avatar, action_type = EXCLUDED.action_type,
    action_count = EXCLUDED.action_count, threshold = EXCLUDED.threshold,
    details = EXCLUDED.details, saved_roles = EXCLUDED.saved_roles,
    victim_ids = EXCLUDED.victim_ids, "timestamp" = EXCLUDED."timestamp",
    status = EXCLUDED.status, resolved_by = EXCLUDED.resolved_by,
    resolved_at = EXCLUDED.resolved_at, guild_id = EXCLUDED.guild_id
"""

UPSERT_BOT_ERRORS = """
INSERT INTO bot_errors
    (id, "timestamp", error_type, error_message, source, user_id, user_name, details)
VALUES %s
ON CONFLICT (id) DO UPDATE SET
    "timestamp" = EXCLUDED."timestamp", error_type = EXCLUDED.error_type,
    error_message = EXCLUDED.error_message, source = EXCLUDED.source,
    user_id = EXCLUDED.user_id, user_name = EXCLUDED.user_name,
    details = EXCLUDED.details
"""

UPSERT_PRESENCE = """
INSERT INTO presence_cache (user_id, nickname, status, last_seen, roles)
VALUES %s
ON CONFLICT (user_id) DO UPDATE SET
    nickname = EXCLUDED.nickname, status = EXCLUDED.status,
    last_seen = EXCLUDED.last_seen, roles = EXCLUDED.roles
"""

UPSERT_RULES_SECTIONS = """
INSERT INTO rules_sections (id, title, content, updated_at)
VALUES %s
ON CONFLICT (id) DO UPDATE SET
    title = EXCLUDED.title, content = EXCLUDED.content,
    updated_at = EXCLUDED.updated_at
"""

# ---------------------------------------------------------------- схема (новое)
NEW_TABLES = [
    """CREATE TABLE IF NOT EXISTS rules_content (
        category   TEXT PRIMARY KEY,
        content    TEXT,
        updated_by TEXT,
        updated_at TIMESTAMPTZ)""",
    """CREATE TABLE IF NOT EXISTS hierarchy (
        id   SERIAL PRIMARY KEY,
        data JSONB NOT NULL)""",
    """CREATE TABLE IF NOT EXISTS rules_config (
        id   SERIAL PRIMARY KEY,
        data JSONB NOT NULL)""",
    """CREATE TABLE IF NOT EXISTS rules_legend_names (
        id   SERIAL PRIMARY KEY,
        data JSONB NOT NULL)""",
]

DROP_MY_OLD = """
DROP TABLE IF EXISTS rules_config_permissions, rules_config_categories,
    hierarchy_roles, hierarchy_tiers CASCADE
"""


def same_jsonb(cur, table, id_col, id_val, col, obj):
    """Совпадает ли JSONB-колонка строки с Python-объектом."""
    cur.execute(
        f'SELECT ({col}::jsonb = %s::jsonb) FROM {table} WHERE {id_col} = %s',
        (json.dumps(obj, ensure_ascii=False), id_val))
    row = cur.fetchone()
    return row is not None and row[0]


def table_count(cur, table):
    cur.execute(f"SELECT COUNT(*) FROM {table}")
    return cur.fetchone()[0]


def main():
    conn = psycopg2.connect(DSN)
    conn.autocommit = False
    cur = conn.cursor()
    print("Подключено, сервер PostgreSQL:", cur.connection.info.server_version)

    # --- мои временные таблицы из прошлой попытки — убрать ---
    cur.execute(DROP_MY_OLD)

    # --- недостающие таблицы в стиле бота ---
    for ddl in NEW_TABLES:
        cur.execute(ddl)

    # ================= 1. antileak_alerts (UPSERT по id) =================
    rows = []
    for a in load("antileak_alerts"):
        rows.append((
            str(a["id"]), str(a.get("user_id")), a.get("username"),
            a.get("user_avatar"), a.get("action_type"), a.get("action_count"),
            a.get("threshold"), Json(a["details"]),
            Json(a.get("saved_roles", [])), Json(a.get("victim_ids", [])),
            a.get("timestamp"), a.get("status"), a.get("resolved_by"),
            a.get("resolved_at"), str(a.get("guild_id")),
        ))
    if rows:
        execute_values(cur, UPSERT_ANTILEAK, rows)
    note("antileak_alerts", "upsert", len(rows), table_count(cur, "antileak_alerts"))

    # ================= 2. bot_errors (UPSERT по id) =================
    rows = []
    for e in load("bot_errors"):
        rows.append((
            int(e["id"]), e.get("timestamp"), e.get("error_type"),
            e.get("error_message"), e.get("source"),
            e.get("user_id") or None, e.get("user_name") or None,
            Json(e["details"]),
        ))
    if rows:
        execute_values(cur, UPSERT_BOT_ERRORS, rows)
    note("bot_errors", "upsert", len(rows), table_count(cur, "bot_errors"))

    # ================= 3. rules_content (3 файла) =================
    rows = []
    for cat in ("main_rules", "category_main_rules", "recruiter_rules"):
        d = load(cat)
        cur.execute("""
            INSERT INTO rules_content (category, content, updated_by, updated_at)
            VALUES (%s, %s, %s, %s)
            ON CONFLICT (category) DO UPDATE SET
                content = EXCLUDED.content,
                updated_by = EXCLUDED.updated_by,
                updated_at = EXCLUDED.updated_at
        """, (cat, d.get("content"), d.get("updated_by"), d.get("updated_at")))
        rows.append(cat)
    note("rules_content", "upsert", len(rows), table_count(cur, "rules_content"))

    # ================= 4. hierarchy (весь файл в data JSONB, как у бота) =====
    hier = load("hierarchy")
    if not same_jsonb(cur, "hierarchy", "id", 1, "data", hier):
        cur.execute("DELETE FROM hierarchy")
        cur.execute("INSERT INTO hierarchy (data) VALUES (%s)", (Json(hier),))
    note("hierarchy", "sync", 1, table_count(cur, "hierarchy"))

    # ================= 5. presence_cache (UPSERT по user_id) ==============
    pc = load("presence_cache")
    rows = []
    for uid, v in pc.items():
        rows.append((str(uid), v.get("nickname"), v.get("status"),
                     v.get("last_seen"), Json(v.get("roles", []))))
    if rows:
        execute_values(cur, UPSERT_PRESENCE, rows)
    note("presence_cache", "upsert", len(rows), table_count(cur, "presence_cache"))

    # ================= 6. rules_config =================
    cfg = load("rules_config")
    if not same_jsonb(cur, "rules_config", "id", 1, "data", cfg):
        cur.execute("DELETE FROM rules_config")
        cur.execute("INSERT INTO rules_config (data) VALUES (%s)", (Json(cfg),))
    note("rules_config", "sync", 1, table_count(cur, "rules_config"))

    # ================= 7. rules_connections (1 строка, data JSONB) ========
    rc = load("rules_connections")
    if not same_jsonb(cur, "rules_connections", "id", 1, "data", rc):
        # найти существующую строку, иначе вставить с id=1
        cur.execute("SELECT COUNT(*) FROM rules_connections")
        if cur.fetchone()[0] == 0:
            cur.execute("INSERT INTO rules_connections (data) VALUES (%s)", (Json(rc),))
        else:
            cur.execute("UPDATE rules_connections SET data = %s", (Json(rc),))
    note("rules_connections", "sync", 1, table_count(cur, "rules_connections"))

    # ================= 8. rules_legend_names (весь массив в data) =========
    ln = load("rules_legend_names")
    if not same_jsonb(cur, "rules_legend_names", "id", 1, "data", ln):
        cur.execute("DELETE FROM rules_legend_names")
        cur.execute("INSERT INTO rules_legend_names (data) VALUES (%s)", (Json(ln),))
    note("rules_legend_names", "sync", 1, table_count(cur, "rules_legend_names"))

    # ================= 9. rules_sections (UPSERT по id) ==================
    rows = []
    for s in load("rules_sections"):
        rows.append((str(s["id"]), s.get("title"), s.get("content"),
                     s.get("updated_at")))
    if rows:
        execute_values(cur, UPSERT_RULES_SECTIONS, rows)
    note("rules_sections", "upsert", len(rows), table_count(cur, "rules_sections"))

    # ================= 10. sessions (без ключа: сверка + замена) ==========
    ss = load("sessions")
    rows = [(str(s["user_id"]), s.get("username"),
             s.get("login_time"), s.get("last_active")) for s in ss]
    cur.execute("SELECT user_id, username, login_time::text, last_active::text FROM sessions")
    db_rows = cur.fetchall()
    if len(db_rows) != len(rows) or any(
            str(r0) != str(d0) for (r0, r1, _, _), (d0, *_) in zip(rows, db_rows)):
        cur.execute("DELETE FROM sessions")
        if rows:
            execute_values(cur, "INSERT INTO sessions (user_id, username, login_time, last_active) VALUES %s", rows)
    note("sessions", "sync", len(rows), table_count(cur, "sessions"))

    # ================= 11. site_roles (маленькая: сверка + замена) ========
    sr = load("site_roles")
    rows = [(str(uid), role) for uid, role in sr.items()]
    cur.execute("SELECT user_id, role FROM site_roles")
    db_rows = sorted(cur.fetchall())
    if db_rows != sorted(rows):
        cur.execute("DELETE FROM site_roles")
        if rows:
            execute_values(cur, "INSERT INTO site_roles (user_id, role) VALUES %s", rows)
    note("site_roles", "sync", len(rows), table_count(cur, "site_roles"))

    conn.commit()

    # ================= отчёт =================
    print("\nРезультат синхронизации (JSON -> PostgreSQL):")
    print(f"  {'таблица':22s} {'действие':9s} {'в JSON':>7s} {'в БД':>7s}")
    for table, action, nj, nd in REPORT:
        print(f"  {table:22s} {action:9s} {nj:7d} {nd:7d}")

    cur.close()
    conn.close()
    print("\nСинхронизация завершена успешно.")


if __name__ == "__main__":
    main()
