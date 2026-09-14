import json
import math
from collections.abc import AsyncIterator, Iterator
from contextlib import AsyncExitStack, ExitStack, asynccontextmanager, contextmanager
from urllib.parse import urlsplit, urlunsplit

from azure.identity import DefaultAzureCredential, get_bearer_token_provider
from azure.identity.aio import (
    DefaultAzureCredential as AsyncDefaultAzureCredential,
)
from azure.identity.aio import (
    get_bearer_token_provider as get_async_bearer_token_provider,
)
from openai import AsyncOpenAI, OpenAI
from openai.types import CreateEmbeddingResponse

from app.config import Settings

EMBEDDING_DIMENSIONS = 1536
TOKEN_SCOPE = "https://cognitiveservices.azure.com/.default"


def openai_base_url(endpoint: str) -> str:
    parts = urlsplit(endpoint.strip())
    if parts.scheme != "https" or not parts.hostname or parts.username or parts.password:
        raise ValueError("AZURE_OPENAI_ENDPOINT must be an HTTPS endpoint without credentials")
    if parts.query or parts.fragment:
        raise ValueError("AZURE_OPENAI_ENDPOINT must not contain a query or fragment")
    path = parts.path.rstrip("/")
    if path not in ("", "/openai/v1", "/openai/v1/responses", "/openai/v1/embeddings"):
        raise ValueError("Use the resource endpoint or its /openai/v1/ endpoint")
    return urlunsplit((parts.scheme, parts.netloc, "/openai/v1/", "", ""))


@contextmanager
def embedding_client(settings: Settings) -> Iterator[OpenAI]:
    with ExitStack() as stack:
        api_key = settings.azure_openai_key
        if not api_key:
            credential = stack.enter_context(DefaultAzureCredential())
            api_key = get_bearer_token_provider(credential, TOKEN_SCOPE)
        client = stack.enter_context(OpenAI(
            base_url=openai_base_url(settings.azure_openai_endpoint),
            api_key=api_key,
        ))
        yield client


@asynccontextmanager
async def async_embedding_client(settings: Settings) -> AsyncIterator[AsyncOpenAI]:
    async with AsyncExitStack() as stack:
        api_key = settings.azure_openai_key
        if not api_key:
            credential = await stack.enter_async_context(AsyncDefaultAzureCredential())
            api_key = get_async_bearer_token_provider(credential, TOKEN_SCOPE)
        client = await stack.enter_async_context(AsyncOpenAI(
            base_url=openai_base_url(settings.azure_openai_endpoint),
            api_key=api_key,
        ))
        yield client


def serialize_embeddings(response: CreateEmbeddingResponse, count: int) -> list[str]:
    items = sorted(response.data, key=lambda item: item.index)
    if [item.index for item in items] != list(range(count)):
        raise ValueError("Embedding response does not match the requested inputs")
    vectors: list[str] = []
    for item in items:
        if len(item.embedding) != EMBEDDING_DIMENSIONS or not all(
            math.isfinite(value) for value in item.embedding
        ):
            raise ValueError("Expected a finite 1536-dimensional embedding")
        vectors.append(json.dumps(item.embedding, allow_nan=False))
    return vectors