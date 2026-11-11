"""Monthly weather outlooks for each live city, and how often storms have come near it.

No one can forecast one day's weather years ahead, so the outlook is for monthly averages:
how warm a month should be in a given year, with a range taken from how far the same
method missed on past years. Rain is too erratic to trend, so it's the usual range from the
last 30 years. Storm chances are how often a storm really passed nearby, not a forecast.
"""
import glob
import math
import os

import numpy as np
import pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HISTORY_DIR = os.path.join(ROOT, "data", "raw", "city_history")
TRACKS_FILE = os.path.join(ROOT, "data", "raw", "ibtracs", "ibtracs.NI.list.v04r01.csv")

MAX_HORIZON = 5
MIN_HISTORY_YEARS = 15
SELECTION_END = 2015
SELECTION_START = 1996
RECENT_YEARS = 30
AVERAGE_WINDOW = 10
TREND_WINDOW = 30
RANGE_Z = 1.96
RAIN_DAY_MM = 1
HEAVY_RAIN_MM = 50
GALE_KMH = 62
STORM_RADIUS_KM = 300
STORM_MIN_KNOTS = 34
EARTH_RADIUS_KM = 6371
TEMPERATURES = {"tmax_c": "Daily high", "tmin_c": "Daily low"}


def recent_average(values, horizon, _yearly=None):
    """The baseline: the same month's average over the last 10 years."""
    return np.full(horizon, np.nanmean(values[-AVERAGE_WINDOW:]))


def recent_trend(values, horizon, _yearly=None):
    """A straight line through the same month in the last 30 years."""
    recent = values[-TREND_WINDOW:]
    slope, intercept = np.polyfit(np.arange(len(recent)), recent, 1)
    return intercept + slope * np.arange(len(recent), len(recent) + horizon)


def average_plus_warming(values, horizon, yearly):
    """The same month's 10-year average, moved forward by the city's whole-year trend.

    One month's trend is noisy, but all 12 months together give a steadier slope. The average
    is centred 4.5 years before the last year, so the trend also has to cover that gap."""
    recent = yearly[-TREND_WINDOW:]
    slope = np.polyfit(np.arange(len(recent)), recent, 1)[0]
    return np.nanmean(values[-AVERAGE_WINDOW:]) + slope * ((AVERAGE_WINDOW - 1) / 2 + np.arange(1, horizon + 1))


METHODS = {"average": ("Average of the last 10 years", recent_average), "trend": ("Trend over the last 30 years for that month", recent_trend),
           "warming": ("Average of the last 10 years plus the city's yearly warming trend", average_plus_warming)}
BASELINE = "average"


def rmse(errors):
    return float(np.sqrt(np.mean(np.square(errors))))


def monthly_table(days):
    """One row per year and month, from a city's daily rows."""
    days = days.copy()
    dates = pd.to_datetime(days["date"])
    days["year"], days["month"] = dates.dt.year, dates.dt.month
    days["rain_day"] = days["rain_mm"] >= RAIN_DAY_MM
    days["heavy_day"] = days["rain_mm"] >= HEAVY_RAIN_MM
    days["gale_day"] = days["gust_kmh"] >= GALE_KMH
    table = days.groupby(["year", "month"], as_index=False).agg({
        "tmax_c": "mean", "tmin_c": "mean", "rain_mm": "sum", "rain_day": "sum", "heavy_day": "sum", "gale_day": "sum"})
    return table.rename(columns={"rain_day": "rain_days", "heavy_day": "heavy_days", "gale_day": "gale_days"})


def backtest(table, method, first_target, last_target):
    """Errors by horizon. table has one row per year and one column per month. Each forecast sees only earlier years."""
    errors = {horizon: [] for horizon in range(1, MAX_HORIZON + 1)}
    years = table.index.to_numpy()
    for horizon in errors:
        for target in range(first_target, last_target + 1):
            origin = target - horizon
            history = table.loc[years <= origin]
            if len(history) < MIN_HISTORY_YEARS or target not in table.index:
                continue
            yearly = history.mean(axis=1).to_numpy()
            for month in table.columns:
                predicted = method(history[month].to_numpy(), horizon, yearly)[-1]
                errors[horizon].append(predicted - table.loc[target, month])
    return errors


def flatten(errors):
    return [error for values in errors.values() for error in values]


