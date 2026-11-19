"""Django settings for EarthScape."""
import os
import sys

# Tests use their own database
TESTING = len(sys.argv) > 1 and sys.argv[1] == "test"
if TESTING:
    from cryptography.fernet import Fernet
    os.environ["MONGO_DB"] = "earthscape_test"
    os.environ["ENCRYPTION_KEY"] = Fernet.generate_key().decode("ascii")
    os.environ["SECRET_KEY"] = "test-secret-only-used-by-the-test-suite"

from . import config  # noqa: E402

BASE_DIR = config.WEB_DIR

# Security
SECRET_KEY = config.SECRET_KEY or "not-set-run-seed"
DEBUG = config.DEBUG
ALLOWED_HOSTS = ["localhost", "127.0.0.1", "[::1]"]
CSRF_TRUSTED_ORIGINS = ["https://localhost", "http://localhost:8000", "http://localhost:8001", "http://localhost:8002", "http://localhost:8003"]

# Apps
INSTALLED_APPS = [
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "accounts",
    "dashboard",
    "website",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
    "earthscape.middleware.instance_header",
]

ROOT_URLCONF = "earthscape.urls"
WSGI_APPLICATION = "earthscape.wsgi.application"

TEMPLATES = [{
    "BACKEND": "django.template.backends.django.DjangoTemplates",
    "DIRS": [BASE_DIR / "templates"],
    "APP_DIRS": True,
    "OPTIONS": {"context_processors": [
        "django.template.context_processors.request",
        "django.template.context_processors.csrf",
        "django.contrib.messages.context_processors.messages",
        "dashboard.context_processors.chrome",
    ]},
}]

# Django's own database: sessions only. Climate data and users live in MongoDB (earthscape/db.py).
DATABASES = {"default": {"ENGINE": "django.db.backends.sqlite3", "NAME": BASE_DIR / "django.sqlite3"}}

# Sessions
SESSION_ENGINE = "django.contrib.sessions.backends.db"
SESSION_COOKIE_AGE = config.SESSION_HOURS * 3600
SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SAMESITE = "Lax"
SESSION_COOKIE_SECURE = config.HTTPS
CSRF_COOKIE_SECURE = config.HTTPS
MESSAGE_STORAGE = "django.contrib.messages.storage.session.SessionStorage"

# Apache in front
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
SECURE_CONTENT_TYPE_NOSNIFF = True
SECURE_REFERRER_POLICY = "same-origin"
X_FRAME_OPTIONS = "DENY"

# Uploads up to 1 GB stream to disk
DATA_UPLOAD_MAX_MEMORY_SIZE = 10 * 1024 * 1024
FILE_UPLOAD_MAX_MEMORY_SIZE = 2 * 1024 * 1024

# Static files
STATIC_URL = "/static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
STATICFILES_DIRS = [BASE_DIR / "static"]

LANGUAGE_CODE = "en-us"
TIME_ZONE = "UTC"
USE_TZ = True
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

LOGGING = {
    "version": 1,
    "handlers": {"console": {"class": "logging.StreamHandler"}},
    # Quiet during tests
    "loggers": {"django": {"handlers": ["console"], "level": "ERROR" if TESTING else "WARNING"}},
}
