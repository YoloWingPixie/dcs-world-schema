// Package dcsref is the DCS World reference data (aircraft, weapons, stores,
// airbases, beacons and the other series datamined from DCS) as typed Go
// values, embedded in the binary.
//
// Each series has a loader (LoadAircraft, LoadWeapons, ...) returning its
// records keyed by id, decoded on first call and shared afterwards: treat the
// maps and records as read-only. The record types are generated from the
// entity JSON Schema of dcs-world-schema; optional fields are nil when absent.
//
// The lookup helpers (ReferencesTo, AircraftCarrying, StoresDelivering,
// ThreatsForUnit, AirbaseByName, FindByName) read the prebuilt reverse and
// name indexes, also embedded. The reference helpers (TheatreByName, ToMapXZ,
// ThreatRange, FitStores, LoadoutMass, IsValidFrequency, ...) compute from the
// data and return errors wrapping ErrNotFound or ErrInvalid.
//
// The embedded data is checked by the package tests, so a decoding failure
// is a build defect: loaders and helpers panic on one instead of returning an
// error.
package dcsref
