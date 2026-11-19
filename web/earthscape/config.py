"""Settings read from the environment and from web/.env (git ignores it)."""
import os
from pathlib import Path

WEB_DIR = Path(__file__).resolve().parent.parent
ROOT_DIR = WEB_DIR.parent
ENV_FILE = WEB_DIR / ".env"


def read_env_file(path):
    """Key=value lines."""
    values = {}
    if path.exists():
        for line in path.read_text(encoding="utf-8").splitlines():
            if "=" in line and not line.lstrip().startswith("#"):
                key, value = line.split("=", 1)
                values[key.strip()] = value.strip()
    return values


_file_values = read_env_file(ENV_FILE)


def setting(name, default=None):
    """Environment first."""
    return os.environ.get(name, _file_values.get(name, default))


# Secrets
SECRET_KEY = setting("SECRET_KEY")
ENCRYPTION_KEY = setting("ENCRYPTION_KEY")
SESSION_HOURS = int(setting("SESSION_HOURS", "8"))
DEBUG = setting("DEBUG", "false").lower() == "true"
HTTPS = setting("HTTPS", "false").lower() == "true"

# MongoDB
MONGO_URI = setting("MONGO_URI", "mongodb://localhost:27017")
MONGO_DB = setting("MONGO_DB", "earthscape")

# Hadoop and ML
YARN_URL = setting("YARN_URL", "http://localhost:8088")
NAMENODE_URL = setting("NAMENODE_URL", "http://localhost:50070")
MAX_UPLOAD_BYTES = int(setting("MAX_UPLOAD_BYTES", str(1024 ** 3)))
ML_PYTHON = setting("ML_PYTHON", str(Path.home() / "anaconda3" / "python.exe"))

# Live data
LIVE_POLL_MINUTES = int(setting("LIVE_POLL_MINUTES", "15"))
LIVE_BATCH_MINUTES = int(setting("LIVE_BATCH_MINUTES", "60"))
LIVE_LOCATIONS = [
    ("Karachi", 24.86, 67.01), ("Lahore", 31.55, 74.34), ("Islamabad", 33.68, 73.05), ("Peshawar", 34.02, 71.52),
    ("Quetta", 30.18, 66.98), ("Faisalabad", 31.45, 73.14), ("Multan", 30.16, 71.52), ("Hyderabad", 25.40, 68.36),
    ("Sukkur", 27.71, 68.86), ("Sialkot", 32.49, 74.52), ("Gilgit", 35.92, 74.31), ("Gwadar", 25.13, 62.32),
]
LIVE_LOCATION_NAMES = [location[0] for location in LIVE_LOCATIONS]

# Alert email
SMTP_HOST = setting("SMTP_HOST")
SMTP_PORT = int(setting("SMTP_PORT", "587"))
SMTP_USER = setting("SMTP_USER")
SMTP_PASSWORD = setting("SMTP_PASSWORD")
SMTP_FROM = setting("SMTP_FROM")
SMTP_TLS = setting("SMTP_TLS", "true").lower() == "true"
ALERT_EMAIL_TO = setting("ALERT_EMAIL_TO")

# Operations
INSTANCE_NAME = setting("INSTANCE_NAME", "web")
BACKUP_DIR = setting("BACKUP_DIR", str(ROOT_DIR / "backups"))
BACKUP_KEEP = int(setting("BACKUP_KEEP", "7"))
MONGO_TOOLS_DIR = setting("MONGO_TOOLS_DIR", r"C:\Program Files\MongoDB\Tools\100\bin")
MONITOR_TARGETS = setting(
    "MONITOR_TARGETS",
    "backend-8000=http://127.0.0.1:8000/api/health,backend-8001=http://127.0.0.1:8001/api/health,"
    "site=https://localhost/api/health")
