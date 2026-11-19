"""Ask panel answers. The 16-day forecast is a stand-in."""
import datetime
import urllib.error
from unittest import mock

from earthscape.db import db
from earthscape.testing import ANALYST, MongoTestCase

from dashboard import ask

NOW = datetime.date(2026, 11, 4)


def calm_days(**changes):
    days = []
    for i in range(16):
        day = {"date": (NOW + datetime.timedelta(days=i)).isoformat(), "high": 30.0, "low": 20.0, "rain": 0.0,
               "rain_chance": 5, "gust": 20.0, "code": 1}
        day.update(changes)
        days.append(day)
    return days


def forecast_of(**changes):
    return lambda names: {name: calm_days(**changes) for name in names}


def add_city_data():
    for month in range(1, 13):
        db.city_outlooks.insert_one({"city": "Karachi", "year": 2027, "month": month, "horizon": 2,
                                     "tmax_c": 25.0 + month, "tmax_c_low": 24.0 + month, "tmax_c_high": 26.0 + month,
                                     "tmin_c": 15.0 + month, "tmin_c_low": 14.0 + month, "tmin_c_high": 16.0 + month})
        db.city_usual.insert_one({"city": "Karachi", "month": month, "years": 30, "rain_low": 0.0,
                                  "rain_mm": 80.0 if month == 7 else 2.0, "rain_high": 200.0, "rain_days": 1.5,
                                  "heavy_days": 0.1, "gale_days": 0.2})
        db.city_history.insert_one({"city": "Karachi", "year": 2023, "month": month, "tmax_c": 30.0 + month,
                                    "tmin_c": 20.0, "rain_mm": 5.0, "rain_days": 1, "gale_days": 0})
    db.city_scores.insert_one({"city": "Karachi", "variable": "tmax_c", "method_label": "Trend over the last 30 years",
                               "test_rmse": 0.8, "baseline_test_rmse": 0.9, "test_period": "2016-2025"})
    no_storms = {str(m): 0 for m in range(1, 13)}
    db.city_storms.insert_many([
        {"city": "Karachi", "first_year": 1980, "last_year": 2025, "years": 46, "years_with_storm": 5, "chance": 0.109,
         "chance_low": 0.05, "chance_high": 0.23, "radius_km": 300, "by_month": dict(no_storms, **{"6": 4, "11": 1}),
         "storms": [{"name": "Phet", "year": 2010, "month": 6, "closest_km": 200, "knots": 60},
                    {"name": "Biparjoy", "year": 2023, "month": 6, "closest_km": 150, "knots": 100}]},
        {"city": "Gilgit", "first_year": 1980, "last_year": 2025, "years": 46, "years_with_storm": 0, "chance": 0.0,
         "chance_low": 0.0, "chance_high": 0.077, "radius_km": 300, "by_month": no_storms, "storms": []},
    ])
    db.ml_forecasts.insert_one({"series": "24N-44N", "forecast": [{"year": 2045, "forecast": 2.1, "lower": 1.5, "upper": 2.7}]})


def add_country_data():
    db.country_outlook.insert_many([{"iso3": "PAK", "country": "Pakistan", "year": year, "horizon": year - 2023,
                                     "value": 1.2 + 0.05 * (year - 2024), "low": 0.6, "high": 1.9} for year in range(2024, 2031)])
    db.country_scores.insert_one({"iso3": "PAK", "country": "Pakistan", "variable": "temperature_change", "method": "trend",
                                  "method_label": "Trend over the last 30 years", "test_rmse": 0.31, "baseline_test_rmse": 0.35,
                                  "test_period": "2011-2023", "last_year": 2023, "last_value": 1.046})
    db.country_indicators.insert_many([{"iso3": "PAK", "country": "Pakistan", "indicator": "temperature_change",
                                        "unit": "Degree Celsius", "year": year, "value": 0.05 * (year - 2000)} for year in range(2000, 2024)])
    for kind, years_with, latest in (("storm", 24, 2024), ("flood", 40, 2024), ("total", 43, 2024)):
        db.country_disasters.insert_one({"iso3": "PAK", "country": "Pakistan", "kind": kind, "first_year": 1980, "last_year": 2024,
                                         "years": 45, "years_with": years_with, "events": years_with, "chance": round(years_with / 45, 3),
                                         "chance_low": 0.4, "chance_high": 0.9, "recent_years": 10, "recent_years_with": 8,
                                         "recent_events": 12, "latest_year": latest, "worst_year": 2022, "worst_affected": 33016869,
                                         "by_year": {}})
    db.country_forest.insert_one({"iso3": "PAK", "country": "Pakistan", "first_year": 1992, "first_share": 6.23,
                                  "last_year": 2023, "last_share": 4.67, "yearly_change": -0.05})


