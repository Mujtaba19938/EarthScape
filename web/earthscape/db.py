"""MongoDB connection, indexes, notifications and shared locks.

Hadoop jobs and ML training write their results to this same database.
"""
import datetime

from bson import ObjectId
from bson.errors import InvalidId
from pymongo import ASCENDING, MongoClient
from pymongo.errors import DuplicateKeyError

from . import config, crypto

client = MongoClient(config.MONGO_URI, serverSelectionTimeoutMS=5000, tz_aware=True)
db = client[config.MONGO_DB]

HEALTH_CHECK_DAYS = 90


def now():
    """Current UTC time."""
    return datetime.datetime.now(datetime.timezone.utc)


def object_id(value):
    """None when invalid."""
    try:
        return ObjectId(value)
    except (InvalidId, TypeError):
        return None


# Indexes

def encrypt_existing_fields():
    """Encrypts old records."""
    for user in db.users.find({"email": {"$exists": True}}):
        db.users.update_one({"_id": user["_id"], "email": user["email"]},
                            {"$set": crypto.email_fields(user["email"]), "$unset": {"email": ""}})
    for ticket in db.tickets.find({"description": {"$exists": True}}):
        db.tickets.update_one({"_id": ticket["_id"], "description": ticket["description"]},
                              {"$set": {"description_enc": crypto.encrypt(ticket["description"])},
                               "$unset": {"description": ""}})


def ensure_indexes():
    """Safe on every start."""
    crypto.check_key()
    if "email_1" in db.users.index_information():
        db.users.drop_index("email_1")
    encrypt_existing_fields()
    db.users.create_index([("email_lookup", ASCENDING)], unique=True)
    db.login_failures.create_index("expires_at", expireAfterSeconds=0)
    db.health_checks.create_index("at", expireAfterSeconds=HEALTH_CHECK_DAYS * 24 * 3600)
    db.health_checks.create_index([("target", ASCENDING), ("at", ASCENDING)])
    db.tickets.create_index([("created_by", ASCENDING), ("created_at", ASCENDING)])
    db.alerts.create_index([("status", ASCENDING)])
    # One open alert per rule and place
    db.alerts.create_index([("rule_id", ASCENDING), ("subject", ASCENDING)], unique=True,
                           partialFilterExpression={"cleared": False})
    db.live_readings.create_index([("location", ASCENDING), ("observed_at", ASCENDING)], unique=True)
    db.live_readings.create_index([("archived", ASCENDING)])
    db.live_polls.create_index([("started_at", ASCENDING)])
    db.newsletter.create_index([("email_lookup", ASCENDING)], unique=True)


# Notifications

def notify(text, user_id=None):
    """One user, or everyone."""
    db.notifications.insert_one({"text": text, "user_id": user_id, "read_by": [], "created_at": now()})


# Locks shared by every instance. Each expires, so a crashed process can't hold one forever.

def acquire_lock(name, seconds):
    """True when acquired."""
    moment = now()
    try:
        db.locks.update_one({"_id": name, "expires_at": {"$lte": moment}},
                            {"$set": {"expires_at": moment + datetime.timedelta(seconds=seconds)}}, upsert=True)
    except DuplicateKeyError:
        return False
    return True


def release_lock(name):
    db.locks.delete_one({"_id": name})


def lock_held(name):
    return db.locks.count_documents({"_id": name, "expires_at": {"$gt": now()}}) > 0
