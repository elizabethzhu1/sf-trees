#!/usr/bin/env python3
import csv
import json
from collections import Counter
from pathlib import Path
import re

CSV_PATH = Path("Street_Tree_List_20260521.csv")
MAP_OUT_PATH = Path("trees-map.json")
DETAILS_OUT_PATH = Path("tree-details.json")
NEIGHBORHOODS_PATH = Path("neighborhoods.geojson")
NEIGHBORHOODS_MAP_OUT_PATH = Path("neighborhoods-map.geojson")
SUMMARY_OUT_PATH = Path("neighborhood-summary.json")
TREE_DATA_DIR = Path("tree-data")
MAP_SIMPLIFY_TOLERANCE = 0.00035
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


def slugify(value):
    slug = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    return slug or "unknown"


def ring_bounds(ring):
    lngs = [point[0] for point in ring]
    lats = [point[1] for point in ring]
    return min(lngs), min(lats), max(lngs), max(lats)


def merge_bounds(bounds):
    return (
        min(item[0] for item in bounds),
        min(item[1] for item in bounds),
        max(item[2] for item in bounds),
        max(item[3] for item in bounds),
    )


def point_in_ring(lat, lng, ring):
    inside = False
    j = len(ring) - 1
    for i, point in enumerate(ring):
        xi, yi = point[0], point[1]
        xj, yj = ring[j][0], ring[j][1]
        intersects = (yi > lat) != (yj > lat)
        if intersects:
            x_at_lat = (xj - xi) * (lat - yi) / (yj - yi) + xi
            if lng < x_at_lat:
                inside = not inside
        j = i
    return inside


def point_in_polygon(lat, lng, polygon):
    if not point_in_ring(lat, lng, polygon[0]):
        return False
    return not any(point_in_ring(lat, lng, hole) for hole in polygon[1:])


def point_in_geometry(lat, lng, geometry):
    geometry_type = geometry.get("type")
    coordinates = geometry.get("coordinates", [])
    if geometry_type == "Polygon":
        return point_in_polygon(lat, lng, coordinates)
    if geometry_type == "MultiPolygon":
        return any(point_in_polygon(lat, lng, polygon) for polygon in coordinates)
    return False


def geometry_bounds(geometry):
    geometry_type = geometry.get("type")
    coordinates = geometry.get("coordinates", [])
    if geometry_type == "Polygon":
        return merge_bounds([ring_bounds(coordinates[0])])
    if geometry_type == "MultiPolygon":
        return merge_bounds([ring_bounds(polygon[0]) for polygon in coordinates])
    return (0, 0, 0, 0)


def point_line_distance(point, start, end):
    px, py = point
    sx, sy = start
    ex, ey = end
    dx = ex - sx
    dy = ey - sy
    if dx == 0 and dy == 0:
        return ((px - sx) ** 2 + (py - sy) ** 2) ** 0.5
    t = max(0, min(1, ((px - sx) * dx + (py - sy) * dy) / (dx * dx + dy * dy)))
    x = sx + t * dx
    y = sy + t * dy
    return ((px - x) ** 2 + (py - y) ** 2) ** 0.5


def simplify_line(points, tolerance):
    if len(points) <= 2:
        return points

    start = points[0]
    end = points[-1]
    max_distance = 0
    max_index = 0
    for index in range(1, len(points) - 1):
        distance = point_line_distance(points[index], start, end)
        if distance > max_distance:
            max_distance = distance
            max_index = index

    if max_distance <= tolerance:
        return [start, end]

    left = simplify_line(points[:max_index + 1], tolerance)
    right = simplify_line(points[max_index:], tolerance)
    return left[:-1] + right


def simplify_ring(ring, tolerance):
    if len(ring) <= 4:
        return ring
    closed = ring[0] == ring[-1]
    points = ring[:-1] if closed else ring
    simplified = simplify_line(points, tolerance)
    if len(simplified) < 3:
        simplified = points[:3]
    simplified.append(simplified[0])
    return simplified


def simplify_geometry(geometry, tolerance):
    geometry_type = geometry.get("type")
    coordinates = geometry.get("coordinates", [])
    if geometry_type == "Polygon":
        return {
            "type": "Polygon",
            "coordinates": [simplify_ring(ring, tolerance) for ring in coordinates],
        }
    if geometry_type == "MultiPolygon":
        return {
            "type": "MultiPolygon",
            "coordinates": [
                [simplify_ring(ring, tolerance) for ring in polygon]
                for polygon in coordinates
            ],
        }
    return geometry


def load_neighborhoods():
    with NEIGHBORHOODS_PATH.open(encoding="utf-8") as file:
        payload = json.load(file)

    neighborhoods = []
    seen_slugs = set()
    for feature in payload.get("features", []):
        geometry = feature.get("geometry")
        if not geometry:
            continue
        properties = feature.get("properties", {})
        name = clean(properties.get("nhood") or properties.get("name"))
        if not name:
            continue
        slug = slugify(name)
        if slug in seen_slugs:
            continue
        seen_slugs.add(slug)
        neighborhoods.append({
            "name": name,
            "slug": slug,
            "geometry": geometry,
            "bounds": geometry_bounds(geometry),
            "rows": [],
            "speciesCounts": Counter(),
            "statusCounts": Counter(),
            "caretakerCounts": Counter(),
        })

    neighborhoods.sort(key=lambda item: item["name"])
    return neighborhoods


