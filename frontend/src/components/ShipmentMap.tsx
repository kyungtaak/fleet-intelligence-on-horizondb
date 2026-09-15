import { useEffect, useRef, useState } from 'react'
import type { RefObject } from 'react'
import { createPortal } from 'react-dom'
import { Ship } from 'lucide-react'
import L from 'leaflet'
import {
  CircleMarker,
  Circle,
  MapContainer,
  Marker,
  Polyline,
  Popup,
  TileLayer,
  useMap,
  useMapEvents,
} from 'react-leaflet'
import 'leaflet/dist/leaflet.css'
import type { Coordinate, Shipment } from '../types'
import { STATUS_COLORS, STATUS_LABELS } from '../shipmentStatus'
import { shipmentRoute } from '../shipmentRoute'

interface ShipmentMapProps {
  shipments: Shipment[]
  selected: Shipment | null
  locateRequest: number | null
  onSelect: (shipment: Shipment) => void
  searchCenter: Coordinate | null
  searchRadiusKm: number
  pickingCenter: boolean
  onPickCenter: (point: Coordinate) => void
}

interface ShipmentMarkerProps extends Pick<ShipmentMapProps, 'onSelect'> {
  shipment: Shipment
  selected: boolean
  outsideResults: boolean
  selectedMarker: RefObject<L.Marker | null>
}

function ShipmentMarker({ shipment, selected, outsideResults, selectedMarker, onSelect }: ShipmentMarkerProps) {
  const [{ container, icon }] = useState(() => {
    const container = document.createElement('div')
    return {
      container,
      icon: L.divIcon({
        className: 'shipment-marker-shell',
        html: container,
        iconSize: [36, 36],
        iconAnchor: [18, 18],
        popupAnchor: [0, -20],
      }),
    }
  })
  return (
    <Marker
      title={shipment.shipment_number}
      ref={selected ? selectedMarker : undefined}
      position={[shipment.current_position.latitude, shipment.current_position.longitude]}
      icon={icon}
      zIndexOffset={selected ? 1000 : 0}
      eventHandlers={{ click: () => onSelect(shipment) }}
    >
      {createPortal(
        <span className="shipment-marker-ship" style={{ color: STATUS_COLORS[shipment.status] }}>
          <Ship size={32} strokeWidth={2.5} aria-hidden="true" />
        </span>,
        container,
      )}
      <Popup autoPan={false}>
        <div className="map-popup">
          <strong>{shipment.shipment_number}</strong>
          <span>{shipment.title}</span>
          <small>{shipment.current_location_name}</small>
          {outsideResults && selected ? <small>현재 검색 결과 외 배송</small> : null}
          <b style={{ color: STATUS_COLORS[shipment.status] }}>{STATUS_LABELS[shipment.status]}</b>
        </div>
      </Popup>
    </Marker>
  )
}

function MapViewport({ shipments, selected, locateRequest, selectedMarker }: Pick<ShipmentMapProps, 'shipments' | 'selected' | 'locateRequest'> & { selectedMarker: RefObject<L.Marker | null> }) {
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
  const selectedId = selected?.id ?? null

  useEffect(() => {
    const popup = selectedMarker.current?.getPopup()
    map.eachLayer(layer => {
      if (layer instanceof L.Popup && (layer !== popup || locateRequest !== null)) {
        map.closePopup(layer)
      }
    })
  }, [map, selectedId, locateRequest, selectedMarker])

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

function MapSearchArea({ searchCenter, searchRadiusKm, pickingCenter, onPickCenter }: Pick<ShipmentMapProps, 'searchCenter' | 'searchRadiusKm' | 'pickingCenter' | 'onPickCenter'>) {
  const map = useMapEvents({
    click(event) {
      if (!pickingCenter) return
      const coordinate = event.latlng.wrap()
      onPickCenter({ latitude: coordinate.lat, longitude: coordinate.lng })
    },
  })
  useEffect(() => {
    const container = map.getContainer()
    container.classList.toggle('picking-radius', pickingCenter)
    return () => container.classList.remove('picking-radius')
  }, [map, pickingCenter])
  return searchCenter ? <>
    <Circle center={[searchCenter.latitude, searchCenter.longitude]} radius={searchRadiusKm * 1000}
      interactive={false} pathOptions={{ color: 'var(--success)', weight: 2, fillOpacity: 0.08, dashArray: '5 5' }} />
    <CircleMarker center={[searchCenter.latitude, searchCenter.longitude]} radius={4}
      interactive={false} pathOptions={{ color: 'var(--success)', fillOpacity: 1 }} />
  </> : null
}

export function ShipmentMap({
  shipments,
  selected,
  locateRequest,
  onSelect,
  searchCenter,
  searchRadiusKm,
  pickingCenter,
  onPickCenter,
}: ShipmentMapProps) {
  const selectedMarker = useRef<L.Marker | null>(null)
  const outsideResults = selected && !shipments.some((shipment) => shipment.id === selected.id)
  const mapShipments = outsideResults ? [...shipments, selected] : shipments

  const selectedRoute = selected ? shipmentRoute(selected) : null

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
      <MapSearchArea searchCenter={searchCenter} searchRadiusKm={searchRadiusKm} pickingCenter={pickingCenter} onPickCenter={onPickCenter} />

      {selected && selectedRoute ? (
        <>
          <Polyline
            interactive={false}
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
            interactive={false}
            radius={5}
            pathOptions={{
              color: '#243348',
              fillColor: '#ffffff',
              fillOpacity: 1,
            }}
          />
          <CircleMarker
            interactive={false}
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
        <ShipmentMarker
          key={shipment.id}
          shipment={shipment}
          selected={selected?.id === shipment.id}
          selectedMarker={selectedMarker}
          outsideResults={Boolean(outsideResults)}
          onSelect={onSelect}
        />
      ))}
    </MapContainer>
  )
}
