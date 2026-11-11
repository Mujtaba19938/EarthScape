"""Answers plain-English weather questions about the live cities.

The words only choose which saved result to show, and every number comes from data:
the next 16 days from Open-Meteo's forecast, later years from the trained city outlooks,
and past years and storm chances from the stored history.
"""
import datetime
import json
import re
import urllib.error
import urllib.parse
import urllib.request

from . import config
from .db import db

FORECAST_URL = "https://api.open-meteo.com/v1/forecast"
FORECAST_DAYS = 16
GALE_KMH = 62
HEAVY_RAIN_MM = 50
TIMEOUT_SECONDS = 20
FORECAST_ERRORS = (urllib.error.URLError, OSError, ValueError, KeyError, TypeError)
BAND_SERIES = "24N-44N"
MONTH_NAMES = ["January", "February", "March", "April", "May", "June", "July", "August", "September", "October", "November", "December"]
MONTH_PATTERNS = [("january|jan", 1), ("february|feb", 2), ("march", 3), ("april|apr", 4), ("june", 6), ("july", 7), ("august|aug", 8),
                  ("september|sept|sep", 9), ("october|oct", 10), ("november|nov", 11), ("december|dec", 12)]
STORM_WORDS = r"hurricanes?|cyclones?|typhoons?|storms?|stormy|thunder\w*|tornado\w*|gales?|lightning"
DISASTER_WORDS = r"floods?|flooding|droughts?|landslides?|disasters?|heat ?waves?"
WEATHER_WORDS = STORM_WORDS + "|" + DISASTER_WORDS + r"|weather|climate|temperature|forecast|predict\w*|rain\w*|monsoon|wet|dry|hot|heat\w*|cold|warm\w*|cool|wind\w*|humid\w*|forests?"
NEAR_WORDS = r"today|tonight|tomorrow|this week|next week|soon|near fu\w+|coming (?:days|weeks?)|next (?:few|couple of) days|upcoming|right now|now"
SEASON_NOTE = "These figures are for whole months. A forecast for one exact day only works up to 16 days ahead."
OFFICIAL_NOTE = "For official warnings, follow the Pakistan Meteorological Department."
STORM_SOURCE = "NOAA IBTrACS storm tracks"
HISTORY_SOURCE = "Open-Meteo archive (ERA5 reanalysis)"
FORECAST_SOURCE = "Open-Meteo forecast"
COUNTRY = "PAK"
COUNTRY_SOURCE = "IMF Climate Change Indicators"
DISASTER_LABELS = {"storm": "Storms", "flood": "Floods", "extreme_temperature": "Extreme heat or cold", "drought": "Droughts", "landslide": "Landslides",
                   "total": "Any climate disaster"}
DISASTER_NOTE = ("Disasters are events in the EM-DAT database (via the IMF), which lists those that caused deaths, affected many people or led to a call for help. "
                 "Fewer were recorded in the 1980s, so older years may be undercounted.")
PROJECTION_SOURCE = "World Bank Climate Change Knowledge Portal (CMIP6)"
SCENARIOS = [("ssp126", "Low emissions (SSP1-2.6)"), ("ssp245", "Middle path (SSP2-4.5)"), ("ssp370", "High emissions (SSP3-7.0)"),
             ("ssp585", "Very high emissions (SSP5-8.5)")]
DEFAULT_SCENARIO = "ssp245"
SCENARIO_PATTERNS = [(r"ssp ?1|1-2\.6|low[- ]emission\w*|best case|paris", "ssp126"), (r"ssp ?3|3-7\.0|high[- ]emission\w*", "ssp370"),
                     (r"ssp ?5|5-8\.5|very high|worst case|business as usual", "ssp585"), (r"ssp ?2|2-4\.5|middle|moderate", "ssp245")]
PROJECTION_YEARS = (2015, 2100)
PROJECTION_MEASURES = ["tas", "hd35", "pr", "txx"]
PROJECTION_NOTE = ("Climate model figures are yearly averages over all of Pakistan from the World Bank's set of CMIP6 climate models. "
                   "The first figure is the models' middle value and the range covers the middle 80% of models (10th to 90th percentile). "
                   "They show how the climate responds to each emissions path, not the weather of a particular year.")
HELP = ("Ask about one of these cities, for example \"What will the weather be in Karachi in 2027?\" or "
        "\"Is there any chance of a storm in the near future?\"")


def today():
    return datetime.datetime.now(datetime.timezone.utc).date()


def condition(code):
    """The forecast's weather code in words."""
    if code is None:
        return "n/a"
    if code in (96, 99):
        return "Thunderstorm with hail"
    if code == 95:
        return "Thunderstorm"
    if code >= 71 and code <= 77 or code in (85, 86):
        return "Snow"
    if code >= 51:
        return "Rain"
    if code in (45, 48):
        return "Fog"
    return "Clear" if code <= 1 else "Cloudy"


