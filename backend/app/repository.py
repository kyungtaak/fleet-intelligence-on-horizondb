from collections.abc import Mapping
from typing import Any, Protocol

from psycopg.rows import dict_row
from psycopg_pool import AsyncConnectionPool

from app.config import Settings
from app.models import (
    Coordinate,
    DatabaseCapabilities,
    Shipment,
    ShipmentStats,
    ShipmentStatus,
    StatusCount,
)

_SHIPMENT_COLUMNS = """
	s.id,
	s.shipment_number,
	s.title,
	s.description,
	s.origin_name,
	public.ST_Y(s.origin_position) AS origin_latitude,
	public.ST_X(s.origin_position) AS origin_longitude,
	s.destination_name,
	public.ST_Y(s.destination_position) AS destination_latitude,
	public.ST_X(s.destination_position) AS destination_longitude,
	s.current_location_name,
	public.ST_Y(s.current_position) AS current_latitude,
	public.ST_X(s.current_position) AS current_longitude,
	s.status,
	s.eta,
	s.updated_at,
	s.metadata
"""


class ShipmentRepository(Protocol):
    mode: str
    search_mode: str

    async def list_shipments(
        self,
        status: ShipmentStatus | None = None,
        search: str | None = None,
    ) -> list[Shipment]: ...

    async def semantic_search(
        self,
        query: str,
        status: ShipmentStatus | None,
        limit: int,
    ) -> list[Shipment]: ...

    async def get_shipment(self, shipment_number: str) -> Shipment | None: ...

    async def stats(self) -> ShipmentStats: ...

    async def capabilities(self) -> DatabaseCapabilities: ...


def _row_to_shipment(row: Mapping[str, Any]) -> Shipment:
    similarity = row.get("similarity")
    return Shipment(
        id=row["id"],
        shipment_number=row["shipment_number"],
        title=row["title"],
        description=row["description"],
        origin_name=row["origin_name"],
        origin=Coordinate(
            latitude=float(row["origin_latitude"]),
            longitude=float(row["origin_longitude"]),
        ),
        destination_name=row["destination_name"],
        destination=Coordinate(
            latitude=float(row["destination_latitude"]),
            longitude=float(row["destination_longitude"]),
        ),
        current_location_name=row["current_location_name"],
        current_position=Coordinate(
            latitude=float(row["current_latitude"]),
            longitude=float(row["current_longitude"]),
        ),
        status=ShipmentStatus(row["status"]),
        eta=row["eta"],
        updated_at=row["updated_at"],
        metadata=row["metadata"],
        similarity=round(float(similarity), 4) if similarity is not None else None,
    )


