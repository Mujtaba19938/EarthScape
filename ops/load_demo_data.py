"""Loads the pipeline and model results from test_data, so the dashboard has data without running Hadoop.

Usage: python ops/load_demo_data.py [--force]
Replaces only the collections in the archive. It holds no user accounts, and --force is needed if results already exist.
"""
import argparse
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "backend"))

from app import config  # noqa: E402
from app.db import db  # noqa: E402

ARCHIVE = ROOT / "test_data" / "demo_results.archive.gz"
SOURCE_DB = "earthscape"


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--force", action="store_true", help="replace results that already exist")
    args = parser.parse_args()
    if db.gistemp_global.estimated_document_count() and not args.force:
        print("Results already exist in", config.MONGO_DB, "- use --force to replace them.")
        return 1
    tool = os.path.join(config.MONGO_TOOLS_DIR, "mongorestore")
    subprocess.run([tool, "--uri", config.MONGO_URI, "--archive=%s" % ARCHIVE, "--gzip", "--drop", "--quiet",
                    "--nsFrom", SOURCE_DB + ".*", "--nsTo", config.MONGO_DB + ".*"], check=True)
    print("Loaded the demo results into", config.MONGO_DB)
    return 0


if __name__ == "__main__":
    sys.exit(main())
