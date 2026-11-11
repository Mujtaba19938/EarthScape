"""Question answering tests against a separate database. The live forecast is replaced by a stand-in."""
import datetime
import os
import urllib.error
from unittest import mock

os.environ["MONGO_DB"] = "earthscape_test"
os.environ["JWT_SECRET"] = "test-secret-only-used-by-the-test-suite-0123456789"

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app import ask  # noqa: E402
from app.db import client as mongo_client  # noqa: E402
from app.db import db  # noqa: E402
from app.field_crypto import email_fields  # noqa: E402
from app.main import app  # noqa: E402
from app.security import hash_password  # noqa: E402

COLLECTIONS = ("city_history", "city_outlooks", "city_usual", "city_storms", "city_scores", "ml_forecasts")
NOW = datetime.date(2026, 11, 4)


@pytest.fixture(autouse=True)
def clean_data():
    assert db.name == "earthscape_test"
    mongo_client.drop_database("earthscape_test")
    for month in range(1, 13):
        db.city_outlooks.insert_one({"city": "Karachi", "year": 2027, "month": month, "horizon": 2, "tmax_c": 25.0 + month, "tmax_c_low": 24.0 + month, "tmax_c_high": 26.0 + month,
                                     "tmin_c": 15.0 + month, "tmin_c_low": 14.0 + month, "tmin_c_high": 16.0 + month})
        db.city_usual.insert_one({"city": "Karachi", "month": month, "years": 30, "rain_low": 0.0, "rain_mm": 80.0 if month == 7 else 2.0, "rain_high": 200.0, "rain_days": 1.5, "heavy_days": 0.1, "gale_days": 0.2})
        db.city_history.insert_one({"city": "Karachi", "year": 2023, "month": month, "tmax_c": 30.0 + month, "tmin_c": 20.0, "rain_mm": 5.0, "rain_days": 1, "gale_days": 0})
    db.city_scores.insert_one({"city": "Karachi", "variable": "tmax_c", "method_label": "Trend over the last 30 years", "test_rmse": 0.8, "baseline_test_rmse": 0.9, "test_period": "2016-2025"})
    db.city_storms.insert_many([
        {"city": "Karachi", "first_year": 1980, "last_year": 2025, "years": 46, "years_with_storm": 5, "chance": 0.109, "chance_low": 0.05, "chance_high": 0.23, "radius_km": 300,
         "by_month": dict({str(m): 0 for m in range(1, 13)}, **{"6": 4, "11": 1}),
         "storms": [{"name": "Phet", "year": 2010, "month": 6, "closest_km": 200, "knots": 60}, {"name": "Biparjoy", "year": 2023, "month": 6, "closest_km": 150, "knots": 100}]},
        {"city": "Gilgit", "first_year": 1980, "last_year": 2025, "years": 46, "years_with_storm": 0, "chance": 0.0, "chance_low": 0.0, "chance_high": 0.077, "radius_km": 300,
         "by_month": {str(m): 0 for m in range(1, 13)}, "storms": []},
    ])
    db.ml_forecasts.insert_one({"series": "24N-44N", "forecast": [{"year": 2045, "forecast": 2.1, "lower": 1.5, "upper": 2.7}]})
    db.users.insert_one(dict(email_fields("analyst@test.local"), password_hash=hash_password("analyst-password"), role="Analyst", name="Ana", active=True))
    yield
    mongo_client.drop_database("earthscape_test")


def calm_days(**changes):
    return [dict({"date": (NOW + datetime.timedelta(days=i)).isoformat(), "high": 30.0, "low": 20.0, "rain": 0.0, "rain_chance": 5, "gust": 20.0, "code": 1}, **changes) for i in range(16)]


def forecast_of(**changes):
    return lambda names: {name: calm_days(**changes) for name in names}


@pytest.mark.parametrize("question, city, year, month", [
    ("what will be the weather of Karachi in 2027", ["Karachi"], 2027, None),
    ("Lahore in June 2028?", ["Lahore"], 2028, 6),
    ("will it rain in QUETTA next year", ["Quetta"], 2027, None),
    ("weather in Multan next month", ["Multan"], 2026, 12),
    ("rain in Sukkur in march", ["Sukkur"], 2027, 3),
    ("in may in Gilgit", ["Gilgit"], 2027, 5),
])
def test_parse_finds_city_and_time(question, city, year, month):
    parsed = ask.parse(question, NOW)
    assert (parsed["cities"], parsed["year"], parsed["month"]) == (city, year, month)


