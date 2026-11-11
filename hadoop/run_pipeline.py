"""Runs the EarthScape batch pipeline: raw files -> HDFS -> MapReduce -> MongoDB.

Usage: python run_pipeline.py [load|imf] [jobs] [mongo] [job name ...]   (no steps runs all three)
"imf" loads only the IMF climate indicator files and the CMIP6 projections. Naming jobs runs and reloads just those.
Run from Anaconda's Python, which has pymongo. HDFS and YARN must already be running.
Set STREAMING_PYTHON if Python lives elsewhere: its path must not contain spaces.
"""
import csv
import datetime
import gzip
import os
import shutil
import subprocess
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RAW = os.path.join(ROOT, "data", "raw")
JOBS = os.path.join(ROOT, "hadoop", "jobs")
STREAMING_JAR = "C:/hadoop/hadoop-2.9.2/share/hadoop/tools/lib/hadoop-streaming-2.9.2.jar"
STREAMING_PYTHON = os.environ.get(
    "STREAMING_PYTHON", "C:/Users/MUJTAB~1/AppData/Local/Programs/Python/Python313/python.exe")
GHCN_YEARS = ["2020", "2023"]
STATIONS = os.path.join(RAW, "ghcn_daily", "ghcnd-stations.txt")
MONGO_URI = os.environ.get("MONGO_URI", "mongodb://localhost:27017")
MONGO_DB = "earthscape"

GHCN_INPUT = "/climate/raw/ghcn_daily/year_*"
IMF_FILES = ["climate_disasters.csv", "temperature_change.csv", "forest_carbon.csv"]
IMF_INPUT = "/climatechange/input"
CMIP6_FILE = os.path.join(RAW, "cmip6", "pakistan_cmip6.csv")
CMIP6_INPUT = "/climatechange/cmip6"
# Jobs whose output goes under /climatechange instead of /climate/processed.
OUTPUT_DIRS = {"country_indicators": "/climatechange/output/country_indicators",
               "cmip6_projections": "/climatechange/output/cmip6_projections"}
STEPS = ("load", "imf", "jobs", "mongo")

# name, input, needs the station list, reducers, CSV columns of the output
JOB_SPECS = [
    ("data_quality", GHCN_INPUT, False, 1,
     ["year", "element", "valid", "missing", "failed_qc", "malformed"]),
    ("regional_monthly", GHCN_INPUT, True, 1,
     ["zone", "year", "month", "element", "mean", "readings"]),
    ("station_anomalies", GHCN_INPUT, False, 4,
     ["station", "date", "element", "value_c", "mean_c", "stddev_c", "z_score"]),
    ("satellite_zonal", "/climate/raw/power", False, 1,
     ["parameter", "zone", "year", "month", "mean", "grid_cells", "missing_cells"]),
    ("air_quality_monthly", "/climate/raw/openaq", False, 1,
     ["location_id", "location", "lat", "lon", "parameter", "units", "year", "month",
      "mean", "max", "readings", "rejected"]),
    ("country_indicators", IMF_INPUT, False, 1,
     ["iso3", "country", "indicator", "unit", "year", "value"]),
    ("cmip6_projections", CMIP6_INPUT, False, 1,
     ["iso3", "measure", "scenario", "percentile", "year", "value", "change"]),
]


def output_dir(name):
    return OUTPUT_DIRS.get(name, "/climate/processed/" + name)


def command_line(args):
    # hadoop and hdfs are .cmd files on Windows, so they must go through cmd,
    # and batch files split unquoted arguments at spaces, "=" and ",".
    quoted = ['"%s"' % a if any(c in a for c in " =,*") else a for a in args]
    return "cmd /c " + " ".join(quoted)


def run(args):
    subprocess.run(command_line(args), check=True)


def hdfs(*args):
    # Not "hdfs dfs": on Windows hdfs.cmd exits with 0 even when the command failed.
    run(["hadoop", "fs"] + list(args))


def put(local, target_dir):
    hdfs("-mkdir", "-p", target_dir)
    hdfs("-put", "-f", local, target_dir + "/")


def unpack(path):
    target = path[:-3]
    if not os.path.exists(target):
        print("Unpacking", path)
        with gzip.open(path, "rb") as source, open(target, "wb") as output:
            shutil.copyfileobj(source, output)
    return target


def load():
    for year in GHCN_YEARS:
        csv_path = unpack(os.path.join(RAW, "ghcn_daily", year + ".csv.gz"))
        put(csv_path, "/climate/raw/ghcn_daily/year_" + year)
    put(STATIONS, "/climate/reference")
    put(os.path.join(RAW, "gistemp", "GLB.Ts+dSST.csv"), "/climate/raw/gistemp")
    put(os.path.join(RAW, "gistemp", "ZonAnn.Ts+dSST.csv"), "/climate/raw/gistemp")
    put(os.path.join(RAW, "co2", "co2_annmean_mlo.csv"), "/climate/raw/co2")
    put(os.path.join(RAW, "power", "power_monthly.csv"), "/climate/raw/power")
    for filename in sorted(os.listdir(os.path.join(RAW, "openaq"))):
        if filename.endswith(".csv"):
            put(os.path.join(RAW, "openaq", filename), "/climate/raw/openaq")
    load_imf()


