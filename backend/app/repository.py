from collections.abc import Mapping
from time import monotonic
from typing import Any, Protocol

from psycopg import AsyncConnection
from psycopg.rows import dict_row
from psycopg_pool import AsyncConnectionPool

from app.config import Settings
from app.embeddings import (
    EMBEDDING_DIMENSIONS,
    async_embedding_client,
    openai_base_url,
    serialize_embeddings,
)
from app.models import (
    Coordinate,
    DatabaseCapabilities,
    Shipment,
    ShipmentFilters,
    ShipmentSearchResult,
    ShipmentStats,
    ShipmentStatus,
    StatusCount,
)
from app.progress import report_progress
from app.region_boundaries import REGION_NAMES
from app.search_locations import LOCATION_COORDINATES, validate_filters

DISKANN_SESSION_SQL = """
SET SESSION diskann.iterative_search TO 'strict_order';
SET SESSION diskann.enable_filter_hook TO 'true';
SET SESSION diskann.selectivity_min TO '0.0';
SET SESSION diskann.selectivity_threshold TO '1.0';
SET SESSION diskann.filtering_beta TO 0.85;
SET SESSION diskann.l_value_is TO 300;
"""


async def configure_search_connection(connection: AsyncConnection[Any]) -> None:
    async with connection.transaction():
        await connection.execute(DISKANN_SESSION_SQL, prepare=False)


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

    async def search_shipments(
        self, filters: ShipmentFilters, limit: int,
    ) -> ShipmentSearchResult: ...

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
            configure=configure_search_connection,
            kwargs={"row_factory": dict_row},
        )
        self._connect_timeout = settings.database_connect_timeout_seconds
        self._model_alias = settings.embedding_model_alias
        self._settings = settings

    async def open(self) -> None:
        await self._pool.open(wait=True, timeout=self._connect_timeout)
        await self._validate_search_readiness()
        async with self._pool.connection() as connection:
            cursor = await connection.execute(
                "SELECT name FROM horizon_ship.region_boundaries;"
            )
            rows = await cursor.fetchall()
        if set(REGION_NAMES) - {row["name"] for row in rows}:
            raise RuntimeError("Region boundaries are incomplete; run python -m app.region_boundaries")

    async def close(self) -> None:
        await self._pool.close()

    async def _validate_search_readiness(self) -> None:
        query = """
SELECT
	count(*) AS shipment_count,
	count(embedding) AS embedding_count,
	EXISTS (
		SELECT 1
        FROM horizon_ship.embedding_configuration
        WHERE singleton = true AND endpoint = %s AND deployment = %s AND dimensions = %s
    ) AS configuration_matches,
	to_regclass('horizon_ship.shipments_embedding_diskann_idx') IS NOT NULL
		AS index_ready
FROM horizon_ship.shipments;
"""
        async with self._pool.connection() as connection:
            cursor = await connection.execute(query, (
                openai_base_url(self._settings.azure_openai_endpoint),
                self._settings.azure_embed_deployment,
                EMBEDDING_DIMENSIONS,
            ))
            row = await cursor.fetchone()
        ready = bool(
            row["shipment_count"]
            and row["shipment_count"] == row["embedding_count"]
            and row["configuration_matches"]
            and row["index_ready"]
        )
        if not ready:
            raise RuntimeError(
                "Live semantic search is not ready: "
                f"{row['embedding_count']}/{row['shipment_count']} Azure embeddings, "
                f"embedding configuration matches={row['configuration_matches']}, "
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
        return await self._search_rows(ShipmentFilters(cargo_query=query, status=status), limit)

    async def search_shipments(
        self, filters: ShipmentFilters, limit: int,
    ) -> ShipmentSearchResult:
        validate_filters(filters)
        rows = await self._search_rows(filters, limit + 1)
        exact_conditions = any((
            filters.status, filters.shipment_number, filters.origin_region,
            filters.destination_region, filters.origin_name, filters.destination_name,
            filters.nearby_location,
        ))
        mode = (
            "hybrid" if filters.cargo_query and exact_conditions
            else "diskann_cosine" if filters.cargo_query
            else "gis" if any((filters.nearby_location, filters.origin_region, filters.destination_region))
            else "sql"
        )
        return ShipmentSearchResult(
            shipments=rows[:limit], search_mode=mode,
            has_more=len(rows) > limit, applied_filters=filters,
        )

    async def _search_rows(self, filters: ShipmentFilters, limit: int) -> list[Shipment]:
        validate_filters(filters)
        parameters: list[Any] = []
        vector_cte = ""
        vector_join = ""
        similarity = "NULL::double precision"
        ordering = "s.shipment_number"
        if filters.cargo_query:
            report_progress(
                "embedding", "화물 검색어를 임베딩 API에 전달하고 있습니다.",
                embedding_input=filters.cargo_query,
                deployment=self._settings.azure_embed_deployment,
            )
            async with async_embedding_client(self._settings) as client:
                response = await client.embeddings.create(
                    model=self._settings.azure_embed_deployment,
                    input=[filters.cargo_query],
                    dimensions=EMBEDDING_DIMENSIONS,
                    encoding_format="float",
                )
            parameters.append(serialize_embeddings(response, 1)[0])
            report_progress("embedding_ready", "검색어 벡터를 생성했습니다.", dimensions=EMBEDDING_DIMENSIONS)
            vector_cte = "WITH query_vector AS (SELECT %s::public.vector(1536) AS embedding)"
            vector_join = "CROSS JOIN query_vector"
            similarity = "1 - (s.embedding <=> query_vector.embedding)"
            ordering = "s.embedding <=> query_vector.embedding"

        status_value = filters.status.value if filters.status else None
        conditions = ["(%s::text IS NULL OR s.status = %s)"]
        parameters.extend((status_value, status_value))
        for column, value in (
            ("shipment_number", filters.shipment_number),
            ("origin_name", filters.origin_name),
            ("destination_name", filters.destination_name),
        ):
            if value is not None:
                conditions.append(f"s.{column} = %s")
                parameters.append(value)
        for column, region in (
            ("origin_position", filters.origin_region),
            ("destination_position", filters.destination_region),
        ):
            if region is not None:
                conditions.append(
                    "EXISTS (SELECT 1 FROM horizon_ship.region_boundaries AS region "
                    f"WHERE region.name = %s AND public.ST_Covers(region.boundary, s.{column}))"
                )
                parameters.append(region)
        if filters.nearby_location:
            coordinate = LOCATION_COORDINATES[filters.nearby_location]
            position = {
                "origin": "origin_position", "destination": "destination_position",
                "current": "current_position",
            }[filters.position_field]
            conditions.append(
                f"public.ST_DWithin(s.{position}::public.geography, "
                "public.ST_SetSRID(public.ST_MakePoint(%s, %s), 4326)::public.geography, %s)"
            )
            parameters.extend((coordinate.longitude, coordinate.latitude, filters.radius_km * 1000))
        parameters.append(limit)
        statement = f"""
{vector_cte}
SELECT
{_SHIPMENT_COLUMNS},
    {similarity} AS similarity
FROM horizon_ship.shipments AS s
{vector_join}
WHERE {' AND '.join(conditions)}
ORDER BY {ordering}
LIMIT %s;
"""
        report_progress("db_connect", "DB 연결 풀에서 연결을 확보하고 있습니다.")
        async with self._pool.connection() as connection, connection.transaction():
            visible_parameters = list(parameters)
            if filters.cargo_query:
                visible_parameters[0] = f"[vector: {EMBEDDING_DIMENSIONS} dimensions; omitted]"
            report_progress(
                "db_query", "배송 조회 SQL을 실행하고 있습니다.",
                sql=statement, parameters=visible_parameters,
            )
            query_started = monotonic()
            cursor = await connection.execute(statement, parameters)
            rows = await cursor.fetchall()
            report_progress(
                "db_result", "DB 조회 결과를 받았습니다.", fetched_count=len(rows),
                duration_ms=round((monotonic() - query_started) * 1000),
            )
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
                "Embeddings are generated by the backend using Azure OpenAI with "
                "Entra ID or an externally configured API key."
            ),
        )
