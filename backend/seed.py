"""First-time setup: writes backend/.env and creates one Admin and one Analyst.

Generated passwords and the token secret go into backend/.env, which git ignores.
Existing users are left as they are, so re-running never resets a password.
"""
import datetime
import secrets
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from app import config  # noqa: E402

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
        "SEED_ADMIN_PASSWORD": secrets.token_urlsafe(16),
        "SEED_ANALYST_EMAIL": "analyst@earthscape.test",
        "SEED_ANALYST_PASSWORD": secrets.token_urlsafe(16),
    }
    if config.ENV_FILE.exists():
        for line in config.ENV_FILE.read_text(encoding="utf-8").splitlines():
            if "=" in line and not line.lstrip().startswith("#"):
                key, value = line.split("=", 1)
                values[key.strip()] = value.strip()
    lines = ["%s=%s" % item for item in values.items()]
    config.ENV_FILE.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return values


def main():
    values = env_values()
    config.JWT_SECRET = values["JWT_SECRET"]

    from app.db import db, ensure_indexes
    from app.security import hash_password

    ensure_indexes()
    people = [
        ("Administrator", "System Administrator", values["SEED_ADMIN_EMAIL"],
         values["SEED_ADMIN_PASSWORD"], "Admin"),
        ("Climate Analyst", "Climate Data Analyst", values["SEED_ANALYST_EMAIL"],
         values["SEED_ANALYST_PASSWORD"], "Analyst"),
    ]
    for name, title, email, password, role in people:
        if db.users.find_one({"email": email}):
            print("Already exists:", email)
            continue
        db.users.insert_one({
            "name": name, "title": title, "email": email, "role": role, "active": True,
            "password_hash": hash_password(password),
            "created_at": datetime.datetime.now(datetime.timezone.utc),
        })
        print("Created:", email)
    if db.alert_rules.count_documents({}) == 0:
        now = datetime.datetime.now(datetime.timezone.utc)
        db.alert_rules.insert_many([
            {"name": name, "metric": metric, "threshold": threshold, "severity": severity,
             "created_by": "Setup", "created_at": now}
            for name, metric, threshold, severity in DEFAULT_RULES])
        print("Created", len(DEFAULT_RULES), "alert rules")
    print("Sign-in details are in", config.ENV_FILE)


if __name__ == "__main__":
    main()