def number(value, unit=""):
    return "n/a" if value is None else "%g%s" % (value, unit)


def percent(share):
    return "%d%%" % round(share * 100)


def parse(question, now=None):
    """Works out the city, the subject and the time from the words."""
    now = now or today()
    text = question.lower()
    cities = [name for name in config.LIVE_LOCATION_NAMES if re.search(r"\b%s\b" % name.lower(), text)]
    month = None
    for pattern, value in MONTH_PATTERNS:
        if re.search(r"\b(?:%s)\b" % pattern, text):
            month = value
    # "May" is often just a verb, so it only counts beside a year or after a word like "in".
    if re.search(r"\b(?:in|during|of|for|by|next|this) may\b|\bmay (?:19|20)\d\d\b", text):
        month = 5
    year_match = re.search(r"\b(19|20)\d\d\b", text)
    year = int(year_match.group()) if year_match else None
    near = bool(re.search(r"\b(?:%s)\b" % NEAR_WORDS, text))
    if re.search(r"\bnext year\b", text):
        year = now.year + 1
    elif re.search(r"\bthis year\b", text):
        year = now.year
    if re.search(r"\bnext month\b", text):
        month = now.month % 12 + 1
        year = year or (now.year + 1 if now.month == 12 else now.year)
    elif re.search(r"\bthis month\b", text):
        month = now.month
        year = year or now.year
    if month and not year:
        year = now.year if month >= now.month else now.year + 1
    day = None
    if re.search(r"\btomorrow\b", text):
        day = now + datetime.timedelta(days=1)
    elif re.search(r"\b(?:today|tonight|right now|now)\b", text):
        day = now
    return {
        "cities": cities, "month": month, "year": year, "near": near or not year, "day": day, "storm": bool(re.search(r"\b(?:%s)\b" % STORM_WORDS, text)),
        "flood": bool(re.search(r"\bflood\w*", text)), "understood": bool(re.search(r"\b(?:%s)\b" % WEATHER_WORDS, text)) or bool(year) or bool(month) or near,
        "country": bool(re.search(r"\bpakistan\b", text)), "disaster": bool(re.search(r"\b(?:%s)\b" % DISASTER_WORDS, text)),
        "forest": bool(re.search(r"\bforests?\b", text)),
        "scenario": next((code for pattern, code in SCENARIO_PATTERNS if re.search(pattern, text)), None),
    }


def fetch_forecast(names):
    """The next 16 days for each named city, in the same order."""
    places = [place for place in config.LIVE_LOCATIONS if place[0] in names]
    query = urllib.parse.urlencode({
        "latitude": ",".join(str(place[1]) for place in places), "longitude": ",".join(str(place[2]) for place in places),
        "daily": "temperature_2m_max,temperature_2m_min,precipitation_sum,precipitation_probability_max,wind_gusts_10m_max,weather_code",
        "forecast_days": FORECAST_DAYS, "timezone": "auto"})
    with urllib.request.urlopen(FORECAST_URL + "?" + query, timeout=TIMEOUT_SECONDS) as response:
        body = json.loads(response.read().decode("utf-8"))
    replies = body if isinstance(body, list) else [body]
    result = {}
    for place, reply in zip(places, replies):
        daily = reply["daily"]
        result[place[0]] = [{
            "date": date, "high": high, "low": low, "rain": rain, "rain_chance": chance, "gust": gust, "code": code,
        } for date, high, low, rain, chance, gust, code in zip(daily["time"], daily["temperature_2m_max"], daily["temperature_2m_min"], daily["precipitation_sum"],
                                                               daily["precipitation_probability_max"], daily["wind_gusts_10m_max"], daily["weather_code"])]
    return result


def stormy_reasons(day):
    reasons = []
    if day["code"] is not None and day["code"] >= 95:
        reasons.append(condition(day["code"]))
    if day["gust"] is not None and day["gust"] >= GALE_KMH:
        reasons.append("gusts of %g km/h" % day["gust"])
    if day["rain"] is not None and day["rain"] >= HEAVY_RAIN_MM:
        reasons.append("%g mm of rain" % day["rain"])
    return reasons


def reply(kind, answer, columns=None, rows=None, notes=None, sources=None, chart=None):
    return {"kind": kind, "answer": answer, "columns": columns or [], "rows": rows or [], "notes": notes or [], "sources": sources or [], "chart": chart}


def _forecast_rows(days):
    return [[day["date"], number(day["high"], " °C"), number(day["low"], " °C"), number(day["rain"], " mm"),
             number(day["rain_chance"], "%"), number(day["gust"], " km/h"), condition(day["code"])] for day in days]


FORECAST_COLUMNS = ["Date", "High", "Low", "Rain", "Chance of rain", "Strongest gust", "Conditions"]


def _forecast_chart(days):
    return {"labels": [day["date"][5:] for day in days], "unit": "°C", "series": [
        {"label": "High", "values": [day["high"] for day in days]}, {"label": "Low", "values": [day["low"] for day in days]}]}


