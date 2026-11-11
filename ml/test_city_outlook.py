"""Checks the city outlook and storm logic on made-up data where the right answer is known."""
import numpy as np
import pandas as pd
import pytest

import city_outlook as co


def yearly_table(slope=0.05, noise=0.0, start=1980, end=2025):
    rng = np.random.RandomState(1)
    years = list(range(start, end + 1))
    rows = {month: [20 + month + slope * (year - start) + rng.normal(0, noise) if noise else 20 + month + slope * (year - start) for year in years] for month in range(1, 13)}
    return pd.DataFrame(rows, index=pd.Index(years, name="year"))


def test_trend_continues_a_straight_line():
    assert np.allclose(co.recent_trend(np.arange(40.0), 3), [40, 41, 42])


def test_backtest_never_uses_the_future():
    seen = []

    def spy(values, horizon, _yearly):
        seen.append(len(values))
        return np.zeros(horizon)

    table = yearly_table(end=2000)
    co.backtest(table, spy, 1996, 2000)
    # A one-year-ahead forecast for 1996 may only see 1980 to 1995, which is 16 years.
    assert max(seen) <= 20
    assert seen[0] == 16


def test_warming_method_adds_the_gap_between_the_average_and_the_future():
    # A rise of 1 a year: the last 10 values, 30 to 39, average 34.5, so one year on should be 40.
    values = np.arange(40.0)
    assert np.allclose(co.average_plus_warming(values, 2, values), [40, 41])


def test_a_steady_rise_chooses_a_rising_method_and_beats_the_baseline():
    score = co.score_variable(yearly_table(noise=0.05))
    assert score["method"] in ("trend", "warming")
    assert score["test_rmse"] < score["baseline_test_rmse"]
    assert score["test_coverage"] > 0.8


def test_flat_noise_keeps_the_simple_average():
    assert co.score_variable(yearly_table(slope=0, noise=1.0))["method"] == "average"


def test_monthly_table_counts_rain_and_gale_days():
    days = pd.DataFrame({"date": ["2020-01-01", "2020-01-02", "2020-01-03"], "tmax_c": [10.0, 20.0, 30.0], "tmin_c": [1.0, 2.0, 3.0],
                         "rain_mm": [0.0, 2.0, 60.0], "gust_kmh": [10.0, 62.0, 90.0]})
    row = co.monthly_table(days).iloc[0]
    assert row["tmax_c"] == 20 and row["rain_mm"] == 62
    assert row["rain_days"] == 2 and row["heavy_days"] == 1 and row["gale_days"] == 2


def test_distance_is_right_for_a_known_pair():
    # Karachi to Lahore is about 1,030 km.
    assert co.distance_km(24.86, 67.01, np.array([31.55]), np.array([74.34]))[0] == pytest.approx(1030, abs=30)


def test_chance_range_stays_above_zero_when_nothing_has_happened():
    low, high = co.chance_range(0, 46)
    assert low == 0 and 0.05 < high < 0.1


def tracks(*points):
    return pd.DataFrame(list(points), columns=["SID", "NAME", "year", "month", "LAT", "LON", "knots"])


def test_storm_record_counts_only_nearby_storms_once_per_year():
    record = co.storm_record(tracks(
        ("A", "NEAR", 2000, 6, 24.0, 67.0, 50), ("A", "NEAR", 2000, 6, 24.5, 67.0, 60),
        ("B", "SECOND", 2000, 10, 25.0, 66.0, 40),
        ("C", "FAR", 2001, 6, 12.0, 85.0, 90),
    ), 24.86, 67.01, 2000, 2009)
    assert [storm["name"] for storm in record["storms"]] == ["Near", "Second"]
    assert record["storms"][0]["knots"] == 60
    assert record["years_with_storm"] == 1
    assert record["chance"] == 0.1
    assert record["by_month"]["6"] == 1 and record["by_month"]["10"] == 1


def test_a_storm_with_two_names_uses_the_last_one():
    record = co.storm_record(tracks(("A", "GULAB:SHAHEEN-GU", 2021, 10, 24.5, 67.0, 50)), 24.86, 67.01, 2021, 2021)
    assert record["storms"][0]["name"] == "Shaheen"


def test_read_tracks_skips_units_line_weak_points_and_spurs(tmp_path):
    path = tmp_path / "tracks.csv"
    path.write_text("SID,SEASON,NAME,ISO_TIME,TRACK_TYPE,LAT,LON,WMO_WIND,USA_WIND\n"
                    ",Year,,,,deg,deg,kts,kts\n"
                    "A,2000,ONE,2000-06-01 00:00:00,main,20,60, ,50\n"
                    "B,2000,TWO,2000-06-01 00:00:00,main,20,60,40, \n"
                    "C,2000,WEAK,2000-06-01 00:00:00,main,20,60, ,30\n"
                    "D,2000,SPUR,2000-06-01 00:00:00,spur-main,20,60, ,60\n")
    assert list(co.read_tracks(str(path))["NAME"]) == ["ONE", "TWO"]
