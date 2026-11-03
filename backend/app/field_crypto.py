"""Encrypts sensitive fields before they reach MongoDB.

Encrypted text is different every time, so it can't be searched. Emails also get a keyed
hash, which lets login find a user without storing a readable address.
"""
import hashlib
import hmac

from cryptography.fernet import Fernet

from . import config


def _key():
    if not config.ENCRYPTION_KEY:
        raise RuntimeError("ENCRYPTION_KEY is not set. Run backend/seed.py first.")
    return config.ENCRYPTION_KEY.encode("ascii")


def check_key():
    Fernet(_key())


def encrypt(text):
    return Fernet(_key()).encrypt(text.encode("utf-8")).decode("ascii")


def decrypt(token):
    return Fernet(_key()).decrypt(token.encode("ascii")).decode("utf-8")


def email_lookup(email):
    return hmac.new(_key(), email.encode("utf-8"), hashlib.sha256).hexdigest()


def email_fields(email):
    return {"email_enc": encrypt(email), "email_lookup": email_lookup(email)}
