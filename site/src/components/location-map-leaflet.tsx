"use client";

import "leaflet/dist/leaflet.css";
import "@/styles/map-leaflet.css";
import L from "leaflet";
import { useEffect, useRef } from "react";
import type { GeoLine, GeoPoint } from "@/lib/geo";

const TILES = "https://tile.openstreetmap.org/{z}/{x}/{y}.png";
const ATTRIBUTION =
  '&copy; <a href="https://www.openstreetmap.org/copyright" target="_blank" rel="noopener noreferrer">OpenStreetMap</a> contributors';

/** Beacons this close to the record's centre are kept in view. */
const NEAR_BEACON_M = 6000;

const markIcon = (cls: string, size: number) =>
  L.divIcon({ className: `map-mark ${cls}`, iconSize: [size, size], html: "" });

const coarse = () =>
  typeof window !== "undefined" && window.matchMedia?.("(pointer: coarse)").matches === true;

/** The Leaflet map inside the location figure (loaded lazily by location-map). */
export default function LeafletMap({
  points,
  context,
  lines,
}: {
  points: GeoPoint[];
  context: GeoPoint[];
  lines: GeoLine[];
}) {
  const el = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const node = el.current;
    if (!node) return;
    const touch = coarse();
    const map = L.map(node, {
      // The page scrolls under the wheel (and one finger) until the map is clicked.
      scrollWheelZoom: false,
      dragging: !touch,
      attributionControl: false,
    });
    L.control.attribution({ prefix: false }).addAttribution(ATTRIBUTION).addTo(map);
    L.tileLayer(TILES, { maxZoom: 19, className: "map-tiles" }).addTo(map);

    for (const r of lines) {
      L.polyline(
        [
          [r.from.lat, r.from.lon],
          [r.to.lat, r.to.lon],
        ],
        { className: "map-runway", interactive: true },
      )
        .bindTooltip(r.label, { sticky: true })
        .addTo(map);
    }
    for (const p of context) {
      if (p.kind === "stand") {
        L.circleMarker([p.lat, p.lon], { radius: 2.5, className: "map-stand" })
          .bindTooltip(p.label)
          .addTo(map);
      } else {
        L.marker([p.lat, p.lon], { icon: markIcon("map-mark-beacon", 10), title: p.label })
          .bindTooltip(p.label)
          .addTo(map);
      }
    }
    for (const p of points) {
      L.marker([p.lat, p.lon], {
        icon: markIcon("map-mark-record", 26),
        title: p.label,
        zIndexOffset: 1000,
        keyboard: false,
      })
        .bindTooltip(p.label)
        .addTo(map);
    }

    // Frame the record: its own points, runways and stands; outlying beacons may fall outside.
    const frame = L.latLngBounds(points.map((p) => [p.lat, p.lon] as [number, number]));
    for (const r of lines) {
      frame.extend([r.from.lat, r.from.lon]).extend([r.to.lat, r.to.lon]);
    }
    for (const p of context) if (p.kind === "stand") frame.extend([p.lat, p.lon]);
    // Beacons near the field (localizers, glideslopes, middle markers) are framed too.
    const centre = frame.getCenter();
    for (const p of context) {
      if (p.kind === "beacon" && centre.distanceTo([p.lat, p.lon]) <= NEAR_BEACON_M) {
        frame.extend([p.lat, p.lon]);
      }
    }
    const ne = frame.getNorthEast();
    const sw = frame.getSouthWest();
    if (ne.equals(sw)) map.setView(ne, 14);
    else map.fitBounds(frame, { padding: [24, 24], maxZoom: 16 });

    const wake = () => {
      map.scrollWheelZoom.enable();
      if (touch) map.dragging.enable();
      node.dataset.active = "true";
    };
    const sleep = () => {
      map.scrollWheelZoom.disable();
      delete node.dataset.active;
    };
    map.on("click", wake);
    map.on("focus", wake);
    node.addEventListener("mouseleave", sleep);

    // The figure can change width (sidebar, rotation): keep the tiles filling it.
    const ro =
      typeof ResizeObserver === "undefined" ? null : new ResizeObserver(() => map.invalidateSize());
    ro?.observe(node);

    return () => {
      ro?.disconnect();
      node.removeEventListener("mouseleave", sleep);
      map.remove();
    };
  }, [points, context, lines]);

  return <div ref={el} className="map-canvas" />;
}
