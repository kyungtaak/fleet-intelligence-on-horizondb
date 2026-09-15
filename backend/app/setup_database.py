import argparse
from contextlib import nullcontext
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import psycopg
from psycopg.types.json import Jsonb

from app.config import Settings
from app.embeddings import (
    DATABASE_EMBEDDING_SQL,
    EMBEDDING_DIMENSIONS,
    embedding_client,
    model_registry_endpoint,
    openai_base_url,
    serialize_embeddings,
    validate_vector_text,
)
from app.models import Shipment
from app.region_boundaries import load_region_boundaries
from app.sample_data import build_sample_shipments

SCHEMA_PATH = Path(__file__).parents[2] / "database" / "schema.sql"
PIPELINE_NAME = "horizon_ship_shipment_embeddings"

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
LEFT JOIN horizon_ship.shipment_embeddings AS embedding
    ON embedding.shipment_id = shipment.id
WHERE embedding.shipment_id IS NULL
ORDER BY shipment_number
LIMIT %s
FOR UPDATE OF shipment;
"""

PRIMARY_INDEX_SQL = """
DROP INDEX IF EXISTS horizon_ship.shipments_embedding_diskann_idx;
DROP INDEX IF EXISTS horizon_ship.shipment_embeddings_diskann_idx;

CREATE INDEX shipment_embeddings_diskann_idx
    ON horizon_ship.shipment_embeddings
    USING diskann (embedding vector_cosine_ops)
    WITH (
        spherical_quantized = true,
        sq_bits = 4,
        sq_training_samples = 25000
    );

ANALYZE horizon_ship.shipment_embeddings;
"""

PIPELINE_SINK_ACTION = """DO UPDATE SET
    embedding_input = EXCLUDED.embedding_input,
    content_version = EXCLUDED.content_version,
    updated_at = EXCLUDED.updated_at,
    metadata = EXCLUDED.metadata,
    embedding = EXCLUDED.embedding"""

CREATE_PIPELINE_SQL = """
SELECT ai.create_pipeline(
    name => %s,
    source => ai.table_source(
        table_name => 'shipment_embedding_jobs',
        schema_name => 'horizon_ship',
        incremental_column => 'updated_at'
    ),
    steps => ARRAY[
        ai.embed(
            input => 'embedding_input',
            model => %s,
            dimensions => 1536
        )
    ],
    trigger => 'on_change',
    sink => ai.table_sink(
        table_name => 'shipment_embeddings',
        schema_name => 'horizon_ship',
        on_conflict => ARRAY['shipment_id'],
        on_conflict_action => %s
    )
);
"""

CREATE_ENQUEUE_TRIGGER_SQL = """
DROP TRIGGER IF EXISTS shipments_enqueue_embedding
ON horizon_ship.shipments;

CREATE TRIGGER shipments_enqueue_embedding
AFTER INSERT OR UPDATE OF
    title,
    description,
    origin_name,
    destination_name,
    current_location_name,
    status,
    metadata
ON horizon_ship.shipments
FOR EACH ROW
EXECUTE FUNCTION horizon_ship.enqueue_shipment_embedding();
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


def configure_pipeline_model(
    connection: psycopg.Connection[Any],
    settings: Settings,
) -> None:
    configure_model(connection, settings, settings.embedding_model_alias, settings.azure_embed_deployment)


def configure_model(
    connection: psycopg.Connection[Any], settings: Settings, alias: str, deployment: str,
) -> None:
    if not settings.azure_openai_key:
        raise RuntimeError(
            "AZURE_OPENAI_KEY is required to register the HorizonDB pipeline model"
        )

    expected = (
        alias,
        model_registry_endpoint(settings.azure_openai_endpoint),
        deployment,
        deployment,
        "subscription-key",
    )
    with connection.cursor() as cursor:
        cursor.execute(
            """
SELECT alias, endpoint, deployment_name, model_name, auth_type
FROM model_registry.model_list_all()
WHERE alias = %s;
""",
            (alias,),
        )
        current = cursor.fetchone()
        if current is None:
            cursor.execute(
                """
SELECT model_registry.model_add(
    p_alias => %s,
    p_endpoint => %s,
    p_deployment_name => %s,
    p_model_name => %s,
    p_api_version => NULL,
    p_auth_type => %s,
    p_endpoint_key => %s
);
""",
                (*expected, settings.azure_openai_key),
            )
            return
        if tuple(current) != expected:
            raise RuntimeError(
                f"Model alias {alias!r} is registered "
                "with different nonsecret metadata"
            )
        cursor.execute(
            "SELECT model_registry.model_key_update(%s, %s);",
            (alias, settings.azure_openai_key),
        )


