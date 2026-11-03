"""The datasets the pipeline loads into HDFS, and the data available as reports."""

DATASETS = [
    {"id": "GHCN-DAILY", "name": "NOAA GHCN-Daily weather station records (2020, 2023)",
     "format": "CSV", "source": "NOAA NCEI", "path": "/climate/raw/ghcn_daily"},
    {"id": "GHCN-STATIONS", "name": "NOAA GHCN station list",
     "format": "Fixed-width text", "source": "NOAA NCEI", "path": "/climate/reference"},
    {"id": "GISTEMP", "name": "NASA GISTEMP v4 temperature anomalies",
     "format": "CSV", "source": "NASA GISS", "path": "/climate/raw/gistemp"},
    {"id": "CO2-MLO", "name": "Mauna Loa annual mean CO2",
     "format": "CSV", "source": "NOAA GML", "path": "/climate/raw/co2"},
    {"id": "POWER", "name": "NASA POWER solar radiation and surface temperature (30-point grid)",
     "format": "CSV", "source": "NASA POWER (CERES, MERRA-2)", "path": "/climate/raw/power"},
    {"id": "OPENAQ", "name": "OpenAQ air-quality sensor readings (9 locations, 2023)",
     "format": "CSV", "source": "OpenAQ", "path": "/climate/raw/openaq"},
    {"id": "LIVE", "name": "Live weather and air quality estimates (12 cities, hourly batches)",
     "format": "CSV", "source": "Open-Meteo models", "path": "/climate/raw/live"},
]

# Some OpenAQ readings at the end of the files fall into January 2024.
AIR_QUALITY_QUERY = {"year": 2023}

REPORTS = {
    "global_temperature": {
        "title": "Global temperature anomaly", "collection": "gistemp_global", "query": {},
        "columns": ["Year", "J-D"], "sort": [("Year", 1)]},
    "zonal_temperature": {
        "title": "Temperature anomaly by latitude zone", "collection": "gistemp_zonal", "query": {},
        "columns": ["Year", "Glob", "NHem", "SHem", "64N-90N", "44N-64N", "24N-44N", "EQU-24N",
                    "24S-EQU", "44S-24S", "64S-44S", "90S-64S"],
        "sort": [("Year", 1)]},
    "co2": {
        "title": "Atmospheric CO2 at Mauna Loa", "collection": "co2_annual", "query": {},
        "columns": ["year", "mean", "unc"], "sort": [("year", 1)]},
    "regional_monthly": {
        "title": "Monthly weather station means by zone", "collection": "regional_monthly", "query": {},
        "columns": ["zone", "year", "month", "element", "mean", "readings"],
        "sort": [("zone", 1), ("year", 1), ("month", 1), ("element", 1)]},
    "station_anomalies": {
        "title": "Station temperature anomalies", "collection": "station_anomalies", "query": {},
        "columns": ["station", "date", "element", "value_c", "mean_c", "stddev_c", "z_score"],
        "sort": [("date", 1), ("station", 1)]},
    "satellite_zonal": {
        "title": "Solar radiation and surface temperature by zone", "collection": "satellite_zonal", "query": {},
        "columns": ["parameter", "zone", "year", "month", "mean", "grid_cells", "missing_cells"],
        "sort": [("parameter", 1), ("zone", 1), ("year", 1), ("month", 1)]},
    "air_quality": {
        "title": "Monthly air quality by sensor location", "collection": "air_quality_monthly",
        "query": AIR_QUALITY_QUERY,
        "columns": ["location_id", "location", "lat", "lon", "parameter", "units", "year", "month",
                    "mean", "max", "readings", "rejected"],
        "sort": [("location", 1), ("parameter", 1), ("month", 1)], "geo": True},
    "live_readings": {
        "title": "Live weather and air quality estimates", "collection": "live_readings", "query": {},
        "columns": ["location", "lat", "lon", "observed_at", "temperature_c", "humidity_pct", "precipitation_mm",
                    "wind_kmh", "pm25", "pm10", "no2", "o3", "us_aqi"],
        "sort": [("observed_at", 1), ("location", 1)], "geo": True},
}

# Signatures of binary formats, so a renamed file can't be registered as climate data.
UPLOAD_SIGNATURES = {
    ".nc": [b"CDF", b"\x89HDF"],
    ".h5": [b"\x89HDF"],
    ".hdf5": [b"\x89HDF"],
    ".tif": [b"II*\x00", b"MM\x00*"],
    ".tiff": [b"II*\x00", b"MM\x00*"],
    ".parquet": [b"PAR1"],
    ".grib2": [b"GRIB"],
    ".csv": None,
}