def test_may_as_a_verb_is_not_the_month():
    assert ask.parse("what may the weather be in Karachi", NOW)["month"] is None


def test_parse_recognises_storm_words_and_the_near_future():
    parsed = ask.parse("are there any chances of any hurricane or storm in the near future", NOW)
    assert parsed["storm"] and parsed["near"] and parsed["cities"] == []


def test_future_year_gives_the_outlook_with_a_range_and_a_warning():
    result = ask.answer_question("What will the weather be in Karachi in 2027?")
    assert result["kind"] == "outlook"
    assert "December" in result["answer"] and "37" in result["answer"]
    assert "July is usually the wettest" in result["answer"]
    assert len(result["rows"]) == 12
    assert any("one exact day" in note for note in result["notes"])
    assert any("off by about 0.8" in note for note in result["notes"])
    assert result["chart"]["labels"][0] == "Jan"


def test_one_month_gives_one_row_and_no_chart():
    result = ask.answer_question("Karachi in July 2027")
    assert len(result["rows"]) == 1 and result["chart"] is None
    assert "32" in result["answer"] and "80 mm" in result["answer"]


def test_a_past_year_uses_the_record_not_the_model():
    result = ask.answer_question("How hot was Karachi in June 2023?")
    assert result["kind"] == "history" and "36" in result["answer"]


def test_a_year_too_far_ahead_is_refused_and_uses_the_band_forecast():
    result = ask.answer_question("weather in Karachi in 2045")
    assert "too far ahead" in result["answer"] and "+2.1" in result["answer"]


def test_a_year_before_the_record_says_so():
    assert "starts in 2023" in ask.answer_question("weather in Karachi in 1950")["answer"]


def test_near_storm_with_calm_forecast_says_nothing_shows_and_covers_every_city():
    with mock.patch.object(ask, "fetch_forecast", forecast_of()) as _patched:
        result = ask.answer_question("are there any chances of any hurricane or storm in the near future")
    assert result["kind"] == "storm" and result["answer"].startswith("Nothing storm-like")
    assert "any of the 12 cities" in result["answer"]
    assert "Karachi has the highest chance" in result["answer"]
    assert any("Pakistan Meteorological Department" in note for note in result["notes"])


@pytest.mark.parametrize("changes, reason", [({"code": 95}, "Thunderstorm"), ({"gust": 80.0}, "gusts of 80"), ({"rain": 70.0}, "70 mm")])
def test_near_storm_flags_the_days_that_qualify(changes, reason):
    with mock.patch.object(ask, "fetch_forecast", forecast_of(**changes)):
        result = ask.answer_question("any storm in Karachi soon?")
    assert result["answer"].startswith("Yes")
    assert reason in result["rows"][0][2]
    assert "Biparjoy" in result["answer"]


def test_future_storm_gives_the_historical_chance_and_never_a_forecast():
    result = ask.answer_question("Could a cyclone hit Karachi in 2028?")
    assert result["answer"].startswith("No one can forecast")
    assert "11%" in result["answer"] and "Biparjoy" in result["answer"] and "June" in result["answer"]


def test_a_city_with_no_storms_still_gives_an_upper_estimate():
    assert "No tropical storm" in ask.answer_question("any cyclone in Gilgit in 2028")["answer"]


def test_a_past_storm_question_lists_that_years_storms():
    result = ask.answer_question("was there a cyclone in Karachi in 2023")
    assert result["rows"][0][0] == "Biparjoy"


def test_the_near_future_weather_uses_the_forecast():
    with mock.patch.object(ask, "fetch_forecast", forecast_of()):
        with mock.patch.object(ask, "today", return_value=NOW):
            result = ask.answer_question("weather in Lahore tomorrow")
    assert result["kind"] == "forecast" and len(result["rows"]) == 16


def test_a_failed_forecast_says_so():
    with mock.patch.object(ask, "fetch_forecast", side_effect=urllib.error.URLError("down")):
        assert ask.answer_question("weather in Lahore tomorrow")["kind"] == "unavailable"


