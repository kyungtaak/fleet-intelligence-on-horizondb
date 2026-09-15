import asyncio
import json
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app
from app.models import ShipmentCreate, ShipmentFilters, ShipmentStatus, ShipmentUpdate
from app.progress import report_progress, stream_chat
from app.repository import DemoEmbeddingPendingError, PostgresShipmentRepository
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


async def test_stream_serializes_eta_bindings_and_completes():
    from datetime import date

    from app.models import ChatResponse

    async def run():
        report_progress(
            "db_query", "ETA query", parameters=[None, date(2026, 9, 1), date(2026, 9, 30), 9],
        )
        return ChatResponse(
            query="ETA search", search_mode="sql", shipments=[], answer="조회 완료", chat_model="chat",
        )

    events = [json.loads(line) async for line in stream_chat(run)]
    query = next(event for event in events if event.get("stage") == "db_query")
    assert query["parameters"] == [None, "2026-09-01", "2026-09-30", 9]
    assert events[-1]["type"] == "result"


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


def test_manual_criteria_search_binds_map_and_eta_without_agent(
    live_settings, fake_repository, fake_agent_client,
):
    with make_client(live_settings, fake_repository, fake_agent_client) as client:
        response = client.post("/api/search/criteria", json={
            "query": "medical supplies", "eta_date": "2026-09-15", "eta_days": 3,
            "search_center": {"latitude": 35.1796, "longitude": 129.0756},
            "radius_km": 500, "status": "delayed", "ranking": "semantic_spatial",
        })
    assert response.status_code == 200
    filters = response.json()["applied_filters"]
    assert filters["eta_start"] == "2026-09-12"
    assert filters["eta_end"] == "2026-09-18"
    assert filters["nearby_point"] == {"latitude": 35.1796, "longitude": 129.0756}
    assert filters["sort_by"] == "semantic_spatial"
    assert "answer" not in response.json()
    assert fake_agent_client.agent_options is None


@pytest.mark.parametrize("payload", [
    {},
    {"status": "delayed", "eta_date": "2026-09-15", "eta_days": 0},
    {"search_center": {"latitude": 10, "longitude": 20}, "radius_km": 50},
])
def test_manual_exact_criteria_allow_no_query(
    live_settings, fake_repository, fake_agent_client, payload,
):
    with make_client(live_settings, fake_repository, fake_agent_client) as client:
        response = client.post("/api/search/criteria", json=payload)
    assert response.status_code == 200
    assert response.json()["applied_filters"]["cargo_query"] is None
    if payload.get("eta_date"):
        assert response.json()["applied_filters"]["eta_start"] == "2026-09-15"
        assert response.json()["applied_filters"]["eta_end"] == "2026-09-15"
    assert fake_agent_client.agent_options is None


@pytest.mark.parametrize("payload", [
    {"query": "x"}, {"eta_days": -1}, {"eta_days": 366},
    {"eta_date": "0001-01-01", "eta_days": 3}, {"eta_date": "not-a-date"},
    {"search_center": {"latitude": 95, "longitude": 129}},
    {"search_center": {"latitude": 35, "longitude": 190}},
    {"radius_km": 0}, {"ranking": "semantic_spatial", "query": "cargo"},
])
def test_manual_criteria_invalid_inputs_return_422(
    live_settings, fake_repository, fake_agent_client, payload,
):
    with make_client(live_settings, fake_repository, fake_agent_client) as client:
        assert client.post("/api/search/criteria", json=payload).status_code == 422


async def test_manual_point_uses_parameterized_gis_without_embeddings(live_settings):
    with (
        patch("app.repository.AsyncConnectionPool") as pool_factory,
        patch("app.repository.async_embedding_client") as sdk,
    ):
        connection = MagicMock()
        cursor = AsyncMock()
        cursor.fetchall.return_value = []
        connection.execute = AsyncMock(return_value=cursor)
        pool_factory.return_value.connection.return_value.__aenter__.return_value = connection
        result = await PostgresShipmentRepository(live_settings).search_shipments(
            ShipmentFilters(nearby_point={"latitude": 10, "longitude": 20}, radius_km=50), 24,
        )
        statement, parameters = connection.execute.await_args.args
        assert "ST_DWithin(s.current_position::public.geography" in statement
        assert parameters[-4:] == [20.0, 10.0, 50000.0, 25]
        assert result.search_mode == "gis"
        sdk.assert_not_called()
    assert "nearby_point" not in ShipmentFilters.model_json_schema()["properties"]


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


