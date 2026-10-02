# dcsref

DCS World reference data as typed Go values embedded in the binary, records keyed by id (`clsid`
for `stores`). Go >= 1.24, standard library only. Built from
[dcs-world-schema](https://github.com/YoloWingPixie/dcs-world-schema).

```bash
go get github.com/YoloWingPixie/dcs-world-schema/packages/go@v0.4.0
```

The generated files (`*_gen.go`, `data/`) are committed on release tags only. For an unreleased
checkout, run `task package:go` and point your `go.mod` at it:

```
require github.com/YoloWingPixie/dcs-world-schema/packages/go v0.0.0
replace github.com/YoloWingPixie/dcs-world-schema/packages/go => /path/to/dcs-world-schema/packages/go
```

```go
import dcsref "github.com/YoloWingPixie/dcs-world-schema/packages/go"

viper := dcsref.LoadAircraft()["F-16C_50"]
fmt.Println(dcsref.DCSVersion, viper.DisplayName)
if viper.Aero.MaxSpeedKmh != nil { // optional fields are nil when absent
	fmt.Println(*viper.Aero.MaxSpeedKmh)
}
tacan := dcsref.BeaconTypeValues["BEACON_TYPE_TACAN"] // == dcsref.BeaconTypeTACAN
```

One loader per series (`SeriesNames`), decoded on first call and cached; treat maps as read-only.
`LoadManifest` is the extraction provenance. Optional fields are nil pointers, slices or maps
(`omitzero`, so records marshal back to their JSON); enums are typed constants with a
`<Name>Values` map; `_source` is `Sources`, free-form DCS fields `any`. A field mixing JSON
kinds is a tagged union (`isTanker` a `BoolOrNumber`; also `NumberOrString`, `Scalar`) with one
pointer set, decoding only its kinds. `Data()` is the embedded bundles as an `fs.FS`.

The data is about 21.7 MB of JSON, embedded gzip-compressed (about 1.9 MB); a binary importing
the package grows by about 3.2 MB.

## Lookups

| Function | Returns |
| --- | --- |
| `ReferencesTo(series, id)` | every record referencing record `id` of `series` (`[]Reference{Series, ID, Path}`) |
| `StoresDelivering(weaponID)` | CLSIDs of the stores delivering the weapon |
| `AircraftCarrying(weaponID)` | aircraft with a station accepting such a store |
| `ThreatsForUnit(unitID)` | threat systems the unit type is or is part of |
| `AirbaseByName(name, theatre)` | airbase ids by name, case-insensitive; `theatre` `""` for any |
| `FindByName(series, name)` | ids by `displayName` or `name`, case-insensitive |

Names match trimmed and ASCII-lowercased (`NameKey`).

## Helpers

Unknown ids return an error wrapping `ErrNotFound`, impossible inputs one wrapping `ErrInvalid`.

| Function | Returns |
| --- | --- |
| `TheatreByName(name)` | the theatre by id, display name, directory or alias (`ok` false if none) |
| `ToMapXZ(theatre, lat, lon)` / `ToLatLon(theatre, x, z)` | WGS84 to DCS map metres and back, through the theatre's projection |
| `ThreatRange(threatID)` | `ThreatLimits`: the union of its engagement envelopes and sensor reach |
| `ThreatForUnitType(unitType)` | threat systems the unit type belongs to |
| `ThreatRingGeoJSON(threatID, lat, lon, segments)` | a GeoJSON FeatureCollection of the engagement ring |
| `AircraftRoles(aircraftID)` / `UnitClass(unitID)` | roles and class from the `classification` index rules |
| `StationsAccepting(aircraftID, clsid)` / `CanMount(aircraftID, station, clsid)` | station fit of a store |
| `FitStores(aircraftID, clsids)` | a station assignment, or the conflicts preventing one |
| `LoadoutMass(aircraftID, loadout, fuelKg)` | empty + stores + fuel mass, against the max take-off mass |
| `RadioBands(aircraftID)` / `IsValidFrequency(aircraftID, radio, mhz)` | radio ranges, presets, step; frequency check |
| `WeaponInfo(idOrCLSID)` | the weapon record (a store's single weapon for a CLSID) with its warhead record |
| `LaunchPlatforms(weaponID)` | aircraft, ground vehicles and ships launching the weapon |
| `ModelToUnits(shape)` | unit ids whose model shape is `shape`, case-insensitive |
| `UnitDetectionOf(unitID)` | the unit's detection fields and its sensors' kind and range |
| `TacanFrequency(channel, band, role)` / `TacanChannel(mhz, role)` / `IsValidTacan(channel, band)` | TACAN/DME channel plan both ways |
| `NavaidsFor(airbaseID)` / `NavaidsForRunway(airbaseID, runway)` | ILS/PRMG navaid ids of an airbase or runway end |
| `RunwayEnds(airbaseID)` / `BestRunway(airbaseID, windFrom, windKt)` | runway ends; the end facing the wind |
| `NearestAirbases(theatre, lat, lon, n, opts)` | the `n` nearest airbases, filtered by runway length or category |
| `StandsFor(airbaseID, aircraftID)` | stands (`termIndex`) that take the aircraft |
| `CountryIDOf(nameOrAlias)` / `CountryName(countryID)` | country id by any of its names or an alias; its name |
| `LiveriesFor(unitType)` / `LiveriesForCountry(unitType, countryID)` | livery ids of a unit type, for a country |
| `DatalinkCapability(aircraftID)` | the aircraft's datalink record, or nil |
| `DistanceBearing(lat1, lon1, lat2, lon2)` / `Destination(lat, lon, bearing, distM)` | spherical distance, bearing and destination |
| `FormatCoord(lat, lon, format)` / `FormatCoordPrecision(...)` / `ParseCoord(text)` | DD, DMS, DDM and MGRS as the mission editor writes them; METRIC too when parsing |

The rules the helpers follow are in the [Python README](../python/README.md#rules).

## Releases

CD runs `task package:go-release` on a new `VERSION`: it commits the generated files onto a
commit off the released `main` commit and tags it `v<version>` and `packages/go/v<version>`.
`task package:go-release -- --dry-run` shows what it would do.
