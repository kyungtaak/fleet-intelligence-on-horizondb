import { greatCircle } from '@turf/great-circle'
import type { Coordinate, Shipment } from './types'

export function shipmentRoute(shipment: Pick<Shipment, 'origin' | 'current_position' | 'destination'>): [number, number][][] {
  const points = [shipment.origin, shipment.current_position, shipment.destination]
  return points.slice(1).flatMap((end, index) => routeLeg(points[index], end))
}

function routeLeg(start: Coordinate, end: Coordinate): [number, number][][] {
  if (start.latitude === end.latitude && start.longitude === end.longitude) return []
  try {
    const { geometry } = greatCircle(
      [start.longitude, start.latitude],
      [end.longitude, end.latitude],
      { npoints: 100 },
    )
    const lines = geometry.type === 'MultiLineString' ? geometry.coordinates : [geometry.coordinates]
    return lines.map(line => line.map(([longitude, latitude]) => [latitude, longitude]))
  } catch {
    return []
  }
}