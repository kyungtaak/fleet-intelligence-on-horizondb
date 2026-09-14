import type {
  Coordinate,
  Shipment,
  ShipmentCreateInput,
  ShipmentUpdateInput,
} from './types'

export type UpdateScenario = 'delay' | 'exception' | 'delivered' | 'position'

interface DemoCargo {
  title: string
  description: string
  tags: string[]
}

interface DemoRoute {
  origin: [string, number, number]
  destination: [string, number, number]
  current: [string, number, number]
  regions: string[]
}

const CARGO_GROUPS: DemoCargo[] = [
  {
    title: 'Cold-Chain Biologics',
    description: 'Temperature-controlled vaccines, biologics, and diagnostic medicine for regional clinics.',
    tags: ['cold-chain', 'medical', 'biologics', 'pipeline-demo'],
  },
  {
    title: 'Humanitarian Relief Supplies',
    description: 'Emergency shelter kits, water filters, blankets, and disaster response equipment for aid teams.',
    tags: ['humanitarian', 'relief', 'emergency', 'pipeline-demo'],
  },
  {
    title: 'Renewable Energy Equipment',
    description: 'Solar inverters, wind power controls, and sustainable grid equipment for clean energy projects.',
    tags: ['renewable', 'energy', 'solar', 'wind', 'pipeline-demo'],
  },
  {
    title: 'Semiconductor Fabrication Tools',
    description: 'High-value semiconductor inspection tools, wafers, and precision electronics for chip fabrication.',
    tags: ['semiconductor', 'electronics', 'high-value', 'pipeline-demo'],
  },
]

const ROUTES: DemoRoute[] = [
  {
    origin: ['Incheon, South Korea', 37.4563, 126.7052],
    destination: ['Nairobi, Kenya', -1.2921, 36.8219],
    current: ['Dubai, UAE', 25.2048, 55.2708],
    regions: ['Asia', 'Middle East', 'Africa'],
  },
  {
    origin: ['Rotterdam, Netherlands', 51.9244, 4.4777],
    destination: ['Accra, Ghana', 5.6037, -0.187],
    current: ['Atlantic Ocean', 24.0, -18.0],
    regions: ['Europe', 'Africa'],
  },
  {
    origin: ['Shenzhen, China', 22.5431, 114.0579],
    destination: ['Los Angeles, USA', 34.0522, -118.2437],
    current: ['North Pacific Ocean', 31.0, -162.0],
    regions: ['Asia', 'North America'],
  },
  {
    origin: ['Copenhagen, Denmark', 55.6761, 12.5683],
    destination: ['Boston, USA', 42.3601, -71.0589],
    current: ['North Atlantic Ocean', 49.0, -31.0],
    regions: ['Europe', 'North America'],
  },
  {
    origin: ['Auckland, New Zealand', -36.8485, 174.7633],
    destination: ['Tokyo, Japan', 35.6895, 139.6917],
    current: ['Brisbane, Australia', -27.4698, 153.0251],
    regions: ['Oceania', 'Asia'],
  },
]

function coordinate(latitude: number, longitude: number): Coordinate {
  return { latitude, longitude }
}

function addDays(value: string | null, days: number): string {
  const date = value ? new Date(`${value}T00:00:00Z`) : new Date()
  date.setUTCDate(date.getUTCDate() + days)
  return date.toISOString().slice(0, 10)
}

function moveToward(current: Coordinate, destination: Coordinate, ratio: number): Coordinate {
  return {
    latitude: current.latitude + (destination.latitude - current.latitude) * ratio,
    longitude: current.longitude + (destination.longitude - current.longitude) * ratio,
  }
}

function allocateNumbers(shipments: Shipment[], count: number): string[] {
  const used = new Set(shipments.map((shipment) => shipment.shipment_number))
  const numbers: string[] = []
  for (let value = 7000; value <= 9999 && numbers.length < count; value += 1) {
    const shipmentNumber = `SHIP-${value}`
    if (!used.has(shipmentNumber)) numbers.push(shipmentNumber)
  }
  if (numbers.length !== count) throw new Error('데모 배송 번호를 할당할 수 없습니다.')
  return numbers
}

export function buildDemoShipments(
  existing: Shipment[],
  count: number,
): ShipmentCreateInput[] {
  const numbers = allocateNumbers(existing, count)
  const eta = addDays(null, 10)
  return numbers.map((shipmentNumber, index) => {
    const cargo = CARGO_GROUPS[Math.floor(index / 5) % CARGO_GROUPS.length]
    const route = ROUTES[index % ROUTES.length]
    return {
      shipment_number: shipmentNumber,
      title: cargo.title,
      description: cargo.description,
      origin_name: route.origin[0],
      origin: coordinate(route.origin[1], route.origin[2]),
      destination_name: route.destination[0],
      destination: coordinate(route.destination[1], route.destination[2]),
      current_location_name: route.current[0],
      current_position: coordinate(route.current[1], route.current[2]),
      status: index % 9 === 7 ? 'delayed' : index % 11 === 9 ? 'exception' : 'in_transit',
      eta,
      metadata: {
        regions: route.regions,
        tags: cargo.tags,
        demo_run: true,
      },
    }
  })
}

export function buildUpdate(
  shipment: Shipment,
  scenario: UpdateScenario,
): ShipmentUpdateInput {
  if (scenario === 'position') {
    return {
      current_position: moveToward(
        shipment.current_position,
        shipment.destination,
        0.35,
      ),
    }
  }
  if (scenario === 'delivered') {
    return {
      current_location_name: shipment.destination_name,
      current_position: shipment.destination,
      status: 'delivered',
      metadata: {
        ...shipment.metadata,
        tags: [...new Set([...(shipment.metadata.tags ?? []), 'delivered'])],
        demo_event: 'delivery-confirmed',
      },
    }
  }
  const status = scenario === 'delay' ? 'delayed' : 'exception'
  const event = scenario === 'delay' ? 'weather-delay' : 'cargo-exception'
  return {
    current_location_name: scenario === 'delay'
      ? `Weather hold near ${shipment.destination_name}`
      : `Inspection required near ${shipment.current_location_name}`,
    current_position: moveToward(
      shipment.current_position,
      shipment.destination,
      scenario === 'delay' ? 0.25 : 0.12,
    ),
    status,
    eta: addDays(shipment.eta, scenario === 'delay' ? 3 : 1),
    metadata: {
      ...shipment.metadata,
      tags: [...new Set([...(shipment.metadata.tags ?? []), status])],
      demo_event: event,
    },
  }
}