def _unavailable():
    return reply("unavailable", "The live forecast can't be reached right now, so I can't answer for the next 16 days. Please try again shortly.",
                 notes=[OFFICIAL_NOTE])


def near_weather(city, parsed):
    try:
        days = fetch_forecast([city])[city]
    except FORECAST_ERRORS:
        return _unavailable()
    wanted = next((day for day in days if parsed["day"] and day["date"] == parsed["day"].isoformat()), None) or days[0]
    label = "tomorrow" if parsed["day"] and parsed["day"] != today() else "today"
    high = max(day["high"] for day in days)
    low = min(day["low"] for day in days)
    answer = "%s %s (%s): high of %s, low of %s, %s, with %s of rain. Over the next %d days, highs reach up to %g °C and lows fall to %g °C." % (
        city, label, wanted["date"], number(wanted["high"], " °C"), number(wanted["low"], " °C"), condition(wanted["code"]).lower(), number(wanted["rain"], " mm"), len(days), high, low)
    notes = ["Forecasts become less reliable towards the end of the 16 days."]
    sources = [FORECAST_SOURCE]
    if parsed["flood"]:
        _add_flood(notes, sources, "This shows forecast rain, not a flood forecast.")
    return reply("forecast", answer, FORECAST_COLUMNS, _forecast_rows(days), notes, sources, _forecast_chart(days))


def _add_flood(notes, sources, lead):
    """Adds how often floods were recorded across Pakistan, or says floods aren't covered."""
    record = disaster_record("flood")
    if record:
        notes.extend([lead + " " + disaster_sentence(record), DISASTER_NOTE])
        sources.append(COUNTRY_SOURCE)
    else:
        notes.append(lead + " EarthScape doesn't model floods themselves.")


def _storm_sentence(record):
    if not record["storms"]:
        return "No tropical storm has passed within %d km of %s since %d, though that can't rule one out (the upper estimate is about %s a year)." % (
            record["radius_km"], record["city"], record["first_year"], percent(record["chance_high"]))
    last = record["storms"][-1]
    return "Tropical storms or cyclones came within %d km of %s in %d of the %d years since %d, so about %s in any year (likely between %s and %s). The latest was %s in %s %d." % (
        record["radius_km"], record["city"], record["years_with_storm"], record["years"], record["first_year"], percent(record["chance"]),
        percent(record["chance_low"]), percent(record["chance_high"]), last["name"], MONTH_NAMES[last["month"] - 1], last["year"])


def disaster_record(kind):
    return db.country_disasters.find_one({"iso3": COUNTRY, "kind": kind}, {"_id": 0})


def disaster_sentence(record):
    """How often this kind of disaster was recorded across Pakistan."""
    label = DISASTER_LABELS[record["kind"]].lower()
    if not record["years_with"]:
        return "Across %s, no %s were recorded as disasters from %d to %d." % (record["country"], label, record["first_year"], record["last_year"])
    return ("Across %s, %s were recorded as disasters in %d of the %d years from %d to %d, so about %s in any year (likely %s to %s). "
            "In the last %d years there were %d, the latest in %d.") % (
        record["country"], label, record["years_with"], record["years"], record["first_year"], record["last_year"], percent(record["chance"]),
        percent(record["chance_low"]), percent(record["chance_high"]), record["recent_years"], record["recent_events"], record["latest_year"])


def country_temperature(year):
    return db.country_outlook.find_one({"iso3": COUNTRY, "year": year}, {"_id": 0})


def country_temperature_sentence(year):
    row = country_temperature(year)
    if not row:
        return None
    return "Across %s, %d should be about %+.1f °C compared with the 1951-1980 average (likely %+.1f to %+.1f)." % (row["country"], year, row["value"], row["low"], row["high"])


def projection_window(year):
    """The 20 years around the asked year, kept inside 2015-2100. Single model years are noisy, so climate figures are 20-year averages."""
    first = min(max(year - 9, PROJECTION_YEARS[0]), PROJECTION_YEARS[1] - 19)
    return first, first + 19


def projection(year, scenario):
    """CMIP6 averages over the 20 years around one year, as measure to percentile to {value, change}."""
    first, last = projection_window(year)
    sums = {}
    for row in db.cmip6_projections.find({"iso3": COUNTRY, "year": {"$gte": first, "$lte": last}, "scenario": scenario, "measure": {"$in": PROJECTION_MEASURES}}, {"_id": 0}):
        total = sums.setdefault(row["measure"], {}).setdefault(row["percentile"], [0.0, 0.0, 0])
        total[0] += row["value"]
        total[1] += row["change"]
        total[2] += 1
    found = {measure: {pct: {"value": value / count, "change": change / count} for pct, (value, change, count) in by_pct.items()} for measure, by_pct in sums.items()}
    return found if "median" in found.get("tas", {}) else None


