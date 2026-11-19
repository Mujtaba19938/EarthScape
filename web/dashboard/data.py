"""Data for each dashboard page: MongoDB queries, calculations and chart series.

Views call these and pass the results to templates. JavaScript only draws the charts.
"""
import csv
import datetime
import io
import json
import os
import re
import tempfile
from concurrent.futures import ThreadPoolExecutor

from django.core.cache import cache

from earthscape import config
from earthscape.crypto import decrypt
from earthscape.db import db

from . import cluster, live
from .catalogue import AIR_QUALITY_QUERY, DATASETS, REPORTS, UPLOAD_SIGNATURES

# Zones
ZONES = ["64N-90N", "44N-64N", "24N-44N", "EQU-24N", "24S-EQU", "44S-24S", "64S-44S", "90S-64S"]
# Each zone is a latitude band, so these name places inside it. Values are the band's average.
ZONE_PLACES = {
    "64N-90N": "Greenland, Northern Alaska, Northern Russia",
    "44N-64N": "London, Moscow, Vancouver",
    "24N-44N": "Karachi, Lahore, Islamabad",
    "EQU-24N": "Lagos, Mumbai, Bangkok",
    "24S-EQU": "Jakarta, Nairobi, São Paulo",
    "44S-24S": "Sydney, Cape Town, Buenos Aires",
    "64S-44S": "Southern Chile, Southern Argentina, Falkland Islands",
    "90S-64S": "Antarctica",
}
ZONE_OPTIONS = [("Glob", "Global")] + [(zone, ZONE_PLACES[zone]) for zone in ZONES]
ANALYTICS_YEAR = 2023
VARIABLES = [
    ("anomaly", "Temperature anomaly (°C), NASA GISTEMP"),
    ("TMAX", "Daily high (°C), weather stations"),
    ("TMIN", "Daily low (°C), weather stations"),
    ("PRCP", "Precipitation (mm/day), weather stations"),
    ("ALLSKY_SFC_SW_DWN", "Solar radiation (MJ/m²/day), CERES satellite"),
    ("TS", "Surface temperature (°C), MERRA-2 model"),
]
MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
LIVE_METRICS = [
    ("temperature_c", "Temperature (°C)"), ("humidity_pct", "Humidity (%)"), ("wind_kmh", "Wind (km/h)"),
    ("precipitation_mm", "Precipitation (mm)"), ("pm25", "PM2.5 (µg/m³)"), ("pm10", "PM10 (µg/m³)"),
    ("no2", "NO₂ (µg/m³)"), ("o3", "Ozone (µg/m³)"), ("us_aqi", "US AQI"),
]
ML_HORIZONS = [2030, 2040, 2050]
ML_CHART_START = 1950
BASELINE = "persistence"
SEVERITIES = ("Critical", "High", "Medium", "Low")
ALERT_STATUSES = ("Acknowledged", "Resolved")
TICKET_CATEGORIES = ("Data pipeline problem", "Incorrect data", "Website or dashboard bug", "Feedback")
TICKET_STATUSES = ("Open", "In progress", "Closed")
UPTIME_GOAL_PERCENT = 99
MONITOR_STALE_MINUTES = 15
BACKUP_STALE_HOURS = 26
ASK_EXAMPLES = [
    "What will the weather be in Karachi in 2027?", "Are there any chances of a storm in the near future?",
    "Could a cyclone hit Gwadar in 2028?", "Weather in Lahore tomorrow", "How hot was Multan in June 2023?",
    "How much warmer will Pakistan be in 2030?", "How hot will Pakistan be in 2050 with high emissions?",
    "How often do floods hit Pakistan?",
]

# Chart colours
INK = "#171717"
ACCENT = "#1a814a"
RAMP = ["#cfcfcf", "#a3a3a3", "#767676", "#4a4a4a", "#171717"]


def now():
    return datetime.datetime.now(datetime.timezone.utc)


def series_colors(count, lead):
    """Lead gets accent."""
    # The rest run light to dark, so earlier years and lower emissions are lighter.
    others = [index for index in range(count) if index != lead]
    colors = [None] * count
    for position, index in enumerate(others):
        step = len(RAMP) - 1 if len(others) == 1 else round(position * (len(RAMP) - 1) / (len(others) - 1))
        colors[index] = RAMP[step]
    if 0 <= lead < count:
        colors[lead] = ACCENT
    return colors


def chart(labels, datasets, y_label=""):
    """Chart.js input."""
    return {"labels": labels, "datasets": datasets, "yLabel": y_label}


