"""First-time setup: writes backend/.env and creates one Admin and one Analyst.

The token secret and encryption key go into backend/.env, which git ignores. Passwords are
never saved: a new account's password is printed once, so copy it then. Existing users are left
as they are, so re-running never resets a password.

To set a new password for a seed account, run: python seed.py --reset-password admin
(or analyst). The new password is printed once, in your own terminal.
"""
import datetime
import secrets
import sys
from pathlib import Path

from cryptography.fernet import Fernet

sys.path.insert(0, str(Path(__file__).resolve().parent))

from app import config  # noqa: E402

PASSWORD_KEYS = ("SEED_ADMIN_PASSWORD", "SEED_ANALYST_PASSWORD")
DEFAULT_RULES = [
    ("Unhealthy air", "live_aqi", 150, "High"),
    ("Very high PM2.5", "air_pm25", 125, "Critical"),
    ("Extreme heat", "live_temperature", 40, "Critical"),
    ("Strong wind", "live_wind", 60, "Medium"),
]


def env_values():
    values = {
        "JWT_SECRET": secrets.token_urlsafe(48),
        "SEED_ADMIN_EMAIL": "admin@earthscape.test",
        "SEED_ANALYST_EMAIL": "analyst@earthscape.test",
        "ENCRYPTION_KEY": Fernet.generate_key().decode("ascii"),
    }
    if config.ENV_FILE.exists():
        for line in config.ENV_FILE.read_text(encoding="utf-8").splitlines():
            if "=" in line and not line.lstrip().startswith("#"):
                key, value = line.split("=", 1)
                values[key.strip()] = value.strip()
    # Older setups saved the first passwords here; they are removed and never written again.
    for key in PASSWORD_KEYS:
        values.pop(key, None)
    lines = ["%s=%s" % item for item in values.items()]
    config.ENV_FILE.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return values


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    reset = None
    if argv:
        if len(argv) != 2 or argv[0] != "--reset-password" or argv[1] not in ("admin", "analyst"):
            sys.exit("Usage: python seed.py [--reset-password admin|analyst]")
        reset = argv[1]
    values = env_values()
    config.JWT_SECRET = values["JWT_SECRET"]
    config.ENCRYPTION_KEY = values["ENCRYPTION_KEY"]

    from app.db import db, ensure_indexes
    from app.field_crypto import email_fields, email_lookup
    from app.security import hash_password

    ensure_indexes()
    people = [
        ("Administrator", "System Administrator", values["SEED_ADMIN_EMAIL"], "Admin"),
        ("Climate Analyst", "Climate Data Analyst", values["SEED_ANALYST_EMAIL"], "Analyst"),
    ]
    if reset:
        email = values["SEED_%s_EMAIL" % reset.upper()]
        password = secrets.token_urlsafe(16)
        result = db.users.update_one({"email_lookup": email_lookup(email)}, {"$set": {"password_hash": hash_password(password)}})
        if not result.matched_count:
            sys.exit("No account for %s yet. Run python seed.py first." % email)
        # On a line of its own, so selecting it in a terminal copies nothing else.
        print("New password for %s (shown only now: copy the next line):" % email)
        print(password)
        return
    for name, title, email, role in people:
        if db.users.find_one({"email_lookup": email_lookup(email)}):
            print("Already exists:", email)
            continue
        password = secrets.token_urlsafe(16)
        db.users.insert_one({
            "name": name, "title": title, **email_fields(email), "role": role, "active": True,
            "password_hash": hash_password(password),
            "created_at": datetime.datetime.now(datetime.timezone.utc),
        })
        print("Created %s with password %s (shown only now: copy it)" % (email, password))
    if db.alert_rules.count_documents({}) == 0:
        now = datetime.datetime.now(datetime.timezone.utc)
        db.alert_rules.insert_many([
            {"name": name, "metric": metric, "threshold": threshold, "severity": severity,
             "created_by": "Setup", "created_at": now}
            for name, metric, threshold, severity in DEFAULT_RULES])
        print("Created", len(DEFAULT_RULES), "alert rules")


if __name__ == "__main__":
    main()
