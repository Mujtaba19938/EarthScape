"""Live data service. Keep it running in its own window, separate from the website.

Usage: backend\\.venv\\Scripts\\python.exe backend\\collector.py [--once]
"""
import argparse
import datetime
import sys
import time
import traceback
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from app import config, live  # noqa: E402
from app.db import ensure_indexes  # noqa: E402


def log(*parts):
    print(datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"), *parts, flush=True)


def poll_once():
    record = live.poll()
    if record["ok"]:
        log("Stored %d readings, %d new alerts, %d cleared, email: %s" % (
            record["readings"], record["alerts_fired"], record["alerts_cleared"], record["email"]))
    else:
        log("Poll failed:", record["error"])


def archive_once():
    batch = live.archive_readings()
    if batch is None:
        log("Nothing new to archive")
    elif batch["ok"]:
        log("Archived %d readings to %s" % (batch["rows"], batch["file"]))
    else:
        log("HDFS archive failed, will retry:", batch["error"])


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--once", action="store_true", help="poll and archive once, then exit")
    arguments = parser.parse_args()
    ensure_indexes()
    if arguments.once:
        poll_once()
        archive_once()
        return

    log("Collecting every %d minutes, archiving to HDFS every %d minutes. Press Ctrl+C to stop." % (
        config.LIVE_POLL_MINUTES, config.LIVE_BATCH_MINUTES))
    last_archive = time.monotonic()
    while True:
        started = time.monotonic()
        # One bad cycle, such as MongoDB restarting, shouldn't stop the service.
        try:
            poll_once()
            if time.monotonic() - last_archive >= config.LIVE_BATCH_MINUTES * 60:
                archive_once()
                last_archive = time.monotonic()
        except Exception:
            log("Cycle failed:\n" + traceback.format_exc())
        time.sleep(max(0, config.LIVE_POLL_MINUTES * 60 - (time.monotonic() - started)))


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        log("Stopped")
