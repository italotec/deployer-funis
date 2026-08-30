import os
import zipfile

EXCLUDE_DIR_NAMES = {".claude", "__pycache__", "pix_status_cache", "logs", "data"}
EXCLUDE_EXTS = {".jsonl", ".sqlite", ".har"}
EXCLUDE_FILES = {"body.html", "req.json"}

ROOT = os.path.join("instance", "funnels")
TARGETS = ["claro", "gv"]
OUT = os.path.join("scripts", "sync_funnels.zip")


def should_skip_dir(name: str) -> bool:
    return name in EXCLUDE_DIR_NAMES


def should_skip_file(name: str) -> bool:
    if name in EXCLUDE_FILES:
        return True
    ext = os.path.splitext(name)[1].lower()
    if ext in EXCLUDE_EXTS:
        return True
    if name.endswith(".sqlite-shm") or name.endswith(".sqlite-wal"):
        return True
    return False


with zipfile.ZipFile(OUT, "w", zipfile.ZIP_DEFLATED) as z:
    for target in TARGETS:
        base = os.path.join(ROOT, target)
        for dirpath, dirnames, filenames in os.walk(base):
            dirnames[:] = [d for d in dirnames if not should_skip_dir(d)]
            for fn in filenames:
                if should_skip_file(fn):
                    continue
                full = os.path.join(dirpath, fn)
                arcname = os.path.relpath(full, ROOT).replace(os.sep, "/")
                z.write(full, arcname)

print("wrote", OUT, os.path.getsize(OUT), "bytes")
