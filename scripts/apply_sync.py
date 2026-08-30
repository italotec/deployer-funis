import json
import sqlite3

conn = sqlite3.connect("instance/app.db")
cur = conn.cursor()

with open("scripts/sync_payload.json", encoding="utf-8") as f:
    data = json.load(f)

inserted = {"provider_credential": 0, "vps": 0, "domain": 0, "funnel": 0}
skipped = {"provider_credential": 0, "vps": 0, "domain": 0, "funnel": 0}

for row in data["provider_credential"]:
    cur.execute(
        "select id from provider_credential where provider=? and kind=? and label=?",
        (row["provider"], row["kind"], row["label"]),
    )
    if cur.fetchone():
        skipped["provider_credential"] += 1
        continue
    cur.execute(
        "insert into provider_credential (user_id, kind, provider, label, secret_enc, created_at) "
        "values (?,?,?,?,?,?)",
        (row["user_id"], row["kind"], row["provider"], row["label"], row["secret_enc"], row["created_at"]),
    )
    inserted["provider_credential"] += 1

for row in data["vps"]:
    cur.execute("select id from vps where ip_address=?", (row["ip_address"],))
    if cur.fetchone():
        skipped["vps"] += 1
        continue
    cur.execute(
        "insert into vps (user_id, credential_id, provider, provider_instance_id, label, ip_address, "
        "region, plan, ssh_user, ssh_port, ssh_key_enc, ssh_password_enc, status, php_installed, "
        "bootstrapped, last_message, created_at) values (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (
            row["user_id"], row["credential_id"], row["provider"], row["provider_instance_id"],
            row["label"], row["ip_address"], row["region"], row["plan"], row["ssh_user"],
            row["ssh_port"], row["ssh_key_enc"], row["ssh_password_enc"], row["status"],
            row["php_installed"], row["bootstrapped"], row["last_message"], row["created_at"],
        ),
    )
    inserted["vps"] += 1

for row in data["domain"]:
    cur.execute("select id from domain where name=?", (row["name"],))
    if cur.fetchone():
        skipped["domain"] += 1
        continue
    cur.execute(
        "insert into domain (user_id, registrar, name, registrar_order_id, status, last_message, created_at) "
        "values (?,?,?,?,?,?,?)",
        (
            row["user_id"], row["registrar"], row["name"], row["registrar_order_id"],
            row["status"], row["last_message"], row["created_at"],
        ),
    )
    inserted["domain"] += 1

for row in data["funnel"]:
    cur.execute("select id from funnel where slug=?", (row["slug"],))
    if cur.fetchone():
        skipped["funnel"] += 1
        continue
    cur.execute(
        "insert into funnel (name, slug, description, storage_path, entry_file, has_php, uploaded_by, "
        "is_active, created_at, stack, app_root) values (?,?,?,?,?,?,?,?,?,?,?)",
        (
            row["name"], row["slug"], row["description"], row["storage_path"], row["entry_file"],
            row["has_php"], row["uploaded_by"], row["is_active"], row["created_at"],
            row.get("stack"), row.get("app_root"),
        ),
    )
    inserted["funnel"] += 1

conn.commit()
print("inserted:", inserted)
print("skipped (already present):", skipped)
