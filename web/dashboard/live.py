"""Live weather and air quality: fetch, store, check alerts, email, archive to HDFS.

Open-Meteo's values are model estimates, not sensor readings.
"""
import csv
import datetime
import json
import os
import smtplib
import tempfile
import urllib.error
import urllib.parse
import urllib.request
from email.message import EmailMessage

from pymongo.errors import DuplicateKeyError

from earthscape import config
from earthscape.db import acquire_lock, db, notify, now, release_lock

from . import cluster

LOCATIONS = config.LIVE_LOCATIONS
LOCATION_NAMES = config.LIVE_LOCATION_NAMES
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
POLL_LOCK = "live_poll"
POLL_LOCK_SECONDS = 120
MAX_NAMES_IN_NOTIFICATION = 3


# Fetching

def _get_current(url, fields):
    """One row per city."""
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
    """Weather plus air."""
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
    """Same hour, same record."""
    for reading in readings:
        try:
            db.live_readings.update_one(
                {"location": reading["location"], "observed_at": reading["observed_at"]},
                {"$set": dict(reading, fetched_at=fetched_at), "$setOnInsert": {"archived": False}},
                upsert=True)
        except DuplicateKeyError:
            # Another process stored it
            pass


def latest_readings():
    """Newest per city."""
    rows = db.live_readings.aggregate([
        {"$match": {"location": {"$in": LOCATION_NAMES}}},
        {"$sort": {"observed_at": -1}},
        {"$group": {"_id": "$location", "reading": {"$first": "$$ROOT"}}},
        {"$replaceRoot": {"newRoot": "$reading"}},
        {"$sort": {"location": 1}},
    ])
    return list(rows)


# Alert metrics

def _live(field):
    def read():
        return [(row["location"], row[field]) for row in latest_readings() if row.get(field) is not None]
    return read


def _latest_global_anomaly():
    row = db.gistemp_global.find_one({"J-D": {"$ne": None}}, sort=[("Year", -1)])
    return [("Global, %s" % row["Year"], row["J-D"])] if row else []


def _latest_co2():
    row = db.co2_annual.find_one(sort=[("year", -1)])
    return [("Mauna Loa, %s" % row["year"], row["mean"])] if row else []


def _highest_station_z():
    row = db.station_anomalies.find_one(sort=[("z_score", -1)])
    return [("Highest station reading", row["z_score"])] if row else []


# key: (label, unit, reader)
METRICS = {
    "air_pm25": ("Live PM2.5 (µg/m³)", "µg/m³", _live("pm25")),
    "air_pm10": ("Live PM10 (µg/m³)", "µg/m³", _live("pm10")),
    "live_no2": ("Live nitrogen dioxide (µg/m³)", "µg/m³", _live("no2")),
    "live_ozone": ("Live ozone (µg/m³)", "µg/m³", _live("o3")),
    "live_aqi": ("Live US air quality index", "AQI", _live("us_aqi")),
    "live_temperature": ("Live temperature (°C)", "°C", _live("temperature_c")),
    "live_wind": ("Live wind speed (km/h)", "km/h", _live("wind_kmh")),
    "live_precipitation": ("Live precipitation (mm)", "mm", _live("precipitation_mm")),
    "global_anomaly": ("Global temperature anomaly (°C), latest year", "°C", _latest_global_anomaly),
    "co2": ("Atmospheric CO2 (ppm), latest year", "ppm", _latest_co2),
    "station_temperature_z": ("Station temperature z-score, highest stored", "z", _highest_station_z),
}
ALERT_METRICS = {key: metric[0] for key, metric in METRICS.items()}
LIVE_METRICS = [key for key in METRICS if key.startswith(("air_", "live_"))]


# Alert checks

def _describe(value, unit, threshold):
    return "%g %s (limit %g)" % (value, unit, threshold)


