import type { ShipmentStatus } from '../types'
import { STATUS_LABELS } from '../shipmentStatus'

interface StatusBadgeProps {
  status: ShipmentStatus
  compact?: boolean
}

export function StatusBadge({ status, compact = false }: StatusBadgeProps) {
  return (
    <span className={`status-badge status-${status} ${compact ? 'compact' : ''}`}>
      <span className="status-dot" aria-hidden="true" />
      {STATUS_LABELS[status]}
    </span>
  )
}