def zone_label(series):
    return "Global" if series == "Glob" else "%s (%s band)" % (ZONE_PLACES.get(series, series), series)


def stat(label, value, note=""):
    return {"label": label, "value": value, "note": note}


def signed(value, suffix=""):
    """Plus sign prefix."""
    if value is None:
        return "n/a"
    return ("+" if value > 0 else "") + str(value) + suffix


def number(value):
    return "n/a" if value is None else "{:,}".format(value)


def size(value):
    """Bytes to text."""
    if value is None:
        return "Unavailable"
    units = ["B", "KB", "MB", "GB", "TB", "PB"]
    unit = 0
    while value >= 1024 and unit < len(units) - 1:
        value /= 1024
        unit += 1
    return ("%.0f %s" if unit == 0 else "%.1f %s") % (value, units[unit])


def percent(share, decimals=0):
    return ("%." + str(decimals) + "f%%") % (100 * share)


# Sidebar and header

def cluster_status():
    """Cached 30 seconds."""
    status = cache.get("cluster_status")
    if status is None:
        status = cluster.cluster_status()
        cache.set("cluster_status", status, 30)
    return status


def sidebar_cluster():
    """HDFS footer text."""
    status = cluster_status()
    if not status["hdfs_online"]:
        return {"nodes": "Offline", "capacity": "HDFS unreachable", "bar": 0}
    return {"nodes": "%s DataNode online" % status["live_datanodes"],
            "capacity": "%s of %s" % (size(status["used_bytes"]), size(status["capacity_bytes"])),
            "bar": max(status["used_percent"], 1)}


def notification_query(user):
    return {"$or": [{"user_id": None}, {"user_id": user["id"]}]}


def notifications(user):
    rows = db.notifications.find(notification_query(user)).sort("created_at", -1).limit(30)
    return [{"text": row["text"], "created_at": row["created_at"], "read": user["id"] in row.get("read_by", [])}
            for row in rows]


def mark_notifications_read(user):
    db.notifications.update_many(notification_query(user), {"$addToSet": {"read_by": user["id"]}})


def maintenance():
    """Public banner."""
    row = db.settings.find_one({"_id": "maintenance"}) or {}
    return {"active": row.get("active", False), "message": row.get("message", "")}


def set_maintenance(active, message, admin_name):
    db.settings.update_one({"_id": "maintenance"}, {"$set": {
        "active": active, "message": message.strip()[:300], "updated_by": admin_name, "updated_at": now()}}, upsert=True)


def active_alert_count():
    return db.alerts.count_documents({"status": "Active"})


# Home and executive dashboard

def _latest_complete(collection, year_key, value_key):
    """Two newest rows."""
    # The current year is often incomplete
    return list(db[collection].find({value_key: {"$ne": None}}, {"_id": 0}).sort(year_key, -1).limit(2))


def overview():
    temperature = _latest_complete("gistemp_global", "Year", "J-D")
    co2 = _latest_complete("co2_annual", "year", "mean")
    return {
        "temperature": temperature[0] if temperature else None,
        "temperature_previous": temperature[1] if len(temperature) > 1 else None,
        "co2": co2[0] if co2 else None,
        "anomaly_count": db.station_anomalies.count_documents({}),
        "active_alerts": active_alert_count(),
        "dataset_count": len(DATASETS) + db.datasets.count_documents({}),
        "cluster": cluster_status(),
    }


def landing_stats():
    data = overview()
    temperature, previous, co2 = data["temperature"], data["temperature_previous"], data["co2"]
    note = ""
    if temperature:
        note = "NASA GISTEMP, %s" % temperature["Year"]
        if previous:
            note += " (%s: %s)" % (previous["Year"], signed(previous["J-D"], " °C"))
    return [
        stat("Global temp anomaly", signed(temperature["J-D"], " °C") if temperature else "n/a", note),
        stat("Atmospheric CO₂", "%s ppm" % co2["mean"] if co2 else "n/a", "Mauna Loa, %s" % co2["year"] if co2 else ""),
        stat("Unusual station readings", number(data["anomaly_count"]), "More than 3 standard deviations from normal"),
        stat("Datasets in HDFS", number(data["dataset_count"]), "Weather, satellite-derived and sensor data"),
    ]


