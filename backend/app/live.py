"""Fetches current weather and air quality, stores it, checks alerts and archives batches to HDFS.

Open-Meteo's values are estimates from weather and atmospheric models, not sensor readings.
"""
import csv
import datetime
import json
import os
import tempfile
import urllib.error
import urllib.parse
import urllib.request

from pymongo.errors import DuplicateKeyError

from . import alert_checks, config, emailer, hadoop_client
from .db import db
from .notifications import notify

LOCATIONS = [
    ("Karachi", 24.86, 67.01), ("Delhi", 28.61, 77.21), ("Beijing", 39.90, 116.40), ("Tokyo", 35.68, 139.69),
    ("Jakarta", -6.21, 106.85), ("Sydney", -33.87, 151.21), ("Cairo", 30.04, 31.24), ("Lagos", 6.52, 3.38),
    ("Nairobi", -1.29, 36.82), ("London", 51.51, -0.13), ("New York", 40.71, -74.01), ("Sao Paulo", -23.55, -46.63),
]
LOCATION_NAMES = [location[0] for location in LOCATIONS]
WEATHER_URL = "https://api.open-meteo.com/v1/forecast"
AIR_URL = "https://air-quality-api.open-meteo.com/v1/air-quality"
WEATHER_FIELDS = {"temperature_2m": "temperature_c", "relative_humidity_2m": "humidity_pct",
                  "precipitation": "precipitation_mm", "wind_speed_10m": "wind_kmh"}
AIR_FIELDS = {"pm2_5": "pm25", "pm10": "pm10", "nitrogen_dioxide": "no2", "ozone": "o3", "us_aqi": "us_aqi"}
CSV_COLUMNS = ["location", "lat", "lon", "observed_at", "air_observed_at"] + list(WEATHER_FIELDS.values()) + list(AIR_FIELDS.values())
HDFS_DIR = "/climate/raw/live"
FETCH_ERRORS = (urllib.error.URLError, OSError, ValueError, KeyError, TypeError)
TIMEOUT_SECONDS = 20
STALE_AFTER_POLLS = 3
MAX_BATCH_ROWS = 50000


def _now():
    return datetime.datetime.now(datetime.timezone.utc)


def _get_current(url, fields):
    """Current values for every location, in the same order as LOCATIONS."""
    query = urllib.parse.urlencode({
        "latitude": ",".join(str(location[1]) for location in LOCATIONS),
        "longitude": ",".join(str(location[2]) for location in LOCATIONS),
        "current": ",".join(fields),
        "timezone": "UTC",
    })
    with urllib.request.urlopen(url + "?" + query, timeout=TIMEOUT_SECONDS) as response:
        rows = json.loads(response.read().decode("utf-8"))
    if not isinstance(rows, list) or len(rows) != len(LOCATIONS):
        raise ValueError("Open-Meteo returned an unexpected number of locations.")
    return [row["current"] for row in rows]


def _utc(text):
    return datetime.datetime.fromisoformat(text).replace(tzinfo=datetime.timezone.utc)


def _number(value):
    return value if isinstance(value, (int, float)) and not isinstance(value, bool) else None


def fetch_current():
    weather = _get_current(WEATHER_URL, WEATHER_FIELDS)
    air = _get_current(AIR_URL, AIR_FIELDS)
    readings = []
    for location, weather_row, air_row in zip(LOCATIONS, weather, air):
        reading = {"location": location[0], "lat": location[1], "lon": location[2],
                   "observed_at": _utc(weather_row["time"]), "air_observed_at": _utc(air_row["time"])}
        reading.update({name: _number(weather_row.get(key)) for key, name in WEATHER_FIELDS.items()})
        reading.update({name: _number(air_row.get(key)) for key, name in AIR_FIELDS.items()})
        readings.append(reading)
    return readings


def store_readings(readings, fetched_at):
    """Polling twice within the source's update interval updates the same record."""
    for reading in readings:
        try:
            db.live_readings.update_one(
                {"location": reading["location"], "observed_at": reading["observed_at"]},
                {"$set": dict(reading, fetched_at=fetched_at), "$setOnInsert": {"archived": False}},
                upsert=True)
        except DuplicateKeyError:
            # Another process stored this same reading a moment ago.
            pass


