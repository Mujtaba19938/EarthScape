"""Live data service. Keep it running in its own window, apart from the website.

    python manage.py collect_live          (runs until Ctrl+C)
    python manage.py collect_live --once   (poll and archive once)
"""
import datetime
import time
import traceback

from django.core.management.base import BaseCommand

from dashboard import live
from earthscape import config
from earthscape.db import ensure_indexes


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


class Command(BaseCommand):
    help = "Fetch live readings every few minutes, check alert rules and archive to HDFS."

    def add_arguments(self, parser):
        parser.add_argument("--once", action="store_true", help="poll and archive once, then exit")

    def handle(self, *args, **options):
        ensure_indexes()
        if options["once"]:
            poll_once()
            archive_once()
            return
        log("Collecting every %d minutes, archiving to HDFS every %d minutes. Press Ctrl+C to stop." % (
            config.LIVE_POLL_MINUTES, config.LIVE_BATCH_MINUTES))
        last_archive = time.monotonic()
        try:
            while True:
                started = time.monotonic()
                # One bad cycle shouldn't stop it
                try:
                    poll_once()
                    if time.monotonic() - last_archive >= config.LIVE_BATCH_MINUTES * 60:
                        archive_once()
                        last_archive = time.monotonic()
                except Exception:
                    log("Cycle failed:\n" + traceback.format_exc())
                time.sleep(max(0, config.LIVE_POLL_MINUTES * 60 - (time.monotonic() - started)))
        except KeyboardInterrupt:
            log("Stopped")
