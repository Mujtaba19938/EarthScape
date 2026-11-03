"""Rebuilds this folder's samples and demo archive from the full data. Only needed if the data changes.

Usage: python test_data/make_test_data.py   (with the backend's Python)
"""
import csv
import os
import shutil
import subprocess
import sys
from itertools import islice
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "backend"))

from app import config  # noqa: E402

HERE = ROOT / "test_data"
RAW = ROOT / "data" / "raw"
SAMPLE_ROWS = 2000
# Accounts, tickets and anything about this machine's running state stay out of the archive.
NOT_IN_ARCHIVE = ["users", "tickets", "revoked_tokens", "login_failures", "locks", "notifications", "settings",
                  "health_checks", "backups", "alerts", "alert_rules", "datasets", "live_polls", "live_batches"]


def first_lines(source, target, count=SAMPLE_ROWS):
    target.parent.mkdir(exist_ok=True)
    with open(source, encoding="utf-8", errors="replace") as lines, open(target, "w", encoding="utf-8", newline="") as out:
        out.writelines(islice(lines, count))


def make_samples():
    samples = HERE / "samples"
    for year in ("2020", "2023"):
        first_lines(RAW / "ghcn_daily" / (year + ".csv"), samples / ("ghcn_daily_%s_sample.csv" % year))
    first_lines(RAW / "ghcn_daily" / "ghcnd-stations.txt", samples / "ghcnd_stations_sample.txt", 500)
    first_lines(RAW / "power" / "power_monthly.csv", samples / "nasa_power_sample.csv")
    first_lines(next(iter(sorted((RAW / "openaq").glob("*.csv")))), samples / "openaq_sample.csv")
    shutil.copy(RAW / "co2" / "co2_annmean_mlo.csv", samples / "noaa_co2_annual.csv")
    shutil.copy(RAW / "gistemp" / "GLB.Ts+dSST.csv", samples / "gistemp_global.csv")
    shutil.copy(RAW / "gistemp" / "ZonAnn.Ts+dSST.csv", samples / "gistemp_zonal.csv")


def make_upload_cases():
    uploads = HERE / "upload_cases"
    uploads.mkdir(exist_ok=True)
    with open(uploads / "valid_readings.csv", "w", encoding="utf-8", newline="") as out:
        writer = csv.writer(out)
        writer.writerow(["station", "date", "element", "value"])
        writer.writerows([["TEST0001", "2026-01-%02d" % day, "TMAX", 20 + day / 10] for day in range(1, 11)])
    # Claims to be a NetCDF file but isn't, so the upload check must refuse it.
    (uploads / "invalid_not_really.nc").write_text("This is plain text, not NetCDF.\n", encoding="utf-8")


def make_archive():
    tool = os.path.join(config.MONGO_TOOLS_DIR, "mongodump")
    excludes = ["--excludeCollection=%s" % name for name in NOT_IN_ARCHIVE]
    subprocess.run([tool, "--uri", config.MONGO_URI, "--db", "earthscape", "--gzip", "--quiet",
                    "--archive=%s" % (HERE / "demo_results.archive.gz")] + excludes, check=True)


if __name__ == "__main__":
    make_samples()
    make_upload_cases()
    make_archive()
    print("Done:", HERE)