def add_projections():
    # Each path warms 0.01-0.04 °C a year
    rows = []
    for step, scenario in enumerate(("ssp126", "ssp245", "ssp370", "ssp585"), start=1):
        for year in range(2015, 2101):
            change = round(0.01 * step * (year - 2014), 3)
            for percentile, shift in (("p10", -0.5), ("median", 0), ("p90", 0.5)):
                base = {"iso3": "PAK", "scenario": scenario, "percentile": percentile, "year": year}
                rows.append(dict(base, measure="tas", value=21 + change + shift, change=change + shift))
                rows.append(dict(base, measure="hd35", value=115 + 10 * change, change=10 * change))
                rows.append(dict(base, measure="pr", value=440.0, change=20.0))
    db.cmip6_projections.insert_many(rows)
    db.country_scores.insert_one({"iso3": "PAK", "variable": "cmip6_check", "scenario": "ssp245", "years": "2015-2023",
                                  "count": 9, "bias": 0.12, "rmse": 0.3, "inside_range": 0.889})


class AskTestCase(MongoTestCase):
    with_users = False

    def setUp(self):
        super().setUp()
        add_city_data()


#----------------------------reading the question--------------------------------------

class ParseTests(AskTestCase):

    def test_parse_finds_city_and_time(self):
        cases = [
            ("what will be the weather of Karachi in 2027", ["Karachi"], 2027, None),
            ("Lahore in June 2028?", ["Lahore"], 2028, 6),
            ("will it rain in QUETTA next year", ["Quetta"], 2027, None),
            ("weather in Multan next month", ["Multan"], 2026, 12),
            ("rain in Sukkur in march", ["Sukkur"], 2027, 3),
            ("in may in Gilgit", ["Gilgit"], 2027, 5),
        ]
        for question, city, year, month in cases:
            with self.subTest(question=question):
                parsed = ask.parse(question, NOW)
                self.assertEqual((parsed["cities"], parsed["year"], parsed["month"]), (city, year, month))

    def test_may_as_a_verb_is_not_the_month(self):
        self.assertIsNone(ask.parse("what may the weather be in Karachi", NOW)["month"])

    def test_parse_recognises_storm_words_and_the_near_future(self):
        parsed = ask.parse("are there any chances of any hurricane or storm in the near future", NOW)
        self.assertTrue(parsed["storm"] and parsed["near"])
        self.assertEqual(parsed["cities"], [])

    def test_scenario_words_choose_the_emissions_path(self):
        self.assertEqual(ask.parse("Pakistan in 2060 worst case")["scenario"], "ssp585")
        self.assertEqual(ask.parse("Pakistan in 2060 with low emissions")["scenario"], "ssp126")
        self.assertIsNone(ask.parse("Pakistan in 2060")["scenario"])

    def test_the_projection_window_stays_inside_the_model_years(self):
        self.assertEqual(ask.projection_window(2050), (2041, 2060))
        self.assertEqual(ask.projection_window(2016), (2015, 2034))
        self.assertEqual(ask.projection_window(2099), (2081, 2100))


#----------------------------city answers--------------------------------------

