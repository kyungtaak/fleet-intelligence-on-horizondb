import asyncio
import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app
from app.models import ShipmentFilters, ShipmentStatus
from app.progress import report_progress, stream_chat
from app.repository import PostgresShipmentRepository
from app.search_locations import LOCATION_COORDINATES


def make_client(live_settings, fake_repository, fake_agent_client) -> TestClient:
    return TestClient(
        create_app(
            settings=live_settings,
            repository=fake_repository,
            agent_client=fake_agent_client,
        )
    )


def test_health_and_list_endpoints_report_live_capabilities(
    live_settings,
    fake_repository,
    fake_agent_client,
) -> None:
    with make_client(live_settings, fake_repository, fake_agent_client) as client:
        health = client.get("/api/health")
        shipments = client.get("/api/shipments", params={"status": "delayed"})

    assert health.status_code == 200
    assert health.json()["mode"] == "horizondb"
    assert health.json()["shipment_count"] == 24
    assert health.json()["embedding_mode"] == "azure_openai"
    assert health.json()["agent_framework"] is True
    assert health.json()["chat_model"] == "gpt-5.4"
    assert shipments.status_code == 200
    assert {shipment["status"] for shipment in shipments.json()} == {"delayed"}
    assert len(shipments.json()) == 3


def test_chat_stream_returns_progress_then_result(live_settings, fake_repository, fake_agent_client):
    with make_client(live_settings, fake_repository, fake_agent_client) as client:
        response = client.post("/api/chat/stream", json={"query": "medical supplies"})
        invalid = client.post("/api/chat/stream", json={"query": "x"})
    events = [json.loads(line) for line in response.text.splitlines()]
    assert response.headers["content-type"].startswith("application/x-ndjson")
    assert [event.get("stage") for event in events[:-1]] == ["accepted", "agent", "filters", "answer"]
    assert events[-1]["type"] == "result"
    assert events[-1]["result"]["shipments"]
    assert len({event["request_id"] for event in events}) == 1
    assert [event["sequence"] for event in events] == list(range(1, len(events) + 1))
    assert invalid.status_code == 422


async def test_stream_error_does_not_expose_exception():
    async def fail():
        report_progress("db_query", "조회 중", sql="SELECT %s", parameters=["delayed"])
        raise RuntimeError("secret-password-test")
    events = [json.loads(line) async for line in stream_chat(fail)]
    assert events[-1]["type"] == "error"
    assert "secret-password-test" not in json.dumps(events)


async def test_stream_timeout_cancels_work():
    stopped = asyncio.Event()

    async def run():
        try:
            await asyncio.Event().wait()
        finally:
            stopped.set()

    events = [json.loads(line) async for line in stream_chat(run, timeout=0.01)]
    assert stopped.is_set()
    assert events[-1]["type"] == "error"
    assert "초과" in events[-1]["message"]


async def test_stream_close_cancels_work():
    started = asyncio.Event()
    stopped = asyncio.Event()

    async def run():
        started.set()
        try:
            await asyncio.Event().wait()
        finally:
            stopped.set()

    stream = stream_chat(run)
    await anext(stream)
    await started.wait()
    await stream.aclose()
    assert stopped.is_set()


async def test_parallel_streams_do_not_mix_events():
    async def collect(label):
        async def run():
            report_progress("filters", label)
            raise RuntimeError("failure")
        return [json.loads(line) async for line in stream_chat(run)]

    first, second = await asyncio.gather(collect("first"), collect("second"))
    assert first[1]["message"] == "first"
    assert second[1]["message"] == "second"
    assert first[0]["request_id"] != second[0]["request_id"]


def test_semantic_search_and_detail_endpoints(
    live_settings,
    fake_repository,
    fake_agent_client,
) -> None:
    with make_client(live_settings, fake_repository, fake_agent_client) as client:
        response = client.post(
            "/api/search",
            json={"query": "healthcare cargo for clinics", "limit": 5},
        )
        chat = client.post(
            "/api/chat",
            json={"query": "healthcare cargo for clinics", "limit": 5},
        )
        detail = client.get("/api/shipments/ship-0014")

    assert response.status_code == 200
    assert response.json()["search_mode"] == "diskann_cosine"
    assert response.json()["shipments"][0]["shipment_number"] == "SHIP-0014"
    assert chat.status_code == 200
    assert chat.json()["agent_framework"] is True
    assert chat.json()["chat_model"] == "gpt-5.4"
    assert chat.json()["shipments"][0]["shipment_number"] == "SHIP-0014"
    assert chat.json()["answer"].startswith("SHIP-0014")
    assert detail.status_code == 200
    assert detail.json()["title"] == "Hospital Equipment"


