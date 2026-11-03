"""Monthly means of TMAX, TMIN and PRCP per latitude zone (the GISTEMP zone bands).

Usage (Hadoop Streaming): regional_monthly.py map | regional_monthly.py reduce
The mapper needs ghcnd-stations.txt beside it, to look up station latitude.
Readings that are missing or failed quality control are skipped.
Output: zone, year, month, element, mean, readings (TMAX/TMIN in C, PRCP in mm/day)
"""
import sys

sys.stdout.reconfigure(newline="\n")

ELEMENTS = {"TMAX", "TMIN", "PRCP"}
MISSING = "-9999"
ZONES = [
    (64, "64N-90N"), (44, "44N-64N"), (24, "24N-44N"), (0, "EQU-24N"),
    (-24, "24S-EQU"), (-44, "44S-24S"), (-64, "64S-44S"), (-90, "90S-64S"),
]


def zone_for(latitude):
    for lower, name in ZONES:
        if latitude >= lower:
            return name
    return None


def load_station_zones(path="ghcnd-stations.txt"):
    zones = {}
    with open(path) as stations:
        for line in stations:
            try:
                zones[line[:11]] = zone_for(float(line[12:20]))
            except ValueError:
                continue
    return zones


def mapper():
    zones = load_station_zones()
    totals = {}
    for line in sys.stdin:
        fields = line.rstrip("\r\n").split(",")
        if len(fields) < 6 or fields[2] not in ELEMENTS or len(fields[1]) != 8:
            continue
        value = fields[3].strip()
        zone = zones.get(fields[0])
        if not zone or not value or value == MISSING or fields[5].strip():
            continue
        key = "%s|%s|%s|%s" % (zone, fields[1][:4], fields[1][4:6], fields[2])
        entry = totals.setdefault(key, [0, 0])
        entry[0] += int(value)
        entry[1] += 1
    for key, (total, count) in totals.items():
        print("%s\t%d %d" % (key, total, count))


def reducer():
    current, total, count = None, 0, 0
    for line in sys.stdin:
        key, value = line.rstrip("\r\n").split("\t")
        if key != current:
            if current is not None:
                emit(current, total, count)
            current, total, count = key, 0, 0
        part_total, part_count = value.split()
        total += int(part_total)
        count += int(part_count)
    if current is not None:
        emit(current, total, count)


def emit(key, total, count):
    # GHCN stores temperature and precipitation in tenths of a unit.
    print("%s,%.2f,%d" % (key.replace("|", ","), total / count / 10.0, count))


if __name__ == "__main__":
    mapper() if sys.argv[1] == "map" else reducer()