class CityAnswerTests(AskTestCase):

    def test_future_year_gives_the_outlook_with_a_range_and_a_warning(self):
        result = ask.answer_question("What will the weather be in Karachi in 2027?")
        self.assertEqual(result["kind"], "outlook")
        self.assertIn("December", result["answer"])
        self.assertIn("37", result["answer"])
        self.assertIn("July is usually the wettest", result["answer"])
        self.assertEqual(len(result["rows"]), 12)
        self.assertTrue(any("one exact day" in note for note in result["notes"]))
        self.assertTrue(any("off by about 0.8" in note for note in result["notes"]))
        self.assertEqual(result["chart"]["labels"][0], "Jan")

    def test_one_month_gives_one_row_and_no_chart(self):
        result = ask.answer_question("Karachi in July 2027")
        self.assertEqual(len(result["rows"]), 1)
        self.assertIsNone(result["chart"])
        self.assertIn("32", result["answer"])
        self.assertIn("80 mm", result["answer"])

    def test_a_past_year_uses_the_record_not_the_model(self):
        result = ask.answer_question("How hot was Karachi in June 2023?")
        self.assertEqual(result["kind"], "history")
        self.assertIn("36", result["answer"])

    def test_a_year_too_far_ahead_is_refused_and_uses_the_band_forecast(self):
        answer = ask.answer_question("weather in Karachi in 2045")["answer"]
        self.assertIn("too far ahead", answer)
        self.assertIn("+2.1", answer)

    def test_a_year_before_the_record_says_so(self):
        self.assertIn("starts in 2023", ask.answer_question("weather in Karachi in 1950")["answer"])

    def test_the_near_future_weather_uses_the_forecast(self):
        with mock.patch.object(ask, "fetch_forecast", forecast_of()), mock.patch.object(ask, "today", return_value=NOW):
            result = ask.answer_question("weather in Lahore tomorrow")
        self.assertEqual(result["kind"], "forecast")
        self.assertEqual(len(result["rows"]), 16)

    def test_a_failed_forecast_says_so(self):
        with mock.patch.object(ask, "fetch_forecast", side_effect=urllib.error.URLError("down")):
            self.assertEqual(ask.answer_question("weather in Lahore tomorrow")["kind"], "unavailable")

    def test_a_weather_question_without_a_city_asks_which_one(self):
        self.assertIn("Which city", ask.answer_question("what will the weather be in 2027")["answer"])

    def test_an_unrelated_question_gets_help(self):
        self.assertEqual(ask.answer_question("who won the cricket")["kind"], "help")

    def test_an_untrained_model_says_so(self):
        db.city_outlooks.drop()
        self.assertEqual(ask.answer_question("weather in Karachi in 2027")["kind"], "unavailable")


#----------------------------storm answers--------------------------------------

class StormAnswerTests(AskTestCase):

    def test_near_storm_with_calm_forecast_says_nothing_shows_and_covers_every_city(self):
        with mock.patch.object(ask, "fetch_forecast", forecast_of()):
            result = ask.answer_question("are there any chances of any hurricane or storm in the near future")
        self.assertEqual(result["kind"], "storm")
        self.assertTrue(result["answer"].startswith("Nothing storm-like"))
        self.assertIn("any of the 12 cities", result["answer"])
        self.assertIn("Karachi has the highest chance", result["answer"])
        self.assertTrue(any("Pakistan Meteorological Department" in note for note in result["notes"]))

    def test_near_storm_flags_the_days_that_qualify(self):
        for changes, reason in (({"code": 95}, "Thunderstorm"), ({"gust": 80.0}, "gusts of 80"), ({"rain": 70.0}, "70 mm")):
            with self.subTest(reason=reason):
                with mock.patch.object(ask, "fetch_forecast", forecast_of(**changes)):
                    result = ask.answer_question("any storm in Karachi soon?")
                self.assertTrue(result["answer"].startswith("Yes"))
                self.assertIn(reason, result["rows"][0][2])
                self.assertIn("Biparjoy", result["answer"])

    def test_future_storm_gives_the_historical_chance_and_never_a_forecast(self):
        answer = ask.answer_question("Could a cyclone hit Karachi in 2028?")["answer"]
        self.assertTrue(answer.startswith("No one can forecast"))
        for text in ("11%", "Biparjoy", "June"):
            self.assertIn(text, answer)

    def test_a_city_with_no_storms_still_gives_an_upper_estimate(self):
        self.assertIn("No tropical storm", ask.answer_question("any cyclone in Gilgit in 2028")["answer"])

    def test_a_past_storm_question_lists_that_years_storms(self):
        self.assertEqual(ask.answer_question("was there a cyclone in Karachi in 2023")["rows"][0][0], "Biparjoy")


#----------------------------pakistan answers--------------------------------------