def past_offset():
    """How much warmer 1995-2014 was than 1951-1980 in the IMF figures, to put the model figures on the same baseline."""
    values = [row["value"] for row in db.country_indicators.find({"iso3": COUNTRY, "indicator": "temperature_change", "year": {"$gte": 1995, "$lte": 2014}})]
    return sum(values) / len(values) if len(values) >= 15 else None


def scenario_label(scenario):
    """The label inside a sentence: "middle path (SSP2-4.5)"."""
    label = dict(SCENARIOS)[scenario]
    return label[0].lower() + label[1:]


def projection_sentence(year, scenario):
    found = projection(year, scenario)
    if not found:
        return None
    tas = found["tas"]
    first, last = projection_window(year)
    sentence = "Climate models on the %s put Pakistan around %d (the average for %d-%d) at about %+.1f °C compared with 1995-2014 (models range %+.1f to %+.1f)" % (
        scenario_label(scenario), year, first, last, tas["median"]["change"], tas["p10"]["change"], tas["p90"]["change"])
    offset = past_offset()
    if offset is not None:
        sentence += ", or about %+.1f °C compared with 1951-1980" % (tas["median"]["change"] + offset)
    sentence += "."
    hot = found.get("hd35", {}).get("median")
    if hot:
        sentence += " Days over 35 °C would average about %d a year, against %d in 1995-2014." % (round(hot["value"]), round(hot["value"] - hot["change"]))
    return sentence


def _projection_table(year):
    rows = []
    for scenario, label in SCENARIOS:
        found = projection(year, scenario)
        if not found:
            continue
        tas, hot, rain, hottest = (found.get(measure, {}) for measure in PROJECTION_MEASURES)
        rows.append([label, "%+.1f °C" % tas["median"]["change"], "%+.1f to %+.1f °C" % (tas["p10"]["change"], tas["p90"]["change"]),
                     "%d" % round(hot["median"]["value"]) if "median" in hot else "n/a",
                     "%d mm (%+d%%)" % (round(rain["median"]["value"]), round(100 * rain["median"]["change"] / (rain["median"]["value"] - rain["median"]["change"])))
                     if "median" in rain else "n/a",
                     "%.1f °C" % hottest["median"]["value"] if "median" in hottest else "n/a"])
    return rows


PROJECTION_COLUMNS = ["Emissions path", "Compared with 1995-2014", "Models range", "Days over 35 °C", "Rain in a year", "Hottest day"]


def _projection_chart(year):
    rows = list(db.cmip6_projections.find({"iso3": COUNTRY, "measure": "tas", "percentile": "median", "year": {"$lte": max(year, 2050)}},
                                          {"_id": 0, "scenario": 1, "year": 1, "change": 1}).sort("year", 1))
    years = sorted({row["year"] for row in rows})
    values = {(row["scenario"], row["year"]): row["change"] for row in rows}
    return {"labels": [str(y) for y in years], "unit": "°C", "series": [
        {"label": label, "values": [values.get((scenario, y)) for y in years]} for scenario, label in SCENARIOS]}


def _projection_notes():
    notes = [PROJECTION_NOTE]
    check = db.country_scores.find_one({"iso3": COUNTRY, "variable": "cmip6_check"}, {"_id": 0})
    if check:
        notes.append("Checked against the measured years %s, the middle path was off by about %.2f °C on average (%s), and %s of those years fell inside the models' range." % (
            check["years"], check["rmse"], "running warm" if check["bias"] > 0 else "running cool", percent(check["inside_range"])))
        if check["inside_range"] < 0.5:
            notes.append("Real years swing above and below the models' range because of ordinary weather, so treat the range as the spread for the long-run climate, not for one year.")
    return notes


def projection_answer(year, scenario, lead=""):
    """Every emissions path for one year, with the asked one (or the middle path) in the answer."""
    sentence = projection_sentence(year, scenario)
    if not sentence:
        return None
    answer = (lead + " " if lead else "") + sentence
    columns = ["Emissions path (%d-%d average)" % projection_window(year)] + PROJECTION_COLUMNS[1:]
    return reply("projection", answer, columns, _projection_table(year),_projection_notes(), [PROJECTION_SOURCE, COUNTRY_SOURCE], _projection_chart(year))


def in_projection_years(year):
    return year is not None and PROJECTION_YEARS[0] <= year <= PROJECTION_YEARS[1]


def _storm_notes():
    return ["Hurricanes are called cyclones in this part of the world. This chance is how often it has happened, not a forecast of a particular storm.", OFFICIAL_NOTE]


def storm_chance_rows(records):
    return [[record["city"], percent(record["chance"]), "%s to %s" % (percent(record["chance_low"]), percent(record["chance_high"])), str(len(record["storms"])),
             (record["storms"][-1]["name"] + " " + str(record["storms"][-1]["year"])) if record["storms"] else "None"] for record in records]


STORM_CHANCE_COLUMNS = ["City", "Chance in a year", "Likely range", "Storms since 1980", "Latest"]


