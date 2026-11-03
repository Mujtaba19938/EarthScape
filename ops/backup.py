"""Backs up MongoDB and the HDFS data that can't be downloaded again, then proves the backup restores.

Usage: backend\\.venv\\Scripts\\python.exe ops\\backup.py

The downloaded raw datasets aren't copied, because data/download_data.sh can fetch them again.
backend/.env isn't copied either: keep ENCRYPTION_KEY somewhere safe, or restored emails and
tickets can't be read.
"""
import datetime
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "backend"))

from app import config, field_crypto, hadoop_client  # noqa: E402
from app.db import client, db, ensure_indexes  # noqa: E402
from app.notifications import notify  # noqa: E402

HDFS_PATHS = ["/climate/processed", "/climate/raw/live", "/climate/raw/uploads"]
FOLDER_PATTERN = re.compile(r"^\d{8}-\d{6}$")
CHECK_DB = "earthscape_restorecheck"
ALLOWED_COUNT_DIFFERENCE = 0.01
TIMEOUT_SECONDS = 1800


def _tool(name):
    return str(Path(config.MONGO_TOOLS_DIR) / name)


def _run(command):
    result = subprocess.run(command, capture_output=True, text=True, errors="replace", timeout=TIMEOUT_SECONDS)
    if result.returncode != 0:
        lines = result.stderr.strip().splitlines()
        raise RuntimeError(lines[-1] if lines else "%s failed" % command[0])


def dump_mongo(folder):
    _run([_tool("mongodump"), "--uri", config.MONGO_URI, "--db", config.MONGO_DB, "--gzip", "--out", str(folder / "mongo")])


def export_hdfs(folder):
    """Returns the paths that couldn't be copied. A missing folder shouldn't lose the MongoDB backup."""
    target = folder / "hdfs"
    target.mkdir(parents=True, exist_ok=True)
    failed = []
    for path in HDFS_PATHS:
        try:
            hadoop_client.run_pipeline.hdfs("-get", path, str(target))
        except (subprocess.CalledProcessError, OSError):
            failed.append(path)
    return failed


def counts_match(original, restored):
    """The live database keeps changing while it's copied, so small differences are expected."""
    problems = []
    for name, count in original.items():
        if name not in restored:
            problems.append("%s is missing" % name)
        elif abs(count - restored[name]) > max(10, count * ALLOWED_COUNT_DIFFERENCE):
            problems.append("%s has %d rows, expected about %d" % (name, restored[name], count))
    return problems


def verify_restore(folder):
    """Restores into a separate database, compares it with the real one, then removes it."""
    assert CHECK_DB != config.MONGO_DB
    client.drop_database(CHECK_DB)
    try:
        _run([_tool("mongorestore"), "--uri", config.MONGO_URI, "--gzip", "--drop",
              "--nsInclude", config.MONGO_DB + ".*", "--nsFrom", config.MONGO_DB + ".*", "--nsTo", CHECK_DB + ".*",
              str(folder / "mongo")])
        restored = client[CHECK_DB]
        original_counts = {name: db[name].count_documents({}) for name in db.list_collection_names()}
        restored_counts = {name: restored[name].count_documents({}) for name in restored.list_collection_names()}
        problems = counts_match(original_counts, restored_counts)
        if problems:
            raise RuntimeError("Restore check failed: " + "; ".join(problems[:3]))
        # Only proves anything if there are users, but then it proves the key still fits.
        user = restored.users.find_one({"email_enc": {"$exists": True}})
        if user:
            field_crypto.decrypt(user["email_enc"])
        return sum(restored_counts.values())
    finally:
        client.drop_database(CHECK_DB)


def folder_size(folder):
    return sum(path.stat().st_size for path in Path(folder).rglob("*") if path.is_file())


def prune(base, keep):
    """Removes the oldest backups. Only touches folders named the way this script names them."""
    folders = sorted(path for path in Path(base).iterdir() if path.is_dir() and FOLDER_PATTERN.match(path.name))
    removed = folders[:-keep] if keep > 0 else []
    for folder in removed:
        shutil.rmtree(folder)
    return [folder.name for folder in removed]


def main():
    ensure_indexes()
    started = datetime.datetime.now(datetime.timezone.utc)
    base = Path(config.BACKUP_DIR)
    folder = base / started.strftime("%Y%m%d-%H%M%S")
    record = {"folder": str(folder), "started_at": started, "ok": True, "error": None, "hdfs_failed": [], "rows_verified": 0}
    try:
        folder.mkdir(parents=True)
        dump_mongo(folder)
        record["rows_verified"] = verify_restore(folder)
        record["hdfs_failed"] = export_hdfs(folder)
        record["size_bytes"] = folder_size(folder)
        record["removed"] = prune(base, config.BACKUP_KEEP)
    except Exception as error:
        record.update(ok=False, error="%s: %s" % (type(error).__name__, error))
        notify("Backup failed: %s" % record["error"])
    record["finished_at"] = datetime.datetime.now(datetime.timezone.utc)
    record["seconds"] = round((record["finished_at"] - started).total_seconds(), 1)
    db.backups.insert_one(record)
    if record["hdfs_failed"]:
        notify("Backup finished, but these HDFS folders weren't copied: %s" % ", ".join(record["hdfs_failed"]))
    print({key: value for key, value in record.items() if key not in ("_id", "started_at", "finished_at")})
    return 0 if record["ok"] else 1


if __name__ == "__main__":
    os.chdir(str(ROOT))
    sys.exit(main())
