"""Fetches CMIP6 climate model projections for Pakistan from the World Bank Climate Change Knowledge Portal.

Writes data/raw/cmip6/pakistan_cmip6.csv (ignored by git): one row per measure, scenario,
model percentile and year. Needs only the standard library.

The figures are the World Bank's country averages of the CMIP6 multi-model ensemble at 0.25°:
the 10th percentile, median and 90th percentile across the models for each year.
"historical" is the models' own run of 1950-2014, used as the baseline for change.
"""
import csv
import json
import os
import time
import urllib.error
import urllib.request

API = "https://cckpapi.worldbank.org/cckp/v1/"
COUNTRY = "PAK"
TARGET = os.path.join(os.path.dirname(os.path.abspath(__file__)), "raw", "cmip6", "pakistan_cmip6.csv")
MEASURES = ["tas", "tasmax", "tasmin", "pr", "hd35", "hd40", "txx", "rx1day", "cdd"]
SCENARIOS = {"ssp126": "2015-2100", "ssp245": "2015-2100", "ssp370": "2015-2100", "ssp585": "2015-2100", "historical": "1950-2014"}
PERCENTILES = ["p10", "median", "p90"]
WAITS = (10, 60, 300)


def get(code):
    request = urllib.request.Request(API + code + "/" + COUNTRY + "?_format=json", headers={"User-Agent": "earthscape-eproject"})
    for wait in WAITS + (None,):
        try:
            with urllib.request.urlopen(request, timeout=60) as response:
                return json.loads(response.read().decode("utf-8"))["data"]
        except (urllib.error.URLError, TimeoutError) as error:
            if wait is None:
                raise
            print("No answer (%s), waiting %d seconds" % (error, wait), flush=True)
            time.sleep(wait)


def series(measure, scenario, percentile):
    code = "cmip6-x0.25_timeseries_%s_timeseries_annual_%s_%s_%s_ensemble_all_mean" % (measure, SCENARIOS[scenario], percentile, scenario)
    data = get(code)
    values = data.get(COUNTRY, {}) if isinstance(data, dict) else {}
    # Each year is keyed by its middle month, such as 2027-07.
    return sorted((int(key[:4]), value) for key, value in values.items() if value is not None)


def main():
    os.makedirs(os.path.dirname(TARGET), exist_ok=True)
    partial = TARGET + ".part"
    rows = 0
    with open(partial, "w", newline="", encoding="utf-8") as output:
        writer = csv.writer(output, lineterminator="\n")
        writer.writerow(["iso3", "measure", "scenario", "percentile", "year", "value"])
        for measure in MEASURES:
            for scenario in SCENARIOS:
                for percentile in PERCENTILES:
                    points = series(measure, scenario, percentile)
                    if not points:
                        raise SystemExit("No data for %s %s %s" % (measure, scenario, percentile))
                    writer.writerows([COUNTRY, measure, scenario, percentile, year, value] for year, value in points)
                    rows += len(points)
                    time.sleep(0.3)
            print("Fetched", measure, flush=True)
    os.replace(partial, TARGET)
    print("Saved", rows, "rows to", TARGET)


if __name__ == "__main__":
    main()
