import json
from typing import Any, Self
from unittest.mock import MagicMock, patch

import httpx
import pytest
from openai import AsyncOpenAI, AuthenticationError

from app.config import Settings
from app.embeddings import (
    TOKEN_SCOPE,
    async_embedding_client,
    embedding_client,
    model_registry_endpoint,
    openai_base_url,
    serialize_embeddings,
)
from app.sample_data import build_sample_shipments
from app.setup_database import (
    CREATE_PIPELINE_SQL,
    EMBEDDING_CONFIG_SQL,
    PIPELINE_NAME,
    PIPELINE_SINK_ACTION,
    PRIMARY_INDEX_SQL,
    backfill_embeddings,
    configure_chat_model,
    configure_embedding_pipeline,
    configure_embeddings,
    configure_pipeline_model,
    setup_database,
    shipment_parameters,
)


class RecordingCursor:
    def __init__(self, lookup_result: tuple[Any, ...] | None = None) -> None:
        self.lookup_result = lookup_result
        self.calls: list[tuple[str, tuple[Any, ...] | None]] = []

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *_: object) -> None:
        return None

    def execute(
        self,
        query: str,
        parameters: tuple[Any, ...] | None = None,
    ) -> None:
        self.calls.append((query, parameters))

    def fetchone(self) -> tuple[Any, ...] | None:
        return self.lookup_result


class RecordingConnection:
    def __init__(self, cursor: RecordingCursor) -> None:
        self.recording_cursor = cursor

    def cursor(self) -> RecordingCursor:
        return self.recording_cursor


def test_embedding_configuration_never_stores_the_subscription_key() -> None:
    cursor = RecordingCursor()
    connection = RecordingConnection(cursor)
    settings = Settings(
        _env_file=None,
        azure_openai_key="bound-only-test-key",
        azure_openai_endpoint="https://example.openai.azure.com/",
    )

    changed = configure_embeddings(connection, settings)  # type: ignore[arg-type]

    assert changed is True
    configuration_query, parameters = cursor.calls[-1]
    assert configuration_query == EMBEDDING_CONFIG_SQL
    assert parameters is not None
    assert "bound-only-test-key" not in str(cursor.calls)
    assert parameters == (
        "https://example.openai.azure.com/openai/v1/",
        settings.azure_embed_deployment,
        1536,
    )


@pytest.mark.parametrize("api_key", [None, "", "rotated-test-key"])
@pytest.mark.parametrize("current_deployment", [None, "old-embedding", "text-embedding-3-small"])
def test_embedding_configuration_tracks_model_not_auth(api_key, current_deployment) -> None:
    settings = Settings(
        _env_file=None,
        azure_openai_key=api_key,
        azure_openai_endpoint="https://example.openai.azure.com/",
    )
    metadata = (
        openai_base_url(settings.azure_openai_endpoint),
        settings.azure_embed_deployment,
        1536,
    )
    current = (metadata[0], current_deployment, 1536) if current_deployment else None
    cursor = RecordingCursor(current)
    connection = RecordingConnection(cursor)

    changed = configure_embeddings(connection, settings)  # type: ignore[arg-type]

    if current_deployment == settings.azure_embed_deployment:
        assert changed is False
        assert len(cursor.calls) == 1
    else:
        assert changed is True
        assert cursor.calls[-1] == (
            EMBEDDING_CONFIG_SQL,
            metadata,
        )
        assert len(cursor.calls) == 2


def test_pipeline_model_registration_binds_subscription_key(live_settings: Settings) -> None:
    connection = MagicMock()
    cursor = connection.cursor.return_value.__enter__.return_value
    cursor.fetchone.return_value = None

    configure_pipeline_model(connection, live_settings)

    registration_query, parameters = cursor.execute.call_args_list[-1].args
    assert "model_registry.model_add" in registration_query
    assert live_settings.azure_openai_key not in registration_query
    assert parameters == (
        live_settings.embedding_model_alias,
        "https://example.openai.azure.com/",
        live_settings.azure_embed_deployment,
        live_settings.azure_embed_deployment,
        "subscription-key",
        live_settings.azure_openai_key,
    )


def test_pipeline_model_registration_requires_subscription_key(
    live_settings: Settings,
) -> None:
    settings = live_settings.model_copy(update={"azure_openai_key": None})
    with pytest.raises(RuntimeError, match="AZURE_OPENAI_KEY"):
        configure_pipeline_model(MagicMock(), settings)