def dashboard_stats():
    data = overview()
    temperature, co2, status = data["temperature"], data["co2"], data["cluster"]
    hadoop_note = "Start HDFS and YARN"
    if status["hdfs_online"]:
        hadoop_note = "%s DataNode, %s YARN node" % (status["live_datanodes"], number(status.get("active_nodes")))
    return [
        stat("Temp anomaly", signed(temperature["J-D"], " °C") if temperature else "n/a", str(temperature["Year"]) if temperature else ""),
        stat("CO₂", "%s ppm" % co2["mean"] if co2 else "n/a", str(co2["year"]) if co2 else ""),
        stat("Active alerts", data["active_alerts"], "Checked each time live data arrives"),
        stat("Datasets", data["dataset_count"], "In HDFS"),
        stat("Hadoop", "Online" if status["hdfs_online"] and status["yarn_online"] else "Offline", hadoop_note),
    ]


def global_chart():
    """Ink line, accent end."""
    rows = list(db.gistemp_global.find({"J-D": {"$ne": None}}).sort("Year", 1))
    last = len(rows) - 1
    return chart([row["Year"] for row in rows], [{
        "label": "Anomaly (°C)", "data": [row["J-D"] for row in rows], "borderColor": INK, "borderWidth": 1.5,
        "tension": 0.2, "pointRadius": [4 if index == last else 0 for index in range(len(rows))], "pointHoverRadius": 4,
        "pointBackgroundColor": ACCENT, "pointBorderColor": ACCENT, "pointBorderWidth": 0,
    }], "°C")


def compact_date(value):
    """YYYYMMDD to ISO."""
    text = str(value)
    return "%s-%s-%s" % (text[:4], text[4:6], text[6:8])


def station_anomalies(limit=20):
    """Largest z-scores."""
    rows = db.station_anomalies.aggregate([
        {"$addFields": {"size": {"$abs": "$z_score"}}},
        {"$sort": {"size": -1, "date": 1, "station": 1}},
        {"$limit": limit},
        {"$project": {"_id": 0, "size": 0}},
    ])
    return [dict(row, date_text=compact_date(row["date"])) for row in rows]


# Climate analytics

def _weighted_mean(rows):
    if not rows:
        return None
    readings = sum(row["readings"] for row in rows)
    return round(sum(row["mean"] * row["readings"] for row in rows) / readings, 2)


def zone_summary():
    """Station averages."""
    anomalies = list(db.gistemp_zonal.find({"Glob": {"$ne": None}}).sort("Year", -1).limit(1))
    latest = anomalies[0] if anomalies else {}
    summary = []
    for zone in ZONES:
        rows = list(db.regional_monthly.find({"zone": zone, "year": ANALYTICS_YEAR}))
        by_element = {}
        for row in rows:
            by_element.setdefault(row["element"], []).append(row)
        summary.append({
            "zone": zone, "place": ZONE_PLACES[zone],
            "anomaly": latest.get(zone), "anomaly_year": latest.get("Year"),
            "tmax": _weighted_mean(by_element.get("TMAX")),
            "tmin": _weighted_mean(by_element.get("TMIN")),
            "prcp": _weighted_mean(by_element.get("PRCP")),
            "readings": sum(row["readings"] for row in rows),
        })
    return summary


def monthly_values(zone, variable):
    """Year to months."""
    if variable in ("TMAX", "TMIN", "PRCP"):
        rows = db.regional_monthly.find({"zone": zone, "element": variable})
    else:
        rows = db.satellite_zonal.find({"zone": zone, "parameter": variable})
    result = {}
    for row in rows:
        result.setdefault(row["year"], {})[row["month"]] = row["mean"]
    return result


def analytics_chart(zone, variable):
    """Returns (chart, message)."""
    if variable == "anomaly":
        rows = db.gistemp_zonal.find({zone: {"$ne": None}}).sort("Year", 1)
        rows = list(rows)
        label = dict(VARIABLES)[variable]
        return chart([row["Year"] for row in rows], [{
            "label": label, "data": [row[zone] for row in rows], "borderColor": INK,
            "pointRadius": 0, "tension": 0.2, "borderWidth": 1.5}], "°C"), None
    if zone == "Glob":
        return None, "This variable is only available by latitude band. Choose a place above."
    years = monthly_values(zone, variable)
    if not years:
        return None, "The grid has no points in this zone. Weather station variables cover every zone."
    keys = sorted(years)
    # Latest year leads
    colors = series_colors(len(keys), len(keys) - 1)
    datasets = [{
        "label": str(year), "data": [years[year].get(month) for month in range(1, 13)],
        "borderColor": colors[index], "backgroundColor": colors[index], "tension": 0.2,
        "borderWidth": 2 if index == len(keys) - 1 else 1.5, "pointRadius": 2,
    } for index, year in enumerate(keys)]
    return chart(MONTHS, datasets), None


