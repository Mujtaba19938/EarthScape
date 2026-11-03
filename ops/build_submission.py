"""Builds dist/EarthScape_eProject.zip for submission. Secrets, logs, backups and large downloads stay out.

Usage: python ops/build_submission.py
"""
import subprocess
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TARGET = ROOT / "dist" / "EarthScape_eProject.zip"
TOP_FOLDER = "EarthScape"
# Ignored by git, but small and needed to retrain the models after installing. GHCN-Daily is about 2.6 GB, so it's left out.
SMALL_DATA = ["data/raw/gistemp", "data/raw/co2", "data/raw/power", "data/raw/openaq"]
EXTRA_FOLDERS = SMALL_DATA + ["video"]
FORBIDDEN_NAMES = {".env", "earthscape.key", "earthscape.crt"}
FORBIDDEN_PARTS = {"backups", "logs", ".venv", "node_modules", "__pycache__", "saved_models", "dist", ".claude"}
LEFT_OUT_SUFFIXES = {".pyc"}


def tracked_files():
    listing = subprocess.run(["git", "ls-files", "--cached", "--others", "--exclude-standard"], cwd=ROOT,
                             capture_output=True, text=True, check=True).stdout
    return [ROOT / line for line in listing.splitlines() if (ROOT / line).is_file()]


def extra_files():
    for folder in EXTRA_FOLDERS:
        path = ROOT / folder
        if path.is_dir():
            yield from (item for item in path.rglob("*") if item.is_file())


def is_allowed(path):
    relative = path.relative_to(ROOT)
    return not (FORBIDDEN_PARTS & set(relative.parts) or path.name in FORBIDDEN_NAMES or path.suffix in LEFT_OUT_SUFFIXES)


def main():
    TARGET.parent.mkdir(exist_ok=True)
    files = sorted({path for path in tracked_files() + list(extra_files()) if is_allowed(path)})
    with zipfile.ZipFile(TARGET, "w", zipfile.ZIP_DEFLATED) as archive:
        for path in files:
            archive.write(path, Path(TOP_FOLDER) / path.relative_to(ROOT))
    print("%s: %d files, %.1f MB" % (TARGET, len(files), TARGET.stat().st_size / 1024 ** 2))


if __name__ == "__main__":
    main()
