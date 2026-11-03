"""Password hashing, login tokens and role checks."""
import datetime
import uuid

import bcrypt
import jwt
from bson import ObjectId
from bson.errors import InvalidId
from fastapi import Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from . import config
from .db import db

ALGORITHM = "HS256"
ROLES = ("Admin", "Analyst")
bearer = HTTPBearer(auto_error=False)


def hash_password(password):
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("ascii")


def verify_password(password, hashed):
    return bcrypt.checkpw(password.encode("utf-8"), hashed.encode("ascii"))


def create_token(user_id):
    if not config.JWT_SECRET:
        raise RuntimeError("JWT_SECRET is not set. Run backend/seed.py first.")
    now = datetime.datetime.now(datetime.timezone.utc)
    claims = {
        "sub": str(user_id),
        "jti": uuid.uuid4().hex,
        "iat": now,
        "exp": now + datetime.timedelta(hours=config.TOKEN_HOURS),
    }
    return jwt.encode(claims, config.JWT_SECRET, algorithm=ALGORITHM)


def _unauthorized():
    return HTTPException(status_code=401, detail="Please sign in.")


def decode_token(credentials):
    if credentials is None:
        raise _unauthorized()
    try:
        return jwt.decode(credentials.credentials, config.JWT_SECRET, algorithms=[ALGORITHM])
    except jwt.PyJWTError:
        raise _unauthorized()


def current_user(credentials: HTTPAuthorizationCredentials = Depends(bearer)):
    # The user is read from the database on every request, so a role change or
    # a disabled account takes effect immediately rather than when the token ends.
    claims = decode_token(credentials)
    if db.revoked_tokens.find_one({"jti": claims["jti"]}):
        raise _unauthorized()
    try:
        user = db.users.find_one({"_id": ObjectId(claims["sub"])})
    except InvalidId:
        raise _unauthorized()
    if not user or not user.get("active", True):
        raise _unauthorized()
    return user


def require_admin(user=Depends(current_user)):
    if user["role"] != "Admin":
        raise HTTPException(status_code=403, detail="Only administrators can do this.")
    return user


def revoke_token(credentials):
    claims = decode_token(credentials)
    expires_at = datetime.datetime.fromtimestamp(claims["exp"], datetime.timezone.utc)
    db.revoked_tokens.insert_one({"jti": claims["jti"], "expires_at": expires_at})
