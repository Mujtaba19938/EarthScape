"""Turns the IMF climate indicator tables (one column per year) into one row per country, indicator and year.

Usage (Hadoop Streaming): country_indicators.py map | country_indicators.py reduce
Input: the IMF CSVs in /climatechange/input: ObjectId,Country,ISO2,ISO3,Indicator,Unit,...,1980,1981,...
Each file is far smaller than an HDFS block, so a map task reads a whole file and sees its header first.
Output: iso3, country, indicator, unit, year, value
"""
import csv
import re
import sys

sys.stdout.reconfigure(newline="\n")


def short_name(indicator):
    """A short key for an indicator, such as disasters_storm or temperature_change."""
    text = indicator.strip()
    if text.startswith("Temperature change"):
        return "temperature_change"
    if ":" in text and "Number of Disasters" in text:
        return "disasters_" + slug(text.split(":")[-1])
    if ":" in text and "People Affected" in text:
        return "people_affected_" + slug(text.split(":")[-1])
    return slug(text)


def slug(text):
    return re.sub(r"[^a-z0-9]+", "_", text.lower()).strip("_")


def clean(text):
    # The output is split on commas, so names like "Afghanistan, Islamic Rep. of" lose theirs.
    return " ".join(text.replace(",", " ").replace("|", " ").split())


def mapper():
    years, columns, skipped = None, {}, 0
    for fields in csv.reader(sys.stdin):
        if fields and fields[0].lstrip("﻿") == "ObjectId":
            columns = {name: index for index, name in enumerate(fields)}
            years = [(index, name) for index, name in enumerate(fields) if re.fullmatch(r"\d{4}", name)]
            continue
        if years is None or len(fields) < len(columns):
            skipped += 1
            continue
        iso3 = fields[columns["ISO3"]].strip()
        if not iso3:
            skipped += 1
            continue
        indicator = short_name(fields[columns["Indicator"]])
        about = "%s|%s" % (clean(fields[columns["Country"]]), clean(fields[columns["Unit"]]))
        for index, year in years:
            value = fields[index].strip()
            if value:
                try:
                    float(value)
                except ValueError:
                    skipped += 1
                    continue
                print("%s|%s|%s\t%s|%s" % (iso3, indicator, year, about, value))
    if skipped:
        sys.stderr.write("reporter:counter:country_indicators,skipped,%d\n" % skipped)


def reducer():
    current, last = None, None
    for line in sys.stdin:
        key, value = line.rstrip("\r\n").split("\t")
        if key != current and current is not None:
            emit(current, last)
        current, last = key, value
    if current is not None:
        emit(current, last)


def emit(key, value):
    iso3, indicator, year = key.split("|")
    country, unit, number = value.split("|")
    print(",".join([iso3, country, indicator, unit, year, number]))


if __name__ == "__main__":
    mapper() if sys.argv[1] == "map" else reducer()
