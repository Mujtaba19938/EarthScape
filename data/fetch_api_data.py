"""Fetches satellite-derived data (NASA POWER) and air-quality sensor data (OpenAQ).

Writes into data/raw (ignored by git). Files already fetched are skipped, so the
script can be re-run after an interruption. Needs only the standard library.
"""
import concurrent.futures
import csv
import gzip
import json
import os
import re
import time
import urllib.parse
import urllib.request

RAW = os.path.join(os.path.dirname(os.path.abspath(__file__)), "raw")
YEARS = (2020, 2023)

POWER_URL = "https://power.larc.nasa.gov/api/temporal/monthly/point"
# ALLSKY_SFC_SW_DWN comes from the CERES satellite; TS comes from the MERRA-2 model.
POWER_PARAMETERS = "ALLSKY_SFC_SW_DWN,TS"
POWER_LATITUDES = range(-60, 61, 30)
POWER_LONGITUDES = range(-150, 151, 60)
MONTHS = ["JAN", "FEB", "MAR", "APR", "MAY", "JUN", "JUL", "AUG", "SEP", "OCT", "NOV", "DEC"]

OPENAQ_URL = "https://openaq-data-archive.s3.amazonaws.com"
OPENAQ_PREFIX = "records/csv.gz/"
OPENAQ_YEAR = 2023
OPENAQ_LOCATIONS = 10
OPENAQ_MIN_DAYS = 300


def get(url):
    request = urllib.request.Request(url, headers={"User-Agent": "earthscape-eproject"})
    with urllib.request.urlopen(request, timeout=90) as response:
        return response.read()


def fetch_power():
    target = os.path.join(RAW, "power", "power_monthly.csv")
    if os.path.exists(target):
        return
    os.makedirs(os.path.dirname(target), exist_ok=True)
    rows = []
    for lat in POWER_LATITUDES:
        for lon in POWER_LONGITUDES:
            query = urllib.parse.urlencode({
                "parameters": POWER_PARAMETERS, "community": "AG", "latitude": lat,
                "longitude": lon, "start": YEARS[0], "end": YEARS[1], "format": "CSV"})
            text = get(POWER_URL + "?" + query).decode("utf-8")
            body = text.split("-END HEADER-")[1].strip().splitlines()
            for row in csv.DictReader(body):
                for number, month in enumerate(MONTHS, 1):
                    rows.append([lat, lon, row["PARAMETER"], row["YEAR"], number, row[month]])
            print("POWER", lat, lon, flush=True)
            time.sleep(1)
    with open(target, "w", newline="", encoding="utf-8") as output:
        csv.writer(output, lineterminator="\n").writerows(rows)


def list_bucket(params):
    query = urllib.parse.urlencode(dict(params, **{"list-type": 2}), safe="/=")
    return get(OPENAQ_URL + "/?" + query).decode("utf-8")


def days_available(location):
    prefix = "%s%s/year=%d/" % (OPENAQ_PREFIX, location, OPENAQ_YEAR)
    return re.findall(r"<Key>([^<]+)</Key>", list_bucket({"prefix": prefix}))


def read_records(key):
    return gzip.decompress(get(OPENAQ_URL + "/" + key)).decode("utf-8").splitlines()


def choose_locations():
    """Picks locations with a nearly full year, at most one per 20 degree grid cell."""
    cache = os.path.join(RAW, "openaq", "locations.json")
    if os.path.exists(cache):
        with open(cache) as source:
            return json.load(source)
    os.makedirs(os.path.dirname(cache), exist_ok=True)
    chosen, cells = {}, set()
    for digit in "123456789":
        listing = list_bucket({
            "delimiter": "/", "prefix": OPENAQ_PREFIX, "max-keys": 40,
            "start-after": OPENAQ_PREFIX + "locationid=" + digit})
        for location in re.findall(r"(locationid=\d+)/</Prefix></CommonPrefixes>", listing):
            if len(chosen) >= OPENAQ_LOCATIONS:
                break
            keys = days_available(location)
            if len(keys) < OPENAQ_MIN_DAYS:
                continue
            first = next(csv.DictReader(read_records(keys[0])), None)
            if not first:
                continue
            cell = (float(first["lat"]) // 20, float(first["lon"]) // 20)
            if cell not in cells:
                cells.add(cell)
                chosen[location] = keys
                print("OpenAQ chose", location, first["location"], flush=True)
    with open(cache, "w") as output:
        json.dump(chosen, output)
    return chosen


def fetch_openaq():
    for location, keys in choose_locations().items():
        target = os.path.join(RAW, "openaq", "%s-%d.csv" % (location.replace("=", "_"), OPENAQ_YEAR))
        if os.path.exists(target):
            continue
        with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
            days = list(pool.map(read_records, keys))
        with open(target, "w", newline="\n", encoding="utf-8") as output:
            for lines in days:
                output.write("\n".join(lines) + "\n")
        print("OpenAQ saved", target, flush=True)


if __name__ == "__main__":
    fetch_power()
    fetch_openaq()
