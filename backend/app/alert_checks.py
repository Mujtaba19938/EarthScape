"""Compares alert rules with the latest values, and opens or clears alerts."""
import datetime

from pymongo.errors import DuplicateKeyError

from .db import db
from .notifications import notify

MAX_NAMES_IN_NOTIFICATION = 3


def latest_readings():
    """The newest live reading for each location."""
    rows = db.live_readings.aggregate([
        {"$sort": {"observed_at": -1}},
        {"$group": {"_id": "$location", "reading": {"$first": "$$ROOT"}}},
        {"$replaceRoot": {"newRoot": "$reading"}},
        {"$sort": {"location": 1}},
    ])
    return list(rows)


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


# key: (label, unit, function returning (subject, value) pairs)
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


def _now():
    return datetime.datetime.now(datetime.timezone.utc)


def _describe(value, unit, threshold):
    return "%g %s (limit %g)" % (value, unit, threshold)


def _open_or_update(rule, subject, value, unit, now):
    """Returns the alert if this is a new one. While a value stays above the limit it stays
    one alert, so someone who resolves it by hand isn't alerted again until it clears first."""
    rule_id = str(rule["_id"])
    text = _describe(value, unit, rule["threshold"])
    updated = db.alerts.update_one(
        {"rule_id": rule_id, "subject": subject, "cleared": False},
        {"$set": {"measured": value, "value": text, "last_seen_at": now}})
    if updated.matched_count:
        return None
    alert = {
        "rule_id": rule_id, "rule_name": rule["name"], "metric": rule["metric"], "subject": subject,
        "severity": rule["severity"], "title": "%s: %s" % (rule["name"], subject), "measured": value,
        "value": text, "status": "Active", "cleared": False, "created_at": now, "last_seen_at": now,
    }
    try:
        db.alerts.insert_one(alert)
    except DuplicateKeyError:
        # Another process opened the same alert a moment ago.
        return None
    return alert


def _clear(query, reason, now):
    cleared = 0
    for alert in db.alerts.find(dict(query, cleared=False)):
        changes = {"cleared": True, "cleared_at": now}
        if alert["status"] != "Resolved":
            changes.update(status="Resolved", updated_by=reason, updated_at=now)
        db.alerts.update_one({"_id": alert["_id"]}, {"$set": changes})
        cleared += 1
    return cleared


def check_rules():
    """Checks every rule. Returns (new alerts, number cleared)."""
    now = _now()
    rules = list(db.alert_rules.find())
    cleared = _clear({"rule_id": {"$nin": [str(rule["_id"]) for rule in rules]}}, "Rule deleted", now)
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
                alert = _open_or_update(rule, subject, value, unit, now)
                if alert:
                    fired.append(alert)
            else:
                cleared += _clear({"rule_id": str(rule["_id"]), "subject": subject}, "Automatic check", now)
    return fired, cleared


def summarise(alerts):
    names = [alert["title"] for alert in alerts[:MAX_NAMES_IN_NOTIFICATION]]
    extra = len(alerts) - len(names)
    return "; ".join(names) + (" and %d more" % extra if extra else "")


def notify_new_alerts(alerts):
    if alerts:
        notify("%d new alert%s: %s" % (len(alerts), "" if len(alerts) == 1 else "s", summarise(alerts)))
