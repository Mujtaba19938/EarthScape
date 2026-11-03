"""MongoDB connection and indexes."""
from pymongo import ASCENDING, MongoClient

from . import config

client = MongoClient(config.MONGO_URI, serverSelectionTimeoutMS=5000, tz_aware=True)
db = client[config.MONGO_DB]


def ensure_indexes():
    db.users.create_index([("email", ASCENDING)], unique=True)
    # MongoDB removes revoked tokens by itself once they would have expired anyway.
    db.revoked_tokens.create_index("expires_at", expireAfterSeconds=0)
    db.tickets.create_index([("created_by", ASCENDING), ("created_at", ASCENDING)])
    db.alerts.create_index([("status", ASCENDING)])