def near_storm(cities, parsed):
    names = cities or config.LIVE_LOCATION_NAMES
    records = {record["city"]: record for record in db.city_storms.find({"city": {"$in": names}}, {"_id": 0})}
    try:
        forecasts = fetch_forecast(names)
    except FORECAST_ERRORS:
        return _unavailable()
    flagged = [(city, day, stormy_reasons(day)) for city in names for day in forecasts[city] if stormy_reasons(day)]
    rows = [[city, day["date"], ", ".join(reasons)] for city, day, reasons in flagged]
    place = cities[0] if len(cities) == 1 else "any of the %d cities" % len(names)
    if flagged:
        answer = "Yes, the next %d days' forecast shows storm-like weather for %s: %d day(s) with thunderstorms, gale-force gusts or very heavy rain." % (FORECAST_DAYS, place, len(flagged))
    else:
        answer = "Nothing storm-like shows in the next %d days' forecast for %s: no thunderstorms, no gusts of %d km/h or more, and no days with %d mm of rain or more." % (
            FORECAST_DAYS, place, GALE_KMH, HEAVY_RAIN_MM)
    if len(cities) == 1 and cities[0] in records:
        answer += " " + _storm_sentence(records[cities[0]])
    elif records:
        highest = max(records.values(), key=lambda record: record["chance"])
        answer += " Over the long run, %s has the highest chance of a tropical storm or cyclone nearby, at about %s in any year." % (highest["city"], percent(highest["chance"]))
    sources = [FORECAST_SOURCE, STORM_SOURCE]
    notes = ["The forecast doesn't track named cyclones, so this looks for their effects."] + _storm_notes()
    country = disaster_record("storm")
    if country:
        answer += " " + disaster_sentence(country)
        notes.insert(1, DISASTER_NOTE)
        sources.append(COUNTRY_SOURCE)
    if rows:
        return reply("storm", answer, ["City", "Date", "Why it's flagged"], rows, notes, sources)
    ordered = sorted(records.values(), key=lambda record: -record["chance"])
    return reply("storm", answer, STORM_CHANCE_COLUMNS, storm_chance_rows(ordered), notes, sources)


def future_storm(city, parsed):
    record = db.city_storms.find_one({"city": city}, {"_id": 0})
    if not record:
        return not_trained()
    when = ("%s %d" % (MONTH_NAMES[parsed["month"] - 1], parsed["year"])) if parsed["month"] else str(parsed["year"])
    if parsed["year"] <= record["last_year"]:
        storms = [storm for storm in record["storms"] if storm["year"] == parsed["year"] and (not parsed["month"] or storm["month"] == parsed["month"])]
        answer = "%d tropical storm(s) or cyclones came within %d km of %s in %s." % (len(storms), record["radius_km"], city, when)
        return reply("storm", answer, ["Storm", "Month", "Closest", "Peak wind"],
                     [[storm["name"], MONTH_NAMES[storm["month"] - 1], "%d km" % storm["closest_km"], "%d knots" % storm["knots"]] for storm in storms],
                     sources=[STORM_SOURCE])
    answer = "No one can forecast a particular storm for %s yet. %s" % (when, _storm_sentence(record))
    months = [MONTH_NAMES[int(month) - 1] for month, count in sorted(record["by_month"].items(), key=lambda item: -item[1]) if count][:3]
    if months:
        answer += " The months they've come in most are %s." % ", ".join(months)
    usual = list(db.city_usual.find({"city": city}, {"_id": 0}).sort("month", 1))
    rows = [[MONTH_NAMES[row["month"] - 1], str(record["by_month"][str(row["month"])]), str(row["gale_days"]), str(row["heavy_days"])] for row in usual
            if not parsed["month"] or row["month"] == parsed["month"]]
    notes = ["Windy and heavy rain days are usual figures for the last %d years, from a model of past weather, which can miss small local storms." % (usual[0]["years"] if usual else 30)] + _storm_notes()
    sources = [STORM_SOURCE, HISTORY_SOURCE]
    country = disaster_record("storm")
    if country:
        answer += " " + disaster_sentence(country)
        notes.insert(1, DISASTER_NOTE)
        sources.append(COUNTRY_SOURCE)
    return reply("storm", answer, ["Month", "Storms since %d" % record["first_year"], "Days with gale gusts a year", "Days with %d mm+ of rain a year" % HEAVY_RAIN_MM], rows, notes, sources)


def not_trained():
    return reply("unavailable", "The city model hasn't been trained yet. An Admin can press Retrain models on this page.")


