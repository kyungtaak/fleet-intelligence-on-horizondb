from typing import Any, Self

from app.config import Settings
from app.sample_data import build_sample_shipments
from app.setup_database import (
    MODEL_ADD_SQL,
    PRIMARY_INDEX_SQL,
    register_embedding_model,
    shipment_parameters,
)


class RecordingCursor:
    def __init__(self, lookup_result: tuple[str, ...] | None = None) -> None:
        self.lookup_result = lookup_result
        self.calls: list[tuple[str, tuple[Any, ...] | None]] = []

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *_: object) -> None:
        return None

    def execute(
        self,
        query: str,
        parameters: tuple[Any, ...] | None = None,
    ) -> None:
        self.calls.append((query, parameters))

    def fetchone(self) -> tuple[str, ...] | None:
        return self.lookup_result


class RecordingConnection:
    def __init__(self, cursor: RecordingCursor) -> None:
        self.recording_cursor = cursor

    def cursor(self) -> RecordingCursor:
        return self.recording_cursor


def test_model_registration_binds_the_subscription_key() -> None:
    cursor = RecordingCursor()
    connection = RecordingConnection(cursor)
    settings = Settings(_env_file=None, azure_openai_key="bound-only-test-key")

    changed = register_embedding_model(connection, settings)  # type: ignore[arg-type]

    assert changed is True
    registration_query, parameters = cursor.calls[-1]
    assert registration_query == MODEL_ADD_SQL
    assert parameters is not None
    assert parameters[-1] == "bound-only-test-key"
    assert "bound-only-test-key" not in registration_query
    assert parameters[1] == "https://jfrost-openai-002.openai.azure.com/"


def test_seed_parameters_use_postgis_longitude_latitude_order() -> None:
    shipment = build_sample_shipments()[0]
    parameters = shipment_parameters(shipment)

    assert parameters[5:7] == (
        shipment.origin.longitude,
        shipment.origin.latitude,
    )
    assert parameters[8:10] == (
        shipment.destination.longitude,
        shipment.destination.latitude,
    )
    assert parameters[11:13] == (
        shipment.current_position.longitude,
        shipment.current_position.latitude,
    )


def test_primary_diskann_index_uses_spherical_quantization() -> None:
    assert "USING diskann (embedding vector_cosine_ops)" in PRIMARY_INDEX_SQL
    assert "spherical_quantized = true" in PRIMARY_INDEX_SQL
    assert "sq_bits = 4" in PRIMARY_INDEX_SQL
    assert "sq_training_samples = 25000" in PRIMARY_INDEX_SQL