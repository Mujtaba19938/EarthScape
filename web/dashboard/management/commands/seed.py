"""First-time setup: writes web/.env and creates one Admin and one Analyst.

The secret key and encryption key go into web/.env, which git ignores. Passwords are never
saved: a new account's password is printed once, so copy it then. Existing users are left as
they are, so running it again never resets a password.

    python manage.py seed
    python manage.py seed --reset-password admin     (or analyst)
"""
import secrets

from cryptography.fernet import Fernet
from django.core.management.base import BaseCommand, CommandError

from earthscape import config

PASSWORD_KEYS = ("SEED_ADMIN_PASSWORD", "SEED_ANALYST_PASSWORD")
DEFAULT_RULES = [
    ("Unhealthy air", "live_aqi", 150, "High"),
    ("Very high PM2.5", "air_pm25", 125, "Critical"),
    ("Extreme heat", "live_temperature", 40, "Critical"),
    ("Strong wind", "live_wind", 60, "Medium"),
]


def env_values():
    """Keep keys, drop passwords."""
    values = {
        "SECRET_KEY": secrets.token_urlsafe(48),
        "ENCRYPTION_KEY": Fernet.generate_key().decode("ascii"),
        "SEED_ADMIN_EMAIL": "admin@earthscape.test",
        "SEED_ANALYST_EMAIL": "analyst@earthscape.test",
    }
    # Existing values win
    values.update(config.read_env_file(config.ENV_FILE))
    for key in PASSWORD_KEYS:
        values.pop(key, None)
    config.ENV_FILE.write_text("".join("%s=%s\n" % item for item in values.items()), encoding="utf-8")
    return values


class Command(BaseCommand):
    help = "Write web/.env and create the seed Admin and Analyst accounts."

    def add_arguments(self, parser):
        parser.add_argument("--reset-password", choices=["admin", "analyst"],
                            help="give a seed account a new password")

    def handle(self, *args, **options):
        values = env_values()
        config.SECRET_KEY = values["SECRET_KEY"]
        config.ENCRYPTION_KEY = values["ENCRYPTION_KEY"]

        from accounts.auth import hash_password
        from earthscape.crypto import email_fields, email_lookup
        from earthscape.db import db, ensure_indexes, now

        ensure_indexes()
        reset = options.get("reset_password")
        if reset:
            email = values["SEED_%s_EMAIL" % reset.upper()]
            password = secrets.token_urlsafe(16)
            result = db.users.update_one({"email_lookup": email_lookup(email)},
                                         {"$set": {"password_hash": hash_password(password)}})
            if not result.matched_count:
                raise CommandError("No account for %s yet. Run python manage.py seed first." % email)
            # Own line, easy to copy
            self.stdout.write("New password for %s (shown only now: copy the next line):" % email)
            self.stdout.write(password)
            return

        people = [
            ("Administrator", "System Administrator", values["SEED_ADMIN_EMAIL"], "Admin"),
            ("Climate Analyst", "Climate Data Analyst", values["SEED_ANALYST_EMAIL"], "Analyst"),
        ]
        for name, title, email, role in people:
            if db.users.find_one({"email_lookup": email_lookup(email)}):
                self.stdout.write("Already exists: %s" % email)
                continue
            password = secrets.token_urlsafe(16)
            db.users.insert_one({
                "name": name, "title": title, **email_fields(email), "role": role, "active": True,
                "password_hash": hash_password(password), "created_at": now(),
            })
            self.stdout.write("Created %s with password %s (shown only now: copy it)" % (email, password))

        # Starter alert rules
        if db.alert_rules.count_documents({}) == 0:
            db.alert_rules.insert_many([
                {"name": name, "metric": metric, "threshold": threshold, "severity": severity,
                 "created_by": "Setup", "created_at": now()}
                for name, metric, threshold, severity in DEFAULT_RULES])
            self.stdout.write("Created %d alert rules" % len(DEFAULT_RULES))