def score_variable(table):
    """Chooses a method on the years up to 2015, then scores it once on the years after that."""
    selection = {key: backtest(table, method, SELECTION_START, SELECTION_END) for key, (_label, method) in METHODS.items()}
    chosen = min(selection, key=lambda key: rmse(flatten(selection[key])))
    last_year = int(table.index.max())
    test = {key: backtest(table, method, SELECTION_END + 1, last_year) for key, (_label, method) in METHODS.items()}
    margins = {horizon: RANGE_Z * rmse(errors) for horizon, errors in selection[chosen].items()}
    inside = [abs(error) <= margins[horizon] for horizon, errors in test[chosen].items() for error in errors]
    return {
        "method": chosen, "method_label": METHODS[chosen][0], "margins": margins,
        "test_rmse": rmse(flatten(test[chosen])), "baseline_test_rmse": rmse(flatten(test[BASELINE])),
        "test_coverage": float(np.mean(inside)), "test_period": "%d-%d" % (SELECTION_END + 1, last_year),
    }


def forecast_city(monthly):
    """Returns (outlook rows, scores) for one city."""
    last_year = int(monthly["year"].max())
    rows = {}
    scores = []
    for variable, label in TEMPERATURES.items():
        table = monthly.pivot(index="year", columns="month", values=variable)
        score = score_variable(table)
        scores.append(dict(score, variable=variable, variable_label=label, margins={str(k): v for k, v in score["margins"].items()}))
        method = METHODS[score["method"]][1]
        yearly = table.mean(axis=1).to_numpy()
        for month in table.columns:
            predicted = method(table[month].to_numpy(), MAX_HORIZON, yearly)
            for horizon in range(1, MAX_HORIZON + 1):
                row = rows.setdefault((last_year + horizon, int(month)), {"year": last_year + horizon, "month": int(month), "horizon": horizon})
                row[variable] = round(float(predicted[horizon - 1]), 1)
                row[variable + "_low"] = round(float(predicted[horizon - 1] - score["margins"][horizon]), 1)
                row[variable + "_high"] = round(float(predicted[horizon - 1] + score["margins"][horizon]), 1)
    return [rows[key] for key in sorted(rows)], scores


def usual_conditions(monthly):
    """The usual rain and storm-like days in each month, over the last 30 years."""
    recent = monthly[monthly["year"] > monthly["year"].max() - RECENT_YEARS]
    rows = []
    for month, group in recent.groupby("month"):
        rows.append({
            "month": int(month), "years": int(group["year"].nunique()),
            "rain_low": round(float(group["rain_mm"].quantile(0.1)), 1), "rain_mm": round(float(group["rain_mm"].median()), 1),
            "rain_high": round(float(group["rain_mm"].quantile(0.9)), 1), "rain_days": round(float(group["rain_days"].mean()), 1),
            "heavy_days": round(float(group["heavy_days"].mean()), 2), "gale_days": round(float(group["gale_days"].mean()), 2),
        })
    return rows


def read_tracks(path=TRACKS_FILE):
    """Track points at tropical storm strength or above, on each storm's main path."""
    columns = ["SID", "SEASON", "NAME", "ISO_TIME", "TRACK_TYPE", "LAT", "LON", "WMO_WIND", "USA_WIND"]
    # The second line of the file gives the units.
    tracks = pd.read_csv(path, usecols=columns, skiprows=[1], keep_default_na=False, low_memory=False)
    for column in ("LAT", "LON", "WMO_WIND", "USA_WIND"):
        tracks[column] = pd.to_numeric(tracks[column], errors="coerce")
    tracks["knots"] = tracks["USA_WIND"].fillna(tracks["WMO_WIND"])
    tracks = tracks[(tracks["knots"] >= STORM_MIN_KNOTS) & ~tracks["TRACK_TYPE"].str.lower().str.startswith("spur")].copy()
    times = pd.to_datetime(tracks["ISO_TIME"])
    tracks["year"], tracks["month"] = times.dt.year, times.dt.month
    return tracks


def distance_km(lat, lon, lats, lons):
    """Great-circle distance from one point to many."""
    lat1, lon1, lat2, lon2 = np.radians(lat), np.radians(lon), np.radians(lats), np.radians(lons)
    a = np.sin((lat2 - lat1) / 2) ** 2 + np.cos(lat1) * np.cos(lat2) * np.sin((lon2 - lon1) / 2) ** 2
    return 2 * EARTH_RADIUS_KM * np.arcsin(np.sqrt(a))


def chance_range(hits, total):
    """The Wilson 95% range for a share, which stays sensible when there are few or no hits."""
    z = RANGE_Z
    share = hits / total
    centre = (share + z * z / (2 * total)) / (1 + z * z / total)
    spread = z * math.sqrt(share * (1 - share) / total + z * z / (4 * total * total)) / (1 + z * z / total)
    return max(0.0, centre - spread), min(1.0, centre + spread)


