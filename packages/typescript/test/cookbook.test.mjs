// Type-check (tsc --strict) and run the TypeScript snippets of docs/cookbook.md
// against the built package: each is written to .cookbook/<recipe>.mts,
// compiled to .cookbook/out/ and run with node.
import assert from 'node:assert/strict';
import { execFileSync } from 'node:child_process';
import { mkdirSync, readFileSync, rmSync, writeFileSync } from 'node:fs';
import { test } from 'node:test';
import { fileURLToPath } from 'node:url';

const pkg = fileURLToPath(new URL('..', import.meta.url));
const dir = `${pkg}.cookbook/`;
const cookbook = readFileSync(new URL('../../../docs/cookbook.md', import.meta.url), 'utf8');

// Recipe slug -> text its output must contain; every TypeScript snippet needs one.
const expected = {
  'load-an-aircraft-and-list-its-stations-and-stores': 'station 1:',
  'sam-threat-ranges-on-a-map': 'SA-10 reaches 120 km',
  'find-stores-by-display-name': 'stores match /GBU-12/i',
  'map-coordinates-to-latitude-and-longitude': 'round trip under 1 mm',
  'a-sam-ring-with-its-dead-zone-as-geojson': 'ring of 65 points, hole of 65',
  'fit-a-loadout-weigh-it-and-check-a-radio-preset': 'six: noFreeStation',
  'the-runway-into-the-wind-and-its-approach-aids': 'TACAN 16X BTM: interrogate 1040 MHz, reply 977 MHz',
  'paste-a-mission-editor-coordinate': "MGRS: N 29°32.059'   E 52°35.930' | 39 R XN 54929 68251",
  'a-weapon-who-launches-it-and-what-they-see': 'PIOTR: detects 250 km, threat 190 km',
  'divert-airfields-that-can-park-an-aircraft': 'USA C-130J liveries: 27',
};

const snippets = {};
let recipe = '';
for (const m of cookbook.matchAll(/^## ([^\n]+)$|^```(\w*)\n([\s\S]*?)^```$/gm)) {
  if (m[1]) recipe = m[1].toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-|-$/g, '');
  else if (m[2] === 'ts') snippets[recipe] = m[3];
}

test('every TypeScript snippet is checked', () => {
  assert.deepEqual(Object.keys(snippets).sort(), Object.keys(expected).sort());
});

test('the TypeScript snippets type-check and run', () => {
  rmSync(dir, { recursive: true, force: true });
  mkdirSync(dir);
  for (const [name, code] of Object.entries(snippets)) writeFileSync(`${dir}${name}.mts`, code);
  writeFileSync(`${dir}tsconfig.json`, JSON.stringify({
    compilerOptions: {
      target: 'es2022',
      module: 'nodenext',
      moduleResolution: 'nodenext',
      strict: true,
      outDir: 'out',
      types: [],
    },
    include: ['*.mts'],
  }));
  const tsc = `${pkg}node_modules/@typescript/native/bin/tsc`;
  execFileSync(process.execPath, [tsc, '-p', dir], { encoding: 'utf8', stdio: 'pipe' });
  for (const name of Object.keys(snippets)) {
    const out = execFileSync(process.execPath, [`${dir}out/${name}.mjs`], { encoding: 'utf8' });
    assert.ok(out.includes(expected[name]), `${name}: ${out}`);
  }
});
