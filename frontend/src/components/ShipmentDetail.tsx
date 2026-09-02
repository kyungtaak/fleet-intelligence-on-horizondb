import { ArrowRight, Clock3, MapPin, X } from 'lucide-react'
import type { Shipment } from '../types'
import { StatusBadge } from './StatusBadge'

interface ShipmentDetailProps {
  shipment: Shipment
  onClose: () => void
}

function formatDate(value: string | null) {
  if (!value) return 'Pending'
  return new Intl.DateTimeFormat('en', {
    month: 'short',
    day: 'numeric',
    year: 'numeric',
    timeZone: 'UTC',
  }).format(new Date(`${value}T00:00:00Z`))
}

function relativeTime(value: string) {
  const elapsedMinutes = Math.max(
    1,
    Math.round((Date.now() - new Date(value).getTime()) / 60000),
  )
  if (elapsedMinutes < 60) return `${elapsedMinutes}m ago`
  const hours = Math.round(elapsedMinutes / 60)
  if (hours < 24) return `${hours}h ago`
  return `${Math.round(hours / 24)}d ago`
}

export function ShipmentDetail({ shipment, onClose }: ShipmentDetailProps) {
  return (
    <section className="shipment-detail" aria-label="Selected shipment details">
      <div className="detail-header">
        <div className="detail-identity">
          <strong>{shipment.shipment_number}</strong>
          <StatusBadge status={shipment.status} compact />
        </div>
        <button
          className="detail-close icon-button"
          type="button"
          aria-label="Close shipment details"
          title="Close"
          onClick={onClose}
        >
          <X size={18} />
        </button>
      </div>

      <div className="detail-content">
        <div className="detail-description">
          <span className="detail-label">Cargo</span>
          <strong>{shipment.title}</strong>
          <p>{shipment.description}</p>
        </div>

        <div className="detail-route">
          <div>
            <span className="route-node origin-node" aria-hidden="true" />
            <span className="detail-label">Origin</span>
            <strong>{shipment.origin_name}</strong>
          </div>
          <ArrowRight size={18} aria-hidden="true" />
          <div>
            <span className="route-node destination-node" aria-hidden="true" />
            <span className="detail-label">Destination</span>
            <strong>{shipment.destination_name}</strong>
          </div>
        </div>

        <div className="detail-facts">
          <div>
            <MapPin size={15} aria-hidden="true" />
            <span>
              <small>Current location</small>
              <strong>{shipment.current_location_name}</strong>
              <em>
                {shipment.current_position.latitude.toFixed(4)},{' '}
                {shipment.current_position.longitude.toFixed(4)}
              </em>
            </span>
          </div>
          <div>
            <Clock3 size={15} aria-hidden="true" />
            <span>
              <small>ETA</small>
              <strong>{formatDate(shipment.eta)}</strong>
              <em>Updated {relativeTime(shipment.updated_at)}</em>
            </span>
          </div>
        </div>
      </div>
    </section>
  )
}