def test_unknown_shipment_and_invalid_search_are_rejected(
    live_settings,
    fake_repository,
    fake_agent_client,
) -> None:
    with make_client(live_settings, fake_repository, fake_agent_client) as client:
        missing = client.get("/api/shipments/SHIP-9999")
        invalid = client.post("/api/search", json={"query": "x"})

    assert missing.status_code == 404
    assert invalid.status_code == 422


def test_startup_rejects_missing_live_configuration() -> None:
    app = create_app(settings=Settings(_env_file=None, azure_openai_endpoint=""))

    with (
        pytest.raises(ValueError, match="Live HorizonShip configuration"),
        TestClient(app),
    ):
        pass


def test_startup_allows_entra_authentication(
    live_settings, fake_repository, fake_agent_client,
) -> None:
    settings = live_settings.model_copy(update={"azure_openai_key": None})
    with make_client(settings, fake_repository, fake_agent_client) as client:
        assert client.get("/api/health").status_code == 200


async def test_repository_generates_query_vector_in_backend(live_settings: Settings) -> None:
    with (
        patch("app.repository.AsyncConnectionPool") as pool_factory,
        patch("app.repository.async_embedding_client") as embedding_factory,
    ):
        connection = MagicMock()
        cursor = AsyncMock()
        cursor.fetchall.return_value = []
        connection.execute = AsyncMock(return_value=cursor)
        pool_factory.return_value.connection.return_value.__aenter__.return_value = connection
        client = embedding_factory.return_value.__aenter__.return_value
        client.embeddings.create = AsyncMock(return_value=MagicMock(
            data=[MagicMock(index=0, embedding=[0.1] * 1536)]
        ))
        repository = PostgresShipmentRepository(live_settings)
        assert await repository.semantic_search("cargo", ShipmentStatus("delayed"), 5) == []
        client.embeddings.create.assert_awaited_once_with(
            model=live_settings.azure_embed_deployment,
            input=["cargo"], dimensions=1536, encoding_format="float",
        )
        statement, parameters = connection.execute.call_args.args
        assert "azure_openai.create_embeddings" not in statement
        assert "ORDER BY s.embedding <=> query_vector.embedding" in statement
        assert json.loads(parameters[0]) == [0.1] * 1536
        assert parameters[1:] == ["delayed", "delayed", 5]
        assert connection.execute.await_count == 1


async def test_pool_configures_each_new_connection_once(live_settings):
    with patch("app.repository.AsyncConnectionPool") as pool_factory:
        PostgresShipmentRepository(live_settings)
        configure = pool_factory.call_args.kwargs["configure"]
        for _ in range(2):
            connection = MagicMock()
            connection.execute = AsyncMock()
            await configure(connection)
            connection.transaction.assert_called_once_with()
            connection.transaction.return_value.__aenter__.assert_awaited_once()
            connection.transaction.return_value.__aexit__.assert_awaited_once_with(None, None, None)
            connection.execute.assert_awaited_once()
            statement = connection.execute.call_args.args[0]
            assert statement.count("SET SESSION diskann.") == 6
            assert "SET LOCAL" not in statement
            assert connection.execute.call_args.kwargs == {"prepare": False}


