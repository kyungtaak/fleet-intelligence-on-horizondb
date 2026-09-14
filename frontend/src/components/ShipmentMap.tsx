import { useEffect, useRef } from 'react'
import type { RefObject } from 'react'
import L from 'leaflet'
import {
  CircleMarker,
  MapContainer,
  Marker,
  Polyline,
  Popup,
  TileLayer,
  useMap,
} from 'react-leaflet'
import 'leaflet/dist/leaflet.css'
import type { Shipment } from '../types'
import { STATUS_COLORS, STATUS_LABELS } from '../shipmentStatus'

interface ShipmentMapProps {
  shipments: Shipment[]
  selected: Shipment | null
  locateRequest: number | null
  onSelect: (shipment: Shipment) => void
}

function markerIcon(shipment: Shipment) {
  return L.divIcon({
    className: 'shipment-marker-shell',
    html: `<span class="shipment-marker-pin" style="--marker-color:${STATUS_COLORS[shipment.status]}"><i></i></span>`,
    iconSize: [30, 38],
    iconAnchor: [15, 36],
    popupAnchor: [0, -32],
  })
}

function MapViewport({ shipments, selected, locateRequest, selectedMarker }: Omit<ShipmentMapProps, 'onSelect'> & { selectedMarker: RefObject<L.Marker | null> }) {
  const map = useMap()
  const previousView = useRef('')
  const previousLocate = useRef<number | null>(null)
  const previousSize = useRef('')
  const positions = JSON.stringify(shipments.map((shipment) => [
    shipment.current_position.latitude, shipment.current_position.longitude,
  ]))
  const focusLatitude = locateRequest !== null && selected ? selected.current_position.latitude : null
  const focusLongitude = locateRequest !== null && selected ? selected.current_position.longitude : null
  const hasSelection = selected !== null

  useEffect(() => {
    const points: [number, number][] = JSON.parse(positions)
    const focus = focusLatitude !== null && focusLongitude !== null
      ? { latitude: focusLatitude, longitude: focusLongitude } : null
    const key = positions
    if (!hasSelection && previousLocate.current !== null) {
      previousView.current = ''
      previousLocate.current = null
    }
    const openSelectedPopup = () => selectedMarker.current?.openPopup()
    function updateView(resized = false) {
      if (!map.getContainer().clientWidth || !map.getContainer().clientHeight) {
        map.stop()
        return
      }
      if (!resized && (focus ? previousLocate.current === locateRequest : previousView.current === key)) return
      previousView.current = key
      map.stop()
      map.invalidateSize({ pan: false })
      if (focus) {
        previousLocate.current = locateRequest
        map.off('moveend', openSelectedPopup)
        map.once('moveend', openSelectedPopup)
        map.flyTo([focus.latitude, focus.longitude], 5, { duration: 0.65 })
      } else if (points.length === 1) {
        map.flyTo(points[0], 5, { duration: 0.65 })
      } else if (points.length > 1) {
        map.fitBounds(L.latLngBounds(points), { padding: [44, 44], maxZoom: 5, animate: true })
      }
    }
    updateView()
    const observer = new ResizeObserver(() => {
      const container = map.getContainer()
      const size = `${container.clientWidth}:${container.clientHeight}`
      if (previousSize.current === size) return
      previousSize.current = size
      updateView(true)
    })
    observer.observe(map.getContainer())
    return () => {
      observer.disconnect()
      map.off('moveend', openSelectedPopup)
    }
  }, [map, positions, focusLatitude, focusLongitude, hasSelection, locateRequest, selectedMarker])

  return null
}

export function ShipmentMap({
  shipments,
  selected,
  locateRequest,
  onSelect,
}: ShipmentMapProps) {
  const selectedMarker = useRef<L.Marker | null>(null)
  const outsideResults = selected && !shipments.some((shipment) => shipment.id === selected.id)
  const mapShipments = outsideResults ? [...shipments, selected] : shipments

  const selectedRoute: [number, number][] | null = selected
    ? [
        [selected.origin.latitude, selected.origin.longitude],
        [
          selected.current_position.latitude,
          selected.current_position.longitude,
        ],
        [selected.destination.latitude, selected.destination.longitude],
      ]
    : null

  return (
    <MapContainer
      className="shipment-map"
      center={[24, 5]}
      zoom={2}
      minZoom={2}
      maxZoom={10}
      scrollWheelZoom
      worldCopyJump
      zoomControl
    >
      <TileLayer
        attribution='&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>'
        url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png"
      />
      <MapViewport shipments={shipments} selected={selected} locateRequest={locateRequest} selectedMarker={selectedMarker} />

      {selected && selectedRoute ? (
        <>
          <Polyline
            positions={selectedRoute}
            pathOptions={{
              color: STATUS_COLORS[selected.status],
              weight: 2,
              opacity: 0.7,
              dashArray: '6 8',
            }}
          />
          <CircleMarker
            center={[selected.origin.latitude, selected.origin.longitude]}
            radius={5}
            pathOptions={{
              color: '#243348',
              fillColor: '#ffffff',
              fillOpacity: 1,
            }}
          />
          <CircleMarker
            center={[
              selected.destination.latitude,
              selected.destination.longitude,
            ]}
            radius={5}
            pathOptions={{
              color: '#243348',
              fillColor: '#243348',
              fillOpacity: 1,
            }}
          />
        </>
      ) : null}

      {mapShipments.map((shipment) => (
        <Marker
          key={shipment.id}
          title={shipment.shipment_number}
          ref={selected?.id === shipment.id ? selectedMarker : undefined}
          position={[
            shipment.current_position.latitude,
            shipment.current_position.longitude,
          ]}
          icon={markerIcon(shipment)}
          zIndexOffset={
            selected?.shipment_number === shipment.shipment_number ? 1000 : 0
          }
          eventHandlers={{ click: () => onSelect(shipment) }}
        >
          <Popup autoPan={false}>
            <div className="map-popup">
              <strong>{shipment.shipment_number}</strong>
              <span>{shipment.title}</span>
              <small>{shipment.current_location_name}</small>
              {outsideResults && selected?.id === shipment.id ? <small>현재 검색 결과 외 배송</small> : null}
              <b style={{ color: STATUS_COLORS[shipment.status] }}>
                {STATUS_LABELS[shipment.status]}
              </b>
            </div>
          </Popup>
        </Marker>
      ))}
    </MapContainer>
  )
}
