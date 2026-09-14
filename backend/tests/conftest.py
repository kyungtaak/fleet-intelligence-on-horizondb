import json
from types import SimpleNamespace
from typing import Any

import pytest

from app.config import Settings
from app.models import (
    DatabaseCapabilities,
    Shipment,
    ShipmentStats,
    ShipmentStatus,
    StatusCount,
)
from app.sample_data import build_sample_shipments


class FakeShipmentRepository:
    mode = "horizondb"
    search_mode = "diskann_cosine"

    def __init__(self) -> None:
        self._shipments = build_sample_shipments()

    async def list_shipments(
        self,
        status: ShipmentStatus | None = None,
        search: str | None = None,
    ) -> list[Shipment]:
        shipments = self._shipments
        if status is not None:
            shipments = [item for item in shipments if item.status is status]
        if search:
            normalized = search.casefold()
            shipments = [
                item
                for item in shipments
                if normalized
                in (
                    f"{item.shipment_number} {item.title} {item.description} "
                    f"{item.origin_name} {item.destination_name} "
                    f"{item.current_location_name}"
                ).casefold()
            ]
        return shipments

    async def semantic_search(
        self,
        query: str,
        status: ShipmentStatus | None,
        limit: int,
    ) -> list[Shipment]:
        del query
        shipments = await self.list_shipments(status=status)
        shipments.sort(key=lambda item: item.shipment_number != "SHIP-0014")
        return [
            item.model_copy(update={"similarity": 0.95 - index * 0.05})
            for index, item in enumerate(shipments[:limit])
        ]

    async def get_shipment(self, shipment_number: str) -> Shipment | None:
        return next(
            (
                item
                for item in self._shipments
                if item.shipment_number == shipment_number
            ),
            None,
        )

    async def stats(self) -> ShipmentStats:
        counts = {
            status: sum(item.status is status for item in self._shipments)
            for status in ShipmentStatus
        }
        return ShipmentStats(
            total=len(self._shipments),
            statuses=[
                StatusCount(status=status, count=counts[status])
                for status in ShipmentStatus
            ],
        )

    async def capabilities(self) -> DatabaseCapabilities:
        return DatabaseCapabilities(
            mode=self.mode,
            connected=True,
            postgis_version="3.5.2",
            vector_version="0.8.0",
            diskann_version="0.7.3",
            azure_ai_version="2.2.2",
            shipment_count=len(self._shipments),
            azure_embedding_count=len(self._shipments),
            embedding_mode="azure_openai",
            embedding_model_alias="horizonship-embedding",
        )


class InvokingAgent:
    def __init__(self, shipment_tool: Any) -> None:
        self._shipment_tool = shipment_tool

    async def run(self, prompt: str) -> SimpleNamespace:
        tool_result = await self._shipment_tool.invoke(
            arguments={
                "query_text": prompt,
                "status_filter": "all",
            }
        )
        payload = json.loads(tool_result[0].text)
        first = payload["matches"][0]
        return SimpleNamespace(
            text=f"{first['shipment_number']} is the strongest medical match."
        )


class FakeAgentClient:
    def __init__(self) -> None:
        self.agent_options: dict[str, Any] | None = None

    def as_agent(self, **kwargs: Any) -> InvokingAgent:
        self.agent_options = kwargs
        return InvokingAgent(kwargs["tools"][0])


@pytest.fixture
def live_settings() -> Settings:
    return Settings(
        _env_file=None,
        database_url="postgresql://user:password@localhost/migration_lab",
        azure_openai_endpoint="https://example.openai.azure.com/",
        azure_openai_key="test-key",
    )


@pytest.fixture
def fake_repository() -> FakeShipmentRepository:
    return FakeShipmentRepository()


@pytest.fixture
def fake_agent_client() -> FakeAgentClient:
    return FakeAgentClient()