import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from app.agent import ShipmentAgent
from app.config import Settings
from app.models import SearchRequest, ShipmentFilters, ShipmentSearchResult


@pytest.mark.parametrize("api_key", [None, "", "test-key"])
@pytest.mark.parametrize("endpoint", [
    "https://example.openai.azure.com/",
    "https://example.services.ai.azure.com/openai/v1/responses",
])
def test_agent_selects_authentication(monkeypatch, fake_repository, api_key, endpoint) -> None:
    credential_factory = Mock()
    client_factory = Mock()
    monkeypatch.setattr("app.agent.DefaultAzureCredential", credential_factory)
    monkeypatch.setattr("app.agent.OpenAIChatClient", client_factory)
    settings = Settings(
        _env_file=None,
        azure_openai_endpoint=endpoint,
        azure_openai_key=api_key,
    )

    ShipmentAgent(settings, fake_repository)

    expected = {
        "model": settings.azure_openai_deployment,
        "azure_endpoint": endpoint.split("/openai/v1")[0].rstrip("/") + "/",
    }
    if api_key:
        credential_factory.assert_not_called()
        expected["api_key"] = api_key
    else:
        credential_factory.assert_called_once_with()
        expected["credential"] = credential_factory.return_value
    client_factory.assert_called_once_with(**expected)


@pytest.mark.asyncio
async def test_agent_framework_tool_drives_semantic_results(
    live_settings: Settings,
    fake_repository,
    fake_agent_client,
) -> None:
    agent = ShipmentAgent(
        live_settings,
        fake_repository,
        client=fake_agent_client,
    )

    result = await agent.run(
        SearchRequest(query="Find healthcare cargo", limit=5)
    )

    assert result.agent_framework is True
    assert result.chat_model == "gpt-5.4"
    assert result.shipments[0].shipment_number == "SHIP-0014"
    assert result.answer.startswith("SHIP-0014")
    assert fake_agent_client.agent_options is not None
    assert fake_agent_client.agent_options["name"] == "HorizonShipAgent"
    instructions = fake_agent_client.agent_options["instructions"]
    assert "Always answer in Korean" in instructions
    assert "Format answers in Markdown" in instructions
    assert "only on the tool output" in instructions
    assert len(fake_agent_client.agent_options["tools"]) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("filters", [
    {"status": "delayed"},
    {"origin_region": "Asia"},
    {"origin_region": "Asia", "cargo_query": "medical supplies"},
    {"nearby_location": "Busan, South Korea", "radius_km": 100},
    {"sort_by": "destination_distance", "result_limit": 2},
    {"sort_by": "destination_distance", "result_limit": 2, "destination_name": "Rotterdam, Netherlands"},
])
async def test_agent_preserves_filters_and_empty_results(live_settings, fake_repository, filters):
    effective = ShipmentFilters(**filters)
    fake_repository.search_shipments = AsyncMock(return_value=ShipmentSearchResult(
        shipments=[], search_mode="sql", applied_filters=effective,
    ))
    fake_repository.semantic_search = AsyncMock()

    class Runner:
        def __init__(self, shipment_tool):
            self.shipment_tool = shipment_tool

        async def run(self, prompt):
            payload = await self.shipment_tool.invoke(arguments={"filters": filters})
            assert json.loads(payload[0].text)["matches"] == []
            return SimpleNamespace(text="조건에 맞는 배송이 없습니다.")

    client = Mock()
    client.as_agent.side_effect = lambda **options: Runner(options["tools"][0])
    agent = ShipmentAgent(live_settings, fake_repository, client=client)
    result = await agent.run(SearchRequest(query="배송 조회"))
    assert result.shipments == []
    assert result.applied_filters == effective
    fake_repository.search_shipments.assert_awaited_once_with(filters=effective, limit=8)
    fake_repository.semantic_search.assert_not_awaited()


@pytest.mark.asyncio
async def test_agent_clarification_does_not_search(live_settings, fake_repository):
    fake_repository.search_shipments = AsyncMock()
    runner = Mock(run=AsyncMock(return_value=SimpleNamespace(text="어느 지역인가요?")))
    client = Mock()
    client.as_agent.return_value = runner
    result = await ShipmentAgent(live_settings, fake_repository, client=client).run(
        SearchRequest(query="가까운 배송"),
    )
    assert result.search_mode == "not_searched"
    assert result.applied_filters is None
    fake_repository.search_shipments.assert_not_awaited()


@pytest.mark.asyncio
async def test_agent_rejects_model_generated_map_coordinates(live_settings, fake_repository):
    fake_repository.search_shipments = AsyncMock()

    class Runner:
        def __init__(self, shipment_tool):
            self.shipment_tool = shipment_tool

        async def run(self, prompt):
            await self.shipment_tool.invoke(arguments={"filters": {
                "nearby_point": {"latitude": 10, "longitude": 20}, "radius_km": 50,
            }})

    client = Mock()
    client.as_agent.side_effect = lambda **options: Runner(options["tools"][0])
    with pytest.raises(ValueError, match="manual criteria search"):
        await ShipmentAgent(live_settings, fake_repository, client=client).run(
            SearchRequest(query="가까운 배송"),
        )
    fake_repository.search_shipments.assert_not_awaited()


