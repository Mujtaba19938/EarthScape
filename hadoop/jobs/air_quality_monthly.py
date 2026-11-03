"""Monthly air-quality statistics per OpenAQ sensor location and pollutant.

Usage (Hadoop Streaming): air_quality_monthly.py map | air_quality_monthly.py reduce
Input: location_id,sensors_id,location,datetime,lat,lon,parameter,units,value
Negative and unreadable values are invalid sensor readings, and are counted as rejected.
Output: location_id, location, lat, lon, parameter, units, year, month, mean, max, readings, rejected
"""
import csv
import sys

sys.stdin.reconfigure(encoding="utf-8", errors="replace")
sys.stdout.reconfigure(encoding="utf-8", newline="\n")


def mapper():
    for row in csv.reader(sys.stdin):
        if len(row) != 9 or row[0] == "location_id":
            continue
        location_id, _, name, stamp, lat, lon, parameter, units, value = row
        key = "|".join([location_id, name.replace(",", " ").replace("|", " "), lat, lon,
                        parameter, units, stamp[:4], stamp[5:7]])
        print("%s\t%s" % (key, value))


def reducer():
    current, values, rejected = None, [], 0
    for line in sys.stdin:
        key, value = line.rstrip("\r\n").split("\t")
        if key != current:
            if current is not None:
                emit(current, values, rejected)
            current, values, rejected = key, [], 0
        try:
            reading = float(value)
        except ValueError:
            reading = -1.0
        if reading < 0:
            rejected += 1
        else:
            values.append(reading)
    if current is not None:
        emit(current, values, rejected)


def emit(key, values, rejected):
    if values:
        # Gases reported in ppm are small, so two decimals would round them to zero.
        print("%s,%.4f,%.4f,%d,%d" % (key.replace("|", ","), sum(values) / len(values),
                                      max(values), len(values), rejected))


if __name__ == "__main__":
    mapper() if sys.argv[1] == "map" else reducer()
