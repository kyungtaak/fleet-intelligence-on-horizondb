import type {
  DatabaseCapabilities,
  SearchResponse,
  SearchProgress,
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

export async function searchShipments(
  query: string,
  status: ShipmentStatus | null,
  onProgress: (event: SearchProgress) => void,
  signal: AbortSignal,
): Promise<SearchResponse> {
  const response = await fetch(`${API_BASE}/api/chat/stream`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ query, status, limit: 8 }),
    signal: AbortSignal.any([signal, AbortSignal.timeout(150_000)]),
  })
  if (!response.ok || !response.body) {
    throw new Error('검색 요청을 시작하지 못했습니다.')
  }
  const reader = response.body.getReader()
  const decoder = new TextDecoder()
  let buffer = ''
  try {
    while (true) {
      const { value, done } = await reader.read()
      buffer += decoder.decode(value, { stream: !done })
      const lines = buffer.split('\n')
      buffer = lines.pop() ?? ''
      if (done && buffer.trim()) lines.push(buffer)
      for (const line of lines) {
        if (!line.trim()) continue
        const event = JSON.parse(line)
        if (event.type === 'progress') onProgress(event as SearchProgress)
        else if (event.type === 'result') return event.result as SearchResponse
        else if (event.type === 'error') throw new Error(event.message)
      }
      if (done) throw new Error('완료 응답을 받기 전에 연결이 종료되었습니다.')
    }
  } finally {
    await reader.cancel().catch(() => undefined)
    reader.releaseLock()
  }
}
