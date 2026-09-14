import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app
from app.models import ShipmentStatus
from app.repository import PostgresShipmentRepository


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
        assert connection.execute.await_count == 7


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