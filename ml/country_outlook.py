"""A country-wide outlook for Pakistan from the IMF Climate Change Indicators.

Temperature: how much warmer than 1951-1980 each year up to 2030 should be, with a range
taken from how far the same method missed on past years.
Disasters: how often storms, floods and other climate disasters were recorded each year.
This is a record of what happened, not a forecast of a particular event.
Reads country_indicators, which the country_indicators MapReduce job fills.
"""
import numpy as np
import pandas as pd

import city_outlook as co

COUNTRY = "PAK"
LAST_OUTLOOK_YEAR = 2030
SELECTION_START = 1994
SELECTION_END = 2010
MIN_HISTORY_YEARS = 20
RECENT_YEARS = 10
DISASTER_KINDS = ["storm", "flood", "extreme_temperature", "drought", "landslide", "total"]
FOREST = "share_of_forest_area"
METHODS = {"average": ("Average of the last 10 years", co.recent_average), "trend": ("Trend over the last 30 years", co.recent_trend)}
BASELINE = "average"


def series(rows, indicator):
    """One indicator as a Series indexed by year."""
    picked = rows[rows["indicator"] == indicator]
    return picked.set_index("year")["value"].astype(float).sort_index()


def backtest(values, method, first_target, last_target, max_horizon):
    """Errors by horizon. Each forecast sees only the years before its starting point."""
    errors = {horizon: [] for horizon in range(1, max_horizon + 1)}
    years = values.index.to_numpy()
    for horizon in errors:
        for target in range(first_target, last_target + 1):
            history = values[years <= target - horizon]
            if len(history) < MIN_HISTORY_YEARS or target not in values.index:
                continue
            errors[horizon].append(method(history.to_numpy(), horizon)[-1] - values[target])
    return errors


def temperature_outlook(values, last_outlook_year=LAST_OUTLOOK_YEAR):
    """Returns (rows for each future year, score). Chooses a method on the years up to 2010, then tests it once on the rest."""
    last_year = int(values.index.max())
    max_horizon = last_outlook_year - last_year
    selection = {key: backtest(values, method, SELECTION_START, SELECTION_END, max_horizon) for key, (_label, method) in METHODS.items()}
    chosen = min(selection, key=lambda key: co.rmse(co.flatten(selection[key])))
    test = {key: backtest(values, method, SELECTION_END + 1, last_year, max_horizon) for key, (_label, method) in METHODS.items()}
    margins = {horizon: co.RANGE_Z * co.rmse(errors) for horizon, errors in selection[chosen].items()}
    inside = [abs(error) <= margins[horizon] for horizon, errors in test[chosen].items() for error in errors]
    predicted = METHODS[chosen][1](values.to_numpy(), max_horizon)
    rows = [{"year": last_year + horizon, "horizon": horizon, "value": round(float(predicted[horizon - 1]), 2),
             "low": round(float(predicted[horizon - 1] - margins[horizon]), 2), "high": round(float(predicted[horizon - 1] + margins[horizon]), 2)}
            for horizon in range(1, max_horizon + 1)]
    score = {"variable": "temperature_change", "method": chosen, "method_label": METHODS[chosen][0],
             "test_rmse": round(co.rmse(co.flatten(test[chosen])), 3), "baseline_test_rmse": round(co.rmse(co.flatten(test[BASELINE])), 3),
             "test_coverage": round(float(np.mean(inside)), 3), "test_period": "%d-%d" % (SELECTION_END + 1, last_year),
             "last_year": last_year, "last_value": round(float(values.iloc[-1]), 3),
             "recent_average": round(float(values.iloc[-RECENT_YEARS:].mean()), 3)}
    return rows, score


def disaster_record(rows, kind, first_year, last_year):
    """How many years had at least one recorded disaster of this kind. A blank year means none were recorded."""
    counts = series(rows, "disasters_" + kind).reindex(range(first_year, last_year + 1)).fillna(0)
    affected = series(rows, "people_affected_" + kind).reindex(range(first_year, last_year + 1)).fillna(0)
    total = len(counts)
    hits = int((counts > 0).sum())
    low, high = co.chance_range(hits, total)
    recent = counts.iloc[-RECENT_YEARS:]
    worst_year = int(affected.idxmax()) if affected.max() > 0 else None
    return {"kind": kind, "first_year": first_year, "last_year": last_year, "years": total, "years_with": hits,
            "events": int(counts.sum()), "chance": round(hits / total, 3), "chance_low": round(low, 3), "chance_high": round(high, 3),
            "recent_years": len(recent), "recent_years_with": int((recent > 0).sum()), "recent_events": int(recent.sum()),
            "latest_year": int(counts[counts > 0].index.max()) if hits else None,
            "worst_year": worst_year, "worst_affected": int(affected.max()) if worst_year else 0,
            "by_year": {str(year): int(count) for year, count in counts.items()}}


