"""Flags daily temperatures more than 3 standard deviations from a station's month mean.

Usage (Hadoop Streaming): station_anomalies.py map | station_anomalies.py reduce
Each station and calendar month is compared across every year in the input, so
the baseline is only as long as the data loaded. Station-months with fewer than
MIN_READINGS valid readings are skipped rather than judged on too little data.
Output: station, date, element, value_c, mean_c, stddev_c, z_score
"""
import math
import sys

sys.stdout.reconfigure(newline="\n")

ELEMENTS = {"TMAX", "TMIN"}
MISSING = "-9999"
MIN_READINGS = 20
THRESHOLD = 3.0


def mapper():
    for line in sys.stdin:
        fields = line.rstrip("\r\n").split(",")
        if len(fields) < 6 or fields[2] not in ELEMENTS or len(fields[1]) != 8:
            continue
        value = fields[3].strip()
        if not value or value == MISSING or fields[5].strip():
            continue
        print("%s|%s|%s\t%s %s" % (fields[0], fields[1][4:6], fields[2], fields[1], value))


def reducer():
    current, readings = None, []
    for line in sys.stdin:
        key, value = line.rstrip("\r\n").split("\t")
        if key != current:
            if current is not None:
                flag_outliers(current, readings)
            current, readings = key, []
        date, reading = value.split()
        readings.append((date, int(reading)))
    if current is not None:
        flag_outliers(current, readings)


def flag_outliers(key, readings):
    if len(readings) < MIN_READINGS:
        return
    mean = sum(r for _, r in readings) / len(readings)
    stddev = math.sqrt(sum((r - mean) ** 2 for _, r in readings) / len(readings))
    if stddev == 0:
        return
    station, _, element = key.split("|")
    for date, reading in readings:
        z_score = (reading - mean) / stddev
        if abs(z_score) > THRESHOLD:
            print("%s,%s,%s,%.1f,%.2f,%.2f,%.2f" % (
                station, date, element, reading / 10.0, mean / 10.0, stddev / 10.0, z_score))


if __name__ == "__main__":
    mapper() if sys.argv[1] == "map" else reducer()