class CountryAnswerTests(AskTestCase):

    def test_pakistan_temperature_question_uses_the_country_outlook(self):
        add_country_data()
        result = ask.answer_question("How much warmer will Pakistan be in 2030?")
        self.assertEqual(result["kind"], "outlook")
        self.assertIn("+1.5", result["answer"])
        self.assertEqual(len(result["rows"]), 7)
        self.assertEqual(result["chart"]["labels"][-1], "2030")
        self.assertTrue(any("off by about 0.31" in note for note in result["notes"]))

    def test_pakistan_flood_question_gives_the_disaster_record(self):
        add_country_data()
        result = ask.answer_question("How often do floods hit Pakistan?")
        self.assertEqual(result["kind"], "disasters")
        self.assertIn("floods were recorded as disasters in 40 of the 45 years", result["answer"])
        self.assertIn("2022", result["answer"])
        self.assertIn("33,016,869", result["answer"])
        self.assertEqual([row[0] for row in result["rows"]], ["Storms", "Floods", "Any climate disaster"])

    def test_city_answers_add_the_country_figures_when_trained(self):
        add_country_data()
        outlook = ask.answer_question("What will the weather be in Karachi in 2027?")
        self.assertIn("Across Pakistan, 2027 should be about +1.4", outlook["answer"])
        with mock.patch.object(ask, "fetch_forecast", forecast_of()):
            storm = ask.answer_question("are there any chances of any hurricane or storm in the near future")
        self.assertIn("storms were recorded as disasters in 24 of the 45 years", storm["answer"])
        self.assertIn("IMF Climate Change Indicators", storm["sources"])

    def test_a_year_past_the_city_outlook_uses_the_country_outlook(self):
        add_country_data()
        self.assertIn("Across Pakistan, 2029 should be", ask.answer_question("weather in Karachi in 2029")["answer"])

    def test_forest_question_reports_the_change(self):
        add_country_data()
        self.assertIn("6.23%", ask.answer_question("How much forest does Pakistan have?")["answer"])

    def test_pakistan_questions_without_country_data_say_the_model_is_not_trained(self):
        self.assertEqual(ask.answer_question("How often do floods hit Pakistan?")["kind"], "unavailable")

    def test_pakistan_far_ahead_uses_the_climate_models(self):
        add_country_data()
        add_projections()
        result = ask.answer_question("How hot will Pakistan be in 2050?")
        self.assertEqual(result["kind"], "projection")
        # Middle path, 2041-2060 average
        self.assertIn("middle path (SSP2-4.5) put Pakistan around 2050 (the average for 2041-2060) at about +0.7 °C", result["answer"])
        self.assertIn("about +1.1 °C compared with 1951-1980", result["answer"])
        self.assertEqual([row[0] for row in result["rows"]], [label for _code, label in ask.SCENARIOS])
        self.assertEqual(result["columns"][0], "Emissions path (2041-2060 average)")
        self.assertEqual(result["rows"][3][1], "+1.5 °C")
        self.assertEqual(result["rows"][0][4], "440 mm (+5%)")
        self.assertTrue(any("89% of those years" in note for note in result["notes"]))
        self.assertEqual(len(result["chart"]["series"]), 4)

    def test_scenario_words_pick_the_path_in_the_answer(self):
        add_country_data()
        add_projections()
        self.assertIn("very high emissions", ask.answer_question("How hot will Pakistan be in 2050 in the worst case?")["answer"])
        # Scenario goes to models
        self.assertEqual(ask.answer_question("Pakistan in 2030 with high emissions")["kind"], "projection")

    def test_a_city_far_ahead_gets_the_country_projection(self):
        add_country_data()
        add_projections()
        result = ask.answer_question("weather in Karachi in 2050")
        self.assertEqual(result["kind"], "projection")
        self.assertIn("too far ahead", result["answer"])
        self.assertIn("Pakistan around 2050", result["answer"])

    def test_within_the_trend_outlook_the_model_figure_is_added(self):
        add_country_data()
        add_projections()
        result = ask.answer_question("How much warmer will Pakistan be in 2030?")
        self.assertEqual(result["kind"], "outlook")
        self.assertIn("Climate models", result["answer"])
        self.assertIn(ask.PROJECTION_SOURCE, result["sources"])


#----------------------------ask panel page--------------------------------------

class AskPageTests(AskTestCase):
    with_users = True

    def test_the_panel_needs_a_login_and_limits_length(self):
        response = self.client.post("/dashboard/ml/", {"question": "weather in Karachi in 2027"})
        self.assertEqual(response.status_code, 302)
        self.sign_in(ANALYST)
        too_long = self.client.post("/dashboard/ml/", {"question": "x" * 301})
        self.assertIsNone(too_long.context["answer"])
        self.assertTrue(too_long.context["form_errors"])
        page = self.client.post("/dashboard/ml/", {"question": "weather in Karachi in 2027"})
        self.assertEqual(page.status_code, 200)
        self.assertEqual(page.context["answer"]["kind"], "outlook")
        self.assertContains(page, "July is usually the wettest")
