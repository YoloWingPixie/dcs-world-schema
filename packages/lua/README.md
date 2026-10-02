# dcs-world-reference (Lua)

DCS World reference data as Lua 5.1 tables, one file per series, records keyed by id (`clsid`
for `stores`). Built from [dcs-world-schema](https://github.com/YoloWingPixie/dcs-world-schema).

`task package` writes `dist/dcs-world-reference-lua-<version>-dcs<dcs version>.zip`, holding the
`dcs_world_reference/` folder.

```lua
package.path = "/path/to/?.lua;/path/to/?/init.lua;" .. package.path
local ref = require("dcs_world_reference")
print(ref.dcsVersion, ref.aircraft["F-16C_50"].displayName)
```

From a DCS hook, with the folder in `Saved Games/DCS/Scripts/`:

```lua
local ref = dofile(lfs.writedir() .. "Scripts/dcs_world_reference/init.lua")
local tacan = ref.beacons["Caucasus.airfield22_2"]
```

Series load on first access (`ref[name]` or `ref.load(name)`); `ref.manifest` is the extraction
provenance. `ref.setDir(dir)` loads the series files from `dir`, `ref.setDir(nil)` through
`require("dcs_world_reference.<series>")`. The mission scripting environment has no `require` or
`lfs` unless desanitised; use `dofile` with an absolute path. `airbases.lua` is about 6.5 MB (40 MB
of Lua memory); load only the series you need. Empty arrays and objects are both `{}`.

EmmyLua annotations for every record and for `DcsWorldReference` (the table `init.lua` returns)
are in `dcs_world_reference/annotations.lua`; add it to `Lua.workspace.library`.

## Lookups

Return new arrays (`{}` when nothing matches):

| Helper | Example |
| --- | --- |
| `ref.referencesTo(series, id)`: every record referencing it, as `{series, id, path}` | `ref.referencesTo("weapons", "AIM_120C")` |
| `ref.storesDelivering(weaponId)`: store CLSIDs | `ref.storesDelivering("AIM_120C")` |
| `ref.aircraftCarrying(weaponId)`: aircraft with a station accepting such a store | `ref.aircraftCarrying("AIM_120C")` |
| `ref.threatsForUnit(unitId)`: threat systems the unit is or is part of | `ref.threatsForUnit("SA-11 Buk LN 9A310M1")` |
| `ref.airbaseByName(name, theatre)` (`theatre` optional) | `ref.airbaseByName("Batumi", "Caucasus") -- {"Caucasus.22"}` |
| `ref.findByName(series, name)`: by `displayName` or `name` | `ref.findByName("aircraft", "F-16CM bl.50") -- {"F-16C_50"}` |

Names match trimmed and ASCII-lowercased (`ref.nameKey`).

## Reference helpers

Unknown ids and impossible inputs raise errors (`pcall` them).

| Helper | Example |
| --- | --- |
| `ref.theatreByName(name)`: by id, `displayName`, `directory` or `aliases` | `ref.theatreByName("NTTR").id -- "Nevada"` |
| `ref.toMapXZ(theatre, lat, lon)` / `ref.toLatLon(theatre, x, z)`: the theatre's Transverse Mercator | `ref.toMapXZ("Caucasus", 41.6, 41.6) -- {x = ..., z = ...}` |
| `ref.threatRange(threatId)`: union of the envelopes, sensors' `detectionKm` | `ref.threatRange("SA5B55").rMaxKm -- 120` |
| `ref.threatForUnitType(unitType)`: threat systems of a unit type | `ref.threatForUnitType("S-300PS 5P85C ln") -- {"SA5B55"}` |
| `ref.threatRingGeoJSON(threatId, lat, lon, {segments = 64})`: range ring (min ring as hole) | `ref.threatRingGeoJSON("SA5B55", 41.6, 41.6)` |
| `ref.aircraftRoles(aircraftId)` | `ref.aircraftRoles("KC-135") -- {"tanker"}` |
| `ref.unitClass(unitId)` | `ref.unitClass("S-300PS 5P85C ln") -- "sam"` |
| `ref.stationsAccepting(aircraftId, clsid)` / `ref.canMount(aircraftId, station, clsid)` | `ref.stationsAccepting("F-16C_50", "CATM-9M")` |
| `ref.fitStores(aircraftId, clsids)`: `{assignment = ...}` or `{conflicts = ...}` | `ref.fitStores("FA-18C_hornet", {"{Mk_83AIR}", "{Mk_83AIR}"})` |
| `ref.loadoutMass(aircraftId, loadout, fuelKg)` (`fuelKg` optional, default full) | `ref.loadoutMass("FA-18C_hornet", {[2] = "{Mk_83AIR}"}).totalKg` |
| `ref.radioBands(aircraftId)` / `ref.isValidFrequency(aircraftId, radioIndex, mhz)` | `ref.isValidFrequency("F-16C_50", 0, 251.01).reason -- "offStep"` |
| `ref.weaponInfo(idOrClsid)`: the weapon record, `warhead` resolved | `ref.weaponInfo("AIM_120C").rangeKm -- 61` |
| `ref.launchPlatforms(weaponId)`: `{aircraft = ..., groundVehicles = ..., ships = ...}` | `ref.launchPlatforms("SA9M311").groundVehicles -- {"2S6 Tunguska"}` |
| `ref.modelToUnits(shape)`: units whose `model.shape` matches (ASCII case-insensitive) | `ref.modelToUnits("F-16") -- {"F-16C bl.50", "F-16C bl.52d"}` |
| `ref.unitDetection(unitId)`: `detection` fields and `sensors` | `ref.unitDetection("SA-11 Buk SR 9S18M1").detectionRangeM -- 100000` |
| `ref.tacanFrequency(channel, band, role)` / `ref.tacanChannel(mhz, role)` / `ref.isValidTacan(channel, band)` | `ref.tacanFrequency(16, "X", "air").rxMHz -- 977` |
| `ref.navaidsFor(airbaseId, runway)` (`runway` optional) | `ref.navaidsFor("Caucasus.22", "13") -- {"Caucasus.ILS.airfield22_0"}` |
| `ref.runwayEnds(airbaseId)` / `ref.bestRunway(airbaseId, windFromDegTrue, windKt)` | `ref.bestRunway("Caucasus.22", 300, 15)["end"].designator -- "31"` |
| `ref.nearestAirbases(theatre, lat, lon, {minRunwayM = ..., n = 5, category = ...})` | `ref.nearestAirbases("Caucasus", 42, 42, {n = 1})[1].id` |
| `ref.standsFor(airbaseId, aircraftId)`: `termIndex` of the stands the editor accepts it on | `#ref.standsFor("Caucasus.25", "C-130J-30") -- 13` |
| `ref.countryId(nameOrAlias)` / `ref.countryName(id)` | `ref.countryId("United States") -- 2` |
| `ref.liveriesFor(unitType, countryId)` (`countryId` optional) | `ref.liveriesFor("F-16C_50", 2)` |
| `ref.datalinkCapability(aircraftId)`: the datalink record, or nil | `ref.datalinkCapability("FA-18C_hornet").datalinkType -- "Link16"` |
| `ref.distanceBearing(lat1, lon1, lat2, lon2)` / `ref.destination(lat, lon, bearingDeg, distM)` | `ref.distanceBearing(41.6, 41.6, 42, 42).distM` |
| `ref.formatCoord(lat, lon, fmt, precision)` / `ref.parseCoord(text)`: DD, DMS, DDM, MGRS; parse also DCS Metric | `ref.formatCoord(41.6096, 41.6002, "MGRS") -- "37 T GG 16662 09697"` |

A `fitStores` conflict's `index` counts from 1. The rules the helpers follow are in the
[Python README](../python/README.md#rules).
