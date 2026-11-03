"""Trains and evaluates the EarthScape climate models, then saves results to MongoDB.

Usage: python train_models.py [--triggered-by NAME]   (run with Anaconda's Python)

Forecasting: several methods compete on past data, using only what was known at
each point in time. The winner is then scored once on the final, unseen decade.
Anomaly detection: an Isolation Forest on daily air-quality sensor readings. There
are no true labels, so it is scored by how many artificial spikes it can find.
Correlation: compares variables as raw values and as year-to-year changes, because
two rising series always correlate strongly whether or not they are linked.
"""
import argparse
import csv
import datetime
import glob
import os
import warnings

import joblib
import numpy as np
import pandas as pd
from pymongo import MongoClient
from scipy import stats
from sklearn.ensemble import IsolationForest
from statsmodels.tsa.holtwinters import Holt

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OPENAQ_DIR = os.path.join(ROOT, "data", "raw", "openaq")
MODEL_DIR = os.path.join(ROOT, "ml", "saved_models")
MONGO_URI = os.environ.get("MONGO_URI", "mongodb://localhost:27017")
MONGO_DB = os.environ.get("MONGO_DB", "earthscape")

SEED = 42
SERIES = ["Glob", "64N-90N", "44N-64N", "24N-44N", "EQU-24N", "24S-EQU", "44S-24S", "64S-44S", "90S-64S"]
FORECAST_SCORE_FIELDS = ("series", "chosen_method", "chosen_label", "test_period", "test_rmse", "baseline_test_rmse",
                         "beats_baseline", "test_coverage", "comparison")
BASELINE = "persistence"
FORECAST_TO = 2050
SELECTION_HORIZON = 10
TEST_YEARS = 10
FIRST_ORIGIN = 1950
Z_95 = 1.96
ANOMALY_FEATURES = ["z_mean", "z_max", "z_range"]
ANOMALY_SHARE = 0.01
MIN_READINGS_PER_DAY = 12
MIN_DAYS_PER_SENSOR = 60
TRAILING_DAYS = 30
INJECTED_SPIKES = (3, 6, 10)


# --- Forecasting methods. Each takes past values and returns the next `horizon`. ---

def persistence(values, horizon):
    return np.repeat(values[-1], horizon)


def _linear(values, horizon, window):
    recent = values[-window:]
    positions = np.arange(len(recent))
    slope, intercept = np.polyfit(positions, recent, 1)
    return intercept + slope * (len(recent) + np.arange(horizon))


def linear_30y(values, horizon):
    return _linear(values, horizon, 30)


def linear_50y(values, horizon):
    return _linear(values, horizon, 50)


def holt(values, horizon):
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        fitted = Holt(np.asarray(values, dtype=float)).fit(optimized=True)
    return np.asarray(fitted.forecast(horizon))


METHODS = {
    "persistence": ("Last value (baseline)", persistence),
    "linear_30y": ("Linear trend, last 30 years", linear_30y),
    "linear_50y": ("Linear trend, last 50 years", linear_50y),
    "holt": ("Holt exponential smoothing", holt),
}


def rmse(errors):
    return float(np.sqrt(np.mean(np.square(errors))))


def backtest_errors(values, years, method, max_horizon, last_year):
    """Forecast errors by horizon. Each forecast only sees years before its origin."""
    errors = {horizon: [] for horizon in range(1, max_horizon + 1)}
    for origin in range(len(years)):
        if years[origin] < FIRST_ORIGIN or years[origin] > last_year:
            continue
        horizon_limit = min(max_horizon, len(years) - 1 - origin)
        if horizon_limit < 1:
            continue
        predicted = method(values[:origin + 1], horizon_limit)
        for horizon in range(1, horizon_limit + 1):
            target = origin + horizon
            if years[target] <= last_year:
                errors[horizon].append(values[target] - predicted[horizon - 1])
    return errors


def evaluate_series(years, values):
    """Picks a method on earlier data, then scores it once on the unseen final decade."""
    years = np.asarray(years)
    values = np.asarray(values, dtype=float)
    split = len(years) - TEST_YEARS
    selection_last_year = years[split - 1]
    comparison = []
    for key, (label, method) in METHODS.items():
        errors = backtest_errors(values, years, method, SELECTION_HORIZON, selection_last_year)
        pooled = [error for bucket in errors.values() for error in bucket]
        held_out = values[split:] - method(values[:split], TEST_YEARS)
        comparison.append({
            "method": key, "label": label,
            "backtest_rmse": round(rmse(pooled), 4),
            "test_rmse": round(rmse(held_out), 4),
            "test_bias": round(float(np.mean(held_out)), 4),
        })
    # The baseline is the score to beat, so it can't be chosen as the forecast itself.
    best = dict(min((row for row in comparison if row["method"] != BASELINE), key=lambda row: row["backtest_rmse"]))
    method = METHODS[best["method"]][1]
    margins = range_margins(backtest_errors(values, years, method, TEST_YEARS, selection_last_year), TEST_YEARS)
    held_out = values[split:] - method(values[:split], TEST_YEARS)
    best["test_coverage"] = round(float(np.mean(np.abs(held_out) <= np.asarray(margins))), 2)
    return best, comparison


