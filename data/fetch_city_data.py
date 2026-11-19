"""Fetches daily weather history for the live cities and NOAA's storm track record.

Writes into data/raw (ignored by git). Files already fetched are skipped, so the
script can be re-run after an interruption. Needs only the standard library.

The history comes from Open-Meteo's archive, which is the ERA5 reanalysis: a model
fitted to past observations, not readings from a station in each city.
"""
import csv
import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request

RAW = os.path.join(os.path.dirname(os.path.abspath(__file__)), "raw")
# The same cities as LIVE_LOCATIONS in web/earthscape/config.py.
CITIES = [
    ("Karachi", 24.86, 67.01), ("Lahore", 31.55, 74.34), ("Islamabad", 33.68, 73.05), ("Peshawar", 34.02, 71.52),
    ("Quetta", 30.18, 66.98), ("Faisalabad", 31.45, 73.14), ("Multan", 30.16, 71.52), ("Hyderabad", 25.40, 68.36),
    ("Sukkur", 27.71, 68.86), ("Sialkot", 32.49, 74.52), ("Gilgit", 35.92, 74.31), ("Gwadar", 25.13, 62.32),
]
START_DATE = "1980-01-01"
END_DATE = "2025-12-31"
ARCHIVE_URL = "https://archive-api.open-meteo.com/v1/archive"
DAILY = ["temperature_2m_max", "temperature_2m_min", "precipitation_sum", "wind_gusts_10m_max", "weather_code"]
COLUMNS = ["date", "tmax_c", "tmin_c", "rain_mm", "gust_kmh", "weather_code"]
IBTRACS_URL = ("https://www.ncei.noaa.gov/data/international-best-track-archive-for-climate-stewardship-ibtracs/"
               "v04r01/access/csv/ibtracs.NI.list.v04r01.csv")
RETRY_WAITS = (70, 300, 1200, 3700, 3700)
CHUNK_YEARS = 10


def get(url):
    request = urllib.request.Request(url, headers={"User-Agent": "earthscape-eproject"})
    with urllib.request.urlopen(request, timeout=180) as response:
        return response.read()


def get_with_retries(url):
    """The free archive limits requests per minute and per hour, so a refusal means wait and try again."""
    for wait in RETRY_WAITS:
        try:
            return get(url)
        except urllib.error.HTTPError as error:
            if error.code != 429:
                raise
            print("Rate limited, waiting", wait, "seconds", flush=True)
        except (TimeoutError, urllib.error.URLError) as error:
            print("No answer (", error, "), waiting", wait, "seconds", flush=True)
        time.sleep(wait)
    return get(url)


def year_chunks():
    """Asks for about ten years at a time; one 46-year request can take the archive over three minutes."""
    first, last = int(START_DATE[:4]), int(END_DATE[:4])
    for start in range(first, last + 1, CHUNK_YEARS):
        end = min(start + CHUNK_YEARS - 1, last)
        yield (START_DATE if start == first else "%d-01-01" % start), (END_DATE if end == last else "%d-12-31" % end)


def fetch_city(name, lat, lon, folder):
    target = os.path.join(folder, name.lower() + ".csv")
    if os.path.exists(target):
        return
    # Without naming one model, the archive switches to another in 2017, which shows up as false warming (over 5 °C in Gilgit).
    rows = []
    for start, end in year_chunks():
        query = urllib.parse.urlencode({"latitude": lat, "longitude": lon, "start_date": start, "end_date": end, "models": "era5",
                                        "daily": ",".join(DAILY), "timezone": "auto"})
        daily = json.loads(get_with_retries(ARCHIVE_URL + "?" + query).decode("utf-8"))["daily"]
        rows.extend(zip(daily["time"], *(daily[field] for field in DAILY)))
        time.sleep(15)  # ten years of daily data uses a large share of the per-minute allowance
    partial = target + ".part"
    with open(partial, "w", newline="", encoding="utf-8") as output:
        writer = csv.writer(output, lineterminator="\n")
        writer.writerow(["city", "lat", "lon"] + COLUMNS)
        for row in rows:
            writer.writerow([name, lat, lon] + list(row))
    os.replace(partial, target)
    print("History saved", name, len(rows), "days", flush=True)


def fetch_ibtracs():
    target = os.path.join(RAW, "ibtracs", "ibtracs.NI.list.v04r01.csv")
    if os.path.exists(target):
        return
    os.makedirs(os.path.dirname(target), exist_ok=True)
    partial = target + ".part"
    with open(partial, "wb") as output:
        output.write(get(IBTRACS_URL))
    os.replace(partial, target)
    print("Storm tracks saved", os.path.getsize(target), "bytes", flush=True)


if __name__ == "__main__":
    history = os.path.join(RAW, "city_history")
    os.makedirs(history, exist_ok=True)
    fetch_ibtracs()
    for city in CITIES:
        fetch_city(*city, history)
