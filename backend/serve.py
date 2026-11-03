"""Runs one backend instance. Start two on different ports for Apache to balance between.

Usage: backend\\.venv\\Scripts\\python.exe backend\\serve.py [--port 8000]
"""
import argparse
import os
import sys
from pathlib import Path

import uvicorn

BACKEND_DIR = Path(__file__).resolve().parent


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=8000)
    arguments = parser.parse_args()
    os.environ["INSTANCE_NAME"] = "backend-%d" % arguments.port
    sys.path.insert(0, str(BACKEND_DIR))
    # Only Apache on this machine may say which address a request really came from.
    uvicorn.run("app.main:app", host="127.0.0.1", port=arguments.port, proxy_headers=True, forwarded_allow_ips="127.0.0.1")


if __name__ == "__main__":
    main()
