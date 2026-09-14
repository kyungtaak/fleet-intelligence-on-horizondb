export type ShipmentStatus =
  | 'in_transit'
  | 'delivered'
  | 'delayed'
  | 'exception'
  | 'unknown'

export interface Coordinate {
  latitude: number
  longitude: number
}

export interface Shipment {
  id: string
  shipment_number: string
  title: string
  description: string
  origin_name: string
  origin: Coordinate
  destination_name: string
  destination: Coordinate
  current_location_name: string
  current_position: Coordinate
  status: ShipmentStatus
  eta: string | null
  updated_at: string
  metadata: {
    regions?: string[]
    tags?: string[]
    [key: string]: unknown
  }
  similarity: number | null
  remaining_distance_km: number | null
}

export interface DatabaseCapabilities {
  mode: 'horizondb'
  connected: boolean
  postgis_version: string | null
  vector_version: string | null
  diskann_version: string | null
  azure_ai_version: string | null
  shipment_count: number
  azure_embedding_count: number
  embedding_mode: 'azure_openai'
  embedding_model_alias: string
  agent_framework: true
  chat_model: string
  detail: string | null
}

export interface StatusCount {
  status: ShipmentStatus
  count: number
}

export interface ShipmentStats {
  total: number
  statuses: StatusCount[]
}

export interface SearchResponse {
  query: string
  search_mode: 'sql' | 'gis' | 'diskann_cosine' | 'hybrid' | 'not_searched'
  shipments: Shipment[]
  answer: string
  agent_framework: true
  chat_model: string
  has_more: boolean
  applied_filters: {
    cargo_query: string | null
    status: ShipmentStatus | null
    shipment_number: string | null
    origin_region: string | null
    destination_region: string | null
    origin_name: string | null
    destination_name: string | null
    nearby_location: string | null
    position_field: 'origin' | 'destination' | 'current'
    radius_km: number | null
    sort_by: 'destination_distance' | null
    result_limit: number | null
  } | null
}

export interface SearchProgress {
  type: 'progress'
  request_id: string
  sequence: number
  elapsed_ms: number
  stage: string
  message: string
  sql?: string
  parameters?: unknown[]
  filters?: Record<string, unknown>
  embedding_input?: string
  deployment?: string
  dimensions?: number
  fetched_count?: number
  returned_count?: number
  has_more?: boolean
  duration_ms?: number
}