# Live monitor

def aqi_tag(value):
    """AQI class, label."""
    if value is None:
        return {"cls": "tag-grey", "text": "AQI n/a"}
    if value > 150:
        cls, label = "tag-red", "Unhealthy"
    elif value > 100:
        cls, label = "tag-gold", "Unhealthy for sensitive groups"
    elif value > 50:
        cls, label = "tag-gold", "Moderate"
    else:
        cls, label = "tag-green", "Good"
    return {"cls": cls, "text": "AQI %s %s" % (value, label)}


def live_cards():
    """One card per city."""
    cards = []
    for row in live.latest_readings():
        values = [("Temperature", row.get("temperature_c"), "°C"), ("Humidity", row.get("humidity_pct"), "%"),
                  ("Wind", row.get("wind_kmh"), "km/h"), ("Precipitation", row.get("precipitation_mm"), "mm"),
                  ("PM2.5", row.get("pm25"), "µg/m³"), ("PM10", row.get("pm10"), "µg/m³"),
                  ("NO₂", row.get("no2"), "µg/m³"), ("Ozone", row.get("o3"), "µg/m³")]
        cards.append({
            "location": row["location"], "observed_at": row["observed_at"], "aqi": aqi_tag(row.get("us_aqi")),
            "values": [(label, "n/a" if value is None else "%s %s" % (value, unit)) for label, value, unit in values],
        })
    return cards


def live_status_text(status):
    """Collector sentence."""
    if not status["last_success_at"]:
        return "No live data yet. Start the collector: python web\\manage.py collect_live"
    last = "Last updated %s" % status["last_success_at"].strftime("%Y-%m-%d %H:%M UTC")
    if status["stale"]:
        return last + ". This is out of date: the collector may have stopped."
    if status["last_poll"] and not status["last_poll"]["ok"]:
        return last + ". The latest attempt failed and will be retried."
    return last + ", checking every %s minutes." % status["poll_minutes"]


def live_batch_text(status):
    batch = status["last_batch"]
    if not batch:
        text = "No HDFS batch yet."
    elif batch["ok"]:
        text = "Last HDFS batch: %s readings at %s." % (batch["rows"], batch["finished_at"].strftime("%Y-%m-%d %H:%M UTC"))
    else:
        text = "The last HDFS batch failed and will be retried."
    return text + " %s readings waiting for the next batch." % status["waiting_for_hdfs"]


def live_history_chart(location, metric, hours=48):
    since = now() - datetime.timedelta(hours=hours)
    rows = list(db.live_readings.find({"location": location, "observed_at": {"$gte": since}}).sort("observed_at", 1))
    label = dict(LIVE_METRICS)[metric]
    return chart([row["observed_at"].strftime("%d %b %H:%M") for row in rows], [{
        "label": label, "data": [row.get(metric) for row in rows], "borderColor": ACCENT, "backgroundColor": ACCENT,
        "pointRadius": 2, "tension": 0.2, "borderWidth": 2}], label)


def air_quality_sensors():
    """Latest month each."""
    latest = {}
    for row in db.air_quality_monthly.find(AIR_QUALITY_QUERY, {"_id": 0}).sort("month", 1):
        location = latest.setdefault(row["location_id"], {
            "name": row["location"], "lat": "%.2f" % row["lat"], "lon": "%.2f" % row["lon"], "pollutants": {}})
        location["pollutants"][row["parameter"]] = {
            "name": row["parameter"].upper(), "month": MONTHS[row["month"] - 1],
            "value": "%s %s" % (format(row["mean"], ".3g"), row["units"])}
    sensors = sorted(latest.values(), key=lambda sensor: sensor["name"])
    for sensor in sensors:
        sensor["pollutants"] = list(sensor["pollutants"].values())
    return sensors


# Data explorer

def datasets():
    """Uploads, then catalogue."""
    uploads = [dict(row, id=str(row.pop("_id")), uploaded=True, size_text=size(row.get("size_bytes")))
               for row in db.datasets.find().sort("ingested_at", -1)]
    sizes = dataset_sizes()
    catalogue = [dict(entry, uploaded=False, size_text=size(sizes.get(entry["path"])))
                 for entry in DATASETS]
    return uploads + catalogue


