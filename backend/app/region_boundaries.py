import argparse
import hashlib
import json
from pathlib import Path
from typing import Any
from urllib.request import urlopen

import psycopg
from shapely import to_wkb
from shapely.geometry import GeometryCollection, shape

from app.config import Settings

SOURCE_URL = (
    "https://raw.githubusercontent.com/nvkelso/natural-earth-vector/"
    "v5.1.2/geojson/ne_50m_admin_0_countries.geojson"
)
DATA_PATH = Path(__file__).parents[2] / "database" / "region_boundaries.json"
REGION_NAMES = (
    "Asia", "Middle East", "Europe", "North America", "South America", "Africa", "Oceania",
)
MIDDLE_EAST_COUNTRIES = frozenset({
    "BHR", "CYP", "EGY", "IRN", "IRQ", "ISR", "JOR", "KWT", "LBN", "OMN",
    "PSX", "QAT", "SAU", "SYR", "TUR", "ARE", "YEM",
})
REGION_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS horizon_ship.region_boundaries (
    name text PRIMARY KEY,
    boundary public.geometry(MultiPolygon, 4326) NOT NULL,
    source_url text NOT NULL,
    source_sha256 text NOT NULL,
    CHECK (public.ST_IsValid(boundary) AND NOT public.ST_IsEmpty(boundary))
);
"""
REGION_UPSERT_SQL = """
INSERT INTO horizon_ship.region_boundaries (name, boundary, source_url, source_sha256)
SELECT %s,
    public.ST_Multi(public.ST_CollectionExtract(public.ST_UnaryUnion(
        public.ST_MakeValid(public.ST_GeomFromWKB(%s, 4326))
    ), 3)), %s, %s
ON CONFLICT (name) DO UPDATE SET
    boundary = EXCLUDED.boundary,
    source_url = EXCLUDED.source_url,
    source_sha256 = EXCLUDED.source_sha256;
"""


def download_boundaries() -> dict[str, Any]:
    with urlopen(SOURCE_URL, timeout=60) as response:
        source = response.read()
    collection = json.loads(source)
    countries = []
    for feature in collection["features"]:
        properties = feature["properties"]
        regions = []
        if properties["CONTINENT"] in REGION_NAMES:
            regions.append(properties["CONTINENT"])
        if properties["ADM0_A3"] in MIDDLE_EAST_COUNTRIES:
            regions.append("Middle East")
        if regions:
            countries.append({
                "name": properties["ADMIN"], "code": properties["ADM0_A3"],
                "regions": regions, "geometry": feature["geometry"],
            })
    return {
        "source_url": SOURCE_URL, "source_sha256": hashlib.sha256(source).hexdigest(),
        "license": "Public domain", "countries": countries,
    }


def load_region_boundaries(connection: psycopg.Connection[Any]) -> int:
    data = json.loads(DATA_PATH.read_text(encoding="utf-8"))
    region_geometries = {
        region: [country["geometry"] for country in data["countries"] if region in country["regions"]]
        for region in REGION_NAMES
    }
    if any(not geometries for geometries in region_geometries.values()):
        raise ValueError("Every supported region must have boundary geometry")
    connection.execute(REGION_SCHEMA_SQL)
    for region, geometries in region_geometries.items():
        geometry = GeometryCollection([shape(item) for item in geometries])
        connection.execute(REGION_UPSERT_SQL, (
            region, to_wkb(geometry), data["source_url"], data["source_sha256"],
        ))
    return len(region_geometries)


def main() -> None:
    parser = argparse.ArgumentParser(description="Load region boundaries without modifying shipments")
    parser.add_argument("--download", action="store_true", help="Refresh the bundled source data only")
    arguments = parser.parse_args()
    if arguments.download:
        data = download_boundaries()
        DATA_PATH.write_text(json.dumps(data, separators=(",", ":")) + "\n", encoding="utf-8")
        print(f"Saved {len(data['countries'])} countries, {DATA_PATH.stat().st_size} bytes")
        return
    settings = Settings()
    if not settings.database_conninfo:
        raise RuntimeError("HorizonDB connection settings are required")
    with psycopg.connect(settings.database_conninfo) as connection:
        count = load_region_boundaries(connection)
    print(f"Loaded {count} region boundaries; shipments and embeddings unchanged")


if __name__ == "__main__":
    main()