"use client";

import "leaflet/dist/leaflet.css";
import { CircleMarker, MapContainer, TileLayer, Tooltip } from "react-leaflet";
import { fmt, type Row } from "./spec";

export default function VisualMap({ rows, lat, lon, label }: { rows: Row[]; lat: string; lon: string; label?: string }) {
  const points = rows.filter((r) => typeof r[lat] === "number" && typeof r[lon] === "number");
  const lats = points.map((r) => r[lat] as number);
  const lons = points.map((r) => r[lon] as number);
  const pad = 0.01;
  const bounds: [[number, number], [number, number]] = [
    [Math.min(...lats) - pad, Math.min(...lons) - pad],
    [Math.max(...lats) + pad, Math.max(...lons) + pad],
  ];
  return (
    <div className="h-80 overflow-hidden rounded-lg">
      <MapContainer bounds={bounds} scrollWheelZoom={false} className="h-full w-full">
        <TileLayer attribution="&copy; OpenStreetMap contributors" url="https://tile.openstreetmap.org/{z}/{x}/{y}.png" />
        {points.map((r, i) => (
          <CircleMarker key={i} center={[r[lat] as number, r[lon] as number]} radius={8}
                        pathOptions={{ color: "#b91c1c", fillColor: "#ef4444", fillOpacity: 0.8 }}>
            <Tooltip>
              <div className="text-xs">
                <b>{label ? fmt(r[label]) : ""}</b>
                {Object.entries(r).filter(([k]) => ![lat, lon, label].includes(k)).slice(0, 6).map(([k, v]) => (
                  <div key={k}>{k}: {fmt(v)}</div>
                ))}
              </div>
            </Tooltip>
          </CircleMarker>
        ))}
      </MapContainer>
    </div>
  );
}
