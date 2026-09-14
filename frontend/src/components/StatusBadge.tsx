import type { ShipmentStatus } from '../types'
import { STATUS_LABELS } from '../shipmentStatus'

interface StatusBadgeProps {
  status: ShipmentStatus
  compact?: boolean
  label?: string
}

export function StatusBadge({ status, compact = false, label }: StatusBadgeProps) {
  return (
    <span className={`status-badge status-${status} ${compact ? 'compact' : ''}`}>
      <span className="status-dot" aria-hidden="true" />
      {label ?? STATUS_LABELS[status]}
    </span>
  )
}
