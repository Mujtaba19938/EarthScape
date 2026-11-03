"""Login, profile and user management."""
import datetime
import re

from bson import ObjectId
from bson.errors import InvalidId
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from pymongo.errors import DuplicateKeyError

from . import login_limit
from .db import db
from .field_crypto import decrypt, email_fields, email_lookup
from .security import (ROLES, bearer, create_token, current_user, hash_password, require_admin,
                       revoke_token, verify_password)

router = APIRouter(prefix="/api")
EMAIL_PATTERN = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
# Compared when the email is unknown, so both failures take the same time to answer.
_DUMMY_HASH = hash_password("not-a-real-password")


class Login(BaseModel):
    email: str = Field(max_length=254)
    password: str = Field(max_length=128)


class ProfileUpdate(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    title: str = Field(default="", max_length=100)


class PasswordChange(BaseModel):
    current_password: str = Field(max_length=128)
    new_password: str = Field(min_length=10, max_length=128)


class NewUser(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    title: str = Field(default="", max_length=100)
    email: str = Field(max_length=254)
    role: str
    password: str = Field(min_length=10, max_length=128)


class UserUpdate(BaseModel):
    role: str | None = None
    active: bool | None = None


def public_user(user):
    return {
        "id": str(user["_id"]),
        "name": user["name"],
        "title": user.get("title", ""),
        "email": decrypt(user["email_enc"]),
        "role": user["role"],
        "active": user.get("active", True),
    }


@router.post("/auth/login")
def login(body: Login, request: Request):
    email = body.email.strip().lower()
    address = request.client.host if request.client else "unknown"
    if login_limit.is_blocked(email, address):
        raise HTTPException(status_code=429, detail="Too many failed sign-ins. Please try again in 15 minutes.",
                            headers={"Retry-After": str(login_limit.RETRY_AFTER_SECONDS)})
    user = db.users.find_one({"email_lookup": email_lookup(email)})
    hashed = user["password_hash"] if user else _DUMMY_HASH
    valid = verify_password(body.password, hashed)
    if not user or not valid or not user.get("active", True):
        login_limit.record_failure(email, address)
        raise HTTPException(status_code=401, detail="Incorrect email or password.")
    login_limit.clear_account(email, address)
    return {"token": create_token(user["_id"]), "user": public_user(user)}


@router.post("/auth/logout")
def logout(credentials=Depends(bearer), _user=Depends(current_user)):
    revoke_token(credentials)
    return {"ok": True}


@router.get("/auth/me")
def me(user=Depends(current_user)):
    return public_user(user)


@router.patch("/auth/me")
def update_me(body: ProfileUpdate, user=Depends(current_user)):
    db.users.update_one({"_id": user["_id"]}, {"$set": {"name": body.name.strip(), "title": body.title.strip()}})
    return public_user(db.users.find_one({"_id": user["_id"]}))


@router.post("/auth/password")
def change_password(body: PasswordChange, user=Depends(current_user)):
    if not verify_password(body.current_password, user["password_hash"]):
        raise HTTPException(status_code=400, detail="Your current password is incorrect.")
    db.users.update_one({"_id": user["_id"]}, {"$set": {"password_hash": hash_password(body.new_password)}})
    return {"ok": True}


@router.get("/users")
def list_users(_user=Depends(current_user)):
    return [public_user(user) for user in db.users.find().sort("name", 1)]


@router.post("/users", status_code=201)
def create_user(body: NewUser, _admin=Depends(require_admin)):
    email = body.email.strip().lower()
    if not EMAIL_PATTERN.match(email):
        raise HTTPException(status_code=422, detail="Enter a valid email address.")
    if body.role not in ROLES:
        raise HTTPException(status_code=422, detail="Unknown role.")
    document = {
        "name": body.name.strip(), "title": body.title.strip(), **email_fields(email), "role": body.role,
        "active": True, "password_hash": hash_password(body.password),
        "created_at": datetime.datetime.now(datetime.timezone.utc),
    }
    try:
        db.users.insert_one(document)
    except DuplicateKeyError:
        raise HTTPException(status_code=409, detail="A user with this email already exists.")
    return public_user(document)


@router.patch("/users/{user_id}")
def update_user(user_id: str, body: UserUpdate, admin=Depends(require_admin)):
    try:
        target = db.users.find_one({"_id": ObjectId(user_id)})
    except InvalidId:
        target = None
    if not target:
        raise HTTPException(status_code=404, detail="User not found.")
    if target["_id"] == admin["_id"]:
        raise HTTPException(status_code=400, detail="You can't change your own role or status.")
    changes = {}
    if body.role is not None:
        if body.role not in ROLES:
            raise HTTPException(status_code=422, detail="Unknown role.")
        changes["role"] = body.role
    if body.active is not None:
        changes["active"] = body.active
    if changes:
        db.users.update_one({"_id": target["_id"]}, {"$set": changes})
    return public_user(db.users.find_one({"_id": target["_id"]}))
