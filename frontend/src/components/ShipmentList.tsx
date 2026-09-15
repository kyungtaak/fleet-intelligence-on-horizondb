import { CalendarDays, DatabaseZap, MapPinned, RefreshCw, RotateCcw, Search, Square, X } from 'lucide-react'
import type { CriteriaSearchRequest, CriteriaSearchResponse, Shipment, ShipmentStatus } from '../types'
import { STATUS_COLORS, STATUS_LABELS } from '../shipmentStatus'

interface ShipmentListProps {
  shipments: Shipment[]
  total: number
  selectedNumber: string | null
  criteria: CriteriaSearchRequest
  result: CriteriaSearchResponse | null
  source: 'criteria' | 'agent' | null
  dirty: boolean
  searching: boolean
  searchError: string | null
  pickingCenter: boolean
  loading: boolean
  onChange: (value: Partial<CriteriaSearchRequest>) => void
  onSearch: () => void
  onCancel: () => void
  onPickCenter: () => void
  onSelect: (shipment: Shipment) => void
  onRefresh: () => void
  onReset: () => void
  onOpenDemo: () => void
}

export function ShipmentList({
  shipments,
  total,
  selectedNumber,
  criteria,
  result,
  source,
  dirty,
  searching,
  searchError,
  pickingCenter,
  loading,
  onChange,
  onSearch,
  onCancel,
  onPickCenter,
  onSelect,
  onRefresh,
  onReset,
  onOpenDemo,
}: ShipmentListProps) {
  return (
    <aside className="shipment-panel workspace-panel" aria-label="Shipments">
      <div className="panel-heading shipment-heading">
        <div>
          <span className="eyebrow">Search Workbench</span>
          <h2>Find shipments</h2>
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

      <form className="criteria-search-form" onSubmit={event => { event.preventDefault(); onSearch() }}>
        <label className="criteria-query-field">
          <span>Search intent</span>
          <span className="criteria-query-row">
            <input type="search" aria-label="Search intent" value={criteria.query} maxLength={300}
              disabled={searching} onChange={event => onChange({
                query: event.target.value,
                ...(event.target.value.trim().length < 2 ? { ranking: 'semantic' } : {}),
              })} />
            {searching ? <button type="button" className="icon-button" title="Cancel search" aria-label="Cancel search" onClick={event => { event.preventDefault(); onCancel() }}><Square size={15} /></button>
              : <button type="submit" className="icon-button criteria-submit" title="Run criteria search" aria-label="Run criteria search" disabled={criteria.query.trim().length === 1}><Search size={16} /></button>}
          </span>
        </label>
        <label className="criteria-control-row">
          <span>Status</span>
          <select aria-label="Filter by status" value={criteria.status ?? 'all'} disabled={searching}
            onChange={event => onChange({ status: event.target.value === 'all' ? null : event.target.value as ShipmentStatus })}>
            <option value="all">All statuses</option>
            {Object.entries(STATUS_LABELS).map(([value, label]) => <option key={value} value={value}>{label}</option>)}
          </select>
        </label>
        <div className="criteria-eta-row">
          <span><CalendarDays size={14} /> ETA</span>
          <div className="criteria-eta-inputs">
            <input type="date" aria-label="ETA date" value={criteria.eta_date ?? ''} disabled={searching}
              onChange={event => onChange({ eta_date: event.target.value || null })} />
            <span aria-hidden="true">±</span>
            <input type="number" aria-label="ETA tolerance in days" min={0} max={365} step={1}
              value={criteria.eta_days} disabled={!criteria.eta_date || searching}
              onChange={event => onChange({ eta_days: Number(event.target.value) })} />
            <small>days</small>
          </div>
        </div>
        <div className="criteria-map-row">
          <button className="criteria-map-pick" type="button" aria-pressed={pickingCenter} onClick={onPickCenter}
            disabled={searching} title="Select radius center on map"><MapPinned size={16} />Map radius</button>
          {criteria.search_center ? <><small>{criteria.search_center.latitude.toFixed(2)}, {criteria.search_center.longitude.toFixed(2)}</small>
            <button className="icon-button" type="button" title="Clear radius" aria-label="Clear radius" disabled={searching}
              onClick={() => onChange({ search_center: null, ranking: 'semantic' })}><X size={14} /></button></> : null}
        </div>
        <label className="criteria-radius-row">
          <span>Radius <b>{criteria.radius_km.toLocaleString()} km</b></span>
          <input type="range" aria-label="Radius in kilometers" min={50} max={3000} step={50}
            value={criteria.radius_km} disabled={!criteria.search_center || searching}
            onChange={event => onChange({ radius_km: Number(event.target.value) })} />
        </label>
        <label className="criteria-control-row">
          <span>Ranking</span>
          <select aria-label="Search ranking" value={criteria.ranking} disabled={searching}
            onChange={event => onChange({ ranking: event.target.value as CriteriaSearchRequest['ranking'] })}>
            <option value="semantic">{criteria.query.trim() ? 'Relevance' : 'Shipment number'}</option>
            <option value="semantic_spatial" disabled={!criteria.search_center || criteria.query.trim().length < 2}>Relevance 72% + proximity 28%</option>
          </select>
        </label>
        <div className="criteria-form-footer">
          <button type="button" onClick={onReset}><RotateCcw size={13} />Clear</button>
          {dirty ? <small>Unapplied changes</small> : null}
        </div>
        {searchError ? <div className="criteria-error" role="alert">{searchError}</div> : null}
      </form>
      {source ? <div className="criteria-result-summary" role="status">
        <strong>{source === 'criteria' ? 'Criteria results' : 'Agent matches'}</strong>
        <span>{total}건{result?.has_more ? ' · 추가 결과 있음' : ''}</span>
        {result ? <small>{result.search_mode}{result.applied_filters.eta_start ? ` · ETA ${result.applied_filters.eta_start} ~ ${result.applied_filters.eta_end}` : ''}</small> : null}
      </div> : null}

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
                  <span className="similarity-mini" title={shipment.hybrid_score != null ? 'Weighted score, not a probability' : 'Cosine similarity, not a probability'}>
                    {shipment.hybrid_score != null ? `score ${shipment.hybrid_score.toFixed(3)}` : `cos ${shipment.similarity.toFixed(2)}`}
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