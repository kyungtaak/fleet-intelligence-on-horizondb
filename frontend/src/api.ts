import type {
  DatabaseCapabilities,
  SearchResponse,
  Shipment,
  ShipmentStats,
  ShipmentStatus,
} from './types'

const API_BASE = (import.meta.env.VITE_API_URL ?? '').replace(/\/$/, '')

async function apiRequest<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${API_BASE}${path}`, {
    ...init,
    headers: {
      'Content-Type': 'application/json',
      ...init?.headers,
    },
  })

  if (!response.ok) {
    const detail = await response.json().catch(() => null)
    const message =
      typeof detail?.detail === 'string'
        ? detail.detail
        : `Request failed with status ${response.status}`
    throw new Error(message)
  }

  return response.json() as Promise<T>
}

export function getCapabilities(): Promise<DatabaseCapabilities> {
  return apiRequest('/api/health')
}

export function getShipments(): Promise<Shipment[]> {
  return apiRequest('/api/shipments')
}

export function getShipmentStats(): Promise<ShipmentStats> {
  return apiRequest('/api/shipments/stats')
}

export function searchShipments(
  query: string,
  status: ShipmentStatus | null,
): Promise<SearchResponse> {
  return apiRequest('/api/chat', {
    method: 'POST',
    body: JSON.stringify({ query, status, limit: 8 }),
  })
}
