"""Monthly means of NASA POWER grid values per latitude zone.

Usage (Hadoop Streaming): satellite_zonal.py map | satellite_zonal.py reduce
Input: lat,lon,parameter,year,month,value (-999 marks a missing value)
Output: parameter, zone, year, month, mean, grid_cells, missing_cells
"""
import sys

sys.stdout.reconfigure(newline="\n")

ZONES = [
    (64, "64N-90N"), (44, "44N-64N"), (24, "24N-44N"), (0, "EQU-24N"),
    (-24, "24S-EQU"), (-44, "44S-24S"), (-64, "64S-44S"), (-90, "90S-64S"),
]


def zone_for(latitude):
    for lower, name in ZONES:
        if latitude >= lower:
            return name
    return None


def mapper():
    for line in sys.stdin:
        fields = line.rstrip("\r\n").split(",")
        if len(fields) != 6:
            continue
        lat, _, parameter, year, month, value = fields
        key = "%s|%s|%s|%s" % (parameter, zone_for(float(lat)), year, month)
        print("%s\t%s" % (key, value))


def reducer():
    current, values, missing = None, [], 0
    for line in sys.stdin:
        key, value = line.rstrip("\r\n").split("\t")
        if key != current:
            if current is not None:
                emit(current, values, missing)
            current, values, missing = key, [], 0
        if float(value) <= -999:
            missing += 1
        else:
            values.append(float(value))
    if current is not None:
        emit(current, values, missing)


def emit(key, values, missing):
    if values:
        print("%s,%.2f,%d,%d" % (key.replace("|", ","), sum(values) / len(values), len(values), missing))


if __name__ == "__main__":
    mapper() if sys.argv[1] == "map" else reducer()
