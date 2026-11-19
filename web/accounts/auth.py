"""Passwords, sign-in limits, and the signed-in user for each request."""
import datetime
import functools
import re

import bcrypt
from bson import ObjectId
from bson.errors import InvalidId
from django.http import HttpResponseForbidden
from django.shortcuts import redirect
from pymongo.errors import DuplicateKeyError

from earthscape.crypto import decrypt, email_lookup
from earthscape.db import db, now

ROLES = ("Admin", "Analyst")
EMAIL_PATTERN = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
SESSION_KEY = "user_id"


# Passwords

def hash_password(password):
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("ascii")


def verify_password(password, hashed):
    return bcrypt.checkpw(password.encode("utf-8"), hashed.encode("ascii"))


# Compared for unknown emails, so both failures take the same time.
DUMMY_HASH = hash_password("not-a-real-password")


# Sign-in limits. Counts live in MongoDB, so every instance shares them.
# Failures count per email and address (a stranger can't lock someone out from elsewhere)
# and per address (one machine can't try many accounts).

WINDOW_MINUTES = 15
MAX_FAILURES_PER_ACCOUNT = 5
MAX_FAILURES_PER_ADDRESS = 30
MAX_SIGNUPS_PER_ADDRESS = 5
SIGNUP_WINDOW_MINUTES = 60


def _limits(email, address):
    return [("account:%s:%s" % (email_lookup(email), address), MAX_FAILURES_PER_ACCOUNT),
            ("address:%s" % address, MAX_FAILURES_PER_ADDRESS)]


def _over_limit(key, limit):
    row = db.login_failures.find_one({"_id": key})
    return bool(row and row["expires_at"] > now() and row["count"] >= limit)


def _count(key, minutes):
    """Adds one."""
    moment = now()
    # A finished window starts again from one
    db.login_failures.delete_one({"_id": key, "expires_at": {"$lte": moment}})
    try:
        db.login_failures.update_one({"_id": key}, {"$inc": {"count": 1}, "$setOnInsert": {
            "expires_at": moment + datetime.timedelta(minutes=minutes)}}, upsert=True)
    except DuplicateKeyError:
        db.login_failures.update_one({"_id": key}, {"$inc": {"count": 1}})


def login_blocked(email, address):
    return any(_over_limit(key, limit) for key, limit in _limits(email, address))


def record_failure(email, address):
    for key, _limit in _limits(email, address):
        _count(key, WINDOW_MINUTES)


def clear_failures(email, address):
    db.login_failures.delete_one({"_id": _limits(email, address)[0][0]})


def signup_blocked(address):
    """Stops sign-up floods."""
    return _over_limit("signup:%s" % address, MAX_SIGNUPS_PER_ADDRESS)


def record_signup(address):
    _count("signup:%s" % address, SIGNUP_WINDOW_MINUTES)


# Users

def find_user(user_id):
    try:
        return db.users.find_one({"_id": ObjectId(user_id)})
    except (InvalidId, TypeError):
        return None


def find_by_email(email):
    return db.users.find_one({"email_lookup": email_lookup(email)})


def public_user(user):
    """Safe display fields."""
    return {
        "id": str(user["_id"]),
        "name": user["name"],
        "title": user.get("title", ""),
        "email": decrypt(user["email_enc"]),
        "role": user["role"],
        "active": user.get("active", True),
        "pending": user.get("pending", False),
        "is_admin": user["role"] == "Admin",
        "initials": "".join(part[0] for part in user["name"].split()[:2]).upper(),
    }


def sign_in(request, user):
    # New session id
    request.session.cycle_key()
    request.session[SESSION_KEY] = str(user["_id"])


def sign_out(request):
    request.session.flush()


def current_user(request):
    """Read fresh each request."""
    # A role change or disabled account takes effect immediately.
    if hasattr(request, "_es_user"):
        return request._es_user
    user = find_user(request.session.get(SESSION_KEY))
    if user and (not user.get("active", True) or user.get("pending")):
        user = None
    request._es_user = public_user(user) if user else None
    if user:
        request._es_user["_id"] = user["_id"]
    return request._es_user


# View decorators

def login_required(view):
    """Signed-in users only."""
    @functools.wraps(view)
    def wrapper(request, *args, **kwargs):
        if not current_user(request):
            return redirect("/login/?next=" + request.path)
        return view(request, *args, **kwargs)
    return wrapper


def admin_required(view):
    """Admins only."""
    @functools.wraps(view)
    def wrapper(request, *args, **kwargs):
        user = current_user(request)
        if not user:
            return redirect("/login/?next=" + request.path)
        if not user["is_admin"]:
            return HttpResponseForbidden("Only administrators can do this.")
        return view(request, *args, **kwargs)
    return wrapper
