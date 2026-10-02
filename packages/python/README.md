# dcs-world-reference

DCS World reference data as typed dictionaries, records keyed by id (`clsid` for `stores`).
Python >= 3.11, no dependencies. Built from
[dcs-world-schema](https://github.com/YoloWingPixie/dcs-world-schema).

```bash
task package
uv pip install /path/to/dcs-world-schema/dist/dcs_world_reference-*.whl
```

```python
import dcs_world_reference as ref
from dcs_world_reference.entities import BeaconTypeValues

print(ref.DCS_VERSION, ref.aircraft()["F-16C_50"]["displayName"])
tacans = [
    b
    for b in ref.beacons().values()
    if b["type"] == BeaconTypeValues["BEACON_TYPE_TACAN"]
]
```

One loader per series (`ref.SERIES`), read on first call and cached; treat the result as read-only.
`ref.manifest()` is the extraction provenance. Record types are `TypedDict`s in
`dcs_world_reference.entities`; enums are `Literal` unions with a `<Name>Values` table of DCS
names. A livery's id is its path relative to the DCS install.

## Lookups

Return lists (`[]` when nothing matches):

| Helper | Example |
| --- | --- |
| `references_to(series, id)`: every record referencing it, as `Reference` dicts (`series`, `id`, `path`) | `ref.references_to("weapons", "AIM_120C")` |
| `stores_delivering(weapon_id)`: store CLSIDs | `ref.stores_delivering("AIM_120C")` |
| `aircraft_carrying(weapon_id)`: aircraft with a station accepting such a store | `ref.aircraft_carrying("AIM_120C")` |
| `threats_for_unit(unit_id)`: threat systems the unit is or is part of | `ref.threats_for_unit("SA-11 Buk LN 9A310M1")` |
| `airbase_by_name(name, theatre=None)` | `ref.airbase_by_name("Batumi", "Caucasus")  # ['Caucasus.22']` |
| `find_by_name(series, name)`: by `displayName` or `name` | `ref.find_by_name("aircraft", "F-16CM bl.50")  # ['F-16C_50']` |

Names match trimmed and ASCII-lowercased (`ref.name_key`).

## Reference helpers

Unknown ids raise `KeyError`, impossible inputs `ValueError`.

| Helper | Example |
| --- | --- |
| `theatre_by_name(name)`: by id, `displayName`, `directory` or `aliases` | `ref.theatre_by_name("NTTR")["id"]  # 'Nevada'` |
| `to_map_xz(theatre, lat, lon)` / `to_lat_lon(theatre, x, z)`: the theatre's Transverse Mercator | `ref.to_map_xz("Caucasus", 41.6, 41.6)  # {'x': ..., 'z': ...}` |
| `threat_range(threat_id)`: union of the envelopes, sensors' `detectionKm` | `ref.threat_range("SA5B55")  # {'rMinKm': 5.0, 'rMaxKm': 120.0, ...}` |
| `threat_for_unit_type(unit_type)`: threat systems of a unit type | `ref.threat_for_unit_type("S-300PS 5P85C ln")  # ['SA5B55']` |
| `threat_ring_geojson(threat_id, lat, lon, segments=64)`: range ring (min ring as hole) | `ref.threat_ring_geojson("SA5B55", 41.6, 41.6)` |
| `aircraft_roles(aircraft_id)` | `ref.aircraft_roles("KC-135")  # ['tanker']` |
| `unit_class(unit_id)` | `ref.unit_class("S-300PS 5P85C ln")  # 'sam'` |
| `stations_accepting(aircraft_id, clsid)` / `can_mount(aircraft_id, station, clsid)` | `ref.stations_accepting("F-16C_50", "CATM-9M")` |
| `fit_stores(aircraft_id, clsids)`: `{"assignment": ...}` or `{"conflicts": ...}` | `ref.fit_stores("FA-18C_hornet", ["{Mk_83AIR}"] * 5)` |
| `loadout_mass(aircraft_id, loadout, fuel_kg=None)`: empty + stores + fuel (default full) | `ref.loadout_mass("FA-18C_hornet", {2: "{Mk_83AIR}"})["totalKg"]` |
| `radio_bands(aircraft_id)` / `is_valid_frequency(aircraft_id, radio_index, mhz)` | `ref.is_valid_frequency("F-16C_50", 0, 251.01)  # {'ok': False, 'reason': 'offStep'}` |
| `weapon_info(id_or_clsid)`: the weapon record, `warhead` resolved; a store CLSID delivering one weapon type works too | `ref.weapon_info("AIM_120C")["rangeKm"]  # 61.0` |
| `launch_platforms(weapon_id)`: `aircraft`, `groundVehicles`, `ships` | `ref.launch_platforms("SA9M311")["ships"]  # ['CV_1143_5', 'KUZNECOW', ...]` |
| `model_to_units(shape)`: units whose `model.shape` matches (ASCII case-insensitive) | `ref.model_to_units("F-16")  # ['F-16C bl.50', 'F-16C bl.52d']` |
| `unit_detection(unit_id)`: `detection` fields and `sensors` | `ref.unit_detection("SA-11 Buk SR 9S18M1")["detectionRangeM"]  # 100000` |
| `tacan_frequency(channel, band, role)` / `tacan_channel(mhz, role)` / `is_valid_tacan(channel, band)` | `ref.tacan_frequency(16, "X", "air")  # {'txMHz': 1040.0, 'rxMHz': 977.0}` |
| `navaids_for(airbase_id, runway=None)`: ILS/PRMG navaid ids, of one runway end | `ref.navaids_for("Caucasus.22", "13")  # ['Caucasus.ILS.airfield22_0']` |
| `runway_ends(airbase_id)` / `best_runway(airbase_id, wind_from_deg_true, wind_kt)` | `ref.best_runway("Caucasus.22", 300, 15)["end"]["designator"]  # '31'` |
| `nearest_airbases(theatre, lat, lon, min_runway_m=None, n=5, category=None)` | `ref.nearest_airbases("Caucasus", 42.0, 42.0, n=1, min_runway_m=2400)  # [{'id': 'Caucasus.25', 'distNm': 23.9..., ...}]` |
| `stands_for(airbase_id, aircraft_id)`: `termIndex` of the stands the editor accepts it on | `len(ref.stands_for("Caucasus.25", "C-130J-30"))  # 13` |
| `country_id(name_or_alias)` / `country_name(country_id)` | `ref.country_id("United States")  # 2` |
| `liveries_for(unit_type, country_id=None)` | `ref.liveries_for("F-16C_50", 2)` |
| `datalink_capability(aircraft_id)`: the datalink record, or None | `ref.datalink_capability("FA-18C_hornet")["datalinkType"]  # 'Link16'` |
| `distance_bearing(lat1, lon1, lat2, lon2)` / `destination(lat, lon, bearing_deg, dist_m)` | `ref.distance_bearing(41.6, 41.6, 42.0, 42.0)["distM"]  # 55476.9` |
| `format_coord(lat, lon, fmt, precision=None)` / `parse_coord(text)`: DD, DMS, DDM, MGRS; parse also DCS Metric | `ref.format_coord(41.6096, 41.6002, "MGRS")  # '37 T GG 16662 09697'` |

## Rules

The TypeScript, Lua and Go packages follow the same rules and pass the same conformance vectors;
docstrings have the details.

- `fit_stores`: stores are taken in list order. One no station accepts is `unsupported`; one with
  no free station beside those kept before it `noFreeStation`; one no placement of which keeps
  every station's `forbidden`/`required` rules `loadoutRules`. A `required` rule may be met by a
  store later in the list; a `required` station must hold a listed store, or be empty where the
  rule has `allowEmpty`; a `forbidden` rule with `anyStore` keeps its station empty. Every
  station accepting a store is a candidate whatever its `type` (internal bays included), as in
  the mission editor. Without conflicts each store gets the lowest-numbered station that leaves
  the rest placeable.
- `aircraft_roles` / `unit_class`: the `aircraft/roles` and `units/classes` rules of
  [overlays.yaml](../../tools/datamine/overlays.yaml) applied to DCS attributes, kind and tasks;
  every matching role, the first matching class (`other` if none).
- Radios: `index` is the `<n>` of the radio id `<aircraft>__radio<n>`; a frequency must lie in a
  range and, with `stepKHz`, on that grid.
- TACAN: ICAO channel plan (`beacons/tacanPlan`); `air` is the interrogator (1025 + channel - 1
  MHz), `ground` the beacon; `pairedVhfMHz` is the VOR/ILS pairing.
- `best_runway`: most headwind; ties (within `WIND_TOLERANCE_KT`) to least crosswind, longer
  runway, lower designator.
- `stands_for`: `Entity.StandLimits`: span (else rotor diameter), length and height below the
  stand's limits (height 1000 m when absent), stand open to the aircraft's kind.
- `country_id`: name, shortName, internationalName, idName or oldId, then `countries/aliases`.
- `liveries_for`: a livery without `countries` is offered to every country, one with an empty
  list to none; the Combined Joint Task Forces get every livery (`countries/allLiveries`).
- Geo: spherical (`EARTH_RADIUS_M`); MGRS is WGS84 UTM with the Norway and Svalbard zones,
  truncated. `parse_coord` reads the mission editor's copy formats, strips a `Label:` prefix and
  returns an MGRS square's centre.
- Values come from the records as extracted; a field the data lacks is left out.