def test_a_weather_question_without_a_city_asks_which_one():
    assert "Which city" in ask.answer_question("what will the weather be in 2027")["answer"]


def test_an_unrelated_question_gets_help():
    assert ask.answer_question("who won the cricket")["kind"] == "help"


def test_an_untrained_model_says_so():
    db.city_outlooks.drop()
    assert ask.answer_question("weather in Karachi in 2027")["kind"] == "unavailable"


def test_the_endpoint_needs_a_login_and_limits_length():
    with TestClient(app) as client:
        assert client.post("/api/ml/ask", json={"question": "weather in Karachi in 2027"}).status_code == 401
        token = client.post("/api/auth/login", json={"email": "analyst@test.local", "password": "analyst-password"}).json()["token"]
        headers = {"Authorization": "Bearer " + token}
        assert client.post("/api/ml/ask", json={"question": "x" * 301}, headers=headers).status_code == 422
        response = client.post("/api/ml/ask", json={"question": "weather in Karachi in 2027"}, headers=headers)
        assert response.status_code == 200 and response.json()["kind"] == "outlook"


def add_country_data():
    db.country_outlook.insert_many([{"iso3": "PAK", "country": "Pakistan", "year": year, "horizon": year - 2023, "value": 1.2 + 0.05 * (year - 2024),
                                     "low": 0.6, "high": 1.9} for year in range(2024, 2031)])
    db.country_scores.insert_one({"iso3": "PAK", "country": "Pakistan", "variable": "temperature_change", "method": "trend", "method_label": "Trend over the last 30 years",
                                  "test_rmse": 0.31, "baseline_test_rmse": 0.35, "test_period": "2011-2023", "last_year": 2023, "last_value": 1.046})
    db.country_indicators.insert_many([{"iso3": "PAK", "country": "Pakistan", "indicator": "temperature_change", "unit": "Degree Celsius", "year": year, "value": 0.05 * (year - 2000)}
                                       for year in range(2000, 2024)])
    for kind, years_with, latest in (("storm", 24, 2024), ("flood", 40, 2024), ("total", 43, 2024)):
        db.country_disasters.insert_one({"iso3": "PAK", "country": "Pakistan", "kind": kind, "first_year": 1980, "last_year": 2024, "years": 45, "years_with": years_with,
                                         "events": years_with, "chance": round(years_with / 45, 3), "chance_low": 0.4, "chance_high": 0.9, "recent_years": 10,
                                         "recent_years_with": 8, "recent_events": 12, "latest_year": latest, "worst_year": 2022, "worst_affected": 33016869, "by_year": {}})
    db.country_forest.insert_one({"iso3": "PAK", "country": "Pakistan", "first_year": 1992, "first_share": 6.23, "last_year": 2023, "last_share": 4.67, "yearly_change": -0.05})


def test_pakistan_temperature_question_uses_the_country_outlook():
    add_country_data()
    result = ask.answer_question("How much warmer will Pakistan be in 2030?")
    assert result["kind"] == "outlook" and "+1.5" in result["answer"]
    assert len(result["rows"]) == 7 and result["chart"]["labels"][-1] == "2030"
    assert any("off by about 0.31" in note for note in result["notes"])


def test_pakistan_flood_question_gives_the_disaster_record():
    add_country_data()
    result = ask.answer_question("How often do floods hit Pakistan?")
    assert result["kind"] == "disasters"
    assert "floods were recorded as disasters in 40 of the 45 years" in result["answer"]
    assert "2022" in result["answer"] and "33,016,869" in result["answer"]
    assert [row[0] for row in result["rows"]] == ["Storms", "Floods", "Any climate disaster"]


def test_city_answers_add_the_country_figures_when_trained():
    add_country_data()
    outlook = ask.answer_question("What will the weather be in Karachi in 2027?")
    assert "Across Pakistan, 2027 should be about +1.4" in outlook["answer"]
    with mock.patch.object(ask, "fetch_forecast", forecast_of()):
        storm = ask.answer_question("are there any chances of any hurricane or storm in the near future")
    assert "storms were recorded as disasters in 24 of the 45 years" in storm["answer"]
    assert "IMF Climate Change Indicators" in storm["sources"]


