# dcs-world-reference

DCS World reference data as JSON with TypeScript types, records keyed by id (`clsid` for `stores`).
ESM, Node >= 20.10. Built from [dcs-world-schema](https://github.com/YoloWingPixie/dcs-world-schema).

```bash
task package
npm install /path/to/dcs-world-schema/dist/dcs-world-reference-*.tgz
```

```ts
import { aircraft } from 'dcs-world-reference/aircraft';        // one series, loaded on import
import { dcsVersion, loadBeacons, BeaconType } from 'dcs-world-reference';

console.log(dcsVersion, aircraft['F-16C_50'].displayName);
const tacans = Object.values(await loadBeacons()).filter((b) => b.type === BeaconType.BEACON_TYPE_TACAN);
```

`load<Series>()`, `loadSeries(name)` (`seriesNames`) and `loadManifest()` load lazily. Record types
(`Aircraft`, ...) are exported from the root; enums are value unions plus a same-named object of
DCS names. Raw bundles: `dcs-world-reference/data/<series>.json`. A livery's id is its path
relative to the DCS install.

## Lookups

Async; return arrays (`[]` when nothing matches):

| Helper | Example |
| --- | --- |
| `referencesTo(series, id)`: every record referencing it, as `{ series, id, path }` | `await referencesTo('weapons', 'AIM_120C')` |
| `storesDelivering(weaponId)`: store CLSIDs | `await storesDelivering('AIM_120C')` |
| `aircraftCarrying(weaponId)`: aircraft with a station accepting such a store | `await aircraftCarrying('AIM_120C')` |
| `threatsForUnit(unitId)`: threat systems the unit is or is part of | `await threatsForUnit('SA-11 Buk LN 9A310M1')` |
| `airbaseByName(name, theatre?)` | `await airbaseByName('Batumi', 'Caucasus') // ['Caucasus.22']` |
| `findByName(series, name)`: by `displayName` or `name` | `await findByName('aircraft', 'F-16CM bl.50') // ['F-16C_50']` |

Names match trimmed and ASCII-lowercased (`nameKey`).

## Reference helpers

Async except `distanceBearing`, `destination`, `formatCoord` and `parseCoord`.

| Helper | Example |
| --- | --- |
| `theatreByName(name)`: by id, `displayName`, `directory` or `aliases` | `(await theatreByName('NTTR'))?.id // 'Nevada'` |
| `toMapXZ(theatre, lat, lon)` / `toLatLon(theatre, x, z)`: the theatre's Transverse Mercator | `await toMapXZ('Caucasus', 41.6, 41.6) // { x, z }` |
| `threatRange(threatId)`: union of the envelopes, sensors' `detectionKm` | `await threatRange('SA5B55') // { rMinKm: 5, rMaxKm: 120, hMinM: 25, hMaxM: 25000, detectionKm: 260 }` |
| `threatForUnitType(unitType)`: threat systems of a unit type | `await threatForUnitType('S-300PS 5P85C ln') // ['SA5B55']` |
| `threatRingGeoJSON(threatId, lat, lon, { segments })`: range ring (min ring as hole) | `await threatRingGeoJSON('SA5B55', 41.6, 41.6, { segments: 64 })` |
| `aircraftRoles(aircraftId)` | `await aircraftRoles('KC-135') // ['tanker']` |
| `unitClass(unitId)` | `await unitClass('S-300PS 5P85C ln') // 'sam'` |
| `stationsAccepting(aircraftId, clsid)` / `canMount(aircraftId, station, clsid)` | `await stationsAccepting('F-16C_50', 'CATM-9M')` |
| `fitStores(aircraftId, clsids)`: `{ assignment }` or `{ conflicts }` | `await fitStores('FA-18C_hornet', Array(5).fill('{Mk_83AIR}'))` |
| `loadoutMass(aircraftId, loadout, fuelKg?)`: empty + stores + fuel (default full) | `(await loadoutMass('FA-18C_hornet', { 2: '{Mk_83AIR}' })).totalKg` |
| `radioBands(aircraftId)` / `isValidFrequency(aircraftId, radioIndex, mhz)` | `await isValidFrequency('F-16C_50', 0, 251.01) // { ok: false, reason: 'offStep' }` |
| `weaponInfo(idOrClsid)`: the weapon record, `warhead` resolved; a store CLSID delivering one weapon type works too | `(await weaponInfo('AIM_120C')).rangeKm // 61` |
| `launchPlatforms(weaponId)`: `{ aircraft, groundVehicles, ships }` | `(await launchPlatforms('SA9M311')).ships // ['CV_1143_5', 'KUZNECOW', ...]` |
| `modelToUnits(shape)`: units whose `model.shape` matches (ASCII case-insensitive) | `await modelToUnits('F-16') // ['F-16C bl.50', 'F-16C bl.52d']` |
| `unitDetection(unitId)`: `detection` fields and `sensors` | `(await unitDetection('SA-11 Buk SR 9S18M1')).detectionRangeM // 100000` |
| `tacanFrequency(channel, band, role)` / `tacanChannel(mhz, role)` / `isValidTacan(channel, band)` | `await tacanFrequency(16, 'X', 'air') // { txMHz: 1040, rxMHz: 977 }` |
| `navaidsFor(airbaseId, runway?)`: ILS/PRMG navaid ids, of one runway end | `await navaidsFor('Caucasus.22', '13') // ['Caucasus.ILS.airfield22_0']` |
| `runwayEnds(airbaseId)` / `bestRunway(airbaseId, windFromDegTrue, windKt)` | `(await bestRunway('Caucasus.22', 300, 15)).end.designator // '31'` |
| `nearestAirbases(theatre, lat, lon, { minRunwayM?, n = 5, category? })` | `await nearestAirbases('Caucasus', 42, 42, { n: 1, minRunwayM: 2400 }) // [{ id: 'Caucasus.25', ... }]` |
| `standsFor(airbaseId, aircraftId)`: `termIndex` of the stands the editor accepts it on | `(await standsFor('Caucasus.25', 'C-130J-30')).length // 13` |
| `countryId(nameOrAlias)` / `countryName(id)` | `await countryId('United States') // 2` |
| `liveriesFor(unitType, countryId?)` | `await liveriesFor('F-16C_50', 2)` |
| `datalinkCapability(aircraftId)`: the datalink record, or `undefined` | `(await datalinkCapability('FA-18C_hornet'))?.datalinkType // 'Link16'` |
| `distanceBearing(lat1, lon1, lat2, lon2)` / `destination(lat, lon, bearingDeg, distM)` | `distanceBearing(41.6, 41.6, 42, 42).distM // 55476.9` |
| `formatCoord(lat, lon, fmt, precision?)` / `parseCoord(text)`: DD, DMS, DDM, MGRS; parse also DCS Metric | `formatCoord(41.6096, 41.6002, 'MGRS') // '37 T GG 16662 09697'` |

Unknown ids and impossible inputs throw. The rules the helpers follow are in the
[Python README](../python/README.md#rules); all four packages pass the same conformance vectors.
