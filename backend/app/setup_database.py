import argparse
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import psycopg
from psycopg.types.json import Jsonb

from app.config import Settings
from app.embeddings import (
    EMBEDDING_DIMENSIONS,
    embedding_client,
    openai_base_url,
    serialize_embeddings,
)
from app.models import Shipment
from app.sample_data import build_sample_shipments

SCHEMA_PATH = Path(__file__).parents[2] / "database" / "schema.sql"

EMBEDDING_CONFIG_LOOKUP_SQL = """
SELECT endpoint, deployment, dimensions
FROM horizon_ship.embedding_configuration
WHERE singleton = true
FOR UPDATE;
"""

EMBEDDING_CONFIG_SQL = """
INSERT INTO horizon_ship.embedding_configuration (singleton, endpoint, deployment, dimensions)
VALUES (true, %s, %s, %s)
ON CONFLICT (singleton) DO UPDATE SET
    endpoint = EXCLUDED.endpoint,
    deployment = EXCLUDED.deployment,
    dimensions = EXCLUDED.dimensions;
"""

SEED_SQL = """
INSERT INTO horizon_ship.shipments AS existing (
    id,
    shipment_number,
    title,
    description,
    origin_name,
    origin_position,
    destination_name,
    destination_position,
    current_location_name,
    current_position,
    status,
    eta,
    updated_at,
    metadata
)
VALUES (
    %s,
    %s,
    %s,
    %s,
    %s,
    public.ST_SetSRID(public.ST_MakePoint(%s, %s), 4326),
    %s,
    public.ST_SetSRID(public.ST_MakePoint(%s, %s), 4326),
    %s,
    public.ST_SetSRID(public.ST_MakePoint(%s, %s), 4326),
    %s,
    %s,
    %s,
    %s
)
ON CONFLICT (shipment_number) DO UPDATE SET
    title = EXCLUDED.title,
    description = EXCLUDED.description,
    origin_name = EXCLUDED.origin_name,
    origin_position = EXCLUDED.origin_position,
    destination_name = EXCLUDED.destination_name,
    destination_position = EXCLUDED.destination_position,
    current_location_name = EXCLUDED.current_location_name,
    current_position = EXCLUDED.current_position,
    status = EXCLUDED.status,
    eta = EXCLUDED.eta,
    updated_at = EXCLUDED.updated_at,
    embedding = CASE
        WHEN existing.title IS DISTINCT FROM EXCLUDED.title
            OR existing.description IS DISTINCT FROM EXCLUDED.description
            OR existing.origin_name IS DISTINCT FROM EXCLUDED.origin_name
            OR existing.destination_name IS DISTINCT FROM EXCLUDED.destination_name
            OR existing.current_location_name IS DISTINCT FROM EXCLUDED.current_location_name
            OR existing.status IS DISTINCT FROM EXCLUDED.status
            OR existing.metadata IS DISTINCT FROM EXCLUDED.metadata
        THEN NULL
        ELSE existing.embedding
    END,
    metadata = EXCLUDED.metadata;
"""

EMBED_BATCH_SQL = """
SELECT id,
    concat_ws(
        ' ',
        shipment.title,
        shipment.description,
        shipment.origin_name,
        shipment.destination_name,
        shipment.current_location_name,
        shipment.status,
        shipment.metadata::text
    ) AS input
FROM horizon_ship.shipments AS shipment
WHERE embedding IS NULL
ORDER BY shipment_number
LIMIT %s
FOR UPDATE;
"""

PRIMARY_INDEX_SQL = """
DROP INDEX IF EXISTS horizon_ship.shipments_embedding_diskann_idx;

CREATE INDEX shipments_embedding_diskann_idx
    ON horizon_ship.shipments
    USING diskann (embedding vector_cosine_ops)
    WITH (
        spherical_quantized = true,
        sq_bits = 4,
        sq_training_samples = 25000
    );

ANALYZE horizon_ship.shipments;
"""


@dataclass(frozen=True)
class SetupResult:
    shipment_count: int
    embedding_count: int
    embedding_configuration_changed: bool
    primary_index_ready: bool