def test_create_and_update_shipment_endpoints(
    live_settings,
    fake_repository,
    fake_agent_client,
) -> None:
    payload = {
        "shipment_number": "SHIP-9001",
        "title": "Laboratory Supplies",
        "description": "Diagnostic equipment for a regional laboratory.",
        "origin_name": "Seoul, South Korea",
        "origin": {"latitude": 37.5665, "longitude": 126.978},
        "destination_name": "Tokyo, Japan",
        "destination": {"latitude": 35.6895, "longitude": 139.6917},
        "current_location_name": "Busan, South Korea",
        "current_position": {"latitude": 35.1796, "longitude": 129.0756},
        "status": "in_transit",
        "eta": "2026-10-01",
        "metadata": {"tags": ["medical"]},
    }
    with make_client(live_settings, fake_repository, fake_agent_client) as client:
        created = client.post("/api/shipments", json=payload)
        duplicate = client.post("/api/shipments", json=payload)
        updated = client.patch(
            "/api/shipments/ship-9001",
            json={"title": "Updated Laboratory Supplies", "eta": None},
        )
        fetched = client.get("/api/shipments/SHIP-9001")
        missing = client.patch("/api/shipments/SHIP-9999", json={"status": "delayed"})
        empty = client.patch("/api/shipments/SHIP-9001", json={})

    assert created.status_code == 201
    assert created.json()["shipment_number"] == "SHIP-9001"
    assert duplicate.status_code == 409
    assert updated.status_code == 200
    assert updated.json()["title"] == "Updated Laboratory Supplies"
    assert updated.json()["eta"] is None
    assert fetched.json() == updated.json()
    assert missing.status_code == 404
    assert empty.status_code == 422


def test_bulk_create_and_embedding_status_endpoints(
    live_settings,
    fake_repository,
    fake_agent_client,
) -> None:
    base_payload = {
        "title": "Cold-chain Demo Cargo",
        "description": "Temperature-controlled medicine for pipeline demonstration.",
        "origin_name": "Seoul, South Korea",
        "origin": {"latitude": 37.5665, "longitude": 126.978},
        "destination_name": "Nairobi, Kenya",
        "destination": {"latitude": -1.2921, "longitude": 36.8219},
        "current_location_name": "Dubai, UAE",
        "current_position": {"latitude": 25.2048, "longitude": 55.2708},
        "status": "in_transit",
        "eta": "2026-10-01",
        "metadata": {"tags": ["cold-chain", "pipeline-demo"]},
    }
    payloads = [
        {**base_payload, "shipment_number": f"SHIP-{9100 + index}"}
        for index in range(20)
    ]
    with make_client(live_settings, fake_repository, fake_agent_client) as client:
        created = client.post("/api/shipments/bulk", json={"shipments": payloads})
        duplicate = client.post("/api/shipments/bulk", json={"shipments": payloads})
        too_many = client.post(
            "/api/shipments/bulk",
            json={"shipments": [*payloads, {**base_payload, "shipment_number": "SHIP-9200"}]},
        )
        embedding_status = client.get(
            "/api/shipments/embedding-status",
            params=[
                ("shipment_number", "ship-9100"),
                ("shipment_number", "SHIP-9101"),
            ],
        )

    assert created.status_code == 201
    assert len(created.json()) == 20
    assert duplicate.status_code == 409
    assert too_many.status_code == 422
    assert embedding_status.status_code == 200
    assert embedding_status.json()["total"] == 2
    assert embedding_status.json()["pending"] == 2


