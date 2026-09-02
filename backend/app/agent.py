import json
from typing import Annotated, Any, Literal, Protocol

from agent_framework import tool
from agent_framework.openai import OpenAIChatClient
from pydantic import Field

from app.config import Settings
from app.models import ChatResponse, SearchRequest, Shipment, ShipmentStatus
from app.repository import ShipmentRepository

StatusArgument = Literal[
    "all",
    "in_transit",
    "delivered",
    "delayed",
    "exception",
    "unknown",
]


class AgentRunner(Protocol):
    async def run(self, prompt: str) -> Any: ...


class AgentClient(Protocol):
    def as_agent(self, **kwargs: Any) -> AgentRunner: ...


def _shipment_tool_payload(shipments: list[Shipment], search_mode: str) -> str:
    return json.dumps(
        {
            "search_mode": search_mode,
            "matches": [
                {
                    "shipment_number": shipment.shipment_number,
                    "title": shipment.title,
                    "description": shipment.description,
                    "status": shipment.status.value,
                    "origin": shipment.origin_name,
                    "destination": shipment.destination_name,
                    "current_location": shipment.current_location_name,
                    "eta": shipment.eta.isoformat() if shipment.eta else None,
                    "cosine_similarity": shipment.similarity,
                }
                for shipment in shipments
            ],
        }
    )


class ShipmentAgent:
    def __init__(
        self,
        settings: Settings,
        repository: ShipmentRepository,
        client: AgentClient | None = None,
    ) -> None:
        if client is None and not settings.azure_openai_key:
            raise ValueError("AZURE_OPENAI_KEY is required for Agent Framework")

        self._settings = settings
        self._repository = repository
        self._client = client or OpenAIChatClient(
            model=settings.azure_openai_deployment,
            azure_endpoint=settings.azure_openai_endpoint,
            api_key=settings.azure_openai_key,
        )

    async def run(self, request: SearchRequest) -> ChatResponse:
        matched_shipments: list[Shipment] = []
        effective_search_mode = self._repository.search_mode

        @tool(
            description=(
                "Semantic search over global shipments using Azure OpenAI embeddings, "
                "pgvector cosine distance, and HorizonDB DiskANN with advanced filtering. "
                "Use this exactly once before answering every shipment question."
            ),
            max_invocations=1,
        )
        async def semantic_shipment_search(
            query_text: Annotated[
                str,
                Field(
                    description=(
                        "A concise natural-language description of the cargo, route, "
                        "region, or operational condition to find."
                    ),
                    min_length=2,
                ),
            ],
            status_filter: Annotated[
                StatusArgument,
                Field(
                    description=(
                        "Required structured status filter. Use 'all' unless the user "
                        "explicitly asks for in-transit, delivered, delayed, exception, "
                        "or unknown shipments."
                    )
                ),
            ] = "all",
        ) -> str:
            nonlocal effective_search_mode
            requested_status = request.status
            inferred_status = (
                None if status_filter == "all" else ShipmentStatus(status_filter)
            )
            effective_status = requested_status or inferred_status
            results = await self._repository.semantic_search(
                query=query_text,
                status=effective_status,
                limit=request.limit,
            )
            matched_shipments[:] = results
            effective_search_mode = self._repository.search_mode
            return _shipment_tool_payload(results, effective_search_mode)

        agent = self._client.as_agent(
            name="HorizonShipAgent",
            instructions=(
                "You are a concise shipping operations assistant. For every user "
                "question, call semantic_shipment_search exactly once before answering. "
                "Base every shipment number, route, status, ETA, and similarity claim "
                "only on the tool output. Mention the best matches and explain briefly "
                "why they fit. Never invent a shipment."
            ),
            tools=[semantic_shipment_search],
        )
        prompt = request.query
        if request.status is not None:
            prompt = f"{prompt}\nApply the required status filter: {request.status.value}."
        result = await agent.run(prompt)

        if not matched_shipments:
            matched_shipments[:] = await self._repository.semantic_search(
                query=request.query,
                status=request.status,
                limit=request.limit,
            )

        return ChatResponse(
            query=request.query,
            search_mode=effective_search_mode,
            shipments=matched_shipments,
            answer=result.text,
            agent_framework=True,
            chat_model=self._settings.azure_openai_deployment,
        )