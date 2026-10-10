"use client";

import "@/styles/map.css";
import { lazy, Suspense, useEffect, useMemo, useRef, useState } from "react";
import { loadRecord } from "@/lib/client-data";
import {
  beaconPoint,
  decimal,
  dms,
  type GeoPoint,
  googleUrl,
  LOCATION_ID,
  type Location,
  locationOf,
  osmUrl,
} from "@/lib/geo";
import type { RecordDoc } from "@/lib/types";

/** Leaflet and its stylesheet: fetched only once the figure nears the viewport. */
const LeafletMap = lazy(() => import("./location-map-leaflet"));

/** Starts loading this far before the figure scrolls into view. */
const NEAR = "300px 0px";

function useNear<T extends Element>() {
  const ref = useRef<T>(null);
  const [near, setNear] = useState(false);
  useEffect(() => {
    const el = ref.current;
    if (!el || near) return;
    if (typeof IntersectionObserver === "undefined") {
      setNear(true);
      return;
    }
    const io = new IntersectionObserver(
      (entries) => {
        if (entries.some((e) => e.isIntersecting)) setNear(true);
      },
      { rootMargin: NEAR },
    );
    io.observe(el);
    return () => io.disconnect();
  }, [near]);
  return [ref, near] as const;
}

type Beacons = { state: "idle" | "loading" | "done"; points: GeoPoint[] };

/** The positions of the beacons a location names (navaid equipment, airbase beacons). */
function useBeacons(loc: Location, near: boolean): Beacons {
  const [b, setB] = useState<Beacons>({ state: "idle", points: [] });
  const ids = loc.beaconIds;
  const kind = loc.beaconsArePoints ? "equipment" : "beacon";
  useEffect(() => {
    if (!near || !ids.length) return;
    let live = true;
    setB({ state: "loading", points: [] });
    Promise.allSettled(ids.map((id) => loadRecord("beacons", id))).then((all) => {
      if (!live) return;
      const points = all.flatMap((r, i) =>
        r.status === "fulfilled" ? (beaconPoint(r.value.data, kind, ids[i] ?? "") ?? []) : [],
      );
      setB({ state: "done", points });
    });
    return () => {
      live = false;
    };
  }, [near, ids, kind]);
  return ids.length ? b : { state: "done", points: [] };
}

function Coordinates({ points }: { points: GeoPoint[] }) {
  return (
    <dl className="map-coords">
      {points.map((p) => (
        <div className="map-coord" key={`${p.label}|${p.lat}|${p.lon}`}>
          <dt>{p.label}</dt>
          <dd>
            <span className="map-dms">
              {dms(p.lat, "lat")} {dms(p.lon, "lon")}
            </span>
            <span className="map-dec">{decimal(p)}</span>
            <span className="map-out">
              <a href={osmUrl(p)} target="_blank" rel="noopener noreferrer">
                Open in OpenStreetMap
              </a>
              <a href={googleUrl(p)} target="_blank" rel="noopener noreferrer">
                Google Maps
              </a>
            </span>
          </dd>
        </div>
      ))}
    </dl>
  );
}

function Legend({ loc, beacons }: { loc: Location; beacons: GeoPoint[] }) {
  const items: Array<[string, string]> = [];
  items.push([
    "map-key-record",
    loc.beaconsArePoints ? "transmitter" : loc.lines.length ? "reference point" : "position",
  ]);
  if (loc.lines.length) items.push(["map-key-runway", "runway"]);
  if (loc.extras.some((p) => p.kind === "stand")) items.push(["map-key-stand", "stand"]);
  if (!loc.beaconsArePoints && beacons.length) items.push(["map-key-beacon", "beacon"]);
  return (
    <span className="map-legend">
      {items.map(([cls, label]) => (
        <span key={cls} className="map-key">
          <span className={`map-glyph ${cls}`} aria-hidden="true" />
          {label}
        </span>
      ))}
    </span>
  );
}

function LocationSection({ loc }: { loc: Location }) {
  const [ref, near] = useNear<HTMLDivElement>();
  const beacons = useBeacons(loc, near);
  const own = loc.beaconsArePoints ? [...loc.points, ...beacons.points] : loc.points;
  const context = loc.beaconsArePoints ? loc.extras : [...loc.extras, ...beacons.points];
  const ready = near && beacons.state === "done";
  const empty = ready && !own.length;

  return (
    <section id={LOCATION_ID} className="section" aria-labelledby={`${LOCATION_ID}-h`}>
      <div className="section-head">
        <h2 id={`${LOCATION_ID}-h`}>Location</h2>
      </div>
      <figure className="map-fig">
        <figcaption className="map-cap">
          <span className="map-cap-title">Location</span>
          <Legend loc={loc} beacons={beacons.points} />
        </figcaption>
        <div ref={ref} className="map-frame">
          {ready && own.length ? (
            <Suspense fallback={<MapPending />}>
              <LeafletMap points={own} context={context} lines={loc.lines} />
            </Suspense>
          ) : (
            <MapPending text={empty ? "No position in the data." : undefined} />
          )}
        </div>
        <p className="map-hint">Click the map to zoom with the scroll wheel.</p>
      </figure>
      {own.length ? (
        <Coordinates points={own} />
      ) : (
        <p className="map-coords muted">{empty ? "No position in the data." : "Loading…"}</p>
      )}
    </section>
  );
}

function MapPending({ text }: { text?: string | undefined }) {
  return (
    <div className="map-pending" aria-busy={text ? undefined : "true"}>
      {text ?? <span className="visually-hidden">Loading map…</span>}
    </div>
  );
}

/**
 * The "Location" section of a record page: a map figure of the record's latitude/longitude
 * (an airbase's runways and stands, a navaid's transmitters) and its coordinates with links
 * out. Nothing when the record has no position. Leaflet and the tiles load on approach.
 */
export function LocationFigure({ doc }: { doc: RecordDoc }) {
  const loc = useMemo(() => locationOf(doc.series, doc.data, doc.name), [doc]);
  if (!loc) return null;
  return <LocationSection key={`${doc.series}/${doc.id}`} loc={loc} />;
}
