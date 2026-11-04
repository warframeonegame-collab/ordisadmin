# -*- coding: utf-8 -*-
"""Осмотр существующих таблиц в целевой базе."""
import sys, io, os
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

conn = psycopg2.connect(DSN)
cur = conn.cursor()

cur.execute("""
    SELECT table_name FROM information_schema.tables
    WHERE table_schema = 'public' ORDER BY table_name
""")
tables = [r[0] for r in cur.fetchall()]
print("Таблиц в public:", len(tables))
for t in tables:
    cur.execute(f'SELECT COUNT(*) FROM "{t}"')
    cnt = cur.fetchone()[0]
    print(f"  {t:32s} строк: {cnt}")
    cur.execute(f"""
        SELECT column_name, data_type FROM information_schema.columns
        WHERE table_name = '{t}' ORDER BY ordinal_position
    """)
    cols = ", ".join(f"{c}:{d}" for c, d in cur.fetchall())
    print(f"     [{cols}]")

cur.close(); conn.close()