def load_imf():
    """The IMF files, saved by data/import_imf_data.py."""
    hdfs("-mkdir", "-p", "/climatechange/output")
    for filename in IMF_FILES:
        put(os.path.join(RAW, "imf", filename), IMF_INPUT)
    # Kept apart from the IMF files, which the country_indicators job reads as one folder.
    put(CMIP6_FILE, CMIP6_INPUT)


def as_uri(path):
    return "file:///" + path.replace("\\", "/")


def run_job(name, job_input, needs_stations, reducers):
    script = name + ".py"
    files = [as_uri(os.path.join(JOBS, script))]
    if needs_stations:
        files.append(as_uri(STATIONS))
    output = output_dir(name)
    hdfs("-rm", "-r", "-f", "-skipTrash", output)
    started = time.time()
    run([
        "hadoop", "jar", STREAMING_JAR,
        "-D", "mapreduce.job.name=earthscape_" + name,
        "-D", "mapreduce.job.reduces=%d" % reducers,
        "-files", ",".join(files),
        "-mapper", "%s %s map" % (STREAMING_PYTHON, script),
        "-reducer", "%s %s reduce" % (STREAMING_PYTHON, script),
        "-input", job_input,
        "-output", output,
    ])
    return time.time() - started


def timing(name, seconds):
    return {"job": name, "seconds": round(seconds, 1),
            "finished_at": datetime.datetime.utcnow()}


def jobs(specs=JOB_SPECS):
    timings = []
    for name, job_input, needs_stations, reducers, _ in specs:
        seconds = run_job(name, job_input, needs_stations, reducers)
        print("%s finished in %.0f s" % (name, seconds))
        timings.append(timing(name, seconds))
    return timings


def read_job_output(name):
    command = command_line(["hadoop", "fs", "-cat", output_dir(name) + "/part-*"])
    text = subprocess.run(command, check=True, stdout=subprocess.PIPE,
                          encoding="utf-8").stdout
    return [line.split(",") for line in text.splitlines() if line]


def typed(value):
    for convert in (int, float):
        try:
            return convert(value)
        except ValueError:
            pass
    return value


def read_gistemp(filename, year_column="Year"):
    # GISTEMP files start with a title line, and mark missing values with ***.
    with open(os.path.join(RAW, "gistemp", filename), newline="") as source:
        lines = [line for line in source if "," in line]
    rows = []
    for row in csv.DictReader(lines):
        rows.append({key: None if "*" in value else typed(value)
                     for key, value in row.items() if key})
    return [row for row in rows if isinstance(row.get(year_column), int)]


def read_co2():
    with open(os.path.join(RAW, "co2", "co2_annmean_mlo.csv"), newline="") as source:
        lines = [line for line in source if not line.startswith("#")]
    return [{key: typed(value) for key, value in row.items()} for row in csv.DictReader(lines)]


def replace_collection(db, name, documents):
    db[name].drop()
    if documents:
        db[name].insert_many(documents)
    print("%s: %d documents" % (name, len(documents)))


def load_job_output(db, spec):
    name, columns = spec[0], spec[4]
    documents = []
    for fields in read_job_output(name):
        values = [fields[0]] + [typed(v) for v in fields[1:]]
        documents.append(dict(zip(columns, values)))
    replace_collection(db, name, documents)
    db.station_anomalies.create_index([("station", 1), ("date", 1)])
    db.regional_monthly.create_index([("zone", 1), ("year", 1), ("month", 1)])
    db.country_indicators.create_index([("iso3", 1), ("indicator", 1), ("year", 1)])
    db.cmip6_projections.create_index([("iso3", 1), ("measure", 1), ("scenario", 1), ("year", 1)])


def record_timings(db, timings):
    if timings:
        db.pipeline_runs.insert_many(timings)


def to_mongo(timings, specs=JOB_SPECS):
    from pymongo import MongoClient

    db = MongoClient(MONGO_URI, serverSelectionTimeoutMS=5000)[MONGO_DB]
    for spec in specs:
        load_job_output(db, spec)
    replace_collection(db, "gistemp_global", read_gistemp("GLB.Ts+dSST.csv"))
    replace_collection(db, "gistemp_zonal", read_gistemp("ZonAnn.Ts+dSST.csv"))
    replace_collection(db, "co2_annual", read_co2())
    record_timings(db, timings)


def main():
    names = [arg for arg in sys.argv[1:] if arg not in STEPS]
    unknown = [name for name in names if name not in [spec[0] for spec in JOB_SPECS]]
    if unknown:
        sys.exit("Unknown step or job: " + ", ".join(unknown))
    steps = [arg for arg in sys.argv[1:] if arg in STEPS] or ["load", "jobs", "mongo"]
    specs = [spec for spec in JOB_SPECS if spec[0] in names] if names else JOB_SPECS
    timings = []
    if "load" in steps:
        load()
    elif "imf" in steps:
        load_imf()
    if "jobs" in steps:
        timings = jobs(specs)
    if "mongo" in steps:
        to_mongo(timings, specs)


if __name__ == "__main__":
    main()
