from pathlib import Path

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