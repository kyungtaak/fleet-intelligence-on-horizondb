import type { ShipmentStatus } from './types'

export const STATUS_LABELS: Record<ShipmentStatus, string> = {
  in_transit: 'In transit',
  delivered: 'Delivered',
  delayed: 'Delayed',
  exception: 'Exception',
  unknown: 'Unknown',
}

export const STATUS_COLORS: Record<ShipmentStatus, string> = {
  in_transit: '#1677ff',
  delivered: '#16a66a',
  delayed: '#ed7a0b',
  exception: '#d92d52',
  unknown: '#7952cc',
}