def _open_or_update(rule, subject, value, unit, moment):
    """New alert, or None."""
    # While a value stays high it stays one alert, so a hand-resolved alert
    # doesn't come back until the value clears first.
    rule_id = str(rule["_id"])
    text = _describe(value, unit, rule["threshold"])
    updated = db.alerts.update_one({"rule_id": rule_id, "subject": subject, "cleared": False},
                                   {"$set": {"measured": value, "value": text, "last_seen_at": moment}})
    if updated.matched_count:
        return None
    alert = {
        "rule_id": rule_id, "rule_name": rule["name"], "metric": rule["metric"], "subject": subject,
        "severity": rule["severity"], "title": "%s: %s" % (rule["name"], subject), "measured": value,
        "value": text, "status": "Active", "cleared": False, "created_at": moment, "last_seen_at": moment,
    }
    try:
        db.alerts.insert_one(alert)
    except DuplicateKeyError:
        return None
    return alert


def _clear(query, reason, moment):
    """Closes matching alerts."""
    cleared = 0
    for alert in db.alerts.find(dict(query, cleared=False)):
        changes = {"cleared": True, "cleared_at": moment}
        if alert["status"] != "Resolved":
            changes.update(status="Resolved", updated_by=reason, updated_at=moment)
        db.alerts.update_one({"_id": alert["_id"]}, {"$set": changes})
        cleared += 1
    return cleared


def check_rules():
    """Returns (fired, cleared)."""
    moment = now()
    rules = list(db.alert_rules.find())
    cleared = _clear({"rule_id": {"$nin": [str(rule["_id"]) for rule in rules]}}, "Rule deleted", moment)
    # Cities no longer polled
    cleared += _clear({"metric": {"$in": LIVE_METRICS}, "subject": {"$nin": LOCATION_NAMES}}, "City no longer monitored", moment)
    values_by_metric = {}
    fired = []
    for rule in rules:
        if rule["metric"] not in METRICS:
            continue
        _label, unit, read = METRICS[rule["metric"]]
        if rule["metric"] not in values_by_metric:
            values_by_metric[rule["metric"]] = read()
        for subject, value in values_by_metric[rule["metric"]]:
            if value > rule["threshold"]:
                alert = _open_or_update(rule, subject, value, unit, moment)
                if alert:
                    fired.append(alert)
            else:
                cleared += _clear({"rule_id": str(rule["_id"]), "subject": subject}, "Automatic check", moment)
    return fired, cleared


def summarise(alerts):
    names = [alert["title"] for alert in alerts[:MAX_NAMES_IN_NOTIFICATION]]
    extra = len(alerts) - len(names)
    return "; ".join(names) + (" and %d more" % extra if extra else "")


def notify_new_alerts(alerts):
    if alerts:
        notify("%d new alert%s: %s" % (len(alerts), "" if len(alerts) == 1 else "s", summarise(alerts)))


# Alert email

def email_recipients():
    return [address.strip() for address in (config.ALERT_EMAIL_TO or "").split(",") if address.strip()]


def email_configured():
    return bool(config.SMTP_HOST and email_recipients())


def _smtp():
    if config.SMTP_PORT == 465:
        return smtplib.SMTP_SSL(config.SMTP_HOST, config.SMTP_PORT, timeout=TIMEOUT_SECONDS)
    server = smtplib.SMTP(config.SMTP_HOST, config.SMTP_PORT, timeout=TIMEOUT_SECONDS)
    if config.SMTP_TLS:
        server.starttls()
    return server


def send_alert_email(alerts):
    """One email, many alerts."""
    message = EmailMessage()
    message["Subject"] = "EarthScape: %d new alert%s" % (len(alerts), "" if len(alerts) == 1 else "s")
    message["From"] = config.SMTP_FROM or config.SMTP_USER or "earthscape@localhost"
    message["To"] = ", ".join(email_recipients())
    lines = ["[%s] %s\n    Measured: %s" % (alert["severity"], alert["title"], alert["value"]) for alert in alerts]
    message.set_content("\n\n".join(lines) + "\n\nLive values are model estimates from Open-Meteo.\n")
    with _smtp() as server:
        if config.SMTP_USER:
            server.login(config.SMTP_USER, config.SMTP_PASSWORD or "")
        server.send_message(message)


