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
