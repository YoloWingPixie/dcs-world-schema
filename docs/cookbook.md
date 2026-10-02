# Cookbook

Recipes for the TypeScript, Python and Lua packages and the SQLite database. `task package:test`
runs every snippet against the built artifacts (`cookbook.test.mjs`, `test_cookbook.py`,
`test_sqlite.py`).

Cross-references are id strings: index the target series. In SQL, a nested reference is a link
table `<series>__<field>_<subfield>` of (`<series>_id`, `ordinal`, `path`, `<target>_id`); nested
fields are JSON text. SQLite 3.38+:

```sh
sqlite3 dist/dcs-world-reference-<version>-dcs<dcs version>.sqlite
```

## Load an aircraft and list its stations and stores

Each station lists the stores it `accepts` by CLSID, with their `forbidden`/`required` loadout rules.
A rule names another station: `forbidden` `{station, clsids}` (it must hold none of them) or
`{station, anyStore: true}` (it must be empty); `required` `{station, clsids, allowEmpty}` (it
must hold one of them, or be empty when `allowEmpty`).

```ts
import { loadAircraft, loadStores } from 'dcs-world-reference';

const aircraft = await loadAircraft();
const stores = await loadStores();
const viper = aircraft['F-16C_50'];
if (!viper) throw new Error('no F-16C_50');
console.log(viper.displayName);
for (const station of viper.stations ?? []) {
  const names = station.accepts.map(({ clsid }) => stores[clsid]?.displayName ?? clsid);
  console.log(`station ${station.station}${station.wet ? ' (wet)' : ''}: ${names.length} stores, e.g. ${names[0]}`);
}
```

```python
from dcs_world_reference import aircraft, stores

viper = aircraft()["F-16C_50"]
by_clsid = stores()
print(viper["displayName"])
for station in viper.get("stations", []):
    clsids = [a["clsid"] for a in station["accepts"]]
    names = [by_clsid[c]["displayName"] if c in by_clsid else c for c in clsids]
    print(f"station {station['station']}: {len(names)} stores, e.g. {names[0]}")
```

```lua
local ref = require("dcs_world_reference")

local viper = ref.aircraft["F-16C_50"]
print(viper.displayName)
for _, station in ipairs(viper.stations) do
    local first = station.accepts[1].clsid
    local store = ref.stores[first]
    print(("station %d: %d stores, e.g. %s"):format(
        station.station, #station.accepts, store and store.displayName or first))
end
```

## Which aircraft can carry the AIM-120C