def past_weather(city, parsed):
    query = {"city": city, "year": parsed["year"]}
    if parsed["month"]:
        query["month"] = parsed["month"]
    rows = list(db.city_history.find(query, {"_id": 0}).sort("month", 1))
    if not rows:
        first = db.city_history.find_one({"city": city}, sort=[("year", 1)])
        if not first:
            return not_trained()
        return reply("history", "I don't have %s's weather for %d. The history starts in %d." % (city, parsed["year"], first["year"]))
    table = [[MONTH_NAMES[row["month"] - 1], "%g °C" % row["tmax_c"], "%g °C" % row["tmin_c"], "%g mm" % row["rain_mm"], str(row["rain_days"])] for row in rows]
    hottest = max(rows, key=lambda row: row["tmax_c"])
    if parsed["month"]:
        answer = "In %s %d, %s averaged daily highs of %g °C and lows of %g °C, with %g mm of rain." % (MONTH_NAMES[parsed["month"] - 1], parsed["year"], city, rows[0]["tmax_c"], rows[0]["tmin_c"], rows[0]["rain_mm"])
    else:
        answer = "In %d, %s's hottest month was %s, with daily highs averaging %g °C, and %g mm of rain fell in the year." % (parsed["year"], city, MONTH_NAMES[hottest["month"] - 1], hottest["tmax_c"], sum(row["rain_mm"] for row in rows))
    chart = None if parsed["month"] else {"labels": [MONTH_NAMES[row["month"] - 1][:3] for row in rows], "unit": "°C", "series": [
        {"label": "Average daily high", "values": [row["tmax_c"] for row in rows]}, {"label": "Average daily low", "values": [row["tmin_c"] for row in rows]}]}
    return reply("history", answer, ["Month", "Average high", "Average low", "Rain", "Rainy days"], table,
                 ["This comes from a model fitted to past observations, not a station in the city."], [HISTORY_SOURCE], chart)


def outlook(city, parsed):
    query = {"city": city, "year": parsed["year"]}
    if parsed["month"]:
        query["month"] = parsed["month"]
    rows = list(db.city_outlooks.find(query, {"_id": 0}).sort("month", 1))
    if not rows:
        return not_trained()
    usual = {row["month"]: row for row in db.city_usual.find({"city": city}, {"_id": 0})}
    scores = {score["variable"]: score for score in db.city_scores.find({"city": city}, {"_id": 0})}
    table = []
    for row in rows:
        rain = usual.get(row["month"], {})
        table.append([MONTH_NAMES[row["month"] - 1], "%g °C (%g to %g)" % (row["tmax_c"], row["tmax_c_low"], row["tmax_c_high"]),
                      "%g °C (%g to %g)" % (row["tmin_c"], row["tmin_c_low"], row["tmin_c_high"]),
                      "%g mm (%g to %g)" % (rain.get("rain_mm", 0), rain.get("rain_low", 0), rain.get("rain_high", 0)), str(rain.get("rain_days", "n/a"))])
    if parsed["month"]:
        only = rows[0]
        rain = usual.get(only["month"], {})
        answer = "%s in %s %d should average daily highs of about %g °C (likely %g to %g) and lows of about %g °C (likely %g to %g). Rain is usually about %g mm that month, on %g days." % (
            city, MONTH_NAMES[only["month"] - 1], parsed["year"], only["tmax_c"], only["tmax_c_low"], only["tmax_c_high"], only["tmin_c"], only["tmin_c_low"], only["tmin_c_high"],
            rain.get("rain_mm", 0), rain.get("rain_days", 0))
        chart = None
    else:
        hottest = max(rows, key=lambda row: row["tmax_c"])
        coolest = min(rows, key=lambda row: row["tmax_c"])
        wettest = max(usual.values(), key=lambda row: row["rain_mm"]) if usual else None
        answer = "%s in %d should be warmest in %s, with daily highs averaging about %g °C (likely %g to %g), and coolest in %s, at about %g °C." % (
            city, parsed["year"], MONTH_NAMES[hottest["month"] - 1], hottest["tmax_c"], hottest["tmax_c_low"], hottest["tmax_c_high"], MONTH_NAMES[coolest["month"] - 1], coolest["tmax_c"])
        if wettest:
            answer += " %s is usually the wettest month, with about %g mm of rain." % (MONTH_NAMES[wettest["month"] - 1], wettest["rain_mm"])
        chart = {"labels": [MONTH_NAMES[row["month"] - 1][:3] for row in rows], "unit": "°C", "series": [
            {"label": "Average daily high", "values": [row["tmax_c"] for row in rows]}, {"label": "Average daily low", "values": [row["tmin_c"] for row in rows]}]}
    notes = [SEASON_NOTE]
    high = scores.get("tmax_c")
    if high:
        if high.get("method") == "average":
            notes.append("Rising trends didn't do better on past years for this city, so daily highs use the average of the last 10 years, which means every future year looks alike. Tested on %s, it was off by about %.1f °C." % (
                high["test_period"], high["test_rmse"]))
        else:
            result = "beat" if high["test_rmse"] < high["baseline_test_rmse"] else "didn't beat"
            notes.append("Tested on %s, this method for daily highs (%s) was off by about %.1f °C and %s simply using the last 10 years' average (%.1f °C)." % (
                high["test_period"], high["method_label"].lower(), high["test_rmse"], result, high["baseline_test_rmse"]))
    notes.append("Rain is too erratic to predict by year, so those figures show the usual amount over the last 30 years. The first figure is typical, and the range covers most years.")
    sources = [HISTORY_SOURCE]
    country = country_temperature_sentence(parsed["year"])
    if country:
        answer += " " + country
        sources.append(COUNTRY_SOURCE)
    if parsed["flood"]:
        _add_flood(notes, sources, "Floods aren't part of this outlook.")
    return reply("outlook", answer, ["Month", "Average high", "Average low", "Rain", "Rainy days"], table, notes, sources, chart)