@pytest.mark.parametrize("configuration_matches", [True, False])
async def test_repository_checks_embedding_configuration(
    live_settings: Settings, configuration_matches: bool,
) -> None:
    with patch("app.repository.AsyncConnectionPool") as pool_factory:
        connection = AsyncMock()
        connection.execute.return_value.fetchone.return_value = {
            "shipment_count": 24, "embedding_count": 24,
            "index_ready": True, "configuration_matches": configuration_matches,
        }
        pool_factory.return_value.connection.return_value.__aenter__.return_value = connection
        repository = PostgresShipmentRepository(live_settings)
        if configuration_matches:
            await repository._validate_search_readiness()
        else:
            with pytest.raises(RuntimeError, match="configuration matches=False"):
                await repository._validate_search_readiness()
        statement, parameters = connection.execute.call_args.args
        assert "model_registry" not in statement
        assert parameters == (
            "https://example.openai.azure.com/openai/v1/",
            live_settings.azure_embed_deployment, 1536,
        )


@pytest.mark.parametrize("filters, mode, sql_fragment", [
    (ShipmentFilters(status="delayed"), "sql", "s.status = %s"),
    (ShipmentFilters(origin_region="Asia"), "gis", "ST_Covers(region.boundary, s.origin_position)"),
    (ShipmentFilters(destination_region="Asia"), "gis", "ST_Covers(region.boundary, s.destination_position)"),
    (ShipmentFilters(nearby_location="Busan, South Korea", radius_km=100), "gis", "ST_DWithin"),
])
async def test_exact_search_skips_embeddings(live_settings, filters, mode, sql_fragment):
    with (
        patch("app.repository.AsyncConnectionPool") as pool_factory,
        patch("app.repository.async_embedding_client") as embedding_factory,
    ):
        connection = MagicMock()
        cursor = AsyncMock()
        cursor.fetchall.return_value = []
        connection.execute = AsyncMock(return_value=cursor)
        pool_factory.return_value.connection.return_value.__aenter__.return_value = connection
        result = await PostgresShipmentRepository(live_settings).search_shipments(filters, 8)
        embedding_factory.assert_not_called()
        assert result.search_mode == mode
        assert result.shipments == []
        assert not result.has_more
        statement, parameters = connection.execute.call_args.args
        assert sql_fragment in statement
        assert "ANY" not in statement
        assert "<=>" not in statement
        assert parameters[-1] == 9
        assert connection.execute.await_count == 1
        if filters.nearby_location:
            assert parameters[-4:-1] == [129.0756, 35.1796, 100000]


@pytest.mark.parametrize("values", [
    {"origin_region": "Atlantis"},
    {"origin_name": "Unknown city"},
    {"nearby_location": "Busan, South Korea"},
    {"radius_km": 100},
    {"cargo_query": "   "},
    {"position_field": "origin"},
    {"sort_by": "destination_distance", "cargo_query": "medical supplies"},
    {"sort_by": "eta"},
    {"result_limit": 0},
    {"result_limit": 25},
])
async def test_invalid_conditions_fail_before_search(live_settings, values):
    with (
        patch("app.repository.AsyncConnectionPool") as pool_factory,
        patch("app.repository.async_embedding_client") as embedding_factory,
    ):
        with pytest.raises(ValueError):
            await PostgresShipmentRepository(live_settings).search_shipments(
                ShipmentFilters(**values), 8,
            )
        pool_factory.return_value.connection.assert_not_called()
        embedding_factory.assert_not_called()


def test_filter_schema_rejects_unknown_conditions():
    with pytest.raises(ValueError):
        ShipmentFilters(origin_country="China")


def test_location_catalog_covers_sample_endpoints(fake_repository):
    for shipment in fake_repository._shipments:
        assert shipment.origin_name in LOCATION_COORDINATES
        assert shipment.destination_name in LOCATION_COORDINATES
    assert "North Pacific Ocean" not in LOCATION_COORDINATES


async def test_more_results_are_not_claimed_as_complete(live_settings, fake_repository):
    with patch("app.repository.AsyncConnectionPool"):
        repository = PostgresShipmentRepository(live_settings)
        repository._search_rows = AsyncMock(return_value=fake_repository._shipments[:9])
        result = await repository.search_shipments(ShipmentFilters(origin_region="Asia"), 8)
        assert len(result.shipments) == 8
        assert result.has_more is True
        assert result.search_mode == "gis"