def dataset_sizes():
    """Cached five minutes."""
    sizes = cache.get("dataset_sizes")
    if sizes is None:
        sizes = {}
        # Skip when offline
        if cluster_status()["hdfs_online"]:
            paths = [entry["path"] for entry in DATASETS]
            with ThreadPoolExecutor(max_workers=8) as pool:
                sizes = dict(zip(paths, pool.map(cluster.hdfs_size, paths)))
        cache.set("dataset_sizes", sizes, 300)
    return sizes


def quality_rows():
    """Pass rate per year."""
    rows = db.data_quality.find({"element": {"$in": ["TMAX", "TMIN", "PRCP"]}}, {"_id": 0}).sort([("year", 1), ("element", 1)])
    result = []
    for row in rows:
        checked = row["valid"] + row["failed_qc"]
        result.append(dict(row, pass_rate="%.2f%%" % (100 * row["valid"] / checked) if checked else "n/a"))
    return result


def clean_filename(filename):
    name = os.path.basename((filename or "").replace("\\", "/"))
    return re.sub(r"[^A-Za-z0-9._-]", "_", name)


class UploadError(Exception):
    """Message for the person."""


def _check_contents(path, extension):
    """Signature check."""
    expected = UPLOAD_SIGNATURES[extension]
    with open(path, "rb") as source:
        start = source.read(4096)
    if expected is None:
        if b"\x00" in start or b"," not in start.split(b"\n")[0]:
            raise UploadError("This doesn't look like a CSV file with a header row.")
        return
    if not any(start.startswith(signature) for signature in expected):
        raise UploadError("The file's contents don't match its %s extension." % extension)


def upload_dataset(uploaded, admin):
    """Stores in HDFS."""
    filename = clean_filename(uploaded.name)
    extension = os.path.splitext(filename)[1].lower()
    if extension not in UPLOAD_SIGNATURES:
        raise UploadError("Unsupported file type. Allowed: " + ", ".join(sorted(UPLOAD_SIGNATURES)))
    if uploaded.size > config.MAX_UPLOAD_BYTES:
        raise UploadError("The file is larger than the upload limit.")
    if uploaded.size == 0:
        raise UploadError("The file is empty.")
    target_dir = "/climate/raw/uploads"
    with tempfile.TemporaryDirectory() as folder:
        local_path = os.path.join(folder, filename)
        with open(local_path, "wb") as target:
            for chunk in uploaded.chunks():
                target.write(chunk)
        _check_contents(local_path, extension)
        try:
            cluster.put_file(local_path, target_dir)
        except Exception:
            raise UploadError("HDFS couldn't store the file. Is it running?")
    document = {
        "name": filename, "format": extension.lstrip(".").upper(), "source": "Upload by " + admin["name"],
        "path": target_dir + "/" + filename, "size_bytes": uploaded.size, "ingested_at": now(),
        "uploaded_by": admin["id"],
    }
    db.datasets.update_one({"path": document["path"]}, {"$set": document}, upsert=True)
    return filename


# Hadoop

def cluster_stats():
    status = cluster_status()
    hdfs, yarn = status["hdfs_online"], status["yarn_online"]
    return [
        stat("HDFS used", size(status["used_bytes"]) if hdfs else "Offline",
             "%.2f%% of %s" % (100 * status["used_bytes"] / status["capacity_bytes"], size(status["capacity_bytes"])) if hdfs and status["capacity_bytes"] else "Start HDFS"),
        stat("DataNodes", "%s live" % status["live_datanodes"] if hdfs else "Offline",
             "%s dead, %s files" % (status["dead_datanodes"], number(status["files"])) if hdfs else ""),
        stat("YARN nodes", "%s active" % status["active_nodes"] if yarn else "Offline",
             "%s containers in use" % status["containers_allocated"] if yarn else "Start YARN as administrator"),
        stat("Jobs since YARN start", "%s done" % status["apps_completed"] if yarn else "Offline",
             "%s running, %s failed" % (status["apps_running"], status["apps_failed"]) if yarn else ""),
    ]


def jobs():
    yarn_jobs = cluster.list_jobs()
    return {
        "yarn_online": yarn_jobs is not None,
        "jobs": yarn_jobs or [],
        "runnable": cluster.runnable_jobs(),
        "recent_runs": list(db.pipeline_runs.find({}, {"_id": 0}).sort("finished_at", -1).limit(20)),
        "any_running": any(job["group"] == "running" for job in yarn_jobs or []),
    }