def too_far(city, year, scenario=None):
    last = db.city_outlooks.find_one(sort=[("year", -1)])
    limit = last["year"] if last else year - 1
    answer = "%d is too far ahead for a monthly outlook for %s, which only goes up to %d." % (year, city, limit)
    country = country_temperature_sentence(year)
    if country and not scenario:
        projected = projection_sentence(year, DEFAULT_SCENARIO)
        if projected:
            return reply("outlook", " ".join([answer, country, projected]), notes=[COUNTRY_TREND_NOTE, PROJECTION_NOTE], sources=[COUNTRY_SOURCE, PROJECTION_SOURCE])
        return reply("outlook", answer + " " + country, notes=[COUNTRY_TREND_NOTE], sources=[COUNTRY_SOURCE])
    if in_projection_years(year):
        projected = projection_answer(year, scenario or DEFAULT_SCENARIO, answer + " There's no model for single cities that far ahead, but for Pakistan as a whole:")
        if projected:
            return projected
    band = db.ml_forecasts.find_one({"series": BAND_SERIES}, {"_id": 0})
    row = next((row for row in (band or {}).get("forecast", []) if row["year"] == year), None)
    if row:
        answer += " For the wider band of the world that includes all these cities, the temperature forecast for %d is about %+.1f °C compared with the 1951-1980 average (likely %+.1f to %+.1f)." % (
            year, row["forecast"], row["lower"], row["upper"])
    return reply("outlook", answer, notes=["That forecast extends past temperatures forward. It isn't a climate model and knows nothing about future emissions."], sources=["NASA GISTEMP"])


COUNTRY_TREND_NOTE = ("Country figures are yearly averages over all of Pakistan, from the IMF's temperature change data. "
                      "The method extends past temperatures forward, so it isn't a climate model and knows nothing about future emissions.")


def _score_note(score):
    result = "beat" if score["test_rmse"] < score["baseline_test_rmse"] else "didn't beat"
    return "Tested on %s, this method (%s) was off by about %.2f °C and %s simply using the last 10 years' average (%.2f °C)." % (
        score["test_period"], score["method_label"].lower(), score["test_rmse"], result, score["baseline_test_rmse"])


def country_disasters_answer(parsed):
    records = {record["kind"]: record for record in db.country_disasters.find({"iso3": COUNTRY}, {"_id": 0, "by_year": 0})}
    if not records:
        return not_trained()
    wanted = "storm" if parsed["storm"] else "flood" if parsed["flood"] else "total"
    for kind in ("drought", "landslide", "extreme_temperature"):
        if re.search({"drought": r"drought", "landslide": r"landslide", "extreme_temperature": r"heat ?wave|extreme"}[kind], parsed.get("text", "")):
            wanted = kind
    main = records.get(wanted) or records["total"]
    answer = disaster_sentence(main)
    if parsed["year"] and parsed["year"] > main["last_year"]:
        answer = "No one can say which disasters will happen in %d. %s" % (parsed["year"], answer)
    if main.get("worst_year"):
        answer += " The worst year for people affected was %d, with about %s people." % (main["worst_year"], "{:,}".format(main["worst_affected"]))
    order = [kind for kind in DISASTER_LABELS if kind in records]
    rows = [[DISASTER_LABELS[kind], "%d of %d" % (records[kind]["years_with"], records[kind]["years"]), percent(records[kind]["chance"]),
             "%s to %s" % (percent(records[kind]["chance_low"]), percent(records[kind]["chance_high"])), str(records[kind]["recent_events"]),
             str(records[kind]["latest_year"] or "None")] for kind in order]
    columns = ["Kind", "Years with one", "Chance in a year", "Likely range", "In the last %d years" % main["recent_years"], "Latest"]
    return reply("disasters", answer, columns, rows, [DISASTER_NOTE, "This is how often it has happened, not a forecast of a particular event.", OFFICIAL_NOTE], [COUNTRY_SOURCE])


