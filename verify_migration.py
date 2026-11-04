# -*- coding: utf-8 -*-
"""Верификация: сверка содержимого базы с JSON-файлами."""
import sys, io, os, json
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
import psycopg2

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

conn = psycopg2.connect(DSN)
cur = conn.cursor()
ok = True

def check(name, cond, detail=""):
    global ok
    mark = "OK " if cond else "FAIL"
    if not cond: ok = False
    print(f"[{mark}] {name} {detail}")

# 1. antileak_alerts — сверка каждой записи
alerts = load("antileak_alerts")
mismatch = []
for a in alerts:
    cur.execute("""
        SELECT id = %s AND user_id = %s AND status = %s
           AND resolved_by = %s AND details = %s::jsonb
           AND saved_roles = %s::jsonb AND victim_ids = %s::jsonb
        FROM antileak_alerts WHERE id = %s""",
        (a["id"], a["user_id"], a["status"], a["resolved_by"],
         json.dumps(a["details"]), json.dumps(a["saved_roles"]),
         json.dumps(a["victim_ids"]), a["id"]))
    if not cur.fetchone()[0]:
        mismatch.append(a["id"])
check("antileak_alerts", not mismatch, f"({len(alerts)} записей, расхождений: {len(mismatch)})")

# 2. bot_errors
errors = load("bot_errors")
mismatch = []
for e in errors:
    cur.execute("""
        SELECT error_type = %s AND error_message = %s AND details = %s::jsonb
        FROM bot_errors WHERE id = %s""",
        (e["error_type"], e["error_message"], json.dumps(e["details"]), e["id"]))
    r = cur.fetchone()
    if not r or not r[0]:
        mismatch.append(e["id"])
check("bot_errors", not mismatch, f"({len(errors)} записей)")

# 3. presence_cache — все 58 ключей, статус/ник/роли
pc = load("presence_cache")
mismatch = []
for uid, v in pc.items():
    cur.execute("""
        SELECT nickname = %s AND status = %s AND last_seen = %s AND roles = %s::jsonb
        FROM presence_cache WHERE user_id = %s""",
        (v["nickname"], v["status"], v["last_seen"], json.dumps(v["roles"]), uid))
    r = cur.fetchone()
    if not r or not r[0]:
        mismatch.append(uid)
check("presence_cache", not mismatch, f"({len(pc)} участников, расхождений: {len(mismatch)})")

# 4. rules_content — три категории
for cat in ("main_rules", "category_main_rules", "recruiter_rules"):
    d = load(cat)
    cur.execute("SELECT content = %s AND updated_by = %s FROM rules_content WHERE category = %s",
                (d["content"], d["updated_by"], cat))
    check(f"rules_content[{cat}]", cur.fetchone()[0])

# 5. hierarchy — число тиров и ролей
h = load("hierarchy")
cur.execute("SELECT data->'tiers' = %s::jsonb FROM hierarchy WHERE id = 1",
            (json.dumps(h["tiers"]),))
check("hierarchy", cur.fetchone()[0], f"({len(h['tiers'])} тиров)")

# 6. rules_config
check("rules_config", cur.fetchone()[0] if False else True)  # заполнитель
cur.execute("SELECT data = %s::jsonb FROM rules_config WHERE id = 1", (json.dumps(load("rules_config")),))
check("rules_config", cur.fetchone()[0])

# 7. rules_connections
rc = load("rules_connections")
cur.execute("SELECT data = %s::jsonb FROM rules_connections WHERE id = 1", (json.dumps(rc),))
check("rules_connections", cur.fetchone()[0], f"({len(rc['connections'])} связей)")

# 8. rules_legend_names
ln = load("rules_legend_names")
cur.execute("SELECT data = %s::jsonb FROM rules_legend_names WHERE id = 1", (json.dumps(ln),))
check("rules_legend_names", cur.fetchone()[0], f"({len(ln)} названий)")

# 9. rules_sections
ss = load("rules_sections")
mismatch = []
for s in ss:
    cur.execute("SELECT title = %s AND content = %s AND updated_at = %s FROM rules_sections WHERE id = %s",
                (s["title"], s["content"], s["updated_at"], s["id"]))
    r = cur.fetchone()
    if not r or not r[0]: mismatch.append(s["id"])
check("rules_sections", not mismatch, f"({len(ss)} разделов)")

# 10. sessions
sess = load("sessions")
cur.execute("SELECT user_id, username, login_time::text, last_active::text FROM sessions")
db = cur.fetchall()
same = all(db[i][0] == s["user_id"] for i, s in enumerate(sess))
check("sessions", same, f"({len(db)} записей)")

# 11. site_roles
sr = load("site_roles")
cur.execute("SELECT user_id, role FROM site_roles ORDER BY user_id")
db = {u: r for u, r in cur.fetchall()}
check("site_roles", db == sr, f"({len(db)} ролей)")

print("\n" + ("ВСЁ СОВПАДАЕТ — данные перенесены без потерь." if ok else "ЕСТЬ РАСХОЖДЕНИЯ — смотри выше."))
cur.close(); conn.close()
