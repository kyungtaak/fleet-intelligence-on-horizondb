import {
  startTransition,
  useDeferredValue,
  useEffect,
  useState,
} from 'react'
import {
  Bot,
  Boxes,
  Database,
  Map as MapIcon,
  PackageSearch,
  Radio,
} from 'lucide-react'
import {
  getCapabilities,
  getShipments,
  getShipmentStats,
  searchShipments,
} from './api'
import { ChatPanel } from './components/ChatPanel'
import { ShipmentDetail } from './components/ShipmentDetail'
import { ShipmentList } from './components/ShipmentList'
import { ShipmentMap } from './components/ShipmentMap'
import type {
  DatabaseCapabilities,
  SearchResponse,
  Shipment,
  ShipmentStats,
  ShipmentStatus,
} from './types'
import './App.css'

type StatusFilter = ShipmentStatus | 'all'
type MobileView = 'shipments' | 'map' | 'assistant'

function App() {
  const [shipments, setShipments] = useState<Shipment[]>([])
  const [semanticResults, setSemanticResults] = useState<Shipment[] | null>(null)
  const [stats, setStats] = useState<ShipmentStats | null>(null)
  const [capabilities, setCapabilities] =
    useState<DatabaseCapabilities | null>(null)
  const [selected, setSelected] = useState<Shipment | null>(null)
  const [search, setSearch] = useState('')
  const [status, setStatus] = useState<StatusFilter>('all')
  const [mobileView, setMobileView] = useState<MobileView>('map')
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const deferredSearch = useDeferredValue(search.trim().toLowerCase())

  async function loadWorkspace() {
    setLoading(true)
    setError(null)
    try {
      const [nextShipments, nextStats, nextCapabilities] = await Promise.all([
        getShipments(),
        getShipmentStats(),
        getCapabilities(),
      ])
      startTransition(() => {
        setShipments(nextShipments)
        setStats(nextStats)
        setCapabilities(nextCapabilities)
      })
    } catch (loadError) {
      setError(
        loadError instanceof Error
          ? loadError.message
          : 'Unable to load the shipping workspace.',
      )
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    let cancelled = false
    Promise.all([getShipments(), getShipmentStats(), getCapabilities()])
      .then(([nextShipments, nextStats, nextCapabilities]) => {
        if (cancelled) return
        startTransition(() => {
          setShipments(nextShipments)
          setStats(nextStats)
          setCapabilities(nextCapabilities)
        })
      })
      .catch((loadError: unknown) => {
        if (cancelled) return
        setError(
          loadError instanceof Error
            ? loadError.message
            : 'Unable to load the shipping workspace.',
        )
      })
      .finally(() => {
        if (!cancelled) setLoading(false)
      })

    return () => {
      cancelled = true
    }
  }, [])

  const sourceShipments = semanticResults ?? shipments
  const visibleShipments = sourceShipments.filter((shipment) => {
    const matchesStatus = status === 'all' || shipment.status === status
    const haystack = [
      shipment.shipment_number,
      shipment.title,
      shipment.description,
      shipment.origin_name,
      shipment.destination_name,
      shipment.current_location_name,
    ]
      .join(' ')
      .toLowerCase()
    return matchesStatus && (!deferredSearch || haystack.includes(deferredSearch))
  })

  const mapSelection = selected
    ? visibleShipments.find(
        (shipment) => shipment.shipment_number === selected.shipment_number,
      ) ?? null
    : null

  function selectShipment(shipment: Shipment, revealMap = false) {
    setSelected(shipment)
    if (revealMap) setMobileView('map')
  }

  function showAllShipments() {
    startTransition(() => {
      setSemanticResults(null)
      setSearch('')
      setStatus('all')
      setSelected(null)
    })
  }

  async function runSemanticSearch(query: string): Promise<SearchResponse> {
    const result = await searchShipments(
      query,
      status === 'all' ? null : status,
    )
    startTransition(() => {
      setSemanticResults(result.shipments)
      setSearch('')
      setSelected(result.shipments[0] ?? null)
    })
    return result
  }

  const statusTotal = (shipmentStatus: ShipmentStatus) =>
    stats?.statuses.find((item) => item.status === shipmentStatus)?.count ?? 0

  return (
    <div className="app-shell">
      <header className="app-header">
        <div className="brand-lockup">
          <span className="brand-mark" aria-hidden="true">
            <Boxes size={20} />
          </span>
          <div>
            <strong>HorizonShip</strong>
            <span>Global operations</span>
          </div>
        </div>

        <div className="capability-strip" aria-label="Platform capabilities">
          <span className={capabilities?.connected ? 'available' : 'standby'}>
            <Database size={14} />
            {capabilities?.connected ? 'HorizonDB live' : 'HorizonDB'}
          </span>
          <span className={capabilities?.postgis_version ? 'available' : 'standby'}>
            <MapIcon size={14} />
            PostGIS
          </span>
          <span className={capabilities?.diskann_version ? 'available' : 'standby'}>
            <PackageSearch size={14} />
            DiskANN
          </span>
          <span className={capabilities?.agent_framework ? 'available' : 'standby'}>
            <Bot size={14} />
            Agent Framework
          </span>
        </div>

        <div className="network-state">
          <Radio size={15} aria-hidden="true" />
          <span>
            <strong>{stats?.total ?? shipments.length}</strong>
            tracked
          </span>
        </div>
      </header>

      {error ? (
        <div className="load-error" role="alert">
          <span>{error}</span>
          <button type="button" onClick={() => void loadWorkspace()}>
            Retry
          </button>
        </div>
      ) : null}

      <main className={`workspace mobile-view-${mobileView}`}>
        <ShipmentList
          shipments={visibleShipments}
          total={visibleShipments.length}
          selectedNumber={mapSelection?.shipment_number ?? null}
          search={search}
          status={status}
          loading={loading}
          onSearchChange={setSearch}
          onStatusChange={setStatus}
          onSelect={(shipment) => selectShipment(shipment, true)}
          onRefresh={() => void loadWorkspace()}
          onReset={() => {
            setSearch('')
            setStatus('all')
          }}
        />

        <section className="map-workspace" aria-label="Global shipment map">
          <div className="map-summary" aria-label="Shipment status summary">
            <span>
              <i className="summary-dot transit" />
              <b>{statusTotal('in_transit')}</b> in transit
            </span>
            <span>
              <i className="summary-dot delayed" />
              <b>{statusTotal('delayed')}</b> delayed
            </span>
            <span>
              <i className="summary-dot exception" />
              <b>{statusTotal('exception')}</b> exceptions
            </span>
            {semanticResults ? (
              <button type="button" onClick={showAllShipments}>
                Show all {shipments.length}
              </button>
            ) : null}
          </div>
          <ShipmentMap
            shipments={visibleShipments}
            selected={mapSelection}
            onSelect={(shipment) => selectShipment(shipment)}
          />
          {mapSelection ? (
            <ShipmentDetail
              shipment={mapSelection}
              onClose={() => setSelected(null)}
            />
          ) : null}
        </section>

        <ChatPanel
          onSearch={runSemanticSearch}
          onLocate={(shipment) => selectShipment(shipment, true)}
          onShowAll={showAllShipments}
        />
      </main>

      <nav className="mobile-navigation" aria-label="Workspace views">
        <button
          type="button"
          className={mobileView === 'shipments' ? 'active' : ''}
          onClick={() => setMobileView('shipments')}
        >
          <Boxes size={19} />
          Shipments
        </button>
        <button
          type="button"
          className={mobileView === 'map' ? 'active' : ''}
          onClick={() => setMobileView('map')}
        >
          <MapIcon size={19} />
          Map
        </button>
        <button
          type="button"
          className={mobileView === 'assistant' ? 'active' : ''}
          onClick={() => setMobileView('assistant')}
        >
          <Bot size={19} />
          Assistant
        </button>
      </nav>
    </div>
  )
}

export default App