A station accepts stores (DCS's obsolete launchers are in `obsoleteAccepts`);
a store `delivers` weapons.

```sql
SELECT DISTINCT a.id, a.displayName
FROM stores__delivers_weapon AS d
JOIN aircraft__stations_accepts_clsid AS s ON s.stores_clsid = d.stores_clsid
JOIN aircraft AS a ON a.id = s.aircraft_id
WHERE d.weapons_id = 'AIM_120C'
ORDER BY a.id;
```

```python
from dcs_world_reference import aircraft, stores

amraam_stores = {
    clsid
    for clsid, store in stores().items()
    if any(d.get("weapon") == "AIM_120C" for d in store["delivers"])
}
carriers = sorted(
    unit_id
    for unit_id, unit in aircraft().items()
    if any(a["clsid"] in amraam_stores for s in unit.get("stations", []) for a in s["accepts"])
)
print(len(carriers), "aircraft:", ", ".join(carriers))
```

## Loadout rules of a store

The stations a store's rules constrain, per station it goes on: a C-101CC BR-250 bomb needs its
mirror station loaded.

```python
from dcs_world_reference import aircraft

for station in aircraft()["C-101CC"].get("stations", []):
    for entry in station["accepts"]:
        if entry["clsid"] != "BR_250":
            continue
        for rule in entry.get("required", []):
            empty = " or empty" if rule["allowEmpty"] else ""
            print(f"on {station['station']}: station {rule['station']} holds {rule['clsids']}{empty}")
        for rule in entry.get("forbidden", []):
            what = "any store" if rule.get("anyStore") else rule["clsids"]
            print(f"on {station['station']}: station {rule['station']} must not hold {what}")
```

```sql
SELECT DISTINCT aircraft_id
FROM aircraft__stations_accepts_required_clsids
WHERE stores_clsid = 'BR_250'
ORDER BY aircraft_id;
```

## Runway ends and magnetic bearings for Batumi

One direction per runway end, with bearings and threshold.

```python
from dcs_world_reference import airbases

batumi = next(a for a in airbases().values() if a.get("name") == "Batumi")
print(batumi["id"], "magnetic variation", batumi["magneticVariation"]["degrees"])
for runway in batumi.get("runways", []):
    for end in runway["directions"]:
        t = end["threshold"]
        print(
            f"{runway['designator']} end {end['designator']}: "
            f"{end['magneticBearingDeg']:.1f} M / {end['trueBearingDeg']:.1f} T, "
            f"threshold {t['latitude']:.5f} {t['longitude']:.5f}"
        )
```

```sql
SELECT json_extract(r.value, '$.designator') AS runway,
       json_extract(d.value, '$.designator') AS runway_end,
       round(json_extract(d.value, '$.magneticBearingDeg'), 1) AS magnetic,
       round(json_extract(d.value, '$.trueBearingDeg'), 1) AS true_bearing
FROM airbases AS a,
     json_each(a.runways) AS r,
     json_each(r.value, '$.directions') AS d
WHERE a.theatre = 'Caucasus' AND a.name = 'Batumi'
ORDER BY runway_end;
```

## SAM threat ranges on a map

Each SAM system's widest engagement `envelope` as a GeoJSON ring around a site.

```ts
import { loadAirbases, loadThreats } from 'dcs-world-reference';

const site = (await loadAirbases())['Caucasus.22']?.referencePoint;
if (!site) throw new Error('no Batumi reference point');

function ring(lat: number, lon: number, km: number): number[][] {
  const points: number[][] = [];
  for (let i = 0; i <= 64; i++) {
    const a = (i / 64) * 2 * Math.PI;
    const dLat = (km / 111.32) * Math.cos(a);
    const dLon = ((km / 111.32) * Math.sin(a)) / Math.cos((lat * Math.PI) / 180);
    points.push([lon + dLon, lat + dLat]);
  }
  return points;
}

const features = Object.values(await loadThreats())
  .filter((t) => t.kind === 'sam')
  .flatMap((t) => {
    const ranges = (t.components ?? []).map((c) => c.envelope?.rMaxKm ?? 0);
    const rMaxKm = Math.max(0, ...ranges);
    if (rMaxKm === 0) return [];
    return [{
      type: 'Feature',
      properties: { threat: t.id, name: t.natoDesignation ?? t.id, rMaxKm },
      geometry: { type: 'Polygon', coordinates: [ring(site.latitude, site.longitude, rMaxKm)] },
    }];
  });
const map = { type: 'FeatureCollection', features };
const sa10 = features.find((f) => f.properties.name === 'SA-10');
console.log(`${map.features.length} SAM rings; SA-10 reaches ${sa10?.properties.rMaxKm} km`);
```

```sql
SELECT t.id,
       t.natoDesignation,
       max(json_extract(c.value, '$.envelope.rMaxKm')) AS r_max_km,
       max(json_extract(c.value, '$.envelope.hMaxM')) AS h_max_m
FROM threats AS t, json_each(t.components) AS c
WHERE t.kind = 'sam'
GROUP BY t.id
HAVING r_max_km IS NOT NULL
ORDER BY r_max_km DESC;
```

## A unit's weapon systems and missile channels

One `weaponSystems` entry per launcher (`WS[i].LN[j]`).

```python
from dcs_world_reference import ground_vehicles, weapons

launcher = ground_vehicles()["SA-11 Buk LN 9A310M1"]
missiles = weapons()
for ws in launcher.get("weaponSystems", []):
    fired = [missiles[w]["displayName"] for w in ws.get("weapons", [])]
    print(
        f"WS{ws['ws']}.LN{ws['ln']}: range {ws.get('rMinKm')}-{ws.get('rMaxKm')} km, "
        f"{ws.get('missileChannels', 0)} missile channels, fires {fired or 'nothing (tracking)'}"
    )
```

```lua
local ref = require("dcs_world_reference")

local launcher = ref.ground_vehicles["SA-11 Buk LN 9A310M1"]
for _, ws in ipairs(launcher.weaponSystems) do
    local fired = {}
    for _, id in ipairs(ws.weapons or {}) do
        fired[#fired + 1] = ref.weapons[id].displayName
    end
    print(("WS%d.LN%d: %s km, %s missile channels, fires %s"):format(
        ws.ws, ws.ln, tostring(ws.rMaxKm), tostring(ws.missileChannels),
        #fired > 0 and table.concat(fired, ", ") or "nothing (tracking)"))
end
```

## Find stores by display name

```ts
import { loadStores } from 'dcs-world-reference';

const pattern = /GBU-12/i;
const found = Object.values(await loadStores())
  .filter((s) => pattern.test(s.displayName))
  .map((s) => `${s.clsid}  ${s.displayName}`)
  .sort();
console.log(`${found.length} stores match ${pattern}`);
for (const line of found.slice(0, 5)) console.log(line);
```

```sql
SELECT clsid, displayName, kind, categoryName
FROM stores
WHERE displayName LIKE '%GBU-12%'
ORDER BY displayName;
```

```lua
local ref = require("dcs_world_reference")

local found = {}
for clsid, store in pairs(ref.stores) do
    if store.displayName:find("GBU-12", 1, true) then
        found[#found + 1] = clsid .. "  " .. store.displayName
    end
end
table.sort(found)
print(#found .. " stores match GBU-12")
print(found[1])
```

## Airbase stands that fit an aircraft

The mission editor's rule, `Entity.StandLimits`; `standsFor` does the same.

```python
from dcs_world_reference import aircraft, airbases

plane = aircraft()["C-130J-30"]
dims = plane["dimensions"]
width = dims.get("wingSpanM", dims.get("rotorDiameterM"))
kind = "helicopters" if plane["kind"] == "rotary" else "airplanes"
kutaisi = airbases()["Caucasus.25"]
fits = [
    stand.get("name", str(stand["termIndex"]))
    for stand in kutaisi.get("stands", [])
    if (limits := stand.get("limits"))
    and width is not None
    and width < limits["maxWidthM"]
    and dims["lengthM"] < limits["maxLengthM"]
    and dims["heightM"] < limits.get("maxHeightM", 1000)
    and limits[kind]
]
print(f"{plane['displayName']} fits {len(fits)} of {len(kutaisi.get('stands', []))} stands at {kutaisi['name']}")
```

```sql
WITH plane AS (
  SELECT coalesce(json_extract(dimensions, '$.wingSpanM'),
                  json_extract(dimensions, '$.rotorDiameterM')) AS width,
         json_extract(dimensions, '$.lengthM') AS length,
         json_extract(dimensions, '$.heightM') AS height,
         CASE kind WHEN 'rotary' THEN '$.limits.helicopters'
                   ELSE '$.limits.airplanes' END AS allowed
  FROM aircraft WHERE id = 'C-130J-30'
)
SELECT json_extract(s.value, '$.name') AS stand,
       json_extract(s.value, '$.limits.maxWidthM') AS max_width_m
FROM airbases AS a, json_each(a.stands) AS s, plane AS p
WHERE a.id = 'Caucasus.25'
  AND p.width < json_extract(s.value, '$.limits.maxWidthM')
  AND p.length < json_extract(s.value, '$.limits.maxLengthM')
  AND p.height < coalesce(json_extract(s.value, '$.limits.maxHeightM'), 1000)
  AND json_extract(s.value, p.allowed)
ORDER BY stand;
```

## Navaids for a runway

A runway end's ILS or PRMG `navaids` and their `equipment` beacons.

```lua
local ref = require("dcs_world_reference")

local batumi = ref.airbases["Caucasus.22"]
for _, runway in ipairs(batumi.runways) do
    for _, dir in ipairs(runway.directions) do
        for _, navaid_id in ipairs(dir.navaids or {}) do
            local navaid = ref.navaids[navaid_id]
            print(("runway %s: %s %s %.2f MHz"):format(
                dir.designator, navaid.type, navaid.callsign, navaid.frequencyHz / 1e6))
            for _, beacon_id in ipairs(navaid.equipment) do
                local beacon = ref.beacons[beacon_id]
                print("  " .. beacon.typeName .. " " .. beacon.displayName)
            end
        end
    end
end
```

```sql
SELECT json_extract(a.runways, '$[' || json_extract(l.path, '$[0]') || '].directions['
                    || json_extract(l.path, '$[1]') || '].designator') AS runway_end,
       n.type, n.callsign, n.frequencyHz / 1e6 AS mhz,
       b.typeName, b.displayName
FROM airbases AS a
JOIN airbases__runways_directions_navaids AS l ON l.airbases_id = a.id
JOIN navaids AS n ON n.id = l.navaids_id
JOIN navaids__equipment AS e ON e.navaids_id = n.id
JOIN beacons AS b ON b.id = e.beacons_id
WHERE a.id = 'Caucasus.22'
ORDER BY runway_end, b.typeName;
```

## Map coordinates to latitude and longitude

DCS map metres (`x` north, `z` east) to WGS84 and back; a theatre id or any of its names.

```ts
import { loadAirbases, toLatLon, toMapXZ } from 'dcs-world-reference';

const batumi = (await loadAirbases())['Caucasus.22']?.referencePoint;
if (!batumi) throw new Error('no Batumi reference point');
const geo = await toLatLon('Caucasus', batumi.x, batumi.z);
const back = await toMapXZ('Caucasus', geo.lat, geo.lon);
const error = Math.hypot(back.x - batumi.x, back.z - batumi.z);
console.log(`Batumi ${geo.lat.toFixed(6)}, ${geo.lon.toFixed(6)}; round trip ${error < 0.001 ? 'under 1 mm' : error}`);
```

```python
import math

import dcs_world_reference as ref

batumi = ref.airbases()["Caucasus.22"]["referencePoint"]
geo = ref.to_lat_lon("Caucasus", batumi["x"], batumi["z"])
print(f"Batumi {geo['lat']:.6f}, {geo['lon']:.6f}")
xz = ref.to_map_xz("Caucasus", batumi["latitude"], batumi["longitude"])
print(f"DCS's own lat/lon lands {math.hypot(xz['x'] - batumi['x'], xz['z'] - batumi['z']):.3f} m off")
nellis = ref.to_map_xz("NTTR", 36.2359, -115.0343)
print(f"NTTR is {ref.theatre_by_name('NTTR')['id']}: x {nellis['x']:.0f}, z {nellis['z']:.0f}")
```

```lua
local ref = require("dcs_world_reference")

local batumi = ref.airbases["Caucasus.22"].referencePoint
local geo = ref.toLatLon("Caucasus", batumi.x, batumi.z)
local back = ref.toMapXZ("Caucasus", geo.lat, geo.lon)
local err = math.sqrt((back.x - batumi.x) ^ 2 + (back.z - batumi.z) ^ 2)
print(("Batumi %.6f, %.6f; round trip %s"):format(geo.lat, geo.lon, err < 0.001 and "under 1 mm" or err))
```

## A SAM ring with its dead zone as GeoJSON

`threatRingGeoJSON` cuts the minimum range out as a hole.

```ts
import { loadAirbases, loadThreats, threatRange, threatRingGeoJSON, unitClass } from 'dcs-world-reference';

const site = (await loadAirbases())['Caucasus.22']?.referencePoint;
const sa10 = Object.values(await loadThreats()).find((t) => t.natoDesignation === 'SA-10');
if (!site || !sa10) throw new Error('no site or SA-10');
const range = await threatRange(sa10.id);
const map = await threatRingGeoJSON(sa10.id, site.latitude, site.longitude, { segments: 64 });
const [outer, hole] = map.features[0].geometry.coordinates;
const classes = await Promise.all((sa10.components ?? []).map((c) => unitClass(c.unit)));
console.log(`SA-10 ${range.rMinKm}-${range.rMaxKm} km, radar ${range.detectionKm} km: ` +
  `ring of ${outer?.length} points, hole of ${hole?.length}; units ${[...new Set(classes)].join(', ')}`);
```

```python
import dcs_world_reference as ref

site = ref.airbases()["Caucasus.22"]["referencePoint"]
sa10 = next(t for t in ref.threats().values() if t.get("natoDesignation") == "SA-10")
rng = ref.threat_range(sa10["id"])
fc = ref.threat_ring_geojson(sa10["id"], site["latitude"], site["longitude"], segments=64)
outer, hole = fc["features"][0]["geometry"]["coordinates"]
classes = sorted({ref.unit_class(c["unit"]) for c in sa10.get("components", [])})
print(f"SA-10 {rng['rMinKm']}-{rng['rMaxKm']} km: ring of {len(outer)} points, hole of {len(hole)}; units {classes}")
```

## Fit a loadout, weigh it and check a radio preset

`fitStores` keeps the stations' `forbidden`/`required` rules; `loadoutMass` defaults to full internal fuel.

```ts
import { fitStores, isValidFrequency, loadoutMass, radioBands } from 'dcs-world-reference';

const request = ['{Mk_83AIR}', '{Mk_83AIR}', '{Mk_83AIR}', '{Mk_83AIR}'];
const fit = await fitStores('FA-18C_hornet', request);
if (fit.conflicts) throw new Error(`does not fit: ${JSON.stringify(fit.conflicts)}`);
const mass = await loadoutMass('FA-18C_hornet', fit.assignment);
console.log(`stations ${Object.keys(fit.assignment).join(', ')}: total ${mass.totalKg} kg of ${mass.maxTakeoffKg}`);
const tooMany = await fitStores('FA-18C_hornet', Array<string>(6).fill('{Mk_83AIR}'));
console.log(`six: ${tooMany.conflicts?.map((c) => c.reason).join(', ')}`);
for (const radio of await radioBands('FA-18C_hornet')) {
  const check = await isValidFrequency('FA-18C_hornet', radio.index, 251.01);
  console.log(`radio ${radio.index} (${radio.band}): 251.01 MHz ${check.ok ? 'ok' : check.reason}`);
}
```

```python
import dcs_world_reference as ref

fit = ref.fit_stores("FA-18C_hornet", ["{Mk_83AIR}"] * 4)
assignment = fit["assignment"]
mass = ref.loadout_mass("FA-18C_hornet", assignment, fuel_kg=3000)
print(f"stations {sorted(assignment)}: total {mass['totalKg']} kg, over MTOW: {mass['overMtow']}")
for radio in ref.radio_bands("FA-18C_hornet"):
    check = ref.is_valid_frequency("FA-18C_hornet", radio["index"], 243.0)
    print(f"radio {radio['index']} {radio['band']}: 243.0 MHz {'ok' if check['ok'] else check['reason']}")
```

```lua
local ref = require("dcs_world_reference")

local fit = ref.fitStores("FA-18C_hornet", { "{Mk_83AIR}", "{Mk_83AIR}", "{Mk_83AIR}", "{Mk_83AIR}" })
assert(fit.assignment, "does not fit")
local mass = ref.loadoutMass("FA-18C_hornet", fit.assignment)
print(("total %.1f kg (stores %.1f kg, fuel %.0f kg)"):format(mass.totalKg, mass.storesKg, mass.fuelKg))
local check = ref.isValidFrequency("FA-18C_hornet", 0, 251.01)
print("251.01 MHz on radio 0: " .. (check.ok and "ok" or check.reason))
```

## The runway into the wind and its approach aids

`bestRunway` takes the wind direction (from, degrees true) and speed (kt); DCS gives TACAN beacons no X/Y mode.

```ts
import { bestRunway, loadAirbases, loadBeacons, loadNavaids, navaidsFor, tacanFrequency } from 'dcs-world-reference';

const batumi = 'Caucasus.22';
const best = await bestRunway(batumi, 140, 18);
console.log(`runway ${best.end.designator}: headwind ${best.headwindKt.toFixed(1)} kt, crosswind ${best.crosswindKt.toFixed(1)} kt`);
const navaids = await loadNavaids();
for (const id of await navaidsFor(batumi, best.end.designator)) {
  const navaid = navaids[id];
  console.log(`  ${navaid?.type} ${navaid?.callsign ?? ''} ${((navaid?.frequencyHz ?? 0) / 1e6).toFixed(2)} MHz`);
}
const beacons = await loadBeacons();
for (const id of (await loadAirbases())[batumi]?.beacons ?? []) {
  const beacon = beacons[id];
  if (beacon?.typeName !== 'BEACON_TYPE_TACAN' || beacon.channel === undefined) continue;
  const tuned = await tacanFrequency(beacon.channel, 'X', 'air');
  console.log(`  TACAN ${beacon.channel}X ${beacon.callsign}: interrogate ${tuned.txMHz} MHz, reply ${tuned.rxMHz} MHz`);
}
```

```python
import dcs_world_reference as ref

batumi = "Caucasus.22"
best = ref.best_runway(batumi, wind_from_deg_true=140, wind_kt=18)
end = best["end"]
print(f"runway {end['designator']} ({end['magDeg']:.0f} M): headwind {best['headwindKt']:.1f} kt, crosswind {best['crosswindKt']:.1f} kt")
for nid in ref.navaids_for(batumi, end["designator"]):
    navaid = ref.navaids()[nid]
    print(f"  {navaid['type']} {navaid.get('callsign', '')} {navaid.get('frequencyHz', 0) / 1e6:.2f} MHz")
for bid in ref.airbases()[batumi].get("beacons", []):
    beacon = ref.beacons()[bid]
    if beacon["typeName"] == "BEACON_TYPE_TACAN" and "channel" in beacon:
        tuned = ref.tacan_frequency(int(beacon["channel"]), "X", "air")
        print(f"  TACAN {beacon['channel']:.0f}X {beacon.get('callsign')}: interrogate {tuned['txMHz']:.0f} MHz, reply {tuned['rxMHz']:.0f} MHz")
```

```lua
local ref = require("dcs_world_reference")

local best = ref.bestRunway("Caucasus.22", 140, 18)
print(("runway %s: headwind %.1f kt, crosswind %.1f kt"):format(best["end"].designator, best.headwindKt, best.crosswindKt))
for _, id in ipairs(ref.navaidsFor("Caucasus.22", best["end"].designator)) do
    local navaid = ref.navaids[id]
    print(("  %s %s %.2f MHz"):format(navaid.type, navaid.callsign or "", (navaid.frequencyHz or 0) / 1e6))
end
local tuned = ref.tacanFrequency(16, "X", "air")
print(("  TACAN 16X: interrogate %d MHz, reply %d MHz"):format(tuned.txMHz, tuned.rxMHz))
```

## Paste a mission editor coordinate

`Metric` parses to map metres, the others to lat/lon; MGRS to the centre of its square.

```ts
import { formatCoord, parseCoord, toLatLon } from 'dcs-world-reference';

const pasted = [
  'Metric: X+00380826 Z-00352108',
  `Lat Long Precise: N 29°32'03.53"   E 52°35'55.82"`,
  'MGRS GRID: 39 R XN 54929 68251',
];
for (const text of pasted) {
  const p = parseCoord(text);
  const geo = p.format === 'METRIC' ? await toLatLon('PersianGulf', p.x ?? 0, p.z ?? 0) : { lat: p.lat ?? 0, lon: p.lon ?? 0 };
  console.log(`${p.format.padStart(6)}: ${formatCoord(geo.lat, geo.lon, 'DDM')} | ${formatCoord(geo.lat, geo.lon, 'MGRS')}`);
}
```

```python
import dcs_world_reference as ref