def country_temperature_answer(parsed):
    rows = list(db.country_outlook.find({"iso3": COUNTRY}, {"_id": 0}).sort("year", 1))
    score = db.country_scores.find_one({"iso3": COUNTRY, "variable": "temperature_change"}, {"_id": 0})
    if not rows or not score:
        return not_trained()
    name = rows[0]["country"]
    year = parsed["year"]
    if year and year > score["last_year"] and in_projection_years(year) and (year > rows[-1]["year"] or parsed.get("scenario")):
        lead = "" if year <= rows[-1]["year"] else "That's past the trend outlook, which goes up to %d, so this comes from climate models." % rows[-1]["year"]
        projected = projection_answer(year, parsed.get("scenario") or DEFAULT_SCENARIO, lead)
        if projected:
            return projected
    if year and year <= score["last_year"]:
        past = db.country_indicators.find_one({"iso3": COUNTRY, "indicator": "temperature_change", "year": year})
        if not past:
            return reply("history", "I don't have %s's temperature change for %d." % (name, year), sources=[COUNTRY_SOURCE])
        answer = "In %d, %s was %+.2f °C compared with the 1951-1980 average." % (year, name, past["value"])
        return reply("history", answer, notes=[COUNTRY_TREND_NOTE.split(". ")[0] + "."], sources=[COUNTRY_SOURCE])
    if year and year > rows[-1]["year"]:
        answer = "%d is too far ahead: the outlook for %s goes up to %d." % (year, name, rows[-1]["year"])
    elif year:
        answer = country_temperature_sentence(year)
        projected = projection_sentence(year, DEFAULT_SCENARIO)
        if projected:
            answer += " " + projected
    else:
        answer = "%s's last recorded year, %d, was %+.2f °C compared with the 1951-1980 average. By %d it should be about %+.1f °C (likely %+.1f to %+.1f)." % (
            name, score["last_year"], score["last_value"], rows[-1]["year"], rows[-1]["value"], rows[-1]["low"], rows[-1]["high"])
    history = list(db.country_indicators.find({"iso3": COUNTRY, "indicator": "temperature_change", "year": {"$gte": score["last_year"] - 19}}, {"_id": 0}).sort("year", 1))
    labels = [str(row["year"]) for row in history] + [str(row["year"]) for row in rows]
    chart = {"labels": labels, "unit": "°C", "series": [
        {"label": "Recorded", "values": [row["value"] for row in history] + [None] * len(rows)},
        {"label": "Outlook", "values": [None] * (len(history) - 1) + [history[-1]["value"] if history else None] + [row["value"] for row in rows]}]}
    table = [[str(row["year"]), "%+.2f °C" % row["value"], "%+.2f to %+.2f °C" % (row["low"], row["high"])] for row in rows]
    notes, sources = [COUNTRY_TREND_NOTE, _score_note(score)], [COUNTRY_SOURCE]
    if "Climate models" in answer:
        notes.append(PROJECTION_NOTE)
        sources.append(PROJECTION_SOURCE)
    return reply("outlook", answer, ["Year", "Compared with 1951-1980", "Likely range"], table, notes, sources, chart)


def country_forest_answer():
    record = db.country_forest.find_one({"iso3": COUNTRY}, {"_id": 0})
    if not record:
        return not_trained()
    answer = "Forest covered %.2f%% of %s's land in %d and %.2f%% in %d, a change of about %+.3f percentage points a year." % (
        record["first_share"], record["country"], record["first_year"], record["last_share"], record["last_year"], record["yearly_change"])
    return reply("history", answer, sources=[COUNTRY_SOURCE + " (FAO forest data)"])


def country_answer(parsed):
    if parsed["forest"]:
        return country_forest_answer()
    if parsed["disaster"] or parsed["storm"]:
        return country_disasters_answer(parsed)
    return country_temperature_answer(parsed)


def answer_question(question):
    parsed = parse(question)
    parsed["text"] = question.lower()
    if not parsed["understood"]:
        return reply("help", HELP, notes=["Cities: " + ", ".join(config.LIVE_LOCATION_NAMES) + ". You can also ask about Pakistan as a whole."])
    if parsed["country"] and not parsed["cities"] and not (parsed["storm"] and parsed["near"] and not parsed["year"]):
        return country_answer(parsed)
    if not parsed["cities"] and (parsed["forest"] or (parsed["disaster"] and not parsed["storm"])):
        return country_answer(parsed)
    far_ahead = parsed["year"] is not None
    if parsed["storm"] and not far_ahead:
        return near_storm(parsed["cities"], parsed)
    if not parsed["cities"]:
        return reply("help", "Which city do you mean? I can answer for %s." % ", ".join(config.LIVE_LOCATION_NAMES), notes=[HELP])
    city = parsed["cities"][0]
    if parsed["storm"]:
        return future_storm(city, parsed)
    if not far_ahead:
        return near_weather(city, parsed)
    last_past = db.city_history.find_one({"city": city}, sort=[("year", -1)])
    if last_past and parsed["year"] <= last_past["year"]:
        return past_weather(city, parsed)
    last = db.city_outlooks.find_one({"city": city}, sort=[("year", -1)])
    if not last:
        return not_trained()
    if parsed["year"] > last["year"]:
        return too_far(city, parsed["year"], parsed["scenario"])
    return outlook(city, parsed)
