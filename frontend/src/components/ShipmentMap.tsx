import { useEffect } from 'react'
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

function FitVisibleShipments({ shipments }: { shipments: Shipment[] }) {
  const map = useMap()

  useEffect(() => {
    if (shipments.length === 0) return
    if (shipments.length === 1) {
      const point = shipments[0].current_position
      map.flyTo([point.latitude, point.longitude], 5, { duration: 0.65 })
      return
    }

    const bounds = L.latLngBounds(
      shipments.map((shipment) => [
        shipment.current_position.latitude,
        shipment.current_position.longitude,
      ]),
    )
    map.fitBounds(bounds, { padding: [44, 44], maxZoom: 5, animate: true })
  }, [map, shipments])

  return null
}

export function ShipmentMap({
  shipments,
  selected,
  onSelect,
}: ShipmentMapProps) {
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
      <FitVisibleShipments shipments={shipments} />

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

      {shipments.map((shipment) => (
        <Marker
          key={shipment.id}
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
          <Popup>
            <div className="map-popup">
              <strong>{shipment.shipment_number}</strong>
              <span>{shipment.title}</span>
              <small>{shipment.current_location_name}</small>
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
