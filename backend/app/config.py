"""Settings, read from the environment and from backend/.env (ignored by git)."""
import os
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent.parent
ROOT_DIR = BACKEND_DIR.parent
FRONTEND_DIR = ROOT_DIR / "frontend"
ENV_FILE = BACKEND_DIR / ".env"


def _read_env_file():
    values = {}
    if ENV_FILE.exists():
        for line in ENV_FILE.read_text(encoding="utf-8").splitlines():
            if "=" in line and not line.lstrip().startswith("#"):
                key, value = line.split("=", 1)
                values[key.strip()] = value.strip()
    return values


_file_values = _read_env_file()


def setting(name, default=None):
    return os.environ.get(name, _file_values.get(name, default))


MONGO_URI = setting("MONGO_URI", "mongodb://localhost:27017")
MONGO_DB = setting("MONGO_DB", "earthscape")
JWT_SECRET = setting("JWT_SECRET")
TOKEN_HOURS = int(setting("TOKEN_HOURS", "8"))
YARN_URL = setting("YARN_URL", "http://localhost:8088")
NAMENODE_URL = setting("NAMENODE_URL", "http://localhost:50070")
MAX_UPLOAD_BYTES = int(setting("MAX_UPLOAD_BYTES", str(1024 ** 3)))
ML_PYTHON = setting("ML_PYTHON", str(Path.home() / "anaconda3" / "python.exe"))
LIVE_POLL_MINUTES = int(setting("LIVE_POLL_MINUTES", "15"))
LIVE_BATCH_MINUTES = int(setting("LIVE_BATCH_MINUTES", "60"))
LIVE_LOCATIONS = [
    ("Karachi", 24.86, 67.01), ("Lahore", 31.55, 74.34), ("Islamabad", 33.68, 73.05), ("Peshawar", 34.02, 71.52),
    ("Quetta", 30.18, 66.98), ("Faisalabad", 31.45, 73.14), ("Multan", 30.16, 71.52), ("Hyderabad", 25.40, 68.36),
    ("Sukkur", 27.71, 68.86), ("Sialkot", 32.49, 74.52), ("Gilgit", 35.92, 74.31), ("Gwadar", 25.13, 62.32),
]
LIVE_LOCATION_NAMES = [location[0] for location in LIVE_LOCATIONS]
SMTP_HOST = setting("SMTP_HOST")
SMTP_PORT = int(setting("SMTP_PORT", "587"))
SMTP_USER = setting("SMTP_USER")
SMTP_PASSWORD = setting("SMTP_PASSWORD")
SMTP_FROM = setting("SMTP_FROM")
SMTP_TLS = setting("SMTP_TLS", "true").lower() == "true"
ALERT_EMAIL_TO = setting("ALERT_EMAIL_TO")
ENCRYPTION_KEY = setting("ENCRYPTION_KEY")
INSTANCE_NAME = setting("INSTANCE_NAME", "backend")
BACKUP_DIR = setting("BACKUP_DIR", str(ROOT_DIR / "backups"))
BACKUP_KEEP = int(setting("BACKUP_KEEP", "7"))
MONGO_TOOLS_DIR = setting("MONGO_TOOLS_DIR", r"C:\Program Files\MongoDB\Tools\100\bin")
MONITOR_TARGETS = setting(
    "MONITOR_TARGETS",
    "backend-8000=http://127.0.0.1:8000/api/health,backend-8001=http://127.0.0.1:8001/api/health,"
    "site=https://localhost/api/health")