def configure_chat_model(connection: psycopg.Connection[Any], settings: Settings) -> None:
    configure_model(connection, settings, settings.chat_model_alias, settings.azure_openai_deployment)


def migrate_legacy_embeddings(connection: psycopg.Connection[Any]) -> int:
    cursor = connection.execute(
        """
SELECT EXISTS (
    SELECT 1
    FROM information_schema.columns
    WHERE table_schema = 'horizon_ship'
        AND table_name = 'shipments'
        AND column_name = 'embedding'
);
"""
    )
    if not cursor.fetchone()[0]:
        return 0
    cursor = connection.execute(
        """
INSERT INTO horizon_ship.shipment_embeddings (
    shipment_id,
    embedding_input,
    content_version,
    updated_at,
    metadata,
    embedding
)
SELECT
    shipment.id,
    concat_ws(
        ' ',
        shipment.title,
        shipment.description,
        shipment.origin_name,
        shipment.destination_name,
        shipment.current_location_name,
        shipment.status,
        shipment.metadata::text
    ),
    1,
    shipment.updated_at,
    jsonb_build_object('shipment_number', shipment.shipment_number),
    shipment.embedding
FROM horizon_ship.shipments AS shipment
WHERE shipment.embedding IS NOT NULL
ON CONFLICT (shipment_id) DO NOTHING;
"""
    )
    return cursor.rowcount


def backfill_embeddings(
    connection: psycopg.Connection[Any],
    settings: Settings,
) -> int:
    embedded = 0
    with (embedding_client(settings) if settings.embedding_provider == "azure_openai" else nullcontext()) as client:
        while True:
            with connection.cursor() as cursor:
                cursor.execute(EMBED_BATCH_SQL, (settings.embedding_batch_size,))
                batch = cursor.fetchall()
                if not batch:
                    return embedded
                if client is None:
                    vectors = []
                    for row in batch:
                        cursor.execute(DATABASE_EMBEDDING_SQL, (settings.embedding_model_alias, row[1]))
                        vectors.append(validate_vector_text(cursor.fetchone()[0]))
                else:
                    response = client.embeddings.create(
                        model=settings.azure_embed_deployment,
                        input=[row[1] for row in batch],
                        dimensions=EMBEDDING_DIMENSIONS,
                        encoding_format="float",
                    )
                    vectors = serialize_embeddings(response, len(batch))
                cursor.executemany(
                    """
INSERT INTO horizon_ship.shipment_embeddings (
    shipment_id,
    embedding_input,
    content_version,
    updated_at,
    metadata,
    embedding
)
SELECT
    shipment.id,
    %s,
    1,
    shipment.updated_at,
    jsonb_build_object('shipment_number', shipment.shipment_number),
    %s::public.vector(1536)
FROM horizon_ship.shipments AS shipment
WHERE shipment.id = %s
ON CONFLICT (shipment_id) DO UPDATE SET
    embedding_input = EXCLUDED.embedding_input,
    content_version = EXCLUDED.content_version,
    updated_at = EXCLUDED.updated_at,
    metadata = EXCLUDED.metadata,
    embedding = EXCLUDED.embedding;
""",
                    [
                        (row[1], vector, row[0])
                        for vector, row in zip(vectors, batch, strict=True)
                    ],
                )
            embedded += len(batch)
            if len(batch) < settings.embedding_batch_size:
                return embedded


