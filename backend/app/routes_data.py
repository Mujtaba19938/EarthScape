"""Read-only climate data produced by the pipeline, and report downloads."""
import csv
import io
import json

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import Response

from . import hadoop_client
from .catalogue import AIR_QUALITY_QUERY, DATASETS, REPORTS
from .db import db
from .security import current_user

router = APIRouter(prefix="/api", dependencies=[Depends(current_user)])

ZONES = ["64N-90N", "44N-64N", "24N-44N", "EQU-24N", "24S-EQU", "44S-24S", "64S-44S", "90S-64S"]
ANALYTICS_YEAR = 2023


def _latest_complete(collection, year_key, value_key):
    """The two most recent rows with a value; the current year is often incomplete."""
    query = {value_key: {"$ne": None}}
    return list(db[collection].find(query, {"_id": 0}).sort(year_key, -1).limit(2))


@router.get("/overview")
def overview():
    temperature = _latest_complete("gistemp_global", "Year", "J-D")
    co2 = _latest_complete("co2_annual", "year", "mean")
    return {
        "temperature": temperature[0] if temperature else None,
        "temperature_previous": temperature[1] if len(temperature) > 1 else None,
        "co2": co2[0] if co2 else None,
        "co2_previous": co2[1] if len(co2) > 1 else None,
        "anomaly_count": db.station_anomalies.count_documents({}),
        "active_alerts": db.alerts.count_documents({"status": "Active"}),
        "dataset_count": len(DATASETS) + db.datasets.count_documents({}),
        "cluster": hadoop_client.cluster_status(),
    }


@router.get("/climate/global")
def global_series():
    co2 = {row["year"]: row["mean"] for row in db.co2_annual.find()}
    rows = db.gistemp_global.find({"J-D": {"$ne": None}}).sort("Year", 1)
    return [{"year": row["Year"], "anomaly": row["J-D"], "co2": co2.get(row["Year"])} for row in rows]


@router.get("/climate/zonal")
def zonal_series(zone: str = Query(...)):
    if zone not in ZONES + ["Glob"]:
        raise HTTPException(status_code=422, detail="Unknown zone.")
    rows = db.gistemp_zonal.find({zone: {"$ne": None}}).sort("Year", 1)
    return [{"year": row["Year"], "value": row[zone]} for row in rows]


@router.get("/climate/monthly")
def monthly_series(zone: str = Query(...), variable: str = Query(...)):
    """Monthly values per year for a zone, from the weather station or satellite jobs."""
    if zone not in ZONES:
        raise HTTPException(status_code=422, detail="Unknown zone.")
    if variable in ("TMAX", "TMIN", "PRCP"):
        rows = db.regional_monthly.find({"zone": zone, "element": variable})
    elif variable in ("ALLSKY_SFC_SW_DWN", "TS"):
        rows = db.satellite_zonal.find({"zone": zone, "parameter": variable})
    else:
        raise HTTPException(status_code=422, detail="Unknown variable.")
    result = {}
    for row in rows:
        result.setdefault(row["year"], {})[row["month"]] = row["mean"]
    return result


@router.get("/climate/zones")
def zone_summary():
    anomalies = list(db.gistemp_zonal.find({"Glob": {"$ne": None}}).sort("Year", -1).limit(1))
    latest = anomalies[0] if anomalies else {}
    summary = []
    for zone in ZONES:
        rows = list(db.regional_monthly.find({"zone": zone, "year": ANALYTICS_YEAR}))
        by_element = {}
        for row in rows:
            by_element.setdefault(row["element"], []).append(row)
        summary.append({
            "zone": zone,
            "anomaly": latest.get(zone),
            "anomaly_year": latest.get("Year"),
            "tmax": _weighted_mean(by_element.get("TMAX")),
            "tmin": _weighted_mean(by_element.get("TMIN")),
            "prcp": _weighted_mean(by_element.get("PRCP")),
            "readings": sum(row["readings"] for row in rows),
        })
    return {"year": ANALYTICS_YEAR, "zones": summary}


def _weighted_mean(rows):
    if not rows:
        return None
    readings = sum(row["readings"] for row in rows)
    return round(sum(row["mean"] * row["readings"] for row in rows) / readings, 2)


@router.get("/anomalies")
def anomalies(limit: int = Query(default=20, ge=1, le=200)):
    rows = db.station_anomalies.aggregate([
        {"$addFields": {"size": {"$abs": "$z_score"}}},
        {"$sort": {"size": -1, "date": 1, "station": 1}},
        {"$limit": limit},
        {"$project": {"_id": 0, "size": 0}},
    ])
    return {"total": db.station_anomalies.count_documents({}), "rows": list(rows)}


@router.get("/air-quality")
def air_quality():
    """The most recent month of each pollutant at each sensor location."""
    latest = {}
    query = db.air_quality_monthly.find(AIR_QUALITY_QUERY, {"_id": 0}).sort("month", 1)
    for row in query:
        location = latest.setdefault(row["location_id"], {
            "id": row["location_id"], "name": row["location"], "lat": row["lat"], "lon": row["lon"],
            "pollutants": {}})
        location["pollutants"][row["parameter"]] = row
    return sorted(latest.values(), key=lambda location: location["name"])


@router.get("/quality")
def quality():
    rows = db.data_quality.find({"element": {"$in": ["TMAX", "TMIN", "PRCP"]}}, {"_id": 0})
    return list(rows.sort([("year", 1), ("element", 1)]))


def _report_rows(report):
    columns = report["columns"]
    query = db[report["collection"]].find(report["query"], {"_id": 0}).sort(report["sort"])
    return [{column: row.get(column) for column in columns} for row in query]


def _as_csv(columns, rows):
    output = io.StringIO()
    writer = csv.DictWriter(output, fieldnames=columns, lineterminator="\n")
    writer.writeheader()
    writer.writerows(rows)
    return output.getvalue()


def _as_geojson(rows):
    features = [{
        "type": "Feature",
        "geometry": {"type": "Point", "coordinates": [row["lon"], row["lat"]]},
        "properties": {k: v for k, v in row.items() if k not in ("lat", "lon")},
    } for row in rows]
    return json.dumps({"type": "FeatureCollection", "features": features})


@router.get("/reports")
def list_reports():
    return [{"id": key, "title": report["title"], "geo": report.get("geo", False)}
            for key, report in REPORTS.items()]


@router.get("/reports/{report_id}")
def download_report(report_id: str, format: str = Query(default="csv")):
    report = REPORTS.get(report_id)
    if not report:
        raise HTTPException(status_code=404, detail="Report not found.")
    rows = _report_rows(report)
    if format == "csv":
        body, media_type = _as_csv(report["columns"], rows), "text/csv"
    elif format == "json":
        body, media_type = json.dumps(rows), "application/json"
    elif format == "geojson" and report.get("geo"):
        body, media_type = _as_geojson(rows), "application/geo+json"
    else:
        raise HTTPException(status_code=422, detail="This report isn't available in that format.")
    headers = {"Content-Disposition": 'attachment; filename="%s.%s"' % (report_id, format)}
    return Response(content=body, media_type=media_type, headers=headers)
