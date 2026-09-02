from datetime import UTC, date, datetime, timedelta
from typing import Any
from uuid import NAMESPACE_URL, uuid5

from app.models import Coordinate, Shipment, ShipmentStatus


_SAMPLE_ROWS: tuple[dict[str, Any], ...] = (
    {"number": "SHIP-0001", "title": "Consumer Electronics", "description": "Tablets, displays, and networking equipment for North American retailers.", "origin": ("Shenzhen, China", 22.5431, 114.0579), "destination": ("Los Angeles, USA", 34.0522, -118.2437), "current": ("North Pacific Ocean", 30.0, -150.0), "status": "in_transit", "eta": date(2026, 9, 8), "minutes": 42, "regions": ["Asia", "North America"], "tags": ["electronics", "priority"]},
    {"number": "SHIP-0002", "title": "Medical Supplies", "description": "PPE, diagnostic kits, and emergency medical equipment for hospitals and clinics.", "origin": ("Shanghai, China", 31.2304, 121.4737), "destination": ("Rotterdam, Netherlands", 51.9244, 4.4777), "current": ("Suez Canal, Egypt", 29.97, 32.55), "status": "in_transit", "eta": date(2026, 9, 6), "minutes": 120, "regions": ["Asia", "Europe", "Middle East"], "tags": ["medical", "emergency", "priority"]},
    {"number": "SHIP-0003", "title": "Automotive Parts", "description": "Precision automotive components for electric vehicle assembly.", "origin": ("Stuttgart, Germany", 48.7758, 9.1829), "destination": ("Hamburg, Germany", 53.5511, 9.9937), "current": ("Hamburg, Germany", 53.5511, 9.9937), "status": "delivered", "eta": date(2026, 8, 31), "minutes": 1440, "regions": ["Europe"], "tags": ["automotive", "electric", "sustainable"]},
    {"number": "SHIP-0004", "title": "Furniture Collection", "description": "Finished furniture and home goods for retail distribution.", "origin": ("Ho Chi Minh City, Vietnam", 10.8231, 106.6297), "destination": ("Singapore", 1.3521, 103.8198), "current": ("Singapore Strait", 1.2, 103.6), "status": "in_transit", "eta": date(2026, 9, 3), "minutes": 180, "regions": ["Asia"], "tags": ["furniture", "retail"]},
    {"number": "SHIP-0005", "title": "Apparel and Textiles", "description": "Seasonal garments, textiles, and fashion accessories.", "origin": ("Mumbai, India", 19.076, 72.8777), "destination": ("Dubai, UAE", 25.2048, 55.2708), "current": ("Arabian Sea", 20.0, 64.0), "status": "delayed", "eta": date(2026, 9, 5), "minutes": 300, "regions": ["Asia", "Middle East"], "tags": ["apparel", "textiles", "delayed"]},
    {"number": "SHIP-0006", "title": "Industrial Machinery", "description": "Heavy industrial machinery and replacement equipment components.", "origin": ("Houston, USA", 29.7604, -95.3698), "destination": ("Toronto, Canada", 43.6532, -79.3832), "current": ("Chicago, USA", 41.8781, -87.6298), "status": "in_transit", "eta": date(2026, 9, 4), "minutes": 28, "regions": ["North America"], "tags": ["machinery", "industrial"]},
    {"number": "SHIP-0007", "title": "Cold-Chain Vaccines", "description": "Temperature-controlled vaccines and pharmaceutical supplies for regional clinics.", "origin": ("Boston, USA", 42.3601, -71.0589), "destination": ("Nairobi, Kenya", -1.2921, 36.8219), "current": ("Dakar, Senegal", 14.7167, -17.4677), "status": "exception", "eta": date(2026, 9, 7), "minutes": 18, "regions": ["North America", "Africa"], "tags": ["medical", "cold-chain", "temperature-alert", "priority"]},
    {"number": "SHIP-0008", "title": "Solar Panels", "description": "Renewable energy solar panels and installation electronics.", "origin": ("Guangzhou, China", 23.1291, 113.2644), "destination": ("Sydney, Australia", -33.8688, 151.2093), "current": ("Timor Sea", -10.0, 132.0), "status": "in_transit", "eta": date(2026, 9, 11), "minutes": 60, "regions": ["Asia", "Oceania"], "tags": ["energy", "solar", "sustainable"]},
    {"number": "SHIP-0009", "title": "Coffee Beans", "description": "Fresh agricultural coffee beans for European roasters.", "origin": ("Santos, Brazil", -23.9608, -46.3289), "destination": ("Antwerp, Belgium", 51.2194, 4.4025), "current": ("Atlantic Ocean", 15.0, -25.0), "status": "in_transit", "eta": date(2026, 9, 12), "minutes": 240, "regions": ["South America", "Europe"], "tags": ["food", "coffee", "agricultural"]},
    {"number": "SHIP-0010", "title": "Aircraft Components", "description": "Time-sensitive aerospace components and precision machinery.", "origin": ("Toulouse, France", 43.6047, 1.4442), "destination": ("Seattle, USA", 47.6062, -122.3321), "current": ("Reykjavik, Iceland", 64.1466, -21.9426), "status": "in_transit", "eta": date(2026, 9, 3), "minutes": 36, "regions": ["Europe", "North America"], "tags": ["aircraft", "machinery", "priority"]},
    {"number": "SHIP-0011", "title": "Lithium Batteries", "description": "Hazardous certified lithium battery modules for consumer electronics.", "origin": ("Seoul, South Korea", 37.5665, 126.978), "destination": ("San Francisco, USA", 37.7749, -122.4194), "current": ("North Pacific Ocean", 39.0, 170.0), "status": "delayed", "eta": date(2026, 9, 10), "minutes": 22, "regions": ["Asia", "North America"], "tags": ["electronics", "energy", "hazardous", "delayed"]},
    {"number": "SHIP-0012", "title": "Fresh Produce", "description": "Refrigerated fresh produce and premium food ingredients.", "origin": ("Auckland, New Zealand", -36.8485, 174.7633), "destination": ("Tokyo, Japan", 35.6895, 139.6917), "current": ("Brisbane, Australia", -27.4698, 153.0251), "status": "in_transit", "eta": date(2026, 9, 8), "minutes": 55, "regions": ["Oceania", "Asia"], "tags": ["food", "fresh", "cold-chain"]},
    {"number": "SHIP-0013", "title": "Humanitarian Relief Tents", "description": "Emergency shelter and disaster relief equipment for aid teams.", "origin": ("Istanbul, Turkey", 41.0082, 28.9784), "destination": ("Amman, Jordan", 31.9539, 35.9106), "current": ("Amman, Jordan", 31.9539, 35.9106), "status": "delivered", "eta": date(2026, 8, 30), "minutes": 2880, "regions": ["Europe", "Middle East"], "tags": ["emergency", "humanitarian", "relief"]},
    {"number": "SHIP-0014", "title": "Hospital Equipment", "description": "Medical imaging equipment and hospital furniture for a new clinic.", "origin": ("Shenzhen, China", 22.5431, 114.0579), "destination": ("Los Angeles, USA", 34.0522, -118.2437), "current": ("Honolulu, USA", 21.3069, -157.8583), "status": "in_transit", "eta": date(2026, 9, 9), "minutes": 47, "regions": ["Asia", "North America"], "tags": ["medical", "hospital", "equipment"]},
    {"number": "SHIP-0015", "title": "Natural Gas Equipment", "description": "Industrial valves and hazardous gas processing machinery.", "origin": ("Doha, Qatar", 25.2854, 51.531), "destination": ("Singapore", 1.3521, 103.8198), "current": ("Indian Ocean", 5.0, 75.0), "status": "in_transit", "eta": date(2026, 9, 13), "minutes": 180, "regions": ["Middle East", "Asia"], "tags": ["energy", "gas", "hazardous", "machinery"]},
    {"number": "SHIP-0016", "title": "Wind Turbine Components", "description": "Renewable energy turbine blades and sustainable power equipment.", "origin": ("Copenhagen, Denmark", 55.6761, 12.5683), "destination": ("Boston, USA", 42.3601, -71.0589), "current": ("North Atlantic Ocean", 48.0, -35.0), "status": "in_transit", "eta": date(2026, 9, 15), "minutes": 60, "regions": ["Europe", "North America"], "tags": ["energy", "wind", "sustainable", "machinery"]},
    {"number": "SHIP-0017", "title": "Pharmaceuticals", "description": "Temperature-controlled pharmaceutical medicine for African hospitals.", "origin": ("Basel, Switzerland", 47.5596, 7.5886), "destination": ("Johannesburg, South Africa", -26.2041, 28.0473), "current": ("Cairo, Egypt", 30.0444, 31.2357), "status": "in_transit", "eta": date(2026, 9, 7), "minutes": 12, "regions": ["Europe", "Africa"], "tags": ["medical", "pharmaceutical", "cold-chain", "priority"]},
    {"number": "SHIP-0018", "title": "Semiconductor Wafers", "description": "High-value computer chips and semiconductor electronics for fabrication.", "origin": ("Taipei, Taiwan", 25.033, 121.5654), "destination": ("Dresden, Germany", 51.0504, 13.7373), "current": ("Singapore", 1.3521, 103.8198), "status": "in_transit", "eta": date(2026, 9, 6), "minutes": 25, "regions": ["Asia", "Europe"], "tags": ["electronics", "semiconductor", "priority"]},
    {"number": "SHIP-0019", "title": "Grain Cargo", "description": "Agricultural grain and food staples held for customs inspection.", "origin": ("Odesa, Ukraine", 46.4825, 30.7233), "destination": ("Alexandria, Egypt", 31.2001, 29.9187), "current": ("Black Sea", 43.0, 33.0), "status": "exception", "eta": date(2026, 9, 4), "minutes": 9, "regions": ["Europe", "Africa"], "tags": ["food", "grain", "customs", "exception"]},
    {"number": "SHIP-0020", "title": "Electric Vehicles", "description": "Finished electric vehicles for European automotive distribution.", "origin": ("Shanghai, China", 31.2304, 121.4737), "destination": ("Rotterdam, Netherlands", 51.9244, 4.4777), "current": ("Arabian Sea", 12.0, 65.0), "status": "delayed", "eta": date(2026, 9, 14), "minutes": 44, "regions": ["Asia", "Europe"], "tags": ["automotive", "electric", "sustainable", "delayed"]},
    {"number": "SHIP-0021", "title": "Emergency Medical Kits", "description": "Emergency medical kits, surgical supplies, and medicine for disaster response.", "origin": ("Frankfurt, Germany", 50.1109, 8.6821), "destination": ("Dubai, UAE", 25.2048, 55.2708), "current": ("Istanbul, Turkey", 41.0082, 28.9784), "status": "in_transit", "eta": date(2026, 9, 3), "minutes": 7, "regions": ["Europe", "Middle East"], "tags": ["medical", "emergency", "priority"]},
    {"number": "SHIP-0022", "title": "Education Supplies", "description": "Books, classroom materials, and computer equipment for schools.", "origin": ("London, United Kingdom", 51.5072, -0.1276), "destination": ("Accra, Ghana", 5.6037, -0.187), "current": ("Lisbon, Portugal", 38.7223, -9.1393), "status": "in_transit", "eta": date(2026, 9, 10), "minutes": 120, "regions": ["Europe", "Africa"], "tags": ["education", "books", "electronics"]},
    {"number": "SHIP-0023", "title": "Fresh Seafood", "description": "Refrigerated seafood and fresh food under continuous cold-chain monitoring.", "origin": ("Reykjavik, Iceland", 64.1466, -21.9426), "destination": ("New York, USA", 40.7128, -74.006), "current": ("Halifax, Canada", 44.6488, -63.5752), "status": "in_transit", "eta": date(2026, 9, 5), "minutes": 31, "regions": ["Europe", "North America"], "tags": ["food", "seafood", "cold-chain"]},
    {"number": "SHIP-0024", "title": "Construction Steel", "description": "Structural steel and heavy construction components with an unreported position update.", "origin": ("Busan, South Korea", 35.1796, 129.0756), "destination": ("Vancouver, Canada", 49.2827, -123.1207), "current": ("North Pacific Ocean", 43.0, 150.0), "status": "unknown", "eta": date(2026, 9, 16), "minutes": 480, "regions": ["Asia", "North America"], "tags": ["steel", "construction", "unknown"]},
)


def build_sample_shipments(now: datetime | None = None) -> list[Shipment]:
    reference_time = now or datetime.now(UTC)
    shipments: list[Shipment] = []

    for row in _SAMPLE_ROWS:
        origin_name, origin_latitude, origin_longitude = row["origin"]
        destination_name, destination_latitude, destination_longitude = row["destination"]
        current_name, current_latitude, current_longitude = row["current"]
        shipments.append(
            Shipment(
                id=uuid5(NAMESPACE_URL, row["number"]),
                shipment_number=row["number"],
                title=row["title"],
                description=row["description"],
                origin_name=origin_name,
                origin=Coordinate(latitude=origin_latitude, longitude=origin_longitude),
                destination_name=destination_name,
                destination=Coordinate(
                    latitude=destination_latitude,
                    longitude=destination_longitude,
                ),
                current_location_name=current_name,
                current_position=Coordinate(
                    latitude=current_latitude,
                    longitude=current_longitude,
                ),
                status=ShipmentStatus(row["status"]),
                eta=row["eta"],
                updated_at=reference_time - timedelta(minutes=row["minutes"]),
                metadata={"regions": row["regions"], "tags": row["tags"]},
            )
        )

    return shipments