def find_neighborhood(lat, lng, neighborhoods):
    for neighborhood in neighborhoods:
        west, south, east, north = neighborhood["bounds"]
        if west <= lng <= east and south <= lat <= north and point_in_geometry(lat, lng, neighborhood["geometry"]):
            return neighborhood
    return None


def build_tree_payload(source_rows, neighborhood):
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

    for row in neighborhood["rows"]:
        raw_species = row["species"]
        status = row["status"]
        caretaker = row["caretaker"]

        species_index = dict_index(species, raw_species)
        status_index = dict_index(statuses, status)
        caretaker_index = dict_index(caretakers, caretaker)

        latitudes.append(row["lat"])
        longitudes.append(row["lng"])
        species_indices.append(species_index)
        status_indices.append(status_index)
        caretaker_indices.append(caretaker_index)
        dbh_values.append(row["dbh"])
        addresses.append(row["address"])
        tree_ids.append(row["id"])

    return {
        "source": CSV_PATH.name,
        "sourceRows": source_rows,
        "neighborhood": neighborhood["name"],
        "slug": neighborhood["slug"],
        "treeCount": len(latitudes),
        "scale": 1_000_000,
        "dbhScale": 10,
        "species": list(species.keys()),
        "statuses": list(statuses.keys()),
        "caretakers": list(caretakers.keys()),
        "topSpecies": neighborhood["speciesCounts"].most_common(10),
        "topStatuses": neighborhood["statusCounts"].most_common(8),
        "topCaretakers": neighborhood["caretakerCounts"].most_common(8),
        "lat": latitudes,
        "lng": longitudes,
        "sp": species_indices,
        "st": status_indices,
        "ca": caretaker_indices,
        "dbh": dbh_values,
        "addr": addresses,
        "id": tree_ids,
    }


def main():
    neighborhoods = load_neighborhoods()
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
    unassigned_rows = 0

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
            packed_row = {
                "lat": round(lat * 1_000_000),
                "lng": round(lng * 1_000_000),
                "species": raw_species,
                "status": status,
                "caretaker": caretaker,
                "dbh": round(dbh * 10),
                "address": address,
                "id": clean(row["TreeID"]),
            }

            neighborhood = find_neighborhood(lat, lng, neighborhoods)
            if neighborhood:
                neighborhood["rows"].append(packed_row)
                neighborhood["speciesCounts"][raw_species] += 1
                neighborhood["statusCounts"][status] += 1
                neighborhood["caretakerCounts"][caretaker] += 1
            else:
                unassigned_rows += 1

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

    TREE_DATA_DIR.mkdir(exist_ok=True)
    for neighborhood in neighborhoods:
        payload = build_tree_payload(total_rows, neighborhood)
        out_path = TREE_DATA_DIR / f"{neighborhood['slug']}.json"
        with out_path.open("w", encoding="utf-8") as file:
            json.dump(payload, file, separators=(",", ":"))

    neighborhood_features = []
    for neighborhood in neighborhoods:
        neighborhood_features.append({
            "type": "Feature",
            "properties": {
                "name": neighborhood["name"],
                "slug": neighborhood["slug"],
                "treeCount": len(neighborhood["rows"]),
            },
            "geometry": simplify_geometry(neighborhood["geometry"], MAP_SIMPLIFY_TOLERANCE),
        })

    with NEIGHBORHOODS_MAP_OUT_PATH.open("w", encoding="utf-8") as file:
        json.dump({
            "type": "FeatureCollection",
            "features": neighborhood_features,
        }, file, separators=(",", ":"))

    with SUMMARY_OUT_PATH.open("w", encoding="utf-8") as file:
        json.dump({
            "source": CSV_PATH.name,
            "sourceRows": total_rows,
            "treeCount": len(latitudes),
            "assignedTreeCount": sum(len(neighborhood["rows"]) for neighborhood in neighborhoods),
            "unassignedTreeCount": unassigned_rows,
            "neighborhoodCount": len(neighborhoods),
            "speciesCount": len(species),
            "neighborhoods": [
                {
                    "name": neighborhood["name"],
                    "slug": neighborhood["slug"],
                    "treeCount": len(neighborhood["rows"]),
                }
                for neighborhood in neighborhoods
            ],
        }, file, separators=(",", ":"))

    print(
        f"Wrote {MAP_OUT_PATH}, {DETAILS_OUT_PATH}, {NEIGHBORHOODS_MAP_OUT_PATH}, "
        f"{SUMMARY_OUT_PATH}, and {len(neighborhoods)} neighborhood files with "
        f"{len(latitudes):,} trees from {total_rows:,} CSV rows "
        f"({unassigned_rows:,} outside neighborhood polygons)"
    )


if __name__ == "__main__":
    main()
