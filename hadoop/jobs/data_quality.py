"""Counts valid, missing and quality-failed GHCN readings per year and element.

Usage (Hadoop Streaming): data_quality.py map | data_quality.py reduce
Input: ID,YYYYMMDD,ELEMENT,VALUE,MFLAG,QFLAG,SFLAG,TIME
Output: year, element, valid, missing, failed_qc, malformed
"""
import sys

sys.stdout.reconfigure(newline="\n")

MISSING = "-9999"


def mapper():
    counts = {}
    for line in sys.stdin:
        fields = line.rstrip("\r\n").split(",")
        if len(fields) < 6 or len(fields[1]) != 8:
            key = ("unknown", "unknown")
            status = 3
        else:
            key = (fields[1][:4], fields[2])
            value = fields[3].strip()
            if not value or value == MISSING:
                status = 1
            elif fields[5].strip():
                status = 2
            else:
                status = 0
        totals = counts.setdefault(key, [0, 0, 0, 0])
        totals[status] += 1
    for (year, element), totals in counts.items():
        print("%s|%s\t%s" % (year, element, " ".join(map(str, totals))))


def reducer():
    current, totals = None, [0, 0, 0, 0]
    for line in sys.stdin:
        key, value = line.rstrip("\r\n").split("\t")
        if key != current:
            if current is not None:
                emit(current, totals)
            current, totals = key, [0, 0, 0, 0]
        totals = [a + int(b) for a, b in zip(totals, value.split())]
    if current is not None:
        emit(current, totals)


def emit(key, totals):
    print(",".join(key.split("|") + [str(t) for t in totals]))


if __name__ == "__main__":
    mapper() if sys.argv[1] == "map" else reducer()
