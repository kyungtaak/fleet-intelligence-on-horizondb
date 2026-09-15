from datetime import date, datetime, timedelta
from enum import StrEnum
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator
from pydantic.json_schema import SkipJsonSchema


class ShipmentStatus(StrEnum):
    IN_TRANSIT = "in_transit"
    DELIVERED = "delivered"
    DELAYED = "delayed"
    EXCEPTION = "exception"
    UNKNOWN = "unknown"


class Coordinate(BaseModel):
    latitude: float = Field(ge=-90, le=90)
    longitude: float = Field(ge=-180, le=180)


class Shipment(BaseModel):
    id: UUID
    shipment_number: str
    title: str
    description: str
    origin_name: str
    origin: Coordinate
    destination_name: str
    destination: Coordinate
    current_location_name: str
    current_position: Coordinate
    status: ShipmentStatus
    eta: date | None
    updated_at: datetime
    metadata: dict[str, Any] = Field(default_factory=dict)
    similarity: float | None = Field(default=None, ge=-1, le=1)
    remaining_distance_km: float | None = Field(default=None, ge=0)
    distance_to_center_km: float | None = Field(default=None, ge=0)
    hybrid_score: float | None = Field(default=None, ge=-0.72, le=1)


class ShipmentCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    shipment_number: str = Field(pattern=r"^SHIP-\d{4}$")
    title: str = Field(min_length=1, max_length=300)
    description: str = Field(min_length=1, max_length=2000)
    origin_name: str = Field(min_length=1, max_length=300)
    origin: Coordinate
    destination_name: str = Field(min_length=1, max_length=300)
    destination: Coordinate
    current_location_name: str = Field(min_length=1, max_length=300)
    current_position: Coordinate
    status: ShipmentStatus
    eta: date | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class ShipmentUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str | None = Field(default=None, min_length=1, max_length=300)
    description: str | None = Field(default=None, min_length=1, max_length=2000)
    origin_name: str | None = Field(default=None, min_length=1, max_length=300)
    origin: Coordinate | None = None
    destination_name: str | None = Field(default=None, min_length=1, max_length=300)
    destination: Coordinate | None = None
    current_location_name: str | None = Field(default=None, min_length=1, max_length=300)
    current_position: Coordinate | None = None
    status: ShipmentStatus | None = None
    eta: date | None = None
    metadata: dict[str, Any] | None = None

    @model_validator(mode="after")
    def validate_patch(self) -> "ShipmentUpdate":
        if not self.model_fields_set:
            raise ValueError("At least one shipment field is required")
        for field_name in self.model_fields_set - {"eta"}:
            if getattr(self, field_name) is None:
                raise ValueError(f"{field_name} cannot be null")
        return self


class ShipmentBulkCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    shipments: list[ShipmentCreate] = Field(min_length=1, max_length=20)


class DemoShipmentDelete(BaseModel):
    model_config = ConfigDict(extra="forbid")

    shipment_ids: list[UUID] = Field(min_length=1, max_length=3000)


class ShipmentEmbeddingState(BaseModel):
    shipment_number: str
    requested_version: int | None = None
    embedded_version: int | None = None
    state: Literal["pending", "ready"]


class ShipmentEmbeddingStatus(BaseModel):
    total: int
    ready: int
    pending: int
    shipments: list[ShipmentEmbeddingState]


class SearchRequest(BaseModel):
    query: str = Field(min_length=2, max_length=300)
    status: ShipmentStatus | None = None
    limit: int = Field(default=8, ge=1, le=24)


