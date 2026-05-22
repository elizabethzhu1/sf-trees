#!/usr/bin/env python3
import csv
import json
from collections import Counter
from pathlib import Path

CSV_PATH = Path("Street_Tree_List_20260521.csv")
MAP_OUT_PATH = Path("trees-map.json")
DETAILS_OUT_PATH = Path("tree-details.json")
SF_BOUNDS = {
    "south": 37.604,
    "west": -122.548,
    "north": 37.833,
    "east": -122.349,
}


def clean(value):
    return (value or "").strip()


def parse_dbh(value):
    try:
        dbh = float(value)
    except (TypeError, ValueError):
        return 0
    return max(0, round(dbh, 1))


def in_bounds(lat, lng):
    return (
        SF_BOUNDS["south"] - 0.08 <= lat <= SF_BOUNDS["north"] + 0.08
        and SF_BOUNDS["west"] - 0.08 <= lng <= SF_BOUNDS["east"] + 0.08
    )


def dict_index(values, value):
    if value not in values:
        values[value] = len(values)
    return values[value]


def main():
    species = {}
    statuses = {}
    caretakers = {}
    latitudes = []
    longitudes = []
    species_indices = []
    status_indices = []
    caretaker_indices = []
    dbh_values = []
    addresses = []
    tree_ids = []
    species_counts = Counter()
    status_counts = Counter()
    caretaker_counts = Counter()
    total_rows = 0

    with CSV_PATH.open(newline="", encoding="utf-8") as file:
        reader = csv.DictReader(file)
        for row in reader:
            total_rows += 1
            try:
                lat = float(row["Latitude"])
                lng = float(row["Longitude"])
            except (TypeError, ValueError):
                continue

            if not in_bounds(lat, lng):
                continue

            raw_species = clean(row["qSpecies"]) or "Unknown"
            status = clean(row["qLegalStatus"]) or "Unknown"
            caretaker = clean(row["qCaretaker"]) or "Unknown"
            address = clean(row["qAddress"])
            dbh = parse_dbh(row["DBH"])

            species_index = dict_index(species, raw_species)
            status_index = dict_index(statuses, status)
            caretaker_index = dict_index(caretakers, caretaker)
            species_counts[raw_species] += 1
            status_counts[status] += 1
            caretaker_counts[caretaker] += 1

            latitudes.append(round(lat * 1_000_000))
            longitudes.append(round(lng * 1_000_000))
            species_indices.append(species_index)
            status_indices.append(status_index)
            caretaker_indices.append(caretaker_index)
            dbh_values.append(round(dbh * 10))
            addresses.append(address)
            tree_ids.append(clean(row["TreeID"]))

    map_payload = {
        "source": CSV_PATH.name,
        "sourceRows": total_rows,
        "treeCount": len(latitudes),
        "scale": 1_000_000,
        "dbhScale": 10,
        "bounds": SF_BOUNDS,
        "species": list(species.keys()),
        "statuses": list(statuses.keys()),
        "caretakers": list(caretakers.keys()),
        "topSpecies": species_counts.most_common(10),
        "topStatuses": status_counts.most_common(8),
        "topCaretakers": caretaker_counts.most_common(8),
        "lat": latitudes,
        "lng": longitudes,
        "sp": species_indices,
        "st": status_indices,
        "ca": caretaker_indices,
        "dbh": dbh_values,
    }

    details_payload = {
        "source": CSV_PATH.name,
        "treeCount": len(latitudes),
        "addr": addresses,
        "id": tree_ids,
    }

    with MAP_OUT_PATH.open("w", encoding="utf-8") as file:
        json.dump(map_payload, file, separators=(",", ":"))

    with DETAILS_OUT_PATH.open("w", encoding="utf-8") as file:
        json.dump(details_payload, file, separators=(",", ":"))

    print(f"Wrote {MAP_OUT_PATH} and {DETAILS_OUT_PATH} with {len(latitudes):,} trees from {total_rows:,} CSV rows")


if __name__ == "__main__":
    main()
