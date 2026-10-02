// The shared conformance vectors of the reference helpers
// (tools/package/tests/vectors/helpers.json, generated from the Python package).
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { test } from 'node:test';

import * as ref from 'dcs-world-reference';

const vectors = JSON.parse(
  readFileSync(new URL('../../../tools/package/tests/vectors/helpers.json', import.meta.url), 'utf8'),
);
const tol = vectors.tolerance;

const calls = {
  theatreByName: async (name) => (await ref.theatreByName(name))?.id ?? null,
  toLatLon: ref.toLatLon,
  toMapXZ: ref.toMapXZ,
  threatRange: ref.threatRange,
  threatForUnitType: ref.threatForUnitType,
  threatRingGeoJSON: (id, lat, lon, segments) => ref.threatRingGeoJSON(id, lat, lon, { segments }),
  aircraftRoles: ref.aircraftRoles,
  unitClass: ref.unitClass,
  stationsAccepting: ref.stationsAccepting,
  canMount: ref.canMount,
  fitStores: ref.fitStores,
  loadoutMass: (id, loadout, fuel) => ref.loadoutMass(id, loadout, fuel ?? undefined),
  radioBands: ref.radioBands,
  isValidFrequency: ref.isValidFrequency,
  weaponInfo: ref.weaponInfo,
  launchPlatforms: ref.launchPlatforms,
  modelToUnits: ref.modelToUnits,
  unitDetection: ref.unitDetection,
  tacanFrequency: ref.tacanFrequency,
  tacanChannel: ref.tacanChannel,
  isValidTacan: ref.isValidTacan,
  navaidsFor: (id, runway) => ref.navaidsFor(id, runway ?? undefined),
  runwayEnds: ref.runwayEnds,
  bestRunway: ref.bestRunway,
  nearestAirbases: ref.nearestAirbases,
  standsFor: ref.standsFor,
  countryId: async (name) => (await ref.countryId(name)) ?? null,
  countryName: ref.countryName,
  liveriesFor: (unit, country) => ref.liveriesFor(unit, country ?? undefined),
  datalinkCapability: async (id) => (await ref.datalinkCapability(id)) ?? null,
  distanceBearing: async (...a) => ref.distanceBearing(...a),
  destination: async (...a) => ref.destination(...a),
  formatCoord: async (lat, lon, fmt, precision) => ref.formatCoord(lat, lon, fmt, precision ?? undefined),
  parseCoord: async (text) => ref.parseCoord(text),
};

function close(got, want, path) {
  if (typeof want === 'number') {
    assert.equal(typeof got, 'number', path);
    assert.ok(Math.abs(got - want) <= tol.abs + tol.rel * Math.abs(want), `${path}: ${got} != ${want}`);
  } else if (Array.isArray(want)) {
    assert.ok(Array.isArray(got) && got.length === want.length, `${path}: ${JSON.stringify(got)}`);
    want.forEach((w, i) => close(got[i], w, `${path}[${i}]`));
  } else if (want !== null && typeof want === 'object') {
    assert.deepEqual(Object.keys(got).map(String).sort(), Object.keys(want).sort(), path);
    for (const [k, w] of Object.entries(want)) close(got[k], w, `${path}.${k}`);
  } else {
    assert.equal(got, want, path);
  }
}

test('the vectors name every helper and this DCS version', () => {
  assert.deepEqual([...new Set(vectors.cases.map((c) => c.fn))].sort(), Object.keys(calls).sort());
  assert.equal(vectors.dcsVersion, ref.dcsVersion);
});

test('every conformance vector', async () => {
  for (const c of vectors.cases) {
    const label = `${c.fn}(${JSON.stringify(c.args).slice(0, 120)})`;
    if (c.throws) await assert.rejects(calls[c.fn](...c.args), Error, label);
    else close(await calls[c.fn](...c.args), c.expect, label);
  }
});