def job_detail(application_id):
    """YARN record, or None."""
    if not re.fullmatch(r"application_\d+_\d+", application_id or ""):
        return None
    app = cluster.get_job(application_id)
    if not app:
        return None
    return {
        "name": app.get("name"), "id": app.get("id"),
        "lines": [
            "State: %s (%s)" % (app.get("state"), app.get("finalStatus")),
            "Progress: %s%%" % app.get("progress"),
            "Started: %s" % datetime.datetime.fromtimestamp((app.get("startedTime") or 0) / 1000, datetime.timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC"),
            "Run time: %s s" % round((app.get("elapsedTime") or 0) / 1000),
            "Resources: %s MB-seconds, %s vcore-seconds" % (app.get("memorySeconds"), app.get("vcoreSeconds")),
            "Message from YARN: %s" % (app.get("diagnostics") or "(none)"),
            "Tracking page: %s" % app.get("trackingUrl"),
        ],
    }


# ML models

def _scores(score):
    """Chosen and baseline error."""
    errors = {row["method"]: row["test_rmse"] for row in score["comparison"]}
    return errors[score["chosen_method"]], errors[BASELINE]


def _history_row(run):
    scores = run["forecast_scores"]
    chosen = [_scores(score) for score in scores]
    global_scores = next((_scores(score) for score in scores if score["series"] == "Glob"), (None, None))
    return {
        "version": run["version"], "trained_at": run["trained_at"], "triggered_by": run["triggered_by"],
        "global_test_rmse": global_scores[0], "global_baseline_rmse": global_scores[1],
        "beating": "%s of %s" % (sum(1 for model, baseline in chosen if model < baseline), len(chosen)),
        "false_alarms": percent(run["anomaly"]["false_alarm_rate"], 2),
        "spikes": percent(run["anomaly"]["recall_by_spike_size"]["10"]),
    }


def ml_summary():
    runs = list(db.ml_runs.find({}, {"_id": 0}).sort("trained_at", -1).limit(10))
    for run in runs:
        run["trained_at"] = run["trained_at"].replace(tzinfo=datetime.timezone.utc)
    latest = runs[0] if runs else None
    result = {"retraining": cluster.training_running(), "latest": latest, "history": [_history_row(run) for run in runs], "stats": []}
    if latest:
        scores, anomaly = latest["forecast_scores"], latest["anomaly"]
        recall = anomaly["recall_by_spike_size"]
        coverage = sum(score["test_coverage"] for score in scores) / len(scores)
        result["stats"] = [
            stat("Beat the baseline", "%s of %s" % (sum(1 for score in scores if score["beats_baseline"]), len(scores)),
                 "Regions where the forecast beat repeating the last value on %s" % scores[0]["test_period"]),
            stat("Inside the 95% range", percent(coverage), "Held-back years inside the range, averaged across regions"),
            stat("False alarms", percent(anomaly["false_alarm_rate"], 2), "Oct-Dec days flagged after training on Jan-Sep, target about 1%"),
            stat("Test spikes found", percent(recall["10"]),
                 "At 10 times a sensor's usual spread. At 6: %s, at 3: %s" % (percent(recall["6"]), percent(recall["3"]))),
        ]
    return result


def forecast(series, horizon):
    """Chart, table, verdict."""
    document = db.ml_forecasts.find_one({"series": series}, {"_id": 0})
    if not document:
        return None
    history = [row for row in document["history"] if row["year"] >= ML_CHART_START]
    future = [row for row in document["forecast"] if row["year"] <= horizon]
    last = history[-1]
    blanks = [None] * (len(history) - 1)
    # Forecast starts at the last measured year
    graph = chart([row["year"] for row in history] + [row["year"] for row in future], [
        {"label": "Measured", "data": [row["value"] for row in history], "borderColor": INK, "backgroundColor": INK,
         "pointRadius": 0, "tension": 0.2, "borderWidth": 1.5},
        {"label": "Forecast", "data": blanks + [last["value"]] + [row["forecast"] for row in future], "borderColor": ACCENT,
         "backgroundColor": ACCENT, "borderDash": [6, 4], "pointRadius": 0, "borderWidth": 2},
        {"label": "95% range, upper", "data": blanks + [last["value"]] + [row["upper"] for row in future], "borderWidth": 0,
         "pointRadius": 0, "backgroundColor": "rgba(26,129,74,.15)", "fill": "+1"},
        {"label": "95% range, lower", "data": blanks + [last["value"]] + [row["lower"] for row in future], "borderWidth": 0,
         "pointRadius": 0, "hideFromLegend": True},
    ], "°C")
    table = [{"year": row["year"], "forecast": signed(round(row["forecast"], 2), " °C"),
              "range": "%s to %s" % (signed(round(row["lower"], 2)), signed(round(row["upper"], 2), " °C"))}
             for row in document["forecast"] if row["year"] in ML_HORIZONS]
    verdict = ("Method for %s: %s. It had the lowest error on past data. On %s, held back from that choice, it %s simply "
               "repeating the last value (error %.3f against %.3f °C), and %s of those years fell inside its 95%% range. "
               "One decade is a small test.") % (
        zone_label(series), document["chosen_label"], document["test_period"],
        "beat" if document["beats_baseline"] else "didn't beat", document["test_rmse"], document["baseline_test_rmse"],
        percent(document["test_coverage"]))
    comparison = [{"label": row["label"], "chosen": row["method"] == document["chosen_method"],
                   "backtest": "%.3f °C" % row["backtest_rmse"], "test": "%.3f °C" % row["test_rmse"],
                   "bias": signed(row["test_bias"], " °C")} for row in document["comparison"]]
    return {"chart": graph, "table": table, "verdict": verdict, "comparison": comparison, "test_period": document["test_period"]}


def ml_anomalies(limit=25):
    return list(db.ml_anomalies.find({}, {"_id": 0}).sort("score", -1).limit(limit))


def ml_correlations():
    return [dict(row, significant=row["pearson_p"] < 0.05) for row in db.ml_correlations.find({}, {"_id": 0})]


def ask_view(result):
    """Answer plus chart."""
    view = dict(result)
    view["notes"] = list(result["notes"]) + (["Source: %s." % ", ".join(result["sources"])] if result["sources"] else [])
    if result.get("chart"):
        series = result["chart"]["series"]
        answer = result["answer"].lower()
        # The series the answer names leads
        lead = next((index for index, item in enumerate(series) if item["label"].lower() in answer), 0)
        colors = series_colors(len(series), lead)
        dots = 3 if len(result["chart"]["labels"]) <= 24 else 0
        view["chart"] = chart(result["chart"]["labels"], [{
            "label": item["label"], "data": item["values"], "borderColor": colors[index], "backgroundColor": colors[index],
            "tension": 0.2, "borderWidth": 2 if index == lead else 1.5, "pointRadius": dots, "order": 0 if index == lead else 1,
        } for index, item in enumerate(series)], result["chart"].get("unit", ""))
    return view


# Alerts

def severity_class(severity):
    return {"Critical": "tag-red", "High": "tag-gold"}.get(severity, "tag-grey")


def alerts():
    rows = db.alerts.find().sort("created_at", -1).limit(200)
    return [dict(row, id=str(row.pop("_id")), severity_cls=severity_class(row["severity"])) for row in rows]


def alert_rules():
    rows = db.alert_rules.find().sort("created_at", -1)
    return [dict(row, id=str(row.pop("_id")), severity_cls=severity_class(row["severity"]),
                 metric_label=live.ALERT_METRICS.get(row["metric"], row["metric"])) for row in rows]


# Reports

def report_list():
    return [{"id": key, "title": report["title"], "geo": report.get("geo", False)} for key, report in REPORTS.items()]


def _plain(value):
    return value.isoformat() if isinstance(value, datetime.datetime) else value


def report_rows(report):
    query = db[report["collection"]].find(report["query"], {"_id": 0}).sort(report["sort"])
    return [{column: _plain(row.get(column)) for column in report["columns"]} for row in query]


def as_csv(columns, rows):
    output = io.StringIO()
    writer = csv.DictWriter(output, fieldnames=columns, lineterminator="\n")
    writer.writeheader()
    writer.writerows(rows)
    return output.getvalue()


def as_geojson(rows):
    """RFC 7946."""
    features = [{"type": "Feature", "geometry": {"type": "Point", "coordinates": [row["lon"], row["lat"]]},
                 "properties": {key: value for key, value in row.items() if key not in ("lat", "lon")}} for row in rows]
    return json.dumps({"type": "FeatureCollection", "features": features})


def build_report(report_id, file_format):
    """Returns (body, type), or None."""
    report = REPORTS.get(report_id)
    if not report:
        return None
    rows = report_rows(report)
    if file_format == "csv":
        return as_csv(report["columns"], rows), "text/csv"
    if file_format == "json":
        return json.dumps(rows), "application/json"
    if file_format == "geojson" and report.get("geo"):
        return as_geojson(rows), "application/geo+json"
    return None


# Support tickets

def tickets(user):
    """Own, or all for Admins."""
    query = {} if user["is_admin"] else {"created_by": user["id"]}
    return [dict(row, id=str(row.pop("_id")), description=decrypt(row.pop("description_enc")))
            for row in db.tickets.find(query).sort("created_at", -1)]


# System status

def _uptime(target, hours):
    since = now() - datetime.timedelta(hours=hours)
    rows = list(db.health_checks.aggregate([
        {"$match": {"target": target, "at": {"$gte": since}}},
        {"$group": {"_id": None, "checks": {"$sum": 1}, "ok": {"$sum": {"$cond": ["$ok", 1, 0]}}}},
    ]))
    if not rows:
        return "No checks yet"
    checks = rows[0]["checks"]
    return "%s%% (%s %s)" % (round(100 * rows[0]["ok"] / checks, 2), number(checks), "check" if checks == 1 else "checks")


def _is_recent(moment, limit):
    return moment is not None and now() - moment <= limit


def components():
    """Six health cards."""
    status = cluster_status()
    last_check = db.health_checks.find_one(sort=[("at", -1)])
    last_backup = db.backups.find_one({"ok": True}, sort=[("finished_at", -1)])
    # Only the collector's own runs count
    last_run = db.live_polls.find_one({"triggered_by": "collector", "ok": True}, sort=[("started_at", -1)])
    collector_ok = _is_recent(last_run["started_at"] if last_run else None,
                              datetime.timedelta(minutes=config.LIVE_POLL_MINUTES * live.STALE_AFTER_POLLS))
    monitor_ok = _is_recent(last_check["at"] if last_check else None, datetime.timedelta(minutes=MONITOR_STALE_MINUTES))
    backup_ok = _is_recent(last_backup["finished_at"] if last_backup else None, datetime.timedelta(hours=BACKUP_STALE_HOURS))
    return [
        {"name": "MongoDB", "ok": True, "detail": "Answering this page"},
        {"name": "HDFS", "ok": status["hdfs_online"], "detail": "%s DataNode live" % status.get("live_datanodes", 0)},
        {"name": "YARN", "ok": status["yarn_online"], "detail": "%s node active" % status.get("active_nodes", 0)},
        {"name": "Live data collector", "ok": collector_ok, "detail": "Collecting on schedule" if collector_ok else "Not running on schedule"},
        {"name": "Health monitor", "ok": monitor_ok, "detail": "Checking on schedule" if monitor_ok else "Not running on schedule"},
        {"name": "Backups", "ok": backup_ok, "detail": "Successful backup in the last day" if backup_ok else "No recent successful backup"},
    ]


def system_status():
    db.command("ping")
    targets = []
    for target in sorted(db.health_checks.distinct("target")):
        latest = db.health_checks.find_one({"target": target}, sort=[("at", -1)], projection={"_id": 0})
        targets.append({"target": target, "latest": latest, "day": _uptime(target, 24), "week": _uptime(target, 24 * 7)})
    backups = [dict(row, size_text=size(row.get("size_bytes"))) for row in db.backups.find({}, {"_id": 0}).sort("finished_at", -1).limit(5)]
    # Pipeline, training and live check times
    runs = [(run["job"], run["seconds"], run["finished_at"]) for run in db.pipeline_runs.find({}, {"_id": 0}).sort("finished_at", -1).limit(5)]
    runs += [("Model training", run["seconds"], run["trained_at"]) for run in
             db.ml_runs.find({}, {"_id": 0, "trained_at": 1, "seconds": 1}).sort("trained_at", -1).limit(5) if "seconds" in run]
    last_poll = live.status()["last_poll"]
    if last_poll:
        runs.append(("Live data check", last_poll["seconds"], last_poll["started_at"]))
    return {"instance": config.INSTANCE_NAME, "goal_percent": UPTIME_GOAL_PERCENT, "components": components(),
            "targets": targets, "backups": backups, "runs": runs}


# Search

def search(query):
    """Datasets, sensors, rules."""
    text = query.strip().lower()
    if len(text) < 2:
        return []
    items = [("Datasets", row["name"], "dashboard:data") for row in DATASETS + list(db.datasets.find({}, {"name": 1}))]
    items += [("Sensors", name, "dashboard:monitor") for name in db.air_quality_monthly.distinct("location", AIR_QUALITY_QUERY)]
    items += [("Live cities", name, "dashboard:monitor") for name in config.LIVE_LOCATION_NAMES]
    items += [("Alert rules", row["name"], "dashboard:alerts") for row in db.alert_rules.find({}, {"name": 1})]
    return [{"group": group, "text": name, "page": page} for group, name, page in items if text in name.lower()][:12]
