import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app


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
    app = create_app(settings=Settings(_env_file=None))

    with (
        pytest.raises(ValueError, match="Live HorizonShip configuration"),
        TestClient(app),
    ):
        pass