def storm_record(tracks, lat, lon, first_year, last_year):
    """Every storm that passed within the radius of a city, and the chance of one in a year."""
    period = tracks[(tracks["year"] >= first_year) & (tracks["year"] <= last_year)]
    near = period.assign(km=distance_km(lat, lon, period["LAT"].to_numpy(), period["LON"].to_numpy()))
    near = near[near["km"] <= STORM_RADIUS_KM]
    storms = []
    for _sid, points in near.groupby("SID"):
        closest = points.loc[points["km"].idxmin()]
        # A storm that crossed into another basin has both names, such as GULAB:SHAHEEN-GU. The last is what it was called here.
        name = str(closest["NAME"]).split(":")[-1].split("-")[0].title()
        storms.append({"name": "Unnamed" if name in ("Not_Named", "Nan", "") else name, "year": int(closest["year"]), "month": int(closest["month"]),
                       "closest_km": int(round(float(closest["km"]))), "knots": int(points["knots"].max())})
    storms.sort(key=lambda storm: (storm["year"], storm["month"]))
    total = last_year - first_year + 1
    hits = len({storm["year"] for storm in storms})
    low, high = chance_range(hits, total)
    by_month = {str(month): sum(1 for storm in storms if storm["month"] == month) for month in range(1, 13)}
    return {"first_year": first_year, "last_year": last_year, "years": total, "years_with_storm": hits, "chance": round(hits / total, 3),
            "chance_low": round(low, 3), "chance_high": round(high, 3), "by_month": by_month, "storms": storms, "radius_km": STORM_RADIUS_KM}


def read_city(path):
    days = pd.read_csv(path)
    return days["city"].iloc[0], float(days["lat"].iloc[0]), float(days["lon"].iloc[0]), monthly_table(days)


def has_data():
    return bool(glob.glob(os.path.join(HISTORY_DIR, "*.csv"))) and os.path.exists(TRACKS_FILE)


def build():
    """Everything to save, as collection name to documents, plus a summary of the scores."""
    tracks = read_tracks()
    collections = {"city_history": [], "city_outlooks": [], "city_usual": [], "city_storms": [], "city_scores": []}
    for path in sorted(glob.glob(os.path.join(HISTORY_DIR, "*.csv"))):
        city, lat, lon, monthly = read_city(path)
        tag = {"city": city}
        for row in monthly.to_dict("records"):
            collections["city_history"].append(dict(tag, year=int(row["year"]), month=int(row["month"]), tmax_c=round(float(row["tmax_c"]), 1),
                                                    tmin_c=round(float(row["tmin_c"]), 1), rain_mm=round(float(row["rain_mm"]), 1),
                                                    rain_days=int(row["rain_days"]), gale_days=int(row["gale_days"])))
        outlook, scores = forecast_city(monthly)
        collections["city_outlooks"].extend(dict(tag, **row) for row in outlook)
        collections["city_scores"].extend(dict(tag, **score) for score in scores)
        collections["city_usual"].extend(dict(tag, **row) for row in usual_conditions(monthly))
        collections["city_storms"].append(dict(tag, lat=lat, lon=lon, **storm_record(tracks, lat, lon, int(monthly["year"].min()), int(monthly["year"].max()))))
    scores = collections["city_scores"]
    summary = {
        "cities": len(collections["city_storms"]), "scores": len(scores),
        "beat_baseline": sum(1 for score in scores if score["test_rmse"] < score["baseline_test_rmse"]),
        "test_rmse": round(float(np.mean([score["test_rmse"] for score in scores])), 2),
        "baseline_test_rmse": round(float(np.mean([score["baseline_test_rmse"] for score in scores])), 2),
        "test_coverage": round(float(np.mean([score["test_coverage"] for score in scores])), 3),
        "test_period": scores[0]["test_period"] if scores else None,
    }
    return collections, summary


def save(db, version, collections):
    for name, documents in collections.items():
        db[name].drop()
        if documents:
            db[name].insert_many([dict(document, version=version) for document in documents])
    db.city_outlooks.create_index([("city", 1), ("year", 1), ("month", 1)])
    db.city_history.create_index([("city", 1), ("year", 1), ("month", 1)])
    db.city_usual.create_index([("city", 1), ("month", 1)])
    db.city_scores.create_index([("city", 1)])
    db.city_storms.create_index([("city", 1)])