def forest_record(rows):
    share = series(rows, FOREST)
    if share.empty:
        return None
    return {"first_year": int(share.index.min()), "first_share": round(float(share.iloc[0]), 2), "last_year": int(share.index.max()),
            "last_share": round(float(share.iloc[-1]), 2), "yearly_change": round(float(np.polyfit(share.index.to_numpy(), share.to_numpy(), 1)[0]), 3)}


CMIP6_BASELINE = (1995, 2014)
CMIP6_CHECK_SCENARIO = "ssp245"


def cmip6_check(observed, projected):
    """How well the climate models' middle scenario matches the measured years since 2015.

    observed: measured temperature change by year (any baseline). projected: CMIP6 rows with
    year, percentile and change against the models' own 1995-2014 average. The measured series
    is moved onto the same 1995-2014 baseline first."""
    base = observed[(observed.index >= CMIP6_BASELINE[0]) & (observed.index <= CMIP6_BASELINE[1])]
    if len(base) < 15 or projected.empty:
        return None
    measured = observed - base.mean()
    table = projected.pivot(index="year", columns="percentile", values="change")
    years = [year for year in measured.index if year in table.index]
    if not years:
        return None
    errors = np.array([table.loc[year, "median"] - measured[year] for year in years])
    inside = [table.loc[year, "p10"] <= measured[year] <= table.loc[year, "p90"] for year in years]
    return {"variable": "cmip6_check", "scenario": CMIP6_CHECK_SCENARIO, "years": "%d-%d" % (years[0], years[-1]), "count": len(years),
            "bias": round(float(errors.mean()), 3), "rmse": round(co.rmse(errors), 3), "inside_range": round(float(np.mean(inside)), 3)}


def read_rows(db, country=COUNTRY):
    rows = pd.DataFrame(list(db.country_indicators.find({"iso3": country}, {"_id": 0})))
    span = list(db.country_indicators.aggregate([{"$match": {"indicator": {"$regex": "^disasters_"}}},
                                                 {"$group": {"_id": None, "first": {"$min": "$year"}, "last": {"$max": "$year"}}}]))
    return rows, (span[0]["first"], span[0]["last"]) if span else (None, None)


def has_data(db, country=COUNTRY):
    return db.country_indicators.find_one({"iso3": country, "indicator": "temperature_change"}) is not None


def build(db, country=COUNTRY):
    """Everything to save, as collection name to documents, plus a summary."""
    rows, (first_year, last_year) = read_rows(db, country)
    name = str(rows["country"].iloc[0])
    tag = {"iso3": country, "country": name}
    outlook, score = temperature_outlook(series(rows, "temperature_change"))
    disasters = [dict(tag, **disaster_record(rows, kind, first_year, last_year)) for kind in DISASTER_KINDS] if first_year else []
    forest = forest_record(rows)
    projected = pd.DataFrame(list(db.cmip6_projections.find({"iso3": country, "measure": "tas", "scenario": CMIP6_CHECK_SCENARIO}, {"_id": 0})))
    check = cmip6_check(series(rows, "temperature_change"), projected)
    collections = {
        "country_outlook": [dict(tag, **row) for row in outlook],
        "country_scores": [dict(tag, **score)] + ([dict(tag, **check)] if check else []),
        "country_disasters": disasters,
        "country_forest": [dict(tag, **forest)] if forest else [],
    }
    summary = dict(score, country=name, outlook_years="%d-%d" % (outlook[0]["year"], outlook[-1]["year"]),
                   storm_chance=next((record["chance"] for record in disasters if record["kind"] == "storm"), None), cmip6_check=check)
    return collections, summary


def save(db, version, collections):
    for name, documents in collections.items():
        db[name].drop()
        if documents:
            db[name].insert_many([dict(document, version=version) for document in documents])
    db.country_outlook.create_index([("iso3", 1), ("year", 1)])
    db.country_disasters.create_index([("iso3", 1), ("kind", 1)])