@pytest.mark.asyncio
async def test_ui_status_remains_required(live_settings, fake_repository, fake_agent_client):
    fake_repository.search_shipments = AsyncMock(return_value=ShipmentSearchResult(
        shipments=fake_repository._shipments[:1], search_mode="hybrid",
        applied_filters=ShipmentFilters(status="delayed", cargo_query="medical"),
    ))
    result = await ShipmentAgent(live_settings, fake_repository, client=fake_agent_client).run(
        SearchRequest(query="medical", status="delayed"),
    )
    assert fake_repository.search_shipments.await_args.kwargs["filters"].status == "delayed"
    assert result.applied_filters.status == "delayed"


def test_tool_payload_includes_destination_distance(fake_repository):
    from app.agent import _shipment_tool_payload

    result = ShipmentSearchResult(
        shipments=[fake_repository._shipments[0].model_copy(update={"remaining_distance_km": 12.345})],
        search_mode="gis", applied_filters=ShipmentFilters(sort_by="destination_distance", result_limit=2),
    )
    assert json.loads(_shipment_tool_payload(result))["matches"][0]["remaining_distance_km"] == 12.345


@pytest.mark.asyncio
async def test_horizondb_adapter_preserves_instructions_and_tool_results(live_settings, fake_repository):
    from app.horizon_agent_client import HorizonDBChatClient

    generator = SimpleNamespace(generate_text=AsyncMock(side_effect=[
        '{"action":"search","filters":{"status":"delayed"}}',
        "조회 결과입니다.",
    ]))
    client = HorizonDBChatClient(generator, "horizonship-chat")
    result = await ShipmentAgent(live_settings, fake_repository, client=client).run(
        SearchRequest(query="지연 배송", status="delayed"),
    )
    assert result.applied_filters.status == "delayed"
    assert result.answer == "조회 결과입니다."
    assert generator.generate_text.await_count == 2
    for call in generator.generate_text.await_args_list:
        assert "Always answer in Korean" in call.args[1]
        assert "Supported regions" in call.args[1]
    for shipment in result.shipments:
        assert shipment.shipment_number in generator.generate_text.await_args_list[1].args[0]


@pytest.mark.asyncio
async def test_horizondb_adapter_clarifies_without_search(live_settings, fake_repository):
    from app.horizon_agent_client import HorizonDBChatClient

    generator = SimpleNamespace(generate_text=AsyncMock(return_value=(
        '{"action":"clarify","answer":"어느 지역인가요?"}'
    )))
    fake_repository.search_shipments = AsyncMock()
    result = await ShipmentAgent(
        live_settings, fake_repository, client=HorizonDBChatClient(generator, "chat"),
    ).run(SearchRequest(query="가까운 배송"))
    assert result.search_mode == "not_searched"
    fake_repository.search_shipments.assert_not_awaited()
    generator.generate_text.assert_awaited_once()


@pytest.mark.asyncio
@pytest.mark.parametrize("plan", [
    '```json\n{"action":"search","filters":{}}\n```',
    '{"action":"search","filters":{"status":"invalid"}}',
    '{"action":"search","filters":{},"sql":"SELECT 1"}',
    '{"action":"clarify","answer":" "}',
])
async def test_horizondb_adapter_rejects_invalid_plan(live_settings, fake_repository, plan):
    from app.horizon_agent_client import HorizonDBChatClient

    generator = SimpleNamespace(generate_text=AsyncMock(return_value=plan))
    fake_repository.search_shipments = AsyncMock()
    with pytest.raises(ValueError):
        await ShipmentAgent(
            live_settings, fake_repository, client=HorizonDBChatClient(generator, "chat"),
        ).run(SearchRequest(query="배송 검색"))
    fake_repository.search_shipments.assert_not_awaited()


def test_horizondb_provider_never_constructs_openai_client(live_settings, fake_repository):
    from unittest.mock import patch

    with patch("app.agent.OpenAIChatClient") as sdk:
        ShipmentAgent(live_settings.model_copy(update={"chat_provider": "horizondb"}), fake_repository)
    sdk.assert_not_called()


async def test_agent_anchors_relative_dates_in_configured_timezone(live_settings, fake_repository):
    from datetime import datetime
    from unittest.mock import patch
    from zoneinfo import ZoneInfo

    from app.horizon_agent_client import HorizonDBChatClient

    generator = SimpleNamespace(generate_text=AsyncMock(side_effect=[
        '{"action":"search","filters":{"eta_start":"2026-09-16","eta_end":"2026-09-16"}}',
        "해당 날짜의 배송입니다.",
    ]))
    with patch("app.agent.datetime") as clock:
        clock.now.return_value = datetime(2026, 9, 15, 23, 59, tzinfo=ZoneInfo("Asia/Seoul"))
        response = await ShipmentAgent(
            live_settings, fake_repository, HorizonDBChatClient(generator, "chat"),
        ).run(SearchRequest(query="내일 도착 예정 배송"))
    assert str(clock.now.call_args.args[0]) == "Asia/Seoul"
    assert "2026-09-15 in Asia/Seoul" in generator.generate_text.await_args_list[0].args[1]
    assert response.applied_filters.eta_start.isoformat() == "2026-09-16"
    with pytest.raises(ValueError, match="IANA timezone"):
        type(live_settings)(_env_file=None, search_timezone="not-a-timezone")