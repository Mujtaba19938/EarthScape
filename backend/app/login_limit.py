"""Slows down password guessing. Counts are in MongoDB, so every backend instance shares them.

Failures count per email and address, so a stranger can't lock someone out from elsewhere,
and per address, so one machine can't try many accounts.
"""
import datetime

from pymongo.errors import DuplicateKeyError

from .db import db
from .field_crypto import email_lookup

WINDOW_MINUTES = 15
MAX_FAILURES_PER_ACCOUNT = 5
MAX_FAILURES_PER_ADDRESS = 30
RETRY_AFTER_SECONDS = WINDOW_MINUTES * 60


def _now():
    return datetime.datetime.now(datetime.timezone.utc)


def _limits(email, address):
    return [("account:%s:%s" % (email_lookup(email), address), MAX_FAILURES_PER_ACCOUNT),
            ("address:%s" % address, MAX_FAILURES_PER_ADDRESS)]


def is_blocked(email, address):
    for key, limit in _limits(email, address):
        row = db.login_failures.find_one({"_id": key})
        if row and row["expires_at"] > _now() and row["count"] >= limit:
            return True
    return False


def record_failure(email, address):
    now = _now()
    expires_at = now + datetime.timedelta(minutes=WINDOW_MINUTES)
    for key, _limit in _limits(email, address):
        # A finished window starts counting again from one.
        db.login_failures.delete_one({"_id": key, "expires_at": {"$lte": now}})
        try:
            db.login_failures.update_one(
                {"_id": key}, {"$inc": {"count": 1}, "$setOnInsert": {"expires_at": expires_at}}, upsert=True)
        except DuplicateKeyError:
            db.login_failures.update_one({"_id": key}, {"$inc": {"count": 1}})


def clear_account(email, address):
    db.login_failures.delete_one({"_id": _limits(email, address)[0][0]})