class ShipmentFilters(BaseModel):
    model_config = ConfigDict(extra="forbid")

    cargo_query: str | None = Field(default=None, min_length=2, max_length=300)
    status: ShipmentStatus | None = None
    shipment_number: str | None = Field(default=None, pattern=r"^SHIP-\d{4}$")
    origin_region: str | None = None
    destination_region: str | None = None
    origin_name: str | None = None
    destination_name: str | None = None
    nearby_location: str | None = None
    nearby_point: SkipJsonSchema[Coordinate | None] = None
    position_field: Literal["origin", "destination", "current"] = "current"
    radius_km: float | None = Field(default=None, gt=0, le=20000)
    eta_start: date | None = Field(default=None, description="Inclusive earliest ETA (YYYY-MM-DD).")
    eta_end: date | None = Field(default=None, description="Inclusive latest ETA (YYYY-MM-DD).")
    sort_by: Literal["destination_distance", "semantic_spatial"] | None = Field(
        default=None, description="Own destination distance, or explicit 72% semantic / 28% proximity ranking.",
    )
    result_limit: int | None = Field(default=None, ge=1, le=24)

    @model_validator(mode="after")
    def validate_ranking_and_dates(self) -> "ShipmentFilters":
        if self.nearby_location and self.nearby_point:
            raise ValueError("Choose a catalog location or a map point, not both")
        if self.eta_start and self.eta_end and self.eta_start > self.eta_end:
            raise ValueError("eta_start must not be after eta_end")
        if self.sort_by == "semantic_spatial" and not (
            self.cargo_query and self.cargo_query.strip()
            and (self.nearby_location or self.nearby_point) and self.radius_km
        ):
            raise ValueError("Semantic-spatial ranking requires cargo_query, nearby_location and radius_km")
        return self


class CriteriaSearchRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    query: str = Field(default="", max_length=300)
    status: ShipmentStatus | None = None
    eta_date: date | None = None
    eta_days: int = Field(default=3, ge=0, le=365)
    search_center: Coordinate | None = None
    radius_km: float = Field(default=500, gt=0, le=20000)
    ranking: Literal["semantic", "semantic_spatial"] = "semantic"
    limit: int = Field(default=24, ge=1, le=24)

    def to_filters(self) -> ShipmentFilters:
        try:
            start = self.eta_date - timedelta(days=self.eta_days) if self.eta_date else None
            end = self.eta_date + timedelta(days=self.eta_days) if self.eta_date else None
        except OverflowError as exc:
            raise ValueError("ETA tolerance exceeds the supported date range") from exc
        return ShipmentFilters(
            cargo_query=self.query.strip() or None, status=self.status,
            eta_start=start, eta_end=end,
            nearby_point=self.search_center,
            radius_km=self.radius_km if self.search_center else None,
            sort_by="semantic_spatial" if self.ranking == "semantic_spatial" else None,
        )

    @model_validator(mode="after")
    def validate_criteria(self) -> "CriteriaSearchRequest":
        self.to_filters()
        return self


SearchMode = Literal["sql", "gis", "diskann_cosine", "hybrid"]


class ShipmentSearchResult(BaseModel):
    shipments: list[Shipment]
    search_mode: SearchMode
    has_more: bool = False
    applied_filters: ShipmentFilters


class SearchResponse(BaseModel):
    query: str
    search_mode: SearchMode
    shipments: list[Shipment]


class CriteriaSearchResponse(SearchResponse):
    has_more: bool = False
    applied_filters: ShipmentFilters


class ChatResponse(SearchResponse):
    search_mode: SearchMode | Literal["not_searched"]
    answer: str
    agent_framework: Literal[True] = True
    chat_model: str
    chat_provider: Literal["azure_openai", "horizondb"] = "azure_openai"
    embedding_provider: Literal["azure_openai", "horizondb"] = "azure_openai"
    has_more: bool = False
    applied_filters: ShipmentFilters | None = None


class StatusCount(BaseModel):
    status: ShipmentStatus
    count: int


class ShipmentStats(BaseModel):
    total: int
    statuses: list[StatusCount]


class DatabaseCapabilities(BaseModel):
    mode: Literal["horizondb"] = "horizondb"
    connected: bool
    postgis_version: str | None = None
    vector_version: str | None = None
    diskann_version: str | None = None
    diskann_spherical_quantization: bool = False
    diskann_sq_bits: int | None = None
    diskann_sq_training_samples: int | None = None
    azure_ai_version: str | None = None
    shipment_count: int = 0
    azure_embedding_count: int = 0
    embedding_mode: Literal["azure_openai"] = "azure_openai"
    embedding_model_alias: str
    agent_framework: Literal[True] = True
    chat_model: str | None = None
    chat_provider: Literal["azure_openai", "horizondb"] = "azure_openai"
    embedding_provider: Literal["azure_openai", "horizondb"] = "azure_openai"
    chat_model_alias: str | None = None
    detail: str | None = None