def database_counts(connection: psycopg.Connection[Any]) -> tuple[int, int]:
    cursor = connection.execute(
        """
SELECT count(*), count(embedding.embedding)
FROM horizon_ship.shipments AS shipment
LEFT JOIN horizon_ship.shipment_embeddings AS embedding
    ON embedding.shipment_id = shipment.id;
"""
    )
    shipment_count, embedding_count = cursor.fetchone()
    return int(shipment_count), int(embedding_count)


def configure_embedding_pipeline(
    connection: psycopg.Connection[Any],
    settings: Settings,
) -> bool:
    cursor = connection.execute(
        "SELECT source_config, steps, sink_config, trigger_type, paused "
        "FROM ai.pipelines WHERE name = %s;",
        (PIPELINE_NAME,),
    )
    current = cursor.fetchone()
    if current is None:
        connection.execute(
            CREATE_PIPELINE_SQL,
            (PIPELINE_NAME, settings.embedding_model_alias, PIPELINE_SINK_ACTION),
        )
        created = True
    else:
        source, steps, sink, trigger_type, paused = current
        valid = (
            source.get("schema_name") == "horizon_ship"
            and source.get("table_name") == "shipment_embedding_jobs"
            and source.get("incremental_column") == "updated_at"
            and len(steps) == 1
            and steps[0].get("step") == "embed"
            and steps[0].get("column") == "embedding_input"
            and steps[0].get("model") == settings.embedding_model_alias
            and steps[0].get("dimensions") == EMBEDDING_DIMENSIONS
            and sink.get("schema_name") == "horizon_ship"
            and sink.get("table_name") == "shipment_embeddings"
            and sink.get("on_conflict") == ["shipment_id"]
            and sink.get("on_conflict_action") == PIPELINE_SINK_ACTION
            and trigger_type == "on_change"
        )
        if not valid:
            raise RuntimeError(
                f"AI pipeline {PIPELINE_NAME!r} exists with a different definition"
            )
        if paused:
            connection.execute("SELECT ai.resume(%s);", (PIPELINE_NAME,))
        created = False
    connection.execute(CREATE_ENQUEUE_TRIGGER_SQL, prepare=False)
    return created


def remove_legacy_embedding_column(connection: psycopg.Connection[Any]) -> None:
    connection.execute(
        """
DROP INDEX IF EXISTS horizon_ship.shipments_embedding_diskann_idx;
ALTER TABLE horizon_ship.shipments DROP COLUMN IF EXISTS embedding;
""",
        prepare=False,
    )


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
        configure_pipeline_model(connection, settings)
        if settings.chat_provider == "horizondb":
            configure_chat_model(connection, settings)
        load_region_boundaries(connection)
        seed_shipments(connection)

        configuration_changed = configure_embeddings(connection, settings)
        migrate_legacy_embeddings(connection)
        if configuration_changed or force_embeddings:
            connection.execute("DELETE FROM horizon_ship.shipment_embeddings;")
        backfill_embeddings(connection, settings)

        shipment_count, embedding_count = database_counts(connection)
        primary_index_ready = shipment_count > 0 and shipment_count == embedding_count
        if not primary_index_ready:
            raise RuntimeError(
                "Azure embedding backfill is incomplete: "
                f"{embedding_count}/{shipment_count} shipments embedded"
            )
        connection.execute(PRIMARY_INDEX_SQL, prepare=False)
        remove_legacy_embedding_column(connection)
        configure_embedding_pipeline(connection, settings)

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
        "--models-only",
        action="store_true",
        help="Register or verify model aliases without seeding data or rebuilding indexes.",
    )
    parser.add_argument(
        "--force-embeddings",
        action="store_true",
        help="Regenerate every Azure OpenAI embedding before rebuilding DiskANN.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if args.models_only:
        settings = Settings()
        settings.validate_live_configuration()
        with psycopg.connect(settings.database_conninfo, connect_timeout=10) as connection:
            configure_pipeline_model(connection, settings)
            if settings.chat_provider == "horizondb":
                configure_chat_model(connection, settings)
        print("HorizonDB model aliases are ready; shipment data was not changed.")
        return
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