def range_margins(errors, count):
    """Size of the 95% range at each horizon. Long horizons have few past examples,
    so the widest range seen so far is kept."""
    margins = []
    widest = 0.0
    for step in range(1, count + 1):
        if len(errors[step]) >= 10:
            widest = max(widest, rmse(errors[step]))
        margins.append(Z_95 * widest)
    return margins


def forecast_with_interval(years, values, method_key):
    """Forecast from the last year, with a 95% range from past errors at each horizon."""
    method = METHODS[method_key][1]
    horizon = FORECAST_TO - int(years[-1])
    years = np.asarray(years)
    values = np.asarray(values, dtype=float)
    predicted = method(values, horizon)
    margins = range_margins(backtest_errors(values, years, method, horizon, years[-1]), horizon)
    return [{
        "year": int(years[-1]) + step + 1,
        "forecast": round(float(predicted[step]), 3),
        "lower": round(float(predicted[step] - margins[step]), 3),
        "upper": round(float(predicted[step] + margins[step]), 3),
    } for step in range(horizon)]


def train_forecasts(db):
    results = []
    for series in SERIES:
        rows = db.gistemp_zonal.find({series: {"$ne": None}}, {"Year": 1, series: 1}).sort("Year", 1)
        rows = list(rows)
        years = [row["Year"] for row in rows]
        values = [row[series] for row in rows]
        best, comparison = evaluate_series(years, values)
        baseline = next(row for row in comparison if row["method"] == BASELINE)
        results.append({
            "series": series,
            "chosen_method": best["method"],
            "chosen_label": best["label"],
            "test_period": "%d-%d" % (years[-TEST_YEARS], years[-1]),
            "test_rmse": best["test_rmse"],
            "baseline_test_rmse": baseline["test_rmse"],
            "beats_baseline": best["test_rmse"] < baseline["test_rmse"],
            "test_coverage": best["test_coverage"],
            "comparison": comparison,
            "history": [{"year": y, "value": v} for y, v in zip(years, values)],
            "forecast": forecast_with_interval(years, values, best["method"]),
        })
    return results


# --- Anomaly detection ---

def read_sensor_days(directory=OPENAQ_DIR):
    """Daily statistics per sensor location and pollutant from the raw OpenAQ files."""
    frames = []
    for path in sorted(glob.glob(os.path.join(directory, "*.csv"))):
        frame = pd.read_csv(path, encoding="utf-8")
        frame = frame[frame["location_id"].astype(str) != "location_id"]
        frame["value"] = pd.to_numeric(frame["value"], errors="coerce")
        frame = frame[frame["value"] >= 0]
        frame["date"] = frame["datetime"].astype(str).str[:10]
        frames.append(frame[frame["date"].str.startswith("2023")])
    readings = pd.concat(frames, ignore_index=True)
    grouped = readings.groupby(["location_id", "location", "parameter", "units", "date"])["value"]
    days = grouped.agg(["mean", "max", "min", "count"]).reset_index()
    days["range"] = days["max"] - days["min"]
    days = days[days["count"] >= MIN_READINGS_PER_DAY]
    sizes = days.groupby(["location_id", "parameter"])["date"].transform("count")
    return days[sizes >= MIN_DAYS_PER_SENSOR].reset_index(drop=True)


def _sensor_scales(days):
    """Median and spread per sensor and pollutant, so each is judged against its own normal."""
    scales = {}
    for column in ("mean", "max", "range"):
        grouped = days.groupby(["location_id", "parameter"])[column]
        median = grouped.median().rename("median")
        iqr = (grouped.quantile(0.75) - grouped.quantile(0.25)).rename("iqr")
        scales[column] = pd.concat([median, iqr], axis=1).reset_index()
    return scales


