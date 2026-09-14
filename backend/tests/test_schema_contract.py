import json
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from shapely import from_wkb, make_valid, union_all
from shapely.geometry import Point, shape

from app.region_boundaries import (
    DATA_PATH,
    MIDDLE_EAST_COUNTRIES,
    REGION_NAMES,
    SOURCE_URL,
    load_region_boundaries,
)

SCHEMA_PATH = Path(__file__).parents[2] / "database" / "schema.sql"


def test_schema_contains_horizon_embedding_contract() -> None:
    schema = SCHEMA_PATH.read_text(encoding="utf-8")

    assert "CREATE TABLE IF NOT EXISTS horizon_ship.embedding_configuration" in schema
    assert "CREATE EXTENSION IF NOT EXISTS azure_ai" not in schema
    assert "embedding public.vector(1536)" in schema
    assert "CREATE OR REPLACE FUNCTION horizon_ship.demo_embedding" not in schema
    assert "demo_embedding public.vector" not in schema
    assert "USING diskann (demo_embedding vector_cosine_ops)" not in schema
    assert "demo_embedding" not in schema


def test_setup_uses_spherical_quantization_contract() -> None:
    setup_path = Path(__file__).parents[1] / "app" / "setup_database.py"
    setup = setup_path.read_text(encoding="utf-8")
    assert "spherical_quantized = true" in setup
    assert "sq_bits = 4" in setup
    assert "sq_training_samples = 25000" in setup


@pytest.fixture(scope="module")
def boundary_data():
    return json.loads(DATA_PATH.read_text(encoding="utf-8"))


def test_boundary_source_and_country_policy(boundary_data):
    assert boundary_data["source_url"] == SOURCE_URL
    assert len(boundary_data["source_sha256"]) == 64
    assert boundary_data["license"] == "Public domain"
    countries = {country["code"]: country for country in boundary_data["countries"]}
    assert countries["TUR"]["regions"] == ["Asia", "Middle East"]
    assert countries["RUS"]["regions"] == ["Europe"]
    assert countries["EGY"]["regions"] == ["Africa", "Middle East"]
    assert countries["QAT"]["regions"] == ["Asia", "Middle East"]
    assert countries["PSX"]["regions"] == ["Asia", "Middle East"]
    assert {code for code, country in countries.items() if "Middle East" in country["regions"]} == MIDDLE_EAST_COUNTRIES
    assert {region for country in countries.values() for region in country["regions"]} == set(REGION_NAMES)


def test_asia_polygon_covers_coordinates_without_city_catalog(boundary_data):
    countries = [make_valid(shape(country["geometry"])) for country in boundary_data["countries"]
                 if "Asia" in country["regions"]]
    boundary = union_all(countries)
    assert boundary.is_valid
    assert boundary.covers(Point(126.978, 37.5665))
    assert boundary.covers(Point(100.5018, 13.7563))
    assert not boundary.covers(Point(2.3522, 48.8566))
    assert not boundary.covers(Point(150, 0))
    assert boundary.covers(Point(boundary.geoms[0].exterior.coords[0]))


def test_region_loader_binds_wkb_and_does_not_touch_shipments():
    connection = MagicMock()
    assert load_region_boundaries(connection) == len(REGION_NAMES)
    calls = connection.execute.call_args_list
    assert len(calls) == len(REGION_NAMES) + 1
    for call in calls:
        assert "shipments" not in call.args[0]
        assert "embedding" not in call.args[0]
        assert "ST_GeomFromGeoJSON" not in call.args[0]
    for call in calls[1:]:
        statement, parameters = call.args
        assert "ST_GeomFromWKB(%s, 4326)" in statement
        assert parameters[0] in REGION_NAMES
        assert not from_wkb(parameters[1]).is_empty