pasted = [
    "Metric: X+00380826 Z-00352108",
    "Lat Long Precise: N 29°32'03.53\"   E 52°35'55.82\"",
    "MGRS GRID: 39 R XN 54929 68251",
]
for text in pasted:
    p = ref.parse_coord(text)
    if p["format"] == "METRIC":
        p = {**p, **ref.to_lat_lon("PersianGulf", p["x"], p["z"])}
    print(f"{p['format']:>6}: {ref.format_coord(p['lat'], p['lon'], 'DDM')} | {ref.format_coord(p['lat'], p['lon'], 'MGRS')}")
a, b = (ref.parse_coord(t) for t in pasted[1:])
print(f"MGRS square centre is {ref.distance_bearing(a['lat'], a['lon'], b['lat'], b['lon'])['distM']:.1f} m from the precise point")
```

```lua
local ref = require("dcs_world_reference")

local p = ref.parseCoord("MGRS GRID: 39 R XN 54929 68251")
print(("%s -> %s"):format(p.format, ref.formatCoord(p.lat, p.lon, "DMS", 2)))
local m = ref.parseCoord("Metric: X+00380826 Z-00352108")
local geo = ref.toLatLon("PersianGulf", m.x, m.z)
print(("METRIC -> %s"):format(ref.formatCoord(geo.lat, geo.lon, "MGRS")))
```

## A weapon, who launches it and what they see

`weaponInfo` also takes a store CLSID delivering one weapon type.

```ts
import { launchPlatforms, unitDetection, weaponInfo } from 'dcs-world-reference';