def _email(alerts):
    if not alerts:
        return None
    status = "not set up"
    if emailer.is_configured():
        try:
            emailer.send_alert_email(alerts)
            status = "sent"
        except Exception as error:
            status = "failed"
            notify("Alert email failed: %s" % type(error).__name__)
    db.alerts.update_many({"_id": {"$in": [alert["_id"] for alert in alerts]}}, {"$set": {"email_status": status}})
    return status


def poll(triggered_by="collector"):
    """One full cycle. A failed fetch is recorded and reported, not raised."""
    started = _now()
    previous = db.live_polls.find_one(sort=[("started_at", -1)])
    record = {"started_at": started, "triggered_by": triggered_by, "ok": True, "error": None,
              "readings": 0, "alerts_fired": 0, "alerts_cleared": 0, "email": None}
    try:
        readings = fetch_current()
    except FETCH_ERRORS as error:
        record.update(ok=False, error="%s: %s" % (type(error).__name__, error))
    else:
        store_readings(readings, started)
        fired, cleared = alert_checks.check_rules()
        alert_checks.notify_new_alerts(fired)
        record.update(readings=len(readings), alerts_fired=len(fired), alerts_cleared=cleared, email=_email(fired))
    record["seconds"] = round((_now() - started).total_seconds(), 2)
    db.live_polls.insert_one(record)
    # Only the change is worth telling people about, not every failed attempt.
    if not record["ok"] and (previous is None or previous["ok"]):
        notify("Live data collection failed: %s" % record["error"])
    if record["ok"] and previous is not None and not previous["ok"]:
        notify("Live data collection is working again.")
    return record


def _write_csv(path, rows):
    with open(path, "w", newline="", encoding="utf-8") as output:
        writer = csv.DictWriter(output, CSV_COLUMNS, extrasaction="ignore", lineterminator="\n")
        writer.writeheader()
        for row in rows:
            writer.writerow(dict(row, observed_at=row["observed_at"].isoformat(), air_observed_at=row["air_observed_at"].isoformat()))


def archive_readings():
    """Copies readings not yet in HDFS into one new file. If HDFS is down they wait for the next try."""
    rows = list(db.live_readings.find({"archived": False}).sort("observed_at", 1).limit(MAX_BATCH_ROWS))
    if not rows:
        return None
    started = _now()
    name = "live_%s.csv" % started.strftime("%Y%m%d-%H%M%S")
    batch = {"file": HDFS_DIR + "/" + name, "rows": len(rows), "finished_at": started, "ok": True, "error": None}
    with tempfile.TemporaryDirectory() as folder:
        local_path = os.path.join(folder, name)
        _write_csv(local_path, rows)
        try:
            hadoop_client.put_file(local_path, HDFS_DIR)
        except Exception as error:
            batch.update(ok=False, error=type(error).__name__)
        else:
            db.live_readings.update_many({"_id": {"$in": [row["_id"] for row in rows]}}, {"$set": {"archived": True}})
    batch["finished_at"] = _now()
    db.live_batches.insert_one(batch)
    return batch


def status():
    last_poll = db.live_polls.find_one(sort=[("started_at", -1)], projection={"_id": 0})
    last_success = db.live_polls.find_one({"ok": True}, sort=[("started_at", -1)], projection={"_id": 0})
    last_batch = db.live_batches.find_one(sort=[("finished_at", -1)], projection={"_id": 0})
    limit = datetime.timedelta(minutes=config.LIVE_POLL_MINUTES * STALE_AFTER_POLLS)
    return {
        "poll_minutes": config.LIVE_POLL_MINUTES,
        "last_poll": last_poll,
        "last_success_at": last_success["started_at"] if last_success else None,
        "stale": last_success is None or _now() - last_success["started_at"] > limit,
        "last_batch": last_batch,
        "waiting_for_hdfs": db.live_readings.count_documents({"archived": False}),
    }