class PostgresShipmentRepository:
    mode = "horizondb"
    search_mode = "diskann_cosine"

    def __init__(self, settings: Settings) -> None:
        if not settings.database_conninfo:
            raise ValueError("HorizonDB connection settings are required")

        self._pool = AsyncConnectionPool(
            conninfo=settings.database_conninfo,
            min_size=settings.database_pool_min_size,
            max_size=settings.database_pool_max_size,
            open=False,
            kwargs={"row_factory": dict_row},
        )
        self._connect_timeout = settings.database_connect_timeout_seconds
        self._model_alias = settings.embedding_model_alias

    async def open(self) -> None:
        await self._pool.open(wait=True, timeout=self._connect_timeout)
        await self._validate_search_readiness()

    async def close(self) -> None:
        await self._pool.close()

    async def _validate_search_readiness(self) -> None:
        query = """
SELECT
	count(*) AS shipment_count,
	count(embedding) AS embedding_count,
	EXISTS (
		SELECT 1
		FROM model_registry.model_list_all()
		WHERE alias = %s
	) AS model_registered,
	to_regclass('horizon_ship.shipments_embedding_diskann_idx') IS NOT NULL
		AS index_ready
FROM horizon_ship.shipments;
"""
        async with self._pool.connection() as connection:
            cursor = await connection.execute(query, (self._model_alias,))
            row = await cursor.fetchone()
        ready = bool(
            row["shipment_count"]
            and row["shipment_count"] == row["embedding_count"]
            and row["model_registered"]
            and row["index_ready"]
        )
        if not ready:
            raise RuntimeError(
                "Live semantic search is not ready: "
                f"{row['embedding_count']}/{row['shipment_count']} Azure embeddings, "
                f"model registered={row['model_registered']}, "
                f"DiskANN index ready={row['index_ready']}"
            )

    async def list_shipments(
        self,
        status: ShipmentStatus | None = None,
        search: str | None = None,
    ) -> list[Shipment]:
        conditions: list[str] = []
        parameters: list[Any] = []

        if status is not None:
            conditions.append("s.status = %s")
            parameters.append(status.value)
        if search and search.strip():
            conditions.append(
                """(
				s.shipment_number ILIKE %s
				OR s.title ILIKE %s
				OR s.description ILIKE %s
				OR s.origin_name ILIKE %s
				OR s.destination_name ILIKE %s
				OR s.current_location_name ILIKE %s
			)"""
            )
            pattern = f"%{search.strip()}%"
            parameters.extend([pattern] * 6)

        where_clause = f"WHERE {' AND '.join(conditions)}" if conditions else ""
        query = f"""
SELECT
{_SHIPMENT_COLUMNS}
FROM horizon_ship.shipments AS s
{where_clause}
ORDER BY s.shipment_number;
"""
        async with self._pool.connection() as connection:
            cursor = await connection.execute(query, parameters)
            rows = await cursor.fetchall()
        return [_row_to_shipment(row) for row in rows]

    async def semantic_search(
        self,
        query: str,
        status: ShipmentStatus | None,
        limit: int,
    ) -> list[Shipment]:
        statement = f"""
WITH query_vector AS (
	SELECT azure_openai.create_embeddings(
		%s,
		%s
	)::public.vector(1536) AS embedding
)
SELECT
{_SHIPMENT_COLUMNS},
	1 - (s.embedding <=> query_vector.embedding) AS similarity
FROM horizon_ship.shipments AS s
CROSS JOIN query_vector
WHERE (%s::text IS NULL OR s.status = %s)
ORDER BY s.embedding <=> query_vector.embedding
LIMIT %s;
"""
        parameters: list[Any] = [self._model_alias, query]
        status_value = status.value if status else None
        parameters.extend((status_value, status_value, limit))
        async with self._pool.connection() as connection, connection.transaction():
            for setting in (
                "SET LOCAL diskann.iterative_search TO 'strict_order'",
                "SET LOCAL diskann.enable_filter_hook TO 'true'",
                "SET LOCAL diskann.selectivity_min TO '0.0'",
                "SET LOCAL diskann.selectivity_threshold TO '1.0'",
                "SET LOCAL diskann.filtering_beta TO 0.85",
                "SET LOCAL diskann.l_value_is TO 300",
            ):
                await connection.execute(setting)
            cursor = await connection.execute(statement, parameters)
            rows = await cursor.fetchall()
        return [_row_to_shipment(row) for row in rows]

    async def get_shipment(self, shipment_number: str) -> Shipment | None:
        query = f"""
SELECT
{_SHIPMENT_COLUMNS}
FROM horizon_ship.shipments AS s
WHERE s.shipment_number = %s;
"""
        async with self._pool.connection() as connection:
            cursor = await connection.execute(query, (shipment_number,))
            row = await cursor.fetchone()
        return _row_to_shipment(row) if row else None

    async def stats(self) -> ShipmentStats:
        query = """
SELECT status, count(*) AS count
FROM horizon_ship.shipments
GROUP BY status
ORDER BY status;
"""
        async with self._pool.connection() as connection:
            cursor = await connection.execute(query)
            rows = await cursor.fetchall()

        counts = {ShipmentStatus(row["status"]): int(row["count"]) for row in rows}
        return ShipmentStats(
            total=sum(counts.values()),
            statuses=[
                StatusCount(status=status, count=counts.get(status, 0))
                for status in ShipmentStatus
            ],
        )

    async def capabilities(self) -> DatabaseCapabilities:
        query = """
SELECT
	(
		SELECT extversion FROM pg_catalog.pg_extension WHERE extname = 'postgis'
	) AS postgis_version,
	(
		SELECT extversion FROM pg_catalog.pg_extension WHERE extname = 'vector'
	) AS vector_version,
	(
		SELECT extversion FROM pg_catalog.pg_extension WHERE extname = 'pg_diskann'
	) AS diskann_version,
    (
        SELECT extversion FROM pg_catalog.pg_extension WHERE extname = 'azure_ai'
    ) AS azure_ai_version,
    count(*) AS shipment_count,
    count(embedding) AS azure_embedding_count
FROM horizon_ship.shipments;
"""
        async with self._pool.connection() as connection:
            cursor = await connection.execute(query)
            row = await cursor.fetchone()

        return DatabaseCapabilities(
            mode=self.mode,
            connected=True,
            postgis_version=row["postgis_version"],
            vector_version=row["vector_version"],
            diskann_version=row["diskann_version"],
            azure_ai_version=row["azure_ai_version"],
            shipment_count=int(row["shipment_count"]),
            azure_embedding_count=int(row["azure_embedding_count"]),
            embedding_mode="azure_openai",
            embedding_model_alias=self._model_alias,
            detail=(
                "Query embeddings are generated in HorizonDB through the azure_ai "
                "model registry."
            ),
        )