const info = await weaponInfo('SA9M311');
console.log(`${info.displayName}: ${info.rangeKm} km, warhead ${info.warhead?.type} ${info.warhead?.explosiveMassKg} kg`);
const platforms = await launchPlatforms(info.id);
for (const unit of [...platforms.groundVehicles, ...platforms.ships]) {
  const seen = await unitDetection(unit);
  const radars = seen.sensors.filter((s) => s.kind === 'radar').map((s) => s.id);
  console.log(`  ${unit}: detects ${(seen.detectionRangeM ?? 0) / 1000} km, threat ${(seen.threatRangeM ?? 0) / 1000} km, radars ${radars.join(', ')}`);
}
```

```python
import dcs_world_reference as ref

info = ref.weapon_info("SA9M311")
warhead = info.get("warhead", {})
print(f"{info['displayName']}: {info.get('categoryName')}, {info.get('rangeKm')} km, warhead {warhead.get('type')} {warhead.get('explosiveMassKg')} kg")
platforms = ref.launch_platforms(info["id"])
for unit in platforms["groundVehicles"] + platforms["ships"]:
    seen = ref.unit_detection(unit)
    radars = [s["id"] for s in seen["sensors"] if s["kind"] == "radar"]
    print(f"  {unit}: detects {seen.get('detectionRangeM', 0) / 1000:.0f} km, threat {seen.get('threatRangeM', 0) / 1000:.0f} km, radars {radars}")