def add_features(days, scales):
    """How unusual each day is compared with the same sensor's previous month.

    Seasons shift a sensor's normal level, so a whole-year average would flag ordinary
    autumn readings. Only earlier days are used, as a live system would have to do.
    """
    keys = ["location_id", "parameter"]
    result = days.sort_values(keys + ["date"]).reset_index(drop=True)
    for column, name in (("mean", "z_mean"), ("max", "z_max"), ("range", "z_range")):
        merged = result[keys].merge(scales[column], on=keys, how="left")
        grouped = result.groupby(keys)[column]
        window = lambda series: series.shift(1).rolling(TRAILING_DAYS, min_periods=10)
        recent_median = grouped.transform(lambda series: window(series).median())
        recent_iqr = grouped.transform(lambda series: window(series).quantile(0.75) - window(series).quantile(0.25))
        # Early days have no history yet, so they fall back on the sensor's overall figures.
        baseline = recent_median.fillna(merged["median"]).values
        spread = np.maximum(recent_iqr.fillna(0).values, merged["iqr"].values) / 1.349
        # A very flat sensor has almost no spread; a small floor stops division by zero.
        floor = np.maximum(np.abs(baseline) * 0.01, 1e-6)
        result[name] = (result[column].values - baseline) / np.maximum(spread, floor)
    return result


