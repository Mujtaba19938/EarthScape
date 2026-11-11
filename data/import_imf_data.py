"""Copies the IMF Climate Change Indicators files into data/raw/imf as plain CSV.

Usage (Anaconda's Python, which can read .xls): python data/import_imf_data.py FILE [FILE ...]

Each file is recognised by its Indicator column, so the downloaded names (such as
jiGWfF.csv) don't matter. Year columns are renamed to plain years (F1992 becomes 1992)
so the MapReduce job reads every file the same way.
"""
import os
import re
import sys

import pandas as pd

RAW = os.path.join(os.path.dirname(os.path.abspath(__file__)), "raw", "imf")
KINDS = [("Climate related disasters", "climate_disasters.csv"), ("Temperature change", "temperature_change.csv"),
         ("forest", "forest_carbon.csv")]
META = ["ObjectId", "Country", "ISO2", "ISO3", "Indicator", "Unit", "Source", "CTS Code", "CTS Name", "CTS Full Descriptor"]


def read(path):
    table = pd.read_excel(path) if path.lower().endswith((".xls", ".xlsx")) else pd.read_csv(path)
    # One file writes CTS_Code where the others write CTS Code.
    return table.rename(columns=lambda name: str(name).replace("_", " ") if str(name).startswith("CTS") else name)


def tidy(table):
    years = {column: re.sub(r"^F", "", str(column)) for column in table.columns if re.fullmatch(r"F?\d{4}", str(column))}
    return table[[column for column in META if column in table.columns] + list(years)].rename(columns=years)


def kind_of(table):
    indicators = " ".join(table["Indicator"].astype(str).unique()).lower()
    return next((name for marker, name in KINDS if marker.lower() in indicators), None)


def main(paths):
    os.makedirs(RAW, exist_ok=True)
    for path in paths:
        table = read(path)
        name = kind_of(table)
        if not name:
            print("Skipped", path, "- not an IMF climate indicator file I know")
            continue
        table = tidy(table)
        table.to_csv(os.path.join(RAW, name), index=False, encoding="utf-8", line_terminator="\n")
        print("Saved", name, "from", os.path.basename(path), "-", len(table), "rows,", len(table.columns) - len(META), "years")


if __name__ == "__main__":
    main(sys.argv[1:])
