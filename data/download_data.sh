#!/usr/bin/env bash
# Downloads the raw climate datasets into data/raw (ignored by git).
set -euo pipefail

RAW="$(cd "$(dirname "$0")" && pwd)/raw"
mkdir -p "$RAW/gistemp" "$RAW/co2" "$RAW/ghcn_daily"

fetch() {
  echo "Downloading $2"
  curl -fsSL --retry 3 -C - -o "$2" "$1"
}

GISS="https://data.giss.nasa.gov/gistemp/tabledata_v4"
GHCN="https://www.ncei.noaa.gov/pub/data/ghcn/daily"

fetch "$GISS/GLB.Ts+dSST.csv" "$RAW/gistemp/GLB.Ts+dSST.csv"
fetch "$GISS/ZonAnn.Ts+dSST.csv" "$RAW/gistemp/ZonAnn.Ts+dSST.csv"
fetch "https://gml.noaa.gov/webdata/ccgg/trends/co2/co2_annmean_mlo.csv" "$RAW/co2/co2_annmean_mlo.csv"
fetch "$GHCN/ghcnd-stations.txt" "$RAW/ghcn_daily/ghcnd-stations.txt"
for year in 2020 2023; do
  fetch "$GHCN/by_year/$year.csv.gz" "$RAW/ghcn_daily/$year.csv.gz"
done