def _email(alerts):
    """Email status."""
    if not alerts:
        return None
    status = "not set up"
    if email_configured():
        try:
            send_alert_email(alerts)
            status = "sent"
        except Exception as error:
            status = "failed"
            notify("Alert email failed: %s" % type(error).__name__)
    db.alerts.update_many({"_id": {"$in": [alert["_id"] for alert in alerts]}}, {"$set": {"email_status": status}})
    return status


# Poll cycle

def poll(triggered_by="collector"):
    """One full cycle."""
    # A failed fetch is recorded, not raised
    started = now()
    previous = db.live_polls.find_one(sort=[("started_at", -1)])
    record = {"started_at": started, "triggered_by": triggered_by, "ok": True, "error": None,
              "readings": 0, "alerts_fired": 0, "alerts_cleared": 0, "email": None}
    try:
        readings = fetch_current()
    except FETCH_ERRORS as error:
        record.update(ok=False, error="%s: %s" % (type(error).__name__, error))
    else:
        store_readings(readings, started)
        fired, cleared = check_rules()
        notify_new_alerts(fired)
        record.update(readings=len(readings), alerts_fired=len(fired), alerts_cleared=cleared, email=_email(fired))
    record["seconds"] = round((now() - started).total_seconds(), 2)
    db.live_polls.insert_one(record)
    # Only report changes
    if not record["ok"] and (previous is None or previous["ok"]):
        notify("Live data collection failed: %s" % record["error"])
    if record["ok"] and previous is not None and not previous["ok"]:
        notify("Live data collection is working again.")
    return record


def poll_now(username):
    """Admin's Check now."""
    if not acquire_lock(POLL_LOCK, POLL_LOCK_SECONDS):
        return None, "A check is already running."
    try:
        record = poll(username)
    finally:
        release_lock(POLL_LOCK)
    if not record["ok"]:
        return record, "Couldn't reach Open-Meteo. Try again shortly."
    return record, None


# HDFS archive

def _write_csv(path, rows):
    with open(path, "w", newline="", encoding="utf-8") as output:
        writer = csv.DictWriter(output, CSV_COLUMNS, extrasaction="ignore", lineterminator="\n")
        writer.writeheader()
        for row in rows:
            writer.writerow(dict(row, observed_at=row["observed_at"].isoformat(), air_observed_at=row["air_observed_at"].isoformat()))


def archive_readings():
    """New rows to HDFS."""
    # If HDFS is down they wait for the next try
    rows = list(db.live_readings.find({"archived": False}).sort("observed_at", 1).limit(MAX_BATCH_ROWS))
    if not rows:
        return None
    started = now()
    name = "live_%s.csv" % started.strftime("%Y%m%d-%H%M%S")
    batch = {"file": HDFS_DIR + "/" + name, "rows": len(rows), "finished_at": started, "ok": True, "error": None}
    with tempfile.TemporaryDirectory() as folder:
        local_path = os.path.join(folder, name)
        _write_csv(local_path, rows)
        try:
            cluster.put_file(local_path, HDFS_DIR)
        except Exception as error:
            batch.update(ok=False, error=type(error).__name__)
        else:
            db.live_readings.update_many({"_id": {"$in": [row["_id"] for row in rows]}}, {"$set": {"archived": True}})
    batch["finished_at"] = now()
    db.live_batches.insert_one(batch)
    return batch


def status():
    """Collector health."""
    last_poll = db.live_polls.find_one(sort=[("started_at", -1)], projection={"_id": 0})
    last_success = db.live_polls.find_one({"ok": True}, sort=[("started_at", -1)], projection={"_id": 0})
    last_batch = db.live_batches.find_one(sort=[("finished_at", -1)], projection={"_id": 0})
    limit = datetime.timedelta(minutes=config.LIVE_POLL_MINUTES * STALE_AFTER_POLLS)
    return {
        "poll_minutes": config.LIVE_POLL_MINUTES,
        "last_poll": last_poll,
        "last_success_at": last_success["started_at"] if last_success else None,
        "stale": last_success is None or now() - last_success["started_at"] > limit,
        "last_batch": last_batch,
        "waiting_for_hdfs": db.live_readings.count_documents({"archived": False}),
    }