async def test_repository_writes_use_postgis_and_fixed_patch_fields(
    live_settings,
    fake_repository,
) -> None:
    sample = fake_repository._shipments[0]
    create_request = ShipmentCreate.model_validate(sample.model_dump(exclude={
        "id", "updated_at", "similarity", "remaining_distance_km", "distance_to_center_km", "hybrid_score",
    }))
    with patch("app.repository.AsyncConnectionPool") as pool_factory:
        connection = MagicMock()
        cursor = AsyncMock()
        cursor.fetchone.return_value = {
            "id": sample.id,
            "shipment_number": sample.shipment_number,
            "title": sample.title,
            "description": sample.description,
            "origin_name": sample.origin_name,
            "origin_latitude": sample.origin.latitude,
            "origin_longitude": sample.origin.longitude,
            "destination_name": sample.destination_name,
            "destination_latitude": sample.destination.latitude,
            "destination_longitude": sample.destination.longitude,
            "current_location_name": sample.current_location_name,
            "current_latitude": sample.current_position.latitude,
            "current_longitude": sample.current_position.longitude,
            "status": sample.status.value,
            "eta": sample.eta,
            "updated_at": sample.updated_at,
            "metadata": sample.metadata,
        }
        connection.execute = AsyncMock(return_value=cursor)
        pool_factory.return_value.connection.return_value.__aenter__.return_value = connection
        repository = PostgresShipmentRepository(live_settings)

        await repository.create_shipment(create_request)
        create_sql, create_parameters = connection.execute.await_args.args
        assert create_sql.count("ST_MakePoint") == 3
        assert create_parameters[4:6] == (
            sample.origin.longitude, sample.origin.latitude,
        )

        await repository.update_shipment(
            sample.shipment_number,
            ShipmentUpdate(current_position={"latitude": 1.25, "longitude": 2.5}),
        )
        patch_sql, patch_parameters = connection.execute.await_args.args
        assert "current_position = public.ST_SetSRID" in patch_sql.as_string()
        assert "title =" not in patch_sql.as_string()
        assert patch_parameters == [2.5, 1.25, sample.shipment_number]


def test_demo_delete_endpoint(live_settings, fake_repository, fake_agent_client):
    shipment_id = uuid4()
    fake_repository.delete_demo_shipments = AsyncMock(return_value=[shipment_id])
    with make_client(live_settings, fake_repository, fake_agent_client) as client:
        response = client.request(
            "DELETE", "/api/shipments/demo", json={"shipment_ids": [str(shipment_id)]},
        )
        assert response.status_code == 200
        assert response.json() == [str(shipment_id)]
        fake_repository.delete_demo_shipments.assert_awaited_once_with([shipment_id])
        assert client.request(
            "DELETE", "/api/shipments/demo", json={"shipment_ids": []},
        ).status_code == 422
        assert client.request(
            "DELETE", "/api/shipments/demo", json={"shipment_ids": ["invalid"]},
        ).status_code == 422
        fake_repository.delete_demo_shipments.side_effect = DemoEmbeddingPendingError()
        assert client.request(
            "DELETE", "/api/shipments/demo", json={"shipment_ids": [str(shipment_id)]},
        ).status_code == 409


@pytest.mark.parametrize("pending", [False, True])
async def test_demo_delete_repository_checks_markers_and_pending(live_settings, pending):
    demo_id, ordinary_id = uuid4(), uuid4()
    with patch("app.repository.AsyncConnectionPool") as pool_factory:
        connection = MagicMock()
        cursor = AsyncMock()
        cursor.fetchall.side_effect = [[{"id": demo_id}], [{"id": demo_id}]]
        cursor.fetchone.return_value = {"pending": pending}
        connection.execute = AsyncMock(return_value=cursor)
        pool_factory.return_value.connection.return_value.__aenter__.return_value = connection
        repository = PostgresShipmentRepository(live_settings)
        if pending:
            with pytest.raises(DemoEmbeddingPendingError):
                await repository.delete_demo_shipments([demo_id, ordinary_id])
            assert connection.execute.await_count == 2
        else:
            assert await repository.delete_demo_shipments([demo_id, ordinary_id]) == [demo_id]
            delete_sql, parameters = connection.execute.await_args.args
            assert "DELETE FROM horizon_ship.shipments" in delete_sql
            assert parameters == ([demo_id],)
        select_sql = connection.execute.await_args_list[0].args[0]
        assert '"demo_run": true' in select_sql
        assert '"tags": ["pipeline-demo"]' in select_sql
        assert "FOR UPDATE" in select_sql
        assert connection.transaction.call_count == 1


