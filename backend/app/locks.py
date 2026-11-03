"""Locks shared by every backend instance. Each one expires, so a crashed instance can't hold it forever."""
import datetime

from pymongo.errors import DuplicateKeyError

from .db import db


def _now():
    return datetime.datetime.now(datetime.timezone.utc)


def acquire(name, seconds):
    """Returns True if this caller now holds the lock."""
    now = _now()
    try:
        db.locks.update_one(
            {"_id": name, "expires_at": {"$lte": now}},
            {"$set": {"expires_at": now + datetime.timedelta(seconds=seconds)}},
            upsert=True)
    except DuplicateKeyError:
        return False
    return True


def release(name):
    db.locks.delete_one({"_id": name})


def is_held(name):
    return db.locks.count_documents({"_id": name, "expires_at": {"$gt": _now()}}) > 0
