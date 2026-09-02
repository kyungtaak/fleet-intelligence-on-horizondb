import pytest

from app.agent import ShipmentAgent
from app.config import Settings
from app.models import SearchRequest


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
    assert len(fake_agent_client.agent_options["tools"]) == 1