def test_chat_alias_registration_and_key_rotation(live_settings):
    connection = MagicMock()
    cursor = connection.cursor.return_value.__enter__.return_value
    cursor.fetchone.return_value = None
    configure_chat_model(connection, live_settings)
    statement, parameters = cursor.execute.call_args.args
    assert "model_registry.model_add" in statement
    assert parameters[0] == live_settings.chat_model_alias
    assert parameters[2:4] == (live_settings.azure_openai_deployment,) * 2
    assert live_settings.azure_openai_key not in statement
    cursor.fetchone.return_value = parameters[:-1]
    configure_chat_model(connection, live_settings)
    assert "model_key_update" in cursor.execute.call_args.args[0]
    cursor.fetchone.return_value = (live_settings.chat_model_alias, "https://different.example/", *parameters[2:-1])
    with pytest.raises(RuntimeError, match="different nonsecret metadata"):
        configure_chat_model(connection, live_settings)


def test_pipeline_creation_uses_incremental_job_source(live_settings: Settings) -> None:
    connection = MagicMock()
    connection.execute.return_value.fetchone.return_value = None

    assert configure_embedding_pipeline(connection, live_settings) is True

    create_call = next(
        call for call in connection.execute.call_args_list
        if call.args[0] == CREATE_PIPELINE_SQL
    )
    assert create_call.args[1] == (
        PIPELINE_NAME,
        live_settings.embedding_model_alias,
        PIPELINE_SINK_ACTION,
    )
    assert "shipment_embedding_jobs" in CREATE_PIPELINE_SQL
    assert "shipment_embeddings" in CREATE_PIPELINE_SQL
    assert "ai.chunk" not in CREATE_PIPELINE_SQL


def test_seed_parameters_use_postgis_longitude_latitude_order() -> None:
    shipment = build_sample_shipments()[0]
    parameters = shipment_parameters(shipment)

    assert parameters[5:7] == (
        shipment.origin.longitude,
        shipment.origin.latitude,
    )
    assert parameters[8:10] == (
        shipment.destination.longitude,
        shipment.destination.latitude,
    )
    assert parameters[11:13] == (
        shipment.current_position.longitude,
        shipment.current_position.latitude,
    )


def test_primary_diskann_index_uses_spherical_quantization() -> None:
    assert "USING diskann (embedding vector_cosine_ops)" in PRIMARY_INDEX_SQL
    assert "spherical_quantized = true" in PRIMARY_INDEX_SQL
    assert "sq_bits = 4" in PRIMARY_INDEX_SQL
    assert "sq_training_samples = 25000" in PRIMARY_INDEX_SQL


@pytest.mark.parametrize("suffix", ["", "/", "/openai/v1/", "/openai/v1/responses"])
def test_foundry_endpoint_normalization(suffix: str) -> None:
    assert openai_base_url("https://example.services.ai.azure.com" + suffix) == (
        "https://example.services.ai.azure.com/openai/v1/"
    )
    assert model_registry_endpoint("https://example.services.ai.azure.com" + suffix) == (
        "https://example.services.ai.azure.com/"
    )


@pytest.mark.parametrize("api_key", [None, "test-only-key"])
def test_embedding_client_selects_authentication(api_key: str | None) -> None:
    settings = Settings(
        _env_file=None,
        azure_openai_endpoint="https://example.openai.azure.com/",
        azure_openai_key=api_key,
    )
    with (
        patch("app.embeddings.OpenAI") as client,
        patch("app.embeddings.DefaultAzureCredential") as credential,
        patch("app.embeddings.get_bearer_token_provider") as provider,
    ):
        with embedding_client(settings):
            pass
        assert client.call_args.kwargs["api_key"] == (api_key or provider.return_value)
        assert credential.call_count == (0 if api_key else 1)
        assert provider.call_count == (0 if api_key else 1)
        client.return_value.__exit__.assert_called_once()


def test_embedding_response_rejects_invalid_dimensions() -> None:
    response = MagicMock(data=[MagicMock(index=0, embedding=[0.1, 0.2])])
    with pytest.raises(ValueError, match="1536-dimensional"):
        serialize_embeddings(response, 1)


@pytest.mark.parametrize("endpoint", [
    "http://example.com", "https://example.com/?key=hidden",
    "https://user:password@example.com", "https://example.com/api/projects/sample",
])
def test_endpoint_rejects_credentials_and_unexpected_paths(endpoint: str) -> None:
    with pytest.raises(ValueError):
        openai_base_url(endpoint)


