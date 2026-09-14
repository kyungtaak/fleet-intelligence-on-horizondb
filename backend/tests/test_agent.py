from unittest.mock import Mock

import pytest

from app.agent import ShipmentAgent
from app.config import Settings
from app.models import SearchRequest


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
    assert len(fake_agent_client.agent_options["tools"]) == 1