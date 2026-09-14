import { DatabaseZap, RefreshCw, Search, SlidersHorizontal } from 'lucide-react'
import type { Shipment, ShipmentStatus } from '../types'
import { STATUS_COLORS, STATUS_LABELS } from '../shipmentStatus'

type StatusFilter = ShipmentStatus | 'all'

interface ShipmentListProps {
  shipments: Shipment[]
  total: number
  selectedNumber: string | null
  search: string
  status: StatusFilter
  loading: boolean
  onSearchChange: (value: string) => void
  onStatusChange: (value: StatusFilter) => void
  onSelect: (shipment: Shipment) => void
  onRefresh: () => void
  onReset: () => void
  onOpenDemo: () => void
}

export function ShipmentList({
  shipments,
  total,
  selectedNumber,
  search,
  status,
  loading,
  onSearchChange,
  onStatusChange,
  onSelect,
  onRefresh,
  onReset,
  onOpenDemo,
}: ShipmentListProps) {
  return (
    <aside className="shipment-panel workspace-panel" aria-label="Shipments">
      <div className="panel-heading shipment-heading">
        <div>
          <span className="eyebrow">Fleet overview</span>
          <h2>Shipments</h2>
        </div>
        <div className="shipment-heading-actions">
          <span className="count-badge" aria-label={`${total} total shipments`}>
            {total}
          </span>
          <button
            className="icon-button"
            type="button"
            title="데모 데이터 입력"
            aria-label="데모 데이터 입력"
            onClick={onOpenDemo}
          >
            <DatabaseZap size={17} />
          </button>
        </div>
      </div>

      <div className="shipment-filters">
        <label className="search-field">
          <Search size={16} aria-hidden="true" />
          <span className="sr-only">Search shipments</span>
          <input
            value={search}
            onChange={(event) => onSearchChange(event.target.value)}
            placeholder="Search shipments"
            type="search"
          />
        </label>
        <div className="filter-row">
          <label className="select-field">
            <span className="sr-only">Filter by status</span>
            <select
              value={status}
              onChange={(event) =>
                onStatusChange(event.target.value as StatusFilter)
              }
            >
              <option value="all">All statuses</option>
              {Object.entries(STATUS_LABELS).map(([value, label]) => (
                <option value={value} key={value}>
                  {label}
                </option>
              ))}
            </select>
          </label>
          <button
            className="icon-button"
            type="button"
            title="Clear filters"
            aria-label="Clear filters"
            onClick={onReset}
            disabled={status === 'all' && !search}
          >
            <SlidersHorizontal size={17} />
          </button>
        </div>
      </div>

      <div className="shipment-list" aria-live="polite" aria-busy={loading}>
        {loading && shipments.length === 0
          ? Array.from({ length: 6 }, (_, index) => (
              <div className="shipment-skeleton" key={index} />
            ))
          : null}

        {!loading && shipments.length === 0 ? (
          <div className="empty-state">
            <Search size={22} />
            <strong>No shipments found</strong>
            <span>Try a different status or phrase.</span>
          </div>
        ) : null}

        {shipments.map((shipment) => (
          <button
            className={`shipment-card ${
              selectedNumber === shipment.shipment_number ? 'selected' : ''
            }`}
            key={shipment.id}
            type="button"
            onClick={() => onSelect(shipment)}
          >
            <span
              className="shipment-card-dot"
              style={{ backgroundColor: STATUS_COLORS[shipment.status] }}
              aria-hidden="true"
            />
            <span className="shipment-card-body">
              <span className="shipment-card-topline">
                <strong>{shipment.shipment_number}</strong>
                {shipment.similarity !== null ? (
                  <span className="similarity-mini">
                    {Math.round(shipment.similarity * 100)}%
                  </span>
                ) : null}
              </span>
              <span className="shipment-title">{shipment.title}</span>
              <span className="shipment-destination">
                {shipment.destination_name}
              </span>
              <span className={`status-text status-text-${shipment.status}`}>
                {STATUS_LABELS[shipment.status]}
              </span>
            </span>
          </button>
        ))}
      </div>

      <div className="shipment-panel-footer">
        <button className="refresh-button" type="button" onClick={onRefresh}>
          <RefreshCw size={15} className={loading ? 'spin' : ''} />
          Refresh fleet
        </button>
      </div>
    </aside>
  )
}