```

## Divert airfields that can park an aircraft

`countryId` also takes common names (`United States`).

```ts
import { countryId, countryName, destination, liveriesFor, loadAirbases, nearestAirbases, standsFor } from 'dcs-world-reference';

const here = destination(42.25, 42.0, 270, 30000);
const airbases = await loadAirbases();
for (const field of await nearestAirbases('Caucasus', here.lat, here.lon, { minRunwayM: 2000, n: 3 })) {
  const stands = await standsFor(field.id, 'C-130J-30');
  console.log(`${airbases[field.id]?.name}: ${field.distNm.toFixed(0)} nm, ${stands.length} stands for a C-130J`);
}
const usa = await countryId('United States');
if (usa === undefined) throw new Error('no such country');
console.log(`${await countryName(usa)} C-130J liveries: ${(await liveriesFor('C-130J-30', usa)).length}`);
```

```python
import dcs_world_reference as ref

here = ref.destination(42.25, 42.0, bearing_deg=270, dist_m=30000)
for field in ref.nearest_airbases("Caucasus", here["lat"], here["lon"], min_runway_m=2000, n=3):
    ab = ref.airbases()[field["id"]]
    stands = ref.stands_for(field["id"], "C-130J-30")
    print(f"{ab['name']}: {field['distNm']:.0f} nm at {field['bearingDeg']:03.0f} T, {len(stands)} stands for a C-130J")
