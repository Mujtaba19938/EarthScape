"""Checks the modelling logic on made-up data where the right answer is known."""
import numpy as np
import pandas as pd

import train_models as tm


def steady_rise(start=1900, end=2020, slope=0.02, noise=0.02):
    rng = np.random.RandomState(1)
    years = np.arange(start, end + 1)
    return years, slope * (years - start) + rng.normal(0, noise, len(years))


def test_linear_method_continues_a_straight_line():
    predicted = tm.linear_30y(np.arange(40.0), 3)
    assert np.allclose(predicted, [40, 41, 42])


def test_backtest_never_uses_the_future():
    seen = []

    def spy(values, horizon):
        seen.append(len(values))
        return np.zeros(horizon)

    years = np.arange(1940, 1971)
    tm.backtest_errors(np.arange(31.0), years, spy, 5, 1970)
    # The first origin is 1950, the 11th year, so it may only see 11 values.
    assert seen[0] == 11
    assert seen == sorted(seen)


def test_backtest_ignores_years_held_back_for_the_final_test():
    years = np.arange(1940, 2021)
    values = np.zeros(len(years))
    values[years > 2010] = 1000.0
    errors = tm.backtest_errors(values, years, tm.persistence, 3, 2010)
    pooled = [error for bucket in errors.values() for error in bucket]
    assert max(abs(error) for error in pooled) == 0


def test_a_trend_beats_the_baseline_on_a_rising_series():
    years, values = steady_rise()
    best, comparison = tm.evaluate_series(years, values)
    scores = {row["method"]: row["test_rmse"] for row in comparison}
    assert best["method"] != "persistence"
    assert scores[best["method"]] < scores["persistence"]


def test_forecast_reaches_the_end_year_and_its_range_never_narrows():
    years, values = steady_rise()
    rows = tm.forecast_with_interval(years, values, "linear_50y")
    assert rows[0]["year"] == 2021
    assert rows[-1]["year"] == tm.FORECAST_TO
    widths = [row["upper"] - row["lower"] for row in rows]
    # Bounds are rounded to 3 decimals, so a steady width can wobble by up to 0.002.
    assert all(later >= earlier - 0.0021 for earlier, later in zip(widths, widths[1:]))
    assert rows[0]["lower"] < rows[0]["forecast"] < rows[0]["upper"]


def test_rising_series_correlate_in_levels_but_unrelated_changes_do_not():
    rng = np.random.RandomState(3)
    trend = np.arange(2000.0)
    left = pd.Series(trend + rng.normal(0, 2, 2000))
    right = pd.Series(trend + rng.normal(0, 2, 2000))
    levels = tm.correlate("a", "l", "r", left, right, "levels", "")
    changes = tm.correlate("b", "l", "r", left.diff(), right.diff(), "changes", "")
    assert levels["pearson"] > 0.9
    assert abs(changes["pearson"]) < 0.15


def test_correlation_skips_too_little_or_flat_data():
    assert tm.correlate("a", "l", "r", [1, 2], [1, 2], "k", "") is None
    assert tm.correlate("a", "l", "r", [1, 1, 1, 1, 1, 1], [1, 2, 3, 4, 5, 6], "k", "") is None


def sensor_days(rng, count=365):
    dates = pd.date_range("2023-01-01", periods=count).strftime("%Y-%m-%d")
    base = rng.normal(10, 1, count)
    return pd.DataFrame({
        "location_id": 1, "location": "A", "parameter": "pm25", "units": "x", "date": dates,
        "mean": base, "max": base + rng.normal(5, 1, count), "min": base - 2, "count": 24,
        "range": 7.0 + rng.normal(0, 1, count),
    })


def test_big_spikes_are_found_more_often_than_clean_days_are_flagged():
    result = tm.injection_test(sensor_days(np.random.RandomState(5)))
    assert result["recall_by_spike_size"]["10"] > 0.9
    assert result["recall_by_spike_size"]["10"] >= result["recall_by_spike_size"]["3"]
    assert result["false_alarm_rate"] < 0.25


def test_each_sensor_is_judged_against_its_own_normal():
    rng = np.random.RandomState(6)
    clean = sensor_days(rng)
    dirty = sensor_days(rng).assign(location_id=2)
    dirty["mean"] = dirty["mean"] * 50
    both = pd.concat([clean, dirty], ignore_index=True)
    features = tm.add_features(both, tm._sensor_scales(both))
    # A city that is always 50 times dirtier isn't an anomaly in itself.
    assert abs(features[features.location_id == 2]["z_mean"].median()) < 0.5


def test_slow_seasonal_rise_scores_far_below_a_sudden_jump():
    days = sensor_days(np.random.RandomState(8))
    days["mean"] = days["mean"] + np.arange(365) * 0.1
    days.loc[200, "mean"] += 100
    features = tm.add_features(days, tm._sensor_scales(days))
    assert features.loc[199, "z_mean"] < 3
    # The ramp itself gives this sensor a spread of about 13.5, so a jump of 100 scores about 7.5.
    assert features.loc[200, "z_mean"] > 5


def test_a_day_is_never_scored_using_later_days():
    days = sensor_days(np.random.RandomState(9))
    scales = tm._sensor_scales(days)
    changed = days.copy()
    changed.loc[changed.index > 100, "mean"] += 1000
    before = tm.add_features(days, scales).loc[100, "z_mean"]
    after = tm.add_features(changed, scales).loc[100, "z_mean"]
    assert before == after


def test_baseline_is_never_chosen_even_when_it_is_hard_to_beat():
    rng = np.random.RandomState(10)
    years = np.arange(1900, 2021)
    best, _ = tm.evaluate_series(years, np.cumsum(rng.normal(0, 1, len(years))))
    assert best["method"] != tm.BASELINE
    assert 0 <= best["test_coverage"] <= 1


def test_coverage_is_measured_against_ranges_built_before_the_test_years():
    years = np.arange(1900, 2021)
    rng = np.random.RandomState(11)
    values = 0.02 * (years - 1900) + rng.normal(0, 0.05, len(years))
    values[-10:] += 100
    best, _ = tm.evaluate_series(years, values)
    # A huge jump in the unseen decade can't widen the ranges meant to catch it.
    assert best["test_coverage"] == 0


def test_flat_sensor_does_not_divide_by_zero():
    days = sensor_days(np.random.RandomState(7))
    days["mean"] = 0.0
    features = tm.add_features(days, tm._sensor_scales(days))
    assert np.isfinite(features["z_mean"]).all()
