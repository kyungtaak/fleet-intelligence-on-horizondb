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
  distance_to_center_km: number | null
  hybrid_score: number | null
}

export type ShipmentCreateInput = Omit<
  Shipment,
  'id' | 'updated_at' | 'similarity' | 'remaining_distance_km' | 'distance_to_center_km' | 'hybrid_score'
>

export type ShipmentUpdateInput = Partial<
  Omit<ShipmentCreateInput, 'shipment_number'>
>

export interface ShipmentEmbeddingState {
  shipment_number: string
  requested_version: number | null
  embedded_version: number | null
  state: 'pending' | 'ready'
}

export interface ShipmentEmbeddingStatus {
  total: number
  ready: number
  pending: number
  shipments: ShipmentEmbeddingState[]
}

export interface DatabaseCapabilities {
  mode: 'horizondb'
  connected: boolean
  postgis_version: string | null
  vector_version: string | null
  diskann_version: string | null
  diskann_spherical_quantization: boolean
  diskann_sq_bits: number | null
  diskann_sq_training_samples: number | null
  azure_ai_version: string | null
  shipment_count: number
  azure_embedding_count: number
  embedding_mode: 'azure_openai'
  embedding_model_alias: string
  agent_framework: true
  chat_model: string
  chat_provider: 'azure_openai' | 'horizondb'
  embedding_provider: 'azure_openai' | 'horizondb'
  chat_model_alias: string | null
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
  chat_provider: 'azure_openai' | 'horizondb'
  embedding_provider: 'azure_openai' | 'horizondb'
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
    nearby_point: Coordinate | null
    position_field: 'origin' | 'destination' | 'current'
    radius_km: number | null
    eta_start: string | null
    eta_end: string | null
    sort_by: 'destination_distance' | 'semantic_spatial' | null
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
  provider?: 'azure_openai' | 'horizondb'
  model_alias?: string | null
  reference_date?: string
  timezone?: string
  plan?: QueryPlanNode
  plan_kind?: 'estimated'
}

export interface CriteriaSearchRequest {
  query: string
  status: ShipmentStatus | null
  eta_date: string | null
  eta_days: number
  search_center: Coordinate | null
  radius_km: number
  ranking: 'semantic' | 'semantic_spatial'
  limit: number
}

export interface CriteriaSearchResponse {
  query: string
  search_mode: Exclude<SearchResponse['search_mode'], 'not_searched'>
  shipments: Shipment[]
  has_more: boolean
  applied_filters: NonNullable<SearchResponse['applied_filters']>
}

export interface QueryPlanNode {
  'Node Type': string
  'Relation Name'?: string
  'Index Name'?: string
  'Total Cost'?: number
  'Startup Cost'?: number
  'Plan Rows'?: number
  'Plan Width'?: number
  Plans?: QueryPlanNode[]
}