@pytest.mark.parametrize("api_key", [None, "", "test-only-key"])
async def test_async_embedding_client_selects_authentication(api_key: str | None) -> None:
    settings = Settings(
        _env_file=None,
        azure_openai_endpoint="https://example.services.ai.azure.com/",
        azure_openai_key=api_key,
    )
    with (
        patch("app.embeddings.AsyncOpenAI") as client,
        patch("app.embeddings.AsyncDefaultAzureCredential") as credential,
        patch("app.embeddings.get_async_bearer_token_provider") as provider,
    ):
        async with async_embedding_client(settings):
            pass
        assert client.call_args.kwargs["api_key"] == (api_key or provider.return_value)
        assert credential.call_count == (0 if api_key else 1)
        if not api_key:
            provider.assert_called_once_with(
                credential.return_value.__aenter__.return_value, TOKEN_SCOPE
            )
            credential.return_value.__aexit__.assert_awaited_once()
        client.return_value.__aexit__.assert_awaited_once()


def test_embedding_response_matches_input_order() -> None:
    response = MagicMock(data=[
        MagicMock(index=1, embedding=[0.2] * 1536),
        MagicMock(index=0, embedding=[0.1] * 1536),
    ])
    vectors = serialize_embeddings(response, 2)
    assert [json.loads(vector)[0] for vector in vectors] == [0.1, 0.2]


@pytest.mark.parametrize("indices", [[], [0, 0], [1], [0, 2]])
def test_embedding_response_rejects_missing_or_duplicate_inputs(indices: list[int]) -> None:
    response = MagicMock(data=[
        MagicMock(index=index, embedding=[0.1] * 1536) for index in indices
    ])
    with pytest.raises(ValueError, match="requested inputs"):
        serialize_embeddings(response, 2)


@pytest.mark.parametrize("value", [float("nan"), float("inf")])
def test_embedding_response_rejects_nonfinite_values(value: float) -> None:
    response = MagicMock(data=[MagicMock(index=0, embedding=[value] * 1536)])
    with pytest.raises(ValueError, match="finite"):
        serialize_embeddings(response, 1)


def test_backfill_batches_embeddings_and_binds_vectors(live_settings: Settings) -> None:
    settings = live_settings.model_copy(update={"embedding_batch_size": 2})
    connection = MagicMock()
    cursor = connection.cursor.return_value.__enter__.return_value
    cursor.fetchall.side_effect = [[("first", "cargo one"), ("second", "cargo two")], []]
    with patch("app.setup_database.embedding_client") as factory:
        client = factory.return_value.__enter__.return_value
        client.embeddings.create.return_value = MagicMock(data=[
            MagicMock(index=1, embedding=[0.2] * 1536),
            MagicMock(index=0, embedding=[0.1] * 1536),
        ])
        assert backfill_embeddings(connection, settings) == 2
        client.embeddings.create.assert_called_once_with(
            model=settings.azure_embed_deployment,
            input=["cargo one", "cargo two"], dimensions=1536, encoding_format="float",
        )
    statement, parameters = cursor.executemany.call_args.args
    assert "azure_openai.create_embeddings" not in statement
    assert "INSERT INTO horizon_ship.shipment_embeddings" in statement
    assert [(input_text, json.loads(vector)[0], row_id)
            for input_text, vector, row_id in parameters] == [
        ("cargo one", 0.1, "first"), ("cargo two", 0.2, "second"),
    ]


def test_backfill_rejects_partial_response_before_writing(live_settings: Settings) -> None:
    connection = MagicMock()
    cursor = connection.cursor.return_value.__enter__.return_value
    cursor.fetchall.return_value = [("first", "cargo")]
    with patch("app.setup_database.embedding_client") as factory:
        factory.return_value.__enter__.return_value.embeddings.create.return_value = MagicMock(
            data=[]
        )
        with pytest.raises(ValueError, match="requested inputs"):
            backfill_embeddings(connection, live_settings)
    cursor.executemany.assert_not_called()


