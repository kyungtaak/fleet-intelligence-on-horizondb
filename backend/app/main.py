from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Annotated
from uuid import UUID

from fastapi import Depends, FastAPI, HTTPException, Query, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse

from app.agent import AgentClient, ShipmentAgent
from app.config import Settings, get_settings
from app.models import (
    ChatResponse,
    CriteriaSearchRequest,
    CriteriaSearchResponse,
    DatabaseCapabilities,
    DemoShipmentDelete,
    SearchRequest,
    SearchResponse,
    Shipment,
    ShipmentBulkCreate,
    ShipmentCreate,
    ShipmentEmbeddingStatus,
    ShipmentStats,
    ShipmentStatus,
    ShipmentUpdate,
)
from app.progress import stream_chat
from app.repository import (
    DemoEmbeddingPendingError,
    PostgresShipmentRepository,
    ShipmentAlreadyExistsError,
    ShipmentRepository,
)


def _get_repository(request: Request) -> ShipmentRepository:
    return request.app.state.repository


RepositoryDependency = Annotated[ShipmentRepository, Depends(_get_repository)]


def create_app(
    settings: Settings | None = None,
    repository: ShipmentRepository | None = None,
    agent_client: AgentClient | None = None,
) -> FastAPI:
    resolved_settings = settings or get_settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        resolved_settings.validate_live_configuration()
        active_repository = repository
        postgres_repository: PostgresShipmentRepository | None = None

        if active_repository is None:
            postgres_repository = PostgresShipmentRepository(resolved_settings)
            try:
                await postgres_repository.open()
            except Exception:
                await postgres_repository.close()
                raise
            active_repository = postgres_repository

        app.state.repository = active_repository
        app.state.shipment_agent = ShipmentAgent(
            resolved_settings,
            active_repository,
            client=agent_client,
        )
        yield

        if postgres_repository is not None:
            await postgres_repository.close()

    app = FastAPI(
        title=resolved_settings.app_name,
        version="0.1.0",
        description=(
            "Shipment tracking with Azure HorizonDB, PostGIS, pgvector, and DiskANN."
        ),
        lifespan=lifespan,
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=resolved_settings.cors_origins,
        allow_credentials=False,
        allow_methods=["GET", "POST", "PATCH", "DELETE"],
        allow_headers=["Content-Type"],
    )

    @app.get("/api/health", response_model=DatabaseCapabilities)
    async def health(
        shipment_repository: RepositoryDependency,
    ) -> DatabaseCapabilities:
        capabilities = await shipment_repository.capabilities()
        return capabilities.model_copy(
            update={
                "agent_framework": True,
                "chat_model": (
                    getattr(shipment_repository, "chat_model_name", resolved_settings.chat_model_alias)
                    if resolved_settings.chat_provider == "horizondb"
                    else resolved_settings.azure_openai_deployment
                ),
                "chat_provider": resolved_settings.chat_provider,
                "embedding_provider": resolved_settings.embedding_provider,
                "chat_model_alias": (
                    resolved_settings.chat_model_alias
                    if resolved_settings.chat_provider == "horizondb" else None
                ),
            }
        )

    @app.get("/api/shipments", response_model=list[Shipment])
    async def list_shipments(
        shipment_repository: RepositoryDependency,
        shipment_status: Annotated[
            ShipmentStatus | None,
            Query(alias="status"),
        ] = None,
        search: Annotated[
            str | None,
            Query(min_length=1, max_length=100),
        ] = None,
    ) -> list[Shipment]:
        return await shipment_repository.list_shipments(shipment_status, search)

    @app.post(
        "/api/shipments",
        response_model=Shipment,
        status_code=status.HTTP_201_CREATED,
    )
    async def create_shipment(
        request: ShipmentCreate,
        shipment_repository: RepositoryDependency,
    ) -> Shipment:
        try:
            return await shipment_repository.create_shipment(request)
        except ShipmentAlreadyExistsError as exc:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Shipment number already exists",
            ) from exc

    @app.post(
        "/api/shipments/bulk",
        response_model=list[Shipment],
        status_code=status.HTTP_201_CREATED,
    )
    async def create_shipments(
        request: ShipmentBulkCreate,
        shipment_repository: RepositoryDependency,
    ) -> list[Shipment]:
        try:
            return await shipment_repository.create_shipments(request.shipments)
        except ShipmentAlreadyExistsError as exc:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="One or more shipment numbers already exist",
            ) from exc

    @app.get("/api/shipments/stats", response_model=ShipmentStats)
    async def shipment_stats(
        shipment_repository: RepositoryDependency,
    ) -> ShipmentStats:
        return await shipment_repository.stats()

    @app.delete("/api/shipments/demo", response_model=list[UUID])
    async def delete_demo_shipments(
        request: DemoShipmentDelete,
        shipment_repository: RepositoryDependency,
    ) -> list[UUID]:
        try:
            return await shipment_repository.delete_demo_shipments(request.shipment_ids)
        except DemoEmbeddingPendingError as exc:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Demo embeddings are still pending. Wait for completion before deleting.",
            ) from exc

    @app.get(
        "/api/shipments/embedding-status",
        response_model=ShipmentEmbeddingStatus,
    )
    async def shipment_embedding_status(
        shipment_repository: RepositoryDependency,
        shipment_numbers: Annotated[
            list[str],
            Query(alias="shipment_number"),
        ],
    ) -> ShipmentEmbeddingStatus:
        return await shipment_repository.embedding_status(
            [shipment_number.upper() for shipment_number in shipment_numbers]
        )

    @app.get("/api/shipments/{shipment_number}", response_model=Shipment)
    async def shipment_detail(
        shipment_number: str,
        shipment_repository: RepositoryDependency,
    ) -> Shipment:
        shipment = await shipment_repository.get_shipment(shipment_number.upper())
        if shipment is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Shipment not found",
            )
        return shipment

    @app.patch("/api/shipments/{shipment_number}", response_model=Shipment)
    async def update_shipment(
        shipment_number: str,
        request: ShipmentUpdate,
        shipment_repository: RepositoryDependency,
    ) -> Shipment:
        shipment = await shipment_repository.update_shipment(
            shipment_number.upper(), request,
        )
        if shipment is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Shipment not found",
            )
        return shipment

    @app.post("/api/search/criteria", response_model=CriteriaSearchResponse)
    async def criteria_search(
        request: CriteriaSearchRequest,
        shipment_repository: RepositoryDependency,
    ) -> CriteriaSearchResponse:
        result = await shipment_repository.search_shipments(request.to_filters(), request.limit)
        return CriteriaSearchResponse(query=request.query, **result.model_dump())

    @app.post("/api/search", response_model=SearchResponse)
    async def semantic_search(
        request: SearchRequest,
        shipment_repository: RepositoryDependency,
    ) -> SearchResponse:
        shipments = await shipment_repository.semantic_search(
            query=request.query,
            status=request.status,
            limit=request.limit,
        )
        return SearchResponse(
            query=request.query,
            search_mode=shipment_repository.search_mode,
            shipments=shipments,
        )

    @app.post("/api/chat", response_model=ChatResponse)
    async def agent_chat(
        request: SearchRequest,
        http_request: Request,
    ) -> ChatResponse:
        shipment_agent: ShipmentAgent = http_request.app.state.shipment_agent
        return await shipment_agent.run(request)

    @app.post("/api/chat/stream")
    async def agent_chat_stream(request: SearchRequest, http_request: Request) -> StreamingResponse:
        shipment_agent: ShipmentAgent = http_request.app.state.shipment_agent
        return StreamingResponse(
            stream_chat(lambda: shipment_agent.run(request)),
            media_type="application/x-ndjson",
            headers={"Cache-Control": "no-store", "X-Accel-Buffering": "no"},
        )

    return app


app = create_app()
