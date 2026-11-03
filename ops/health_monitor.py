"""Checks each backend instance and the public site, and records the results.

Usage: backend\\.venv\\Scripts\\python.exe ops\\health_monitor.py [--loop SECONDS]
"""
import argparse
import datetime
import logging
import logging.handlers
import ssl
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "backend"))

from app import config  # noqa: E402
from app.db import db, ensure_indexes  # noqa: E402
from app.notifications import notify  # noqa: E402

CERTIFICATE = ROOT / "deploy" / "apache" / "certs" / "earthscape.crt"
LOG_FILE = ROOT / "logs" / "health.log"
TIMEOUT_SECONDS = 10

logger = logging.getLogger("earthscape.health")


def targets():
    pairs = (entry.split("=", 1) for entry in config.MONITOR_TARGETS.split(",") if "=" in entry)
    return {name.strip(): url.strip() for name, url in pairs}


def _ssl_context():
    # The site's certificate is self-signed, so it's the one certificate worth trusting here.
    return ssl.create_default_context(cafile=str(CERTIFICATE)) if CERTIFICATE.exists() else ssl.create_default_context()


def check(url):
    started = time.monotonic()
    result = {"ok": False, "status": None, "error": None}
    try:
        context = _ssl_context() if url.startswith("https") else None
        with urllib.request.urlopen(url, timeout=TIMEOUT_SECONDS, context=context) as response:
            result.update(ok=response.status == 200, status=response.status)
    except urllib.error.HTTPError as error:
        result.update(status=error.code, error="HTTP %d" % error.code)
    except (urllib.error.URLError, OSError) as error:
        result["error"] = type(error).__name__
    result["ms"] = round((time.monotonic() - started) * 1000)
    return result


def record(name, result):
    """Saves one result, and tells people only when a target goes down or comes back."""
    previous = db.health_checks.find_one({"target": name}, sort=[("at", -1)])
    db.health_checks.insert_one(dict(result, target=name, at=datetime.datetime.now(datetime.timezone.utc)))
    if previous is not None and previous["ok"] != result["ok"]:
        notify("%s is %s." % (name, "back up" if result["ok"] else "down"))


def run_once():
    for name, url in targets().items():
        result = check(url)
        logger.info("%s ok=%s status=%s ms=%s error=%s", name, result["ok"], result["status"], result["ms"], result["error"])
        record(name, result)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--loop", type=int, help="keep checking every this many seconds")
    arguments = parser.parse_args()
    LOG_FILE.parent.mkdir(exist_ok=True)
    handler = logging.handlers.RotatingFileHandler(LOG_FILE, maxBytes=5 * 1024 * 1024, backupCount=3, encoding="utf-8")
    handler.setFormatter(logging.Formatter("%(asctime)s %(message)s"))
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)
    ensure_indexes()
    while True:
        # If MongoDB itself is down the log file still shows what happened.
        try:
            run_once()
        except Exception as error:
            logger.error("Check failed: %s: %s", type(error).__name__, error)
        if not arguments.loop:
            return
        time.sleep(arguments.loop)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        pass
