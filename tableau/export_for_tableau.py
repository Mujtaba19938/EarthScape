"""Writes the results in MongoDB as CSV files for Tableau, one row per measurement.

Usage: python tableau/export_for_tableau.py   (with the backend's Python)
"""
import csv
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "backend"))

from app.db import db  # noqa: E402

HERE = ROOT / "tableau"
ZONES = ["64N-90N", "44N-64N", "24N-44N", "EQU-24N", "24S-EQU", "44S-24S", "64S-44S", "90S-64S"]
LIVE_FIELDS = ["observed_at", "location", "lat", "lon", "temperature_c", "humidity_pct", "wind_kmh", "precipitation_mm",
               "us_aqi", "pm25", "pm10", "no2", "o3"]


def write(name, fields, rows):
    rows = list(rows)
    with open(HERE / (name + ".csv"), "w", encoding="utf-8-sig", newline="") as out:
        writer = csv.DictWriter(out, fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)
    print("%-22s %6d rows" % (name, len(rows)))


def temperature_and_co2():
    co2 = {row["year"]: row["mean"] for row in db.co2_annual.find()}
    for row in db.gistemp_global.find().sort("Year"):
        if isinstance(row.get("J-D"), (int, float)):
            yield {"year": row["Year"], "anomaly_c": row["J-D"], "co2_ppm": co2.get(row["Year"])}


def zonal_temperature():
    for row in db.gistemp_zonal.find().sort("Year"):
        for zone in ZONES:
            if isinstance(row.get(zone), (int, float)):
                yield {"year": row["Year"], "zone": zone, "anomaly_c": row[zone]}


def forecasts():
    for row in db.ml_forecasts.find():
        for point in row["history"]:
            yield {"series": row["series"], "method": row["chosen_label"], "year": point["year"], "kind": "History",
                   "anomaly_c": point["value"]}
        for point in row["forecast"]:
            yield {"series": row["series"], "method": row["chosen_label"], "year": point["year"], "kind": "Forecast",
                   "anomaly_c": point["forecast"], "lower_c": point["lower"], "upper_c": point["upper"]}


def main():
    write("global_temperature_co2", ["year", "anomaly_c", "co2_ppm"], temperature_and_co2())
    write("zonal_temperature", ["year", "zone", "anomaly_c"], zonal_temperature())
    write("forecasts", ["series", "method", "year", "kind", "anomaly_c", "lower_c", "upper_c"], forecasts())
    write("regional_monthly", ["zone", "year", "month", "element", "mean", "readings"], db.regional_monthly.find())
    write("air_quality_monthly", ["location", "lat", "lon", "parameter", "units", "year", "month", "mean", "max", "readings"],
          db.air_quality_monthly.find())
    write("air_quality_anomalies", ["location", "parameter", "units", "date", "mean", "max", "z_mean", "score"],
          db.ml_anomalies.find())
    write("live_readings", LIVE_FIELDS, db.live_readings.find().sort("observed_at"))


if __name__ == "__main__":
    main()