def shipment_parameters(shipment: Shipment) -> tuple[Any, ...]:
    return (
        shipment.id,
        shipment.shipment_number,
        shipment.title,
        shipment.description,
        shipment.origin_name,
        shipment.origin.longitude,
        shipment.origin.latitude,
        shipment.destination_name,
        shipment.destination.longitude,
        shipment.destination.latitude,
        shipment.current_location_name,
        shipment.current_position.longitude,
        shipment.current_position.latitude,
        shipment.status.value,
        shipment.eta,
        shipment.updated_at,
        Jsonb(shipment.metadata),
    )


def apply_schema(connection: psycopg.Connection[Any]) -> None:
    connection.execute(SCHEMA_PATH.read_text(encoding="utf-8"), prepare=False)


def seed_shipments(connection: psycopg.Connection[Any]) -> int:
    shipments = build_sample_shipments()
    with connection.cursor() as cursor:
        cursor.executemany(SEED_SQL, map(shipment_parameters, shipments))
    return len(shipments)


def configure_embeddings(
    connection: psycopg.Connection[Any],
    settings: Settings,
) -> bool:
    expected = (
        openai_base_url(settings.azure_openai_endpoint),
        settings.azure_embed_deployment,
        EMBEDDING_DIMENSIONS,
    )
    with connection.cursor() as cursor:
        cursor.execute(EMBEDDING_CONFIG_LOOKUP_SQL)
        current = cursor.fetchone()
        if current is not None and tuple(current) == expected:
            return False
        cursor.execute(EMBEDDING_CONFIG_SQL, expected)
    return True


def backfill_embeddings(
    connection: psycopg.Connection[Any],
    settings: Settings,
) -> int:
    embedded = 0
    with embedding_client(settings) as client:
        while True:
            with connection.cursor() as cursor:
                cursor.execute(EMBED_BATCH_SQL, (settings.embedding_batch_size,))
                batch = cursor.fetchall()
                if not batch:
                    return embedded
                response = client.embeddings.create(
                    model=settings.azure_embed_deployment,
                    input=[row[1] for row in batch],
                    dimensions=EMBEDDING_DIMENSIONS,
                    encoding_format="float",
                )
                vectors = serialize_embeddings(response, len(batch))
                cursor.executemany(
                    "UPDATE horizon_ship.shipments SET embedding = %s::public.vector(1536) "
                    "WHERE id = %s;",
                    [(vector, row[0]) for vector, row in zip(vectors, batch, strict=True)],
                )
            embedded += len(batch)
            if len(batch) < settings.embedding_batch_size:
                return embedded


def database_counts(connection: psycopg.Connection[Any]) -> tuple[int, int]:
    cursor = connection.execute(
        "SELECT count(*), count(embedding) FROM horizon_ship.shipments;"
    )
    shipment_count, embedding_count = cursor.fetchone()
    return int(shipment_count), int(embedding_count)


def setup_database(
    settings: Settings,
    *,
    force_embeddings: bool = False,
) -> SetupResult:
    settings.validate_live_configuration()
    database_conninfo = settings.database_conninfo
    if database_conninfo is None:
        raise RuntimeError("HorizonDB connection settings are required")

    with psycopg.connect(database_conninfo) as connection:
        apply_schema(connection)
        seed_shipments(connection)

        configuration_changed = configure_embeddings(connection, settings)
        if configuration_changed or force_embeddings:
            connection.execute("UPDATE horizon_ship.shipments SET embedding = NULL;")
        backfill_embeddings(connection, settings)

        shipment_count, embedding_count = database_counts(connection)
        primary_index_ready = shipment_count > 0 and shipment_count == embedding_count
        if not primary_index_ready:
            raise RuntimeError(
                "Azure embedding backfill is incomplete: "
                f"{embedding_count}/{shipment_count} shipments embedded"
            )
        connection.execute(PRIMARY_INDEX_SQL, prepare=False)

    return SetupResult(
        shipment_count=shipment_count,
        embedding_count=embedding_count,
        embedding_configuration_changed=configuration_changed,
        primary_index_ready=primary_index_ready,
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Create and populate the HorizonShip HorizonDB schema."
    )
    parser.add_argument(
        "--force-embeddings",
        action="store_true",
        help="Regenerate every Azure OpenAI embedding before rebuilding DiskANN.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    result = setup_database(
        Settings(),
        force_embeddings=args.force_embeddings,
    )
    print(
        f"HorizonShip ready: {result.shipment_count} shipments, "
        f"{result.embedding_count} Azure embeddings, "
        f"primary DiskANN index: {'ready' if result.primary_index_ready else 'not built'}"
    )


if __name__ == "__main__":
    main()