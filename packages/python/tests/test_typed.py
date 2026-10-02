"""Typed use of the loaders; checked by ``mypy --strict`` and run by pytest."""

from __future__ import annotations

from collections.abc import Mapping

import dcs_world_reference as ref
from dcs_world_reference.entities import (
    Airbase,
    Aircraft,
    Beacon,
    BeaconType,
    BeaconTypeValues,
    Livery,
    Provenance,
    Store,
)


def test_typed_access() -> None:
    aircraft: Mapping[str, Aircraft] = ref.aircraft()
    airbases: Mapping[str, Airbase] = ref.airbases()
    beacons: Mapping[str, Beacon] = ref.beacons()
    liveries: Mapping[str, Livery] = ref.liveries()
    stores: Mapping[str, Store] = ref.stores()
    manifest: Provenance = ref.manifest()
    version: str = ref.DCS_VERSION

    assert version == manifest["dcsVersion"]
    assert all(a["id"] == k for k, a in aircraft.items())
    assert all(s["clsid"] == k for k, s in stores.items())
    assert all(v["id"] == k for k, v in liveries.items())
    tacan: BeaconType = BeaconTypeValues["BEACON_TYPE_TACAN"]
    assert any(b["type"] == tacan for b in beacons.values())
    runways = [r for a in airbases.values() for r in a.get("runways", [])]
    assert runways