usa = ref.country_id("United States")
assert usa is not None
print(f"{ref.country_name(usa)} C-130J liveries: {len(ref.liveries_for('C-130J-30', usa))}")
```

```lua
local ref = require("dcs_world_reference")

local here = ref.destination(42.25, 42.0, 270, 30000)
for _, field in ipairs(ref.nearestAirbases("Caucasus", here.lat, here.lon, { minRunwayM = 2000, n = 3 })) do
    local stands = ref.standsFor(field.id, "C-130J-30")
    print(("%s: %.0f nm, %d stands for a C-130J"):format(ref.airbases[field.id].name, field.distNm, #stands))
end
print(("USA is country %d"):format(ref.countryId("United States")))
```

## AI tasks for a CAP flight

`availableFor` lists the group categories and Mission Editor group tasks an action is offered for;
`probe` is how DCS took each id casing in each context.

```python
from dcs_world_reference import actions


def offered(action, category, group_task):
    return any(
        f["category"] == category and f["groupTask"] == group_task
        for f in action.get("availableFor", [])
    )


for a in sorted(actions().values(), key=lambda a: (a["kind"], a["dcsId"])):
    if a["kind"] in ("task", "enrouteTask") and offered(a, "plane", "CAP"):
        print(f"{a['kind']:<11} {a['dcsId']:<19} {a['displayName']}")
for p in actions()["ORBIT"].get("probe", []):
    if p["category"] == "plane":
        seen = "seen" if p.get("effectObserved") else "not seen"
        print(f"{p['context']:<9} {p['id']}: {'accepted' if p['accepted'] else 'rejected'}, effect {seen}")
```

```sql
SELECT a.kind, a.dcsId, a.displayName
FROM actions AS a, json_each(a.availableFor) AS f
WHERE json_extract(f.value, '$.category') = 'plane'
  AND json_extract(f.value, '$.groupTask') = 'CAP'
  AND a.kind IN ('task', 'enrouteTask')
ORDER BY a.kind, a.dcsId;
```
