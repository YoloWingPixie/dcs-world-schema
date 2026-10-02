import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { test } from 'node:test';

import * as ref from 'dcs-world-reference';

test('dcsVersion matches the manifest', async () => {
  const manifest = await ref.loadManifest();
  assert.equal(ref.dcsVersion, manifest.dcsVersion);
});

for (const name of ref.seriesNames) {
  test(`${name}: loaders agree with the bundle`, async () => {
    const lazy = await ref.loadSeries(name);
    const eager = (await import(`dcs-world-reference/${name}`)).default;
    const loader = ref[`load${name.split('_').map((p) => p[0].toUpperCase() + p.slice(1)).join('')}`];
    assert.equal(eager, lazy);
    assert.equal(await loader(), lazy);
    const raw = JSON.parse(readFileSync(new URL(`../data/${name}.json`, import.meta.url), 'utf8'));
    assert.deepEqual(Object.keys(lazy), Object.keys(raw));
    assert.ok(Object.keys(lazy).length > 0);
    for (const [key, record] of Object.entries(lazy)) {
      assert.equal(String(record[ref.seriesKeys[name]]), key);
    }
  });
}

const indexFile = (name) =>
  JSON.parse(readFileSync(new URL(`../data/_index/${name}.json`, import.meta.url), 'utf8'));
const asciiUpper = (s) => s.replace(/[a-z]/g, (c) => c.toUpperCase());

test('referencesTo returns the reverse index, [] for unknown ids', async () => {
  const meta = await ref.loadIndexMeta();
  for (const series of meta.references) {
    for (const [id, refs] of Object.entries(indexFile(`references_${series}`))) {
      assert.deepEqual(await ref.referencesTo(series, id), refs);
    }
  }
  assert.deepEqual(await ref.referencesTo('weapons', 'constructor'), []);
  assert.deepEqual(await ref.referencesTo('countries', 'x'), []);
});

test('storesDelivering and aircraftCarrying match a scan of the bundles', async () => {
  const stores = await ref.loadStores();
  const aircraft = await ref.loadAircraft();
  for (const weapon of Object.keys(await ref.loadWeapons())) {
    const delivering = Object.keys(stores)
      .filter((k) => (stores[k].delivers ?? []).some((d) => d.weapon === weapon))
      .sort();
    assert.deepEqual(await ref.storesDelivering(weapon), delivering, weapon);
    const set = new Set(delivering);
    const carriers = Object.keys(aircraft)
      .filter((k) => (aircraft[k].stations ?? []).some((s) => (s.accepts ?? []).some((a) => set.has(a.clsid))))
      .sort();
    assert.deepEqual(await ref.aircraftCarrying(weapon), carriers, weapon);
  }
  assert.ok((await ref.aircraftCarrying('AIM_120C')).includes('F-16C_50'));
  // B-52H has AGM-84A only on an obsolete launcher
  assert.ok(!(await ref.aircraftCarrying('AGM_84A')).includes('B-52H'));
  assert.deepEqual(await ref.aircraftCarrying('constructor'), []);
});

test('threatsForUnit matches a scan of the threats', async () => {
  const threats = await ref.loadThreats();
  const meta = await ref.loadIndexMeta();
  for (const series of meta.unitSeries) {
    for (const unit of Object.keys(await ref.loadSeries(series))) {
      const expected = Object.keys(threats)
        .filter((k) => threats[k].unit === unit || (threats[k].components ?? []).some((c) => c.unit === unit))
        .sort();
      assert.deepEqual(await ref.threatsForUnit(unit), expected, unit);
    }
  }
});

test('name lookups are case-insensitive and list collisions', async () => {
  assert.equal(ref.nameKey('  F-16C Viper\t'), 'f-16c viper');
  assert.deepEqual(await ref.airbaseByName(' BATUMI ', 'caucasus'), ['Caucasus.22']);
  assert.deepEqual(await ref.airbaseByName('Batumi', 'Syria'), []);
  for (const [id, airbase] of Object.entries(await ref.loadAirbases())) {
    assert.ok((await ref.airbaseByName(asciiUpper(airbase.name), airbase.theatre)).includes(id));
  }
  const meta = await ref.loadIndexMeta();
  for (const series of ref.seriesNames) {
    const expected = new Map();
    for (const [id, record] of Object.entries(await ref.loadSeries(series))) {
      for (const field of ['displayName', 'name']) {
        const name = record[field];
        if (typeof name !== 'string' || !ref.nameKey(name)) continue;
        const key = ref.nameKey(name);
        expected.set(key, new Set([...(expected.get(key) ?? []), id]));
      }
    }
    assert.equal(meta.names.includes(series), expected.size > 0, series);
    for (const [key, ids] of expected) {
      assert.deepEqual(await ref.findByName(series, ` ${asciiUpper(key)} `), [...ids].sort(), `${series} ${key}`);
    }
  }
  assert.deepEqual(await ref.findByName('racks', 'x'), []);
});