async def test_database_model_calls_execute_once_and_release_connection(live_settings):
    settings = live_settings.model_copy(update={
        "chat_provider": "horizondb", "embedding_provider": "horizondb",
    })
    with (
        patch("app.repository.AsyncConnectionPool") as pool_factory,
        patch("app.repository.async_embedding_client") as sdk,
    ):
        connection = MagicMock()
        cursor = AsyncMock()
        cursor.fetchone.side_effect = [{"answer": "model answer"}, {"embedding": json.dumps([0.1] * 1536)}]
        cursor.fetchall.return_value = []
        connection.execute = AsyncMock(return_value=cursor)
        context = pool_factory.return_value.connection.return_value
        context.__aenter__.return_value = connection
        repository = PostgresShipmentRepository(settings)
        assert await repository.generate_text("question", "instructions") == "model answer"
        context.__aexit__.assert_awaited_once()
        await repository.semantic_search("medical cargo", None, 8)
        statements = [call.args[0] for call in connection.execute.await_args_list]
        assert sum("azure_ai.generate" in statement for statement in statements) == 1
        assert sum("create_embeddings" in statement for statement in statements) == 1
        assert not any("EXPLAIN" in statement for statement in statements)
        sdk.assert_not_called()


@pytest.mark.parametrize("start,end", [("2026-09-15", "2026-09-15"), (None, "2026-09-17"), ("2026-09-15", None)])
async def test_eta_filters_are_inclusive_bound_sql_without_embeddings(live_settings, start, end):
    with (
        patch("app.repository.AsyncConnectionPool") as pool_factory,
        patch("app.repository.async_embedding_client") as sdk,
    ):
        connection = MagicMock()
        cursor = AsyncMock()
        cursor.fetchall.return_value = []
        connection.execute = AsyncMock(return_value=cursor)
        pool_factory.return_value.connection.return_value.__aenter__.return_value = connection
        result = await PostgresShipmentRepository(live_settings).search_shipments(
            ShipmentFilters(eta_start=start, eta_end=end), 8,
        )
        statement, parameters = connection.execute.await_args.args
        assert ("s.eta >= %s::date" in statement) is bool(start)
        assert ("s.eta <= %s::date" in statement) is bool(end)
        assert parameters[-1] == 9
        assert result.search_mode == "sql"
        sdk.assert_not_called()


@pytest.mark.parametrize("filters", [
    {"eta_start": "2026-09-20", "eta_end": "2026-09-19"},
    {"eta_start": "2026-02-30"},
    {"sort_by": "semantic_spatial"},
    {"sort_by": "semantic_spatial", "cargo_query": "cargo", "nearby_location": "Busan, South Korea"},
    {"sort_by": "semantic_spatial", "cargo_query": "cargo", "radius_km": 100},
])
def test_invalid_dates_and_weighted_ranking_are_rejected(filters):
    with pytest.raises(ValueError):
        ShipmentFilters(**filters)