def test_a_year_past_the_city_outlook_uses_the_country_outlook():
    add_country_data()
    db.city_outlooks.update_many({}, {"$set": {"year": 2027}})
    assert "Across Pakistan, 2029 should be" in ask.answer_question("weather in Karachi in 2029")["answer"]


def test_forest_question_reports_the_change():
    add_country_data()
    assert "6.23%" in ask.answer_question("How much forest does Pakistan have?")["answer"]


def test_pakistan_questions_without_country_data_say_the_model_is_not_trained():
    assert ask.answer_question("How often do floods hit Pakistan?")["kind"] == "unavailable"


def add_projections():
    # Each path warms 0.01, 0.02, 0.03 or 0.04 °C a year from 2015; the models range is 0.5 either side.
    rows = []
    for step, scenario in enumerate(("ssp126", "ssp245", "ssp370", "ssp585"), start=1):
        for year in range(2015, 2101):
            change = round(0.01 * step * (year - 2014), 3)
            for percentile, shift in (("p10", -0.5), ("median", 0), ("p90", 0.5)):
                rows.append({"iso3": "PAK", "measure": "tas", "scenario": scenario, "percentile": percentile, "year": year, "value": 21 + change + shift, "change": change + shift})
                rows.append({"iso3": "PAK", "measure": "hd35", "scenario": scenario, "percentile": percentile, "year": year, "value": 115 + 10 * change, "change": 10 * change})
                rows.append({"iso3": "PAK", "measure": "pr", "scenario": scenario, "percentile": percentile, "year": year, "value": 440.0, "change": 20.0})
    db.cmip6_projections.insert_many(rows)
    db.country_scores.insert_one({"iso3": "PAK", "variable": "cmip6_check", "scenario": "ssp245", "years": "2015-2023", "count": 9, "bias": 0.12, "rmse": 0.3, "inside_range": 0.889})


def test_pakistan_far_ahead_uses_the_climate_models():
    add_country_data()
    add_projections()
    result = ask.answer_question("How hot will Pakistan be in 2050?")
    assert result["kind"] == "projection"
    # Middle path averaged over 2041-2060: 0.02 * 36.5 = +0.73; 1995-2014 was +0.35 against 1951-1980 in the test data.
    assert "middle path (SSP2-4.5) put Pakistan around 2050 (the average for 2041-2060) at about +0.7 °C" in result["answer"]
    assert "about +1.1 °C compared with 1951-1980" in result["answer"]
    assert [row[0] for row in result["rows"]] == [label for _code, label in ask.SCENARIOS]
    assert result["columns"][0] == "Emissions path (2041-2060 average)"
    assert result["rows"][3][1] == "+1.5 °C" and result["rows"][0][4] == "440 mm (+5%)"
    assert any("89% of those years" in note for note in result["notes"])
    assert len(result["chart"]["series"]) == 4


def test_scenario_words_choose_the_emissions_path():
    assert ask.parse("Pakistan in 2060 worst case")["scenario"] == "ssp585"
    assert ask.parse("Pakistan in 2060 with low emissions")["scenario"] == "ssp126"
    assert ask.parse("Pakistan in 2060")["scenario"] is None
    add_country_data()
    add_projections()
    assert "very high emissions" in ask.answer_question("How hot will Pakistan be in 2050 in the worst case?")["answer"]
    # A scenario asked inside the trend outlook's years still goes to the models.
    assert ask.answer_question("Pakistan in 2030 with high emissions")["kind"] == "projection"


def test_a_city_far_ahead_gets_the_country_projection():
    add_country_data()
    add_projections()
    result = ask.answer_question("weather in Karachi in 2050")
    assert result["kind"] == "projection" and "too far ahead" in result["answer"] and "Pakistan around 2050" in result["answer"]


def test_the_projection_window_stays_inside_the_model_years():
    assert ask.projection_window(2050) == (2041, 2060)
    assert ask.projection_window(2016) == (2015, 2034)
    assert ask.projection_window(2099) == (2081, 2100)


def test_within_the_trend_outlook_the_model_figure_is_added():
    add_country_data()
    add_projections()
    result = ask.answer_question("How much warmer will Pakistan be in 2030?")
    assert result["kind"] == "outlook" and "Climate models" in result["answer"]
    assert ask.PROJECTION_SOURCE in result["sources"]
