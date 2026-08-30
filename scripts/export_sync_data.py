import json
import sqlite3

conn = sqlite3.connect("instance/app.db")
conn.row_factory = sqlite3.Row
cur = conn.cursor()

data = {}

cur.execute("select * from provider_credential where id = 1")
data["provider_credential"] = [dict(r) for r in cur.fetchall()]

cur.execute("select * from vps where id in (3,4,5)")
data["vps"] = [dict(r) for r in cur.fetchall()]

cur.execute("select * from domain where id between 6 and 22")
data["domain"] = [dict(r) for r in cur.fetchall()]

cur.execute("select * from funnel where id in (2,3)")
data["funnel"] = [dict(r) for r in cur.fetchall()]

with open("scripts/sync_payload.json", "w", encoding="utf-8") as f:
    json.dump(data, f, ensure_ascii=False, indent=2)

for k, v in data.items():
    print(k, len(v))
