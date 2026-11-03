"""MongoDB connection and indexes."""
from pymongo import ASCENDING, MongoClient

from . import config, field_crypto

client = MongoClient(config.MONGO_URI, serverSelectionTimeoutMS=5000, tz_aware=True)
db = client[config.MONGO_DB]

HEALTH_CHECK_DAYS = 90


def encrypt_existing_fields():
    """Converts records saved before encryption was added. Safe to run on every start."""
    for user in db.users.find({"email": {"$exists": True}}):
        db.users.update_one({"_id": user["_id"], "email": user["email"]},
                            {"$set": field_crypto.email_fields(user["email"]), "$unset": {"email": ""}})
    for ticket in db.tickets.find({"description": {"$exists": True}}):
        db.tickets.update_one({"_id": ticket["_id"], "description": ticket["description"]},
                              {"$set": {"description_enc": field_crypto.encrypt(ticket["description"])},
                               "$unset": {"description": ""}})


def ensure_indexes():
    field_crypto.check_key()
    if "email_1" in db.users.index_information():
        db.users.drop_index("email_1")
    encrypt_existing_fields()
    db.users.create_index([("email_lookup", ASCENDING)], unique=True)
    # MongoDB removes revoked tokens by itself once they would have expired anyway.
    db.revoked_tokens.create_index("expires_at", expireAfterSeconds=0)
    db.login_failures.create_index("expires_at", expireAfterSeconds=0)
    db.health_checks.create_index("at", expireAfterSeconds=HEALTH_CHECK_DAYS * 24 * 3600)
    db.health_checks.create_index([("target", ASCENDING), ("at", ASCENDING)])
    db.tickets.create_index([("created_by", ASCENDING), ("created_at", ASCENDING)])
    db.alerts.create_index([("status", ASCENDING)])
    # Only one open alert per rule and place, even if two processes check at once.
    db.alerts.create_index([("rule_id", ASCENDING), ("subject", ASCENDING)], unique=True,
                           partialFilterExpression={"cleared": False})
    db.live_readings.create_index([("location", ASCENDING), ("observed_at", ASCENDING)], unique=True)
    db.live_readings.create_index([("archived", ASCENDING)])
    db.live_polls.create_index([("started_at", ASCENDING)])
