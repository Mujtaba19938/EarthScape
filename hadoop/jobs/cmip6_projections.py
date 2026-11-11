"""Works out how much each CMIP6 projection for Pakistan differs from the models' own recent past.

Usage (Hadoop Streaming): cmip6_projections.py map | cmip6_projections.py reduce
Input: iso3,measure,scenario,percentile,year,value (data/fetch_cmip6.py), including the models'
"historical" run of 1950-2014.
Output: iso3, measure, scenario, percentile, year, value, change
change is the value minus the same models' 1995-2014 average, the IPCC's usual baseline.
Comparing a model with itself removes its fixed bias, so the change is more reliable than the value.
"""
import sys

sys.stdout.reconfigure(newline="\n")

BASELINE = range(1995, 2015)


def mapper():
    for line in sys.stdin:
        fields = line.rstrip("\r\n").split(",")
        if len(fields) != 6 or fields[0] == "iso3":
            continue
        iso3, measure, scenario, percentile, year, value = fields
        try:
            float(value)
            int(year)
        except ValueError:
            continue
        # Grouped by measure and percentile, so one reducer call sees the baseline and every scenario.
        print("%s|%s|%s\t%s|%s|%s" % (iso3, measure, percentile, scenario, year, value))


def reducer():
    current, rows = None, []
    for line in sys.stdin:
        key, value = line.rstrip("\r\n").split("\t")
        if key != current:
            if current is not None:
                emit(current, rows)
            current, rows = key, []
        scenario, year, number = value.split("|")
        rows.append((scenario, int(year), float(number)))
    if current is not None:
        emit(current, rows)


def emit(key, rows):
    iso3, measure, percentile = key.split("|")
    baseline = [value for scenario, year, value in rows if scenario == "historical" and year in BASELINE]
    if not baseline:
        return
    average = sum(baseline) / len(baseline)
    for scenario, year, value in sorted(rows):
        if scenario != "historical":
            print(",".join([iso3, measure, scenario, percentile, str(year), "%g" % value, "%.3f" % (value - average)]))


if __name__ == "__main__":
    mapper() if sys.argv[1] == "map" else reducer()
