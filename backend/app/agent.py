import json
from typing import Annotated, Any, Protocol

from agent_framework import tool
from agent_framework.openai import OpenAIChatClient
from azure.identity import DefaultAzureCredential
from pydantic import Field

from app.config import Settings
from app.embeddings import openai_base_url
from app.models import ChatResponse, SearchRequest, ShipmentFilters, ShipmentSearchResult
from app.progress import report_progress
from app.region_boundaries import REGION_NAMES
from app.repository import ShipmentRepository
from app.search_locations import LOCATION_COORDINATES


class AgentRunner(Protocol):
    async def run(self, prompt: str) -> Any: ...


class AgentClient(Protocol):
    def as_agent(self, **kwargs: Any) -> AgentRunner: ...


def _shipment_tool_payload(result: ShipmentSearchResult) -> str:
    return json.dumps(
        {
            "search_mode": result.search_mode,
            "applied_filters": result.applied_filters.model_dump(mode="json"),
            "has_more": result.has_more,
            "returned_count": len(result.shipments),
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
                    "remaining_distance_km": shipment.remaining_distance_km,
                }
                for shipment in result.shipments
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
        self._settings = settings
        self._repository = repository
        if client is not None:
            self._client = client
        elif settings.azure_openai_key:
            self._client = OpenAIChatClient(
                model=settings.azure_openai_deployment,
                azure_endpoint=openai_base_url(settings.azure_openai_endpoint).removesuffix(
                    "openai/v1/"
                ),
                api_key=settings.azure_openai_key,
            )
        else:
            self._client = OpenAIChatClient(
                model=settings.azure_openai_deployment,
                azure_endpoint=openai_base_url(settings.azure_openai_endpoint).removesuffix(
                    "openai/v1/"
                ),
                credential=DefaultAzureCredential(),
            )

    async def run(self, request: SearchRequest) -> ChatResponse:
        search_result: ShipmentSearchResult | None = None
        tool_called = False

        @tool(
            description=(
                "Search shipments using exact SQL conditions and PostGIS distances. "
                "Only set cargo_query when semantic cargo matching is needed. "
                "Use this exactly once for a supported shipment search."
            ),
            max_invocations=1,
        )
        async def search_shipments(
            filters: Annotated[
                ShipmentFilters,
                Field(
                    description=(
                        "Exact status, shipment_number, origin/destination region or place. "
                        "For distance use a catalog nearby_location, radius_km and "
                        "position_field (current by default). cargo_query contains ONLY "
                        "cargo meaning, never status, geography, IDs, or output instructions."
                    )
                ),
            ],
        ) -> str:
            nonlocal search_result, tool_called
            if tool_called:
                raise ValueError("Only one shipment search is allowed per request")
            tool_called = True
            filters = ShipmentFilters.model_validate(filters)
            if request.status is not None:
                filters = filters.model_copy(update={"status": request.status})
            report_progress(
                "filters", "검색 조건을 확인했습니다.",
                filters=filters.model_dump(mode="json", exclude_none=True),
            )
            search_result = await self._repository.search_shipments(
                filters=filters, limit=request.limit,
            )
            report_progress(
                "answer", "조회 결과로 한국어 답변을 작성하고 있습니다.",
                returned_count=len(search_result.shipments), has_more=search_result.has_more,
            )
            return _shipment_tool_payload(search_result)

        agent = self._client.as_agent(
            name="HorizonShipAgent",
            instructions=(
                "You are a concise shipping operations assistant. For every user "
                "supported search, call search_shipments exactly once before answering. "
                "Base every shipment number, route, status, ETA, and similarity claim "
                "only on the tool output. Mention the best matches and explain briefly "
                "why they fit. Never invent a shipment. "
                "Always answer in Korean using polite, natural Korean sentences, "
                "even when the question or tool output is in English. "
                "Translate cargo descriptions, locations, and status labels into Korean "
                "where appropriate, preserving shipment numbers, proper names, dates, "
                "and numeric values accurately. Format answers in Markdown with short "
                "paragraphs, lists, and bold shipment numbers when useful. "
                "Use compact headings and avoid wide tables in this narrow chat panel. "
                "Do not wrap the entire answer in a code fence or emit raw HTML. "
                "Use exact structured filters for every explicit constraint. "
                "Set cargo_query to null for status-only, region-only, place-only, ID, "
                "or distance-only questions including destination_distance sorting. Use it ONLY for cargo meaning such as "
                "medical supplies. Never put exact constraints into cargo_query instead "
                "of filters. An Asia origin is origin_region='Asia', not destination_region. "
                "Example delayed shipments: filters={status:'delayed'}. "
                "Example '목적지에 가장 가까운 2개' (also with Markdown bold): "
                "filters={sort_by:'destination_distance',result_limit:2}. This means shortest "
                "distance from each shipment's CURRENT position to its OWN destination; "
                "no named city or radius is required. Do not ask for a reference city in this case. "
                "Example '로테르담으로 가는 운송 중 배송 중 목적지에 가장 가까운 2개': "
                "filters={destination_name:'Rotterdam, Netherlands',status:'in_transit',"
                "sort_by:'destination_distance',result_limit:2}. "
                "Set result_limit to the user's requested count (1..24); the request's display "
                "limit may cap the result further. Distance sorting excludes delivered shipments "
                "by default unless an explicit status is supplied. Explain this default when used. "
                "Report remaining_distance_km from tool results, preserving their distance order. "
                "This is geodesic distance, not remaining route distance or arrival time. "
                "For '도착 임박' without an explicit distance criterion ask whether distance or ETA "
                "is intended; ETA sorting is not supported yet. Combining cargo meaning with "
                "destination-distance ranking is not supported; ask which ranking is intended "
                "without calling the tool. Never silently omit either constraint. "
                "Example medical cargo departing Asia: "
                "filters={origin_region:'Asia',cargo_query:'medical supplies'}. "
                "Example current position within 100km of Busan: "
                "filters={nearby_location:'Busan, South Korea',radius_km:100,position_field:'current'}. "
                "Never invent coordinates or use approximate bounding boxes for continents. "
                "Use only the supported catalog names below, translating Korean place names "
                "to these exact names. Region filters compare shipment coordinates with "
                "stored Natural Earth 1:50m country polygons grouped by CONTINENT using ST_Covers. "
                "Turkey including Istanbul is Asia; Russia is Europe under this country-level "
                "classification, not a physical continent split. Middle East is a separately "
                "documented country group including Egypt and Turkey. Points outside land "
                "polygons are excluded, including offshore ports; no coastline buffer is applied. "
                "Country-wide filters, dates, exclusions and other "
                "unsupported conditions must NOT be silently omitted or approximated by "
                "cargo_query. Ask for clarification in Korean without calling the tool. "
                "For an unlisted place or ambiguous distance center ask for clarification. "
                "Do not retry or relax conditions on zero matches. If has_more is true, "
                "state this is a limited result, not all matches. Similarity is relevance, "
                "not proof of a cargo category. Only report similarity when provided. "
                f"Supported regions: {json.dumps(REGION_NAMES)}. "
                f"Supported places: {json.dumps(sorted(LOCATION_COORDINATES))}."
            ),
            tools=[search_shipments],
        )
        prompt = request.query
        if request.status is not None:
            prompt = f"{prompt}\nApply the required status filter: {request.status.value}."
        report_progress("agent", "AI가 질문을 해석하고 검색 조건을 정하고 있습니다.")
        result = await agent.run(prompt)

        if tool_called and search_result is None:
            raise RuntimeError("Shipment search did not complete; no results were returned")

        return ChatResponse(
            query=request.query,
            search_mode=search_result.search_mode if search_result else "not_searched",
            shipments=search_result.shipments if search_result else [],
            answer=result.text,
            agent_framework=True,
            chat_model=self._settings.azure_openai_deployment,
            has_more=search_result.has_more if search_result else False,
            applied_filters=search_result.applied_filters if search_result else None,
        )