@pytest.mark.parametrize("status", [None, "in_transit", "delivered"])
async def test_destination_distance_sort_and_limit(live_settings, status):
    with (
        patch("app.repository.AsyncConnectionPool") as pool_factory,
        patch("app.repository.async_embedding_client") as embedding_factory,
    ):
        connection = MagicMock()
        cursor = AsyncMock()
        cursor.fetchall.return_value = []
        connection.execute = AsyncMock(return_value=cursor)
        pool_factory.return_value.connection.return_value.__aenter__.return_value = connection
        filters = ShipmentFilters(
            sort_by="destination_distance", result_limit=2, status=status,
            destination_name="Rotterdam, Netherlands",
        )
        result = await PostgresShipmentRepository(live_settings).search_shipments(filters, 8)
        assert result.search_mode == "gis"
        embedding_factory.assert_not_called()
        connection.execute.assert_awaited_once()
        statement, parameters = connection.execute.call_args.args
        assert "ST_Distance(s.current_position::public.geography, s.destination_position::public.geography) / 1000.0" in statement
        assert "ORDER BY remaining_distance_km ASC, s.shipment_number ASC" in statement
        assert "s.destination_name = %s" in statement
        assert "<=>" not in statement
        expected = [status, status]
        if status is None:
            assert "s.status <> %s" in statement
            expected.append("delivered")
        else:
            assert "s.status <> %s" not in statement
        assert parameters == [*expected, "Rotterdam, Netherlands", 3]


@pytest.mark.parametrize("requested, expected", [(2, 2), (24, 8)])
async def test_requested_count_respects_api_limit(live_settings, fake_repository, requested, expected):
    with patch("app.repository.AsyncConnectionPool"):
        repository = PostgresShipmentRepository(live_settings)
        repository._search_rows = AsyncMock(return_value=fake_repository._shipments[:expected + 1])
        filters = ShipmentFilters(sort_by="destination_distance", result_limit=requested)
        result = await repository.search_shipments(filters, 8)
        repository._search_rows.assert_awaited_once_with(filters, expected + 1)
        assert len(result.shipments) == expected
        assert result.has_more


async def test_hybrid_search_keeps_exact_conditions_in_sql(live_settings):
    with (
        patch("app.repository.AsyncConnectionPool") as pool_factory,
        patch("app.repository.async_embedding_client") as embedding_factory,
        patch("app.repository.report_progress") as progress,
    ):
        connection = MagicMock()
        cursor = AsyncMock()
        cursor.fetchall.return_value = []
        connection.execute = AsyncMock(return_value=cursor)
        pool_factory.return_value.connection.return_value.__aenter__.return_value = connection
        client = embedding_factory.return_value.__aenter__.return_value
        client.embeddings.create = AsyncMock(return_value=MagicMock(
            data=[MagicMock(index=0, embedding=[0.1] * 1536)],
        ))
        result = await PostgresShipmentRepository(live_settings).search_shipments(
            ShipmentFilters(cargo_query="medical supplies", status="delayed", origin_region="Asia"), 8,
        )
        assert result.search_mode == "hybrid"
        assert connection.execute.await_count == 1
        assert client.embeddings.create.await_args.kwargs["input"] == ["medical supplies"]
        statement, parameters = connection.execute.call_args.args
        assert "ST_Covers(region.boundary, s.origin_position)" in statement
        assert "ORDER BY s.embedding <=> query_vector.embedding" in statement
        assert parameters[1:] == ["delayed", "delayed", "Asia", 9]
        events = progress.call_args_list
        assert all(event.args[0] != "db_setting" for event in events)
        embedding_event = next(event for event in events if event.args[0] == "embedding")
        assert embedding_event.kwargs["embedding_input"] == client.embeddings.create.await_args.kwargs["input"][0]
        sql_event = next(event for event in events if event.args[0] == "db_query")
        assert sql_event.kwargs["sql"] == statement
        assert sql_event.kwargs["parameters"][0] == "[vector: 1536 dimensions; omitted]"
        assert sql_event.kwargs["parameters"][1:] == parameters[1:]
        assert json.loads(parameters[0]) == [0.1] * 1536
        assert [event.args[0] for event in events][:3] == ["embedding", "embedding_ready", "db_connect"]
        assert events[-1].args[0] == "db_result"
        assert events[-1].kwargs["fetched_count"] == 0