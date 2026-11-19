"""Runs one EarthScape instance with Waitress. Start two on different ports for Apache.

Usage: web\\.venv\\Scripts\\python.exe web\\serve.py [--port 8000]
"""
import argparse
import os
import sys
from pathlib import Path

WEB_DIR = Path(__file__).resolve().parent


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=8000)
    arguments = parser.parse_args()
    # Instance name
    os.environ["INSTANCE_NAME"] = "backend-%d" % arguments.port
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "earthscape.settings")
    sys.path.insert(0, str(WEB_DIR))

    import django
    django.setup()
    from django.core.management import call_command
    from earthscape.db import ensure_indexes

    # Sessions table and Mongo indexes
    call_command("migrate", verbosity=0, interactive=False)
    ensure_indexes()

    from waitress import serve
    from earthscape.wsgi import application
    # Only Apache on this machine may set forwarded headers
    serve(application, host="127.0.0.1", port=arguments.port, threads=8,
          trusted_proxy="127.0.0.1", trusted_proxy_headers="x-forwarded-for x-forwarded-proto",
          max_request_body_size=1024 ** 3 + 10 * 1024 * 1024, ident="EarthScape")


if __name__ == "__main__":
    main()
