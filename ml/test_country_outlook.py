"""Checks the country outlook on made-up data where the right answer is known."""
import os
import subprocess
import sys

import numpy as np
import pandas as pd

import country_outlook as cty

JOB = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "hadoop", "jobs", "country_indicators.py")


def rows(indicator, values, first_year):
    return pd.DataFrame([{"iso3": "PAK", "country": "Pakistan", "indicator": indicator, "year": first_year + i, "value": v}
                         for i, v in enumerate(values) if v is not None])


def test_steady_warming_chooses_the_trend_and_reaches_2030():
    rng = np.random.RandomState(2)
    values = pd.Series([0.03 * i + rng.normal(0, 0.05) for i in range(63)], index=range(1961, 2024))
    outlook, score = cty.temperature_outlook(values)
    assert score["method"] == "trend"
    assert score["test_rmse"] < score["baseline_test_rmse"]
    assert [row["year"] for row in outlook] == list(range(2024, 2031))
    assert outlook[-1]["value"] > outlook[0]["value"]
    assert all(row["low"] < row["value"] < row["high"] for row in outlook)


def test_flat_noise_keeps_the_average():
    rng = np.random.RandomState(3)
    values = pd.Series(rng.normal(0, 0.5, 63), index=range(1961, 2024))
    assert cty.temperature_outlook(values)[1]["method"] == "average"


def test_blank_years_count_as_no_recorded_disaster():
    data = pd.concat([rows("disasters_storm", [1, None, 2, None], 2021), rows("people_affected_storm", [10, None, 500, None], 2021)])
    record = cty.disaster_record(data, "storm", 2020, 2024)
    assert record["years"] == 5 and record["years_with"] == 2 and record["events"] == 3
    assert record["chance"] == 0.4 and record["latest_year"] == 2023
    assert record["worst_year"] == 2023 and record["worst_affected"] == 500
    assert record["by_year"]["2020"] == 0 and record["by_year"]["2022"] == 0


def test_forest_record_reports_the_yearly_change():
    record = cty.forest_record(rows("share_of_forest_area", [6.0, 5.9, 5.8], 2000))
    assert record["first_share"] == 6.0 and record["last_share"] == 5.8
    assert abs(record["yearly_change"] + 0.1) < 1e-9


def run_job(text):
    mapped = subprocess.run([sys.executable, JOB, "map"], input=text, stdout=subprocess.PIPE, universal_newlines=True, check=True).stdout
    ordered = "".join(sorted(mapped.splitlines(True)))
    return subprocess.run([sys.executable, JOB, "reduce"], input=ordered, stdout=subprocess.PIPE, universal_newlines=True, check=True).stdout.splitlines()


def test_job_turns_year_columns_into_rows_and_drops_commas_in_names():
    text = ("ObjectId,Country,ISO2,ISO3,Indicator,Unit,Source,CTS Code,CTS Name,CTS Full Descriptor,2000,2001\n"
            '1,"Afghanistan, Islamic Rep. of",AF,AFG,"Climate related disasters frequency, Number of Disasters: Storm",Number of,"x, y",E,N,"a, b",,2\n'
            '2,Pakistan,PK,PAK,"Temperature change with respect to a baseline climatology, corresponding to the period 1951-1980",Degree Celsius,s,E,N,d,0.5,0.75\n'
            "3,World,,,Forest area,1000 HA,s,E,N,d,1,2\n")
    assert run_job(text) == ["AFG,Afghanistan Islamic Rep. of,disasters_storm,Number of,2001,2",
                             "PAK,Pakistan,temperature_change,Degree Celsius,2000,0.5",
                             "PAK,Pakistan,temperature_change,Degree Celsius,2001,0.75"]


def test_cmip6_check_moves_the_measured_years_onto_the_models_baseline():
    # Measured: 0.5 every year from 1995 to 2014, then 1.5; on a 1995-2014 baseline that is +1.0.
    observed = pd.Series([0.5] * 20 + [1.5] * 3, index=range(1995, 2018))
    projected = pd.DataFrame([{"year": year, "percentile": pct, "change": change} for year in (2015, 2016, 2017)
                              for pct, change in (("p10", 0.5), ("median", 1.2), ("p90", 1.4))])
    check = cty.cmip6_check(observed, projected)
    assert check["count"] == 3 and abs(check["bias"] - 0.2) < 1e-9
    assert check["inside_range"] == 1.0


def test_cmip6_check_needs_a_baseline():
    assert cty.cmip6_check(pd.Series([1.0, 1.1], index=[2015, 2016]), pd.DataFrame([{"year": 2015, "percentile": "median", "change": 1.0}])) is None
