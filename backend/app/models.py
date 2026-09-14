from datetime import date, datetime
from enum import StrEnum
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator


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
    position_field: Literal["origin", "destination", "current"] = "current"
    radius_km: float | None = Field(default=None, gt=0, le=20000)
    sort_by: Literal["destination_distance"] | None = Field(
        default=None, description="Rank by distance from current position to each shipment's own destination.",
    )
    result_limit: int | None = Field(default=None, ge=1, le=24)


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


class ChatResponse(SearchResponse):
    search_mode: SearchMode | Literal["not_searched"]
    answer: str
    agent_framework: Literal[True] = True
    chat_model: str
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
    azure_ai_version: str | None = None
    shipment_count: int = 0
    azure_embedding_count: int = 0
    embedding_mode: Literal["azure_openai"] = "azure_openai"
    embedding_model_alias: str
    agent_framework: Literal[True] = True
    chat_model: str | None = None
    detail: str | None = None