def injection_test(days):
    """Trains on January to September, then measures detection on the later months."""
    is_test = days["date"].str[5:7].astype(int) >= 10
    features = add_features(days, _sensor_scales(days[~is_test])).dropna(subset=ANOMALY_FEATURES)
    months = features["date"].str[5:7].astype(int)
    train, clean = features[months < 10], features[months >= 10]
    model = IsolationForest(n_estimators=200, contamination=ANOMALY_SHARE, behaviour="new", random_state=SEED)
    model.fit(train[ANOMALY_FEATURES].values)

    false_alarm_rate = float(np.mean(model.predict(clean[ANOMALY_FEATURES].values) == -1))
    rng = np.random.RandomState(SEED)
    picked = clean.iloc[rng.choice(len(clean), size=max(1, len(clean) // 20), replace=False)]
    recalls = {}
    for size in INJECTED_SPIKES:
        # Raises the day's mean and peak by this many of the sensor's usual spreads.
        spiked = picked[ANOMALY_FEATURES].values.copy()
        spiked[:, 0] += size
        spiked[:, 1] += size
        recalls[str(size)] = round(float(np.mean(model.predict(spiked) == -1)), 3)
    return {
        "train_days": int(len(train)), "test_days": int(len(clean)), "injected_days": int(len(picked)),
        "false_alarm_rate": round(false_alarm_rate, 4), "recall_by_spike_size": recalls,
    }


def train_anomaly_model():
    days = read_sensor_days()
    evaluation = injection_test(days)
    scales = _sensor_scales(days)
    features = add_features(days, scales).dropna(subset=ANOMALY_FEATURES)
    model = IsolationForest(n_estimators=200, contamination=ANOMALY_SHARE, behaviour="new", random_state=SEED)
    model.fit(features[ANOMALY_FEATURES].values)
    features = features.assign(score=-model.score_samples(features[ANOMALY_FEATURES].values),
                               flagged=model.predict(features[ANOMALY_FEATURES].values) == -1)
    flagged = features[features["flagged"]].sort_values("score", ascending=False)
    rows = [{
        "location": row["location"], "parameter": row["parameter"], "units": row["units"], "date": row["date"],
        "mean": round(float(row["mean"]), 4), "max": round(float(row["max"]), 4),
        "z_mean": round(float(row["z_mean"]), 2), "score": round(float(row["score"]), 3),
    } for _, row in flagged.iterrows()]
    summary = dict(evaluation, days_scored=int(len(features)), days_flagged=int(len(flagged)),
                   sensors=int(features.groupby(["location_id", "parameter"]).ngroups))
    return model, rows, summary


# --- Correlation ---

def correlate(name, left_label, right_label, left, right, kind, note):
    pairs = pd.DataFrame({"left": left, "right": right}).dropna()
    if len(pairs) < 5 or pairs["left"].std() == 0 or pairs["right"].std() == 0:
        return None
    pearson, pearson_p = stats.pearsonr(pairs["left"], pairs["right"])
    spearman, _ = stats.spearmanr(pairs["left"], pairs["right"])
    return {
        "name": name, "left": left_label, "right": right_label, "kind": kind, "n": int(len(pairs)),
        "pearson": round(float(pearson), 3), "pearson_p": float("%.3g" % pearson_p),
        "spearman": round(float(spearman), 3), "note": note,
    }


def correlations(db):
    results = []
    anomaly = {row["Year"]: row["J-D"] for row in db.gistemp_global.find({"J-D": {"$ne": None}})}
    co2 = {row["year"]: row["mean"] for row in db.co2_annual.find()}
    years = sorted(set(anomaly) & set(co2))
    both = pd.DataFrame({"anomaly": [anomaly[y] for y in years], "co2": [co2[y] for y in years]}, index=years)
    results.append(correlate(
        "co2_levels", "Atmospheric CO2", "Global temperature anomaly", both["co2"], both["anomaly"], "Raw yearly values",
        "Both series rise over time, which makes this figure high by itself, and its p-value too small. It doesn't prove cause."))
    changes = both.diff()
    results.append(correlate(
        "co2_changes", "Yearly change in CO2", "Yearly change in temperature anomaly", changes["co2"], changes["anomaly"],
        "Year-to-year changes", "Removes the shared long-term rise, so it tests whether the short-term changes move together."))
    for zone in db.regional_monthly.distinct("zone"):
        station = {(r["year"], r["month"]): r["mean"] for r in db.regional_monthly.find({"zone": zone, "element": "TMAX"})}
        model = {(r["year"], r["month"]): r["mean"] for r in db.satellite_zonal.find({"zone": zone, "parameter": "TS"})}
        solar = {(r["year"], r["month"]): r["mean"] for r in db.satellite_zonal.find({"zone": zone, "parameter": "ALLSKY_SFC_SW_DWN"})}
        keys = sorted(set(station) & set(model))
        if keys:
            results.append(correlate(
                "station_vs_model_" + zone, "Station daily high, " + zone, "MERRA-2 surface temperature, " + zone,
                [station[k] for k in keys], [model[k] for k in keys], "Monthly values",
                "A cross-check between ground stations and a model. Seasons drive much of this, and only 2020 and 2023 are compared."))
        keys = sorted(set(solar) & set(model))
        if keys:
            results.append(correlate(
                "solar_vs_temperature_" + zone, "CERES solar radiation, " + zone, "MERRA-2 surface temperature, " + zone,
                [solar[k] for k in keys], [model[k] for k in keys], "Monthly values",
                "Seasons drive much of this, so it is weak where seasons are small. Based on a coarse 30-point global grid."))
    return [result for result in results if result]


def export_for_r(db, path):
    """Writes the table that ml/correlation_analysis.R reads."""
    co2 = {row["year"]: row["mean"] for row in db.co2_annual.find()}
    with open(path, "w", newline="") as output:
        writer = csv.writer(output, lineterminator="\n")
        writer.writerow(["year", "anomaly", "co2"])
        for row in db.gistemp_global.find({"J-D": {"$ne": None}}).sort("Year", 1):
            if row["Year"] in co2:
                writer.writerow([row["Year"], row["J-D"], co2[row["Year"]]])


# --- Saving ---

def save_run(db, version, forecasts, anomaly_rows, anomaly_summary, correlation_rows, triggered_by):
    """Replaces the current results and adds a permanent record of this run's scores."""
    trained_at = datetime.datetime.utcnow()
    for name, documents in (("ml_forecasts", forecasts), ("ml_anomalies", anomaly_rows), ("ml_correlations", correlation_rows)):
        db[name].drop()
        if documents:
            db[name].insert_many([dict(document, version=version) for document in documents])
    db.ml_runs.insert_one({
        "version": version, "trained_at": trained_at, "triggered_by": triggered_by,
        "forecast_scores": [{key: forecast[key] for key in FORECAST_SCORE_FIELDS} for forecast in forecasts],
        "anomaly": anomaly_summary,
    })


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--triggered-by", default="command line")
    arguments = parser.parse_args()

    db = MongoClient(MONGO_URI, serverSelectionTimeoutMS=5000)[MONGO_DB]
    version = datetime.datetime.utcnow().strftime("%Y%m%d-%H%M%S")
    forecasts = train_forecasts(db)
    print("Forecasts trained:", len(forecasts))
    model, anomaly_rows, anomaly_summary = train_anomaly_model()
    print("Anomaly model:", anomaly_summary)
    correlation_rows = correlations(db)
    print("Correlations:", len(correlation_rows))

    folder = os.path.join(MODEL_DIR, version)
    os.makedirs(folder, exist_ok=True)
    joblib.dump(model, os.path.join(folder, "isolation_forest.joblib"))
    export_for_r(db, os.path.join(ROOT, "ml", "co2_temperature.csv"))
    save_run(db, version, forecasts, anomaly_rows, anomaly_summary, correlation_rows, arguments.triggered_by)
    print("Saved version", version)


if __name__ == "__main__":
    main()