async def test_weighted_ranking_scores_all_eligible_rows_and_preserves_filters(live_settings):
    with (
        patch("app.repository.AsyncConnectionPool") as pool_factory,
        patch("app.repository.async_embedding_client") as sdk,
    ):
        connection = MagicMock()
        cursor = AsyncMock()
        cursor.fetchall.return_value = []
        connection.execute = AsyncMock(return_value=cursor)
        pool_factory.return_value.connection.return_value.__aenter__.return_value = connection
        sdk.return_value.__aenter__.return_value.embeddings.create = AsyncMock(
            return_value=MagicMock(data=[MagicMock(index=0, embedding=[0.1] * 1536)]),
        )
        filters = ShipmentFilters(
            cargo_query="medical supplies", sort_by="semantic_spatial", status="delayed",
            nearby_location="Busan, South Korea", radius_km=500, position_field="origin",
            eta_start="2026-09-01", eta_end="2026-09-30", result_limit=3,
        )
        result = await PostgresShipmentRepository(live_settings).search_shipments(filters, 8)
        statement, parameters = connection.execute.await_args.args
        assert statement.count("LIMIT") == 1
        assert "hybrid_score DESC, s.shipment_number ASC" in statement
        assert "0.72 *" in statement and "0.28 * GREATEST" in statement
        assert "ST_Distance(s.origin_position::public.geography, search_center.point)" in statement
        assert "ST_DWithin(s.origin_position::public.geography" in statement
        assert "sej.content_version = se.content_version" in statement
        assert parameters[3] == 500 and parameters[-1] == 4
        assert result.search_mode == "hybrid"


async def test_estimated_plan_reuses_vector_and_removes_expressions(live_settings):
    settings = live_settings.model_copy(update={"capture_query_plan": True})
    with (
        patch("app.repository.AsyncConnectionPool") as pool_factory,
        patch("app.repository.async_embedding_client") as sdk,
        patch("app.repository.report_progress") as progress,
    ):
        connection = MagicMock()
        cursor = AsyncMock()
        cursor.fetchall.return_value = []
        cursor.fetchone.return_value = {"QUERY PLAN": [{"Plan": {
            "Node Type": "Limit", "Total Cost": 42, "Plan Rows": 8,
            "Output": ["sensitive vector"], "Plans": [{
                "Node Type": "Index Scan", "Index Name": "shipment_embeddings_diskann_idx",
                "Order By": "sensitive vector", "Filter": "private literal",
            }],
        }}]}
        connection.execute = AsyncMock(return_value=cursor)
        pool_factory.return_value.connection.return_value.__aenter__.return_value = connection
        sdk.return_value.__aenter__.return_value.embeddings.create = AsyncMock(
            return_value=MagicMock(data=[MagicMock(index=0, embedding=[0.1] * 1536)]),
        )
        await PostgresShipmentRepository(settings).search_shipments(ShipmentFilters(cargo_query="cargo"), 8)
        sdk.return_value.__aenter__.return_value.embeddings.create.assert_awaited_once()
        assert connection.execute.await_count == 2
        explain, select = connection.execute.await_args_list
        assert explain.args[0].startswith("EXPLAIN (FORMAT JSON")
        assert "ANALYZE" not in explain.args[0]
        assert explain.args[1] == select.args[1]
        plan_event = next(call for call in progress.call_args_list if call.args[0] == "query_plan")
        assert plan_event.kwargs["plan_kind"] == "estimated"
        assert plan_event.kwargs["plan"]["Plans"][0] == {
            "Node Type": "Index Scan", "Index Name": "shipment_embeddings_diskann_idx",
        }
        assert "sensitive vector" not in str(progress.call_args_list)
        assert "private literal" not in str(progress.call_args_list)


async def test_database_provider_rejects_missing_model_functions(live_settings):
    settings = live_settings.model_copy(update={"chat_provider": "horizondb"})
    with patch("app.repository.AsyncConnectionPool") as pool_factory:
        connection = MagicMock()
        cursor = AsyncMock()
        cursor.fetchall.return_value = []
        connection.execute = AsyncMock(return_value=cursor)
        pool_factory.return_value.connection.return_value.__aenter__.return_value = connection
        with pytest.raises(RuntimeError, match="functions are unavailable"):
            await PostgresShipmentRepository(settings)._validate_model_readiness()


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
        assert "JOIN horizon_ship.shipment_embeddings AS se" in statement
        assert "sej.content_version = se.content_version" in statement
        assert "ORDER BY se.embedding <=> query_vector.embedding" in statement
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
        assert "JOIN horizon_ship.shipment_embeddings AS se" in statement
        assert "sej.content_version = se.content_version" in statement
        assert "ORDER BY se.embedding <=> query_vector.embedding" in statement
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