def test_database_backfill_keeps_input_and_does_not_use_sdk(live_settings):
    connection = MagicMock()
    cursor = connection.cursor.return_value.__enter__.return_value
    cursor.fetchall.return_value = [("shipment-id", "unchanged embedding input")]
    cursor.fetchone.return_value = (json.dumps([0.1] * 1536),)
    settings = live_settings.model_copy(update={"embedding_provider": "horizondb"})
    with patch("app.setup_database.embedding_client") as sdk:
        assert backfill_embeddings(connection, settings) == 1
    sdk.assert_not_called()
    model_calls = [call for call in cursor.execute.call_args_list if "create_embeddings" in call.args[0]]
    assert len(model_calls) == 1
    assert model_calls[0].args[1] == (settings.embedding_model_alias, "unchanged embedding input")
    assert cursor.executemany.call_args.args[1][0][0] == "unchanged embedding input"


@pytest.mark.parametrize("configuration_changed,force,cleared", [
    (True, False, True), (False, False, False), (False, True, True),
])
def test_setup_invalidates_vectors_only_when_needed(
    live_settings: Settings, configuration_changed: bool, force: bool, cleared: bool,
) -> None:
    with (
        patch("app.setup_database.psycopg.connect") as connect,
        patch("app.setup_database.apply_schema"),
        patch("app.setup_database.configure_pipeline_model"),
        patch("app.setup_database.load_region_boundaries") as load_regions,
        patch("app.setup_database.seed_shipments"),
        patch("app.setup_database.configure_embeddings", return_value=configuration_changed),
        patch("app.setup_database.migrate_legacy_embeddings"),
        patch("app.setup_database.backfill_embeddings"),
        patch("app.setup_database.database_counts", return_value=(24, 24)),
        patch("app.setup_database.remove_legacy_embedding_column"),
        patch("app.setup_database.configure_embedding_pipeline"),
    ):
        result = setup_database(live_settings, force_embeddings=force)
        connection = connect.return_value.__enter__.return_value
        load_regions.assert_called_once_with(connection)
        statements = [call.args[0] for call in connection.execute.call_args_list]
        assert ("DELETE FROM horizon_ship.shipment_embeddings;" in statements) is cleared
        assert result.primary_index_ready
        assert result.embedding_configuration_changed is configuration_changed


@pytest.mark.parametrize("api_key", [None, "external-test-key"])
@pytest.mark.parametrize("status_code", [200, 401])
async def test_sdk_uses_foundry_v1_and_does_not_fallback_on_auth_failure(
    api_key: str | None, status_code: int,
) -> None:
    settings = Settings(
        _env_file=None,
        azure_openai_endpoint="https://example.services.ai.azure.com/openai/v1/responses",
        azure_openai_key=api_key,
    )
    requests: list[httpx.Request] = []

    def handle_request(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        assert str(request.url) == "https://example.services.ai.azure.com/openai/v1/embeddings"
        assert request.headers["Authorization"] == f"Bearer {api_key or 'entra-test-token'}"
        assert json.loads(request.content) == {
            "input": ["cargo"], "model": settings.azure_embed_deployment,
            "dimensions": 1536, "encoding_format": "float",
        }
        if status_code == 401:
            return httpx.Response(401, json={"error": {"message": "Unauthorized"}})
        return httpx.Response(200, json={
            "object": "list", "model": settings.azure_embed_deployment,
            "data": [{"object": "embedding", "index": 0, "embedding": [0.1] * 1536}],
            "usage": {"prompt_tokens": 1, "total_tokens": 1},
        })

    def make_client(**kwargs: Any) -> AsyncOpenAI:
        return AsyncOpenAI(
            **kwargs, http_client=httpx.AsyncClient(transport=httpx.MockTransport(handle_request))
        )

    async def get_token() -> str:
        return "entra-test-token"

    with (
        patch("app.embeddings.AsyncOpenAI", side_effect=make_client),
        patch("app.embeddings.AsyncDefaultAzureCredential") as credential,
        patch("app.embeddings.get_async_bearer_token_provider", return_value=get_token),
    ):
        async with async_embedding_client(settings) as client:
            if status_code == 401:
                with pytest.raises(AuthenticationError):
                    await client.embeddings.create(
                        model=settings.azure_embed_deployment, input=["cargo"],
                        dimensions=1536, encoding_format="float",
                    )
            else:
                response = await client.embeddings.create(
                    model=settings.azure_embed_deployment, input=["cargo"],
                    dimensions=1536, encoding_format="float",
                )
                assert len(json.loads(serialize_embeddings(response, 1)[0])) == 1536
        assert credential.call_count == (0 if api_key else 1)
        assert len(requests) == 1