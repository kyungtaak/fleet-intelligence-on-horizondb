from app.models import ShipmentFilters
from app.region_boundaries import REGION_NAMES
from app.sample_data import build_sample_shipments

LOCATION_COORDINATES = {
    name: coordinate
    for shipment in build_sample_shipments()
    for name, coordinate in (
        (shipment.origin_name, shipment.origin),
        (shipment.destination_name, shipment.destination),
    )
}


def validate_filters(filters: ShipmentFilters) -> None:
    for region in (filters.origin_region, filters.destination_region):
        if region is not None and region not in REGION_NAMES:
            raise ValueError(f"Unsupported region: {region}")
    for location in (
        filters.origin_name, filters.destination_name, filters.nearby_location,
    ):
        if location is not None and location not in LOCATION_COORDINATES:
            raise ValueError(f"Unsupported location: {location}")
    if (filters.nearby_location is None and filters.nearby_point is None) != (filters.radius_km is None):
        raise ValueError("nearby_location and radius_km must be provided together")
    if filters.cargo_query is not None and not filters.cargo_query.strip():
        raise ValueError("cargo_query must not be blank")
    if filters.position_field != "current" and not (filters.nearby_location or filters.nearby_point):
        raise ValueError("position_field requires a distance condition")