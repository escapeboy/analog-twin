// node web/scripts/test-stage-copy.mjs : unit test of web/src/stage/copy.ts (bundled with rolldown).
import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import { fileURLToPath, pathToFileURL } from 'node:url';
import { mkdirSync } from 'node:fs';
import path from 'node:path';
import os from 'node:os';

const here = path.dirname(fileURLToPath(import.meta.url));
const web = path.resolve(here, '..');
const require = createRequire(path.join(web, 'package.json'));
const { build } = require('rolldown'); // vite 8 bundles with rolldown; esbuild is not installed
const outDir = path.join(os.tmpdir(), 'stage-copy');
mkdirSync(outDir, { recursive: true });
const out = path.join(outDir, 'copy.mjs');
await build({ input: path.join(web, 'src/stage/copy.ts'), platform: 'node', output: { file: out, format: 'esm' }, logLevel: 'silent' });
const c = await import(pathToFileURL(out).href + `?t=${Date.now()}`);

let n = 0;
const t = (name, fn) => { fn(); n++; };

t('oneIn', () => {
  assert.equal(c.oneIn(0.0925), '1 in 1,100');
  assert.equal(c.oneIn(2.38), '1 in 42');
  assert.equal(c.oneIn(null), '');
  assert.equal(c.oneIn(undefined), '');
  assert.equal(c.oneIn(0), 'fewer than 1 in 200,000');
  assert.equal(c.oneIn(1), '1 in 100');
  assert.equal(c.oneIn(50), '1 in 2');
});
t('verdict', () => {
  assert.equal(c.verdict(0.05), 'strong');
  assert.equal(c.verdict(0.5), 'good');
  assert.equal(c.verdict(2), 'weak');
  assert.equal(c.verdict(0.1), 'good');
  assert.equal(c.verdict(1), 'weak');
  assert.equal(c.verdict(null), null);
  assert.equal(c.verdictText('strong'), 'Strong terrain match');
  assert.equal(c.verdictText('good'), 'Good terrain match');
  assert.equal(c.verdictText('weak'), 'Weak terrain match');
});
t('windowLine', () => {
  const bw = { start: '02-04', end: '03-03', emd: 1, light_sim: 0.3 };
  assert.equal(c.windowLine({ ...bw, distinct: false }), 'No season stands out');
  assert.equal(c.windowLine({ ...bw, distinct: null }), 'No season stands out');
  assert.equal(c.windowLine({ ...bw }), 'No season stands out');
  assert.equal(c.windowLine(null), 'No season stands out');
  assert.equal(c.windowLine({ ...bw, distinct: true }), '4 Feb – 3 Mar');
});
t('whenHeading', () => {
  assert.equal(c.whenHeading('Jezero', 'Danakil Desert', { distinct: true }), "Sun most like Jezero's");
  assert.equal(c.whenHeading('Jezero', 'Danakil Desert', { distinct: false }), 'Sun at Danakil Desert');
  assert.equal(c.whenHeading('Jezero', 'Danakil Desert', null), 'Sun at Danakil Desert');
});
t('sun', () => {
  const mars = { body: 'mars', light_sim: null };
  const earth = { body: 'earth', light_sim: 0.94, best_window: { earth_range: [0.1, 0.35] } };
  assert.equal(c.sunLine('moon', mars), 'Sun not compared');
  assert.equal(c.sunLine('mars', earth), 'Sun pattern 94% alike');
  assert.equal(c.sunLine('earth', { body: 'earth', light_sim: null }), 'Sun not compared');
  assert.equal(c.sunMax(earth), 'Earth reaches at most 35%');
  assert.equal(c.sunMax({ body: 'earth' }), '');
});
t('bulgariaNote / earthHasNoTwin / top3Note', () => {
  const weak = c.bulgariaNote({ random_closer_pct: 25, env: { barren: false } });
  assert.equal(weak, 'No good twin in Bulgaria for this site.');
  assert.ok(!/shape matches/i.test(weak));
  assert.equal(c.bulgariaNote({ random_closer_pct: 0.5, env: { barren: false } }), 'Shape matches; surface does not match (vegetated ground).');
  assert.equal(c.bulgariaNote({ random_closer_pct: 0.5, env: { barren: true } }), 'Shape matches.');
  assert.equal(c.bulgariaNote({ random_closer_pct: 0.5, env: null }), 'Shape matches.');
  assert.equal(c.earthHasNoTwin('moon', { random_closer_pct: 3 }), true);
  assert.equal(c.earthHasNoTwin('moon', { random_closer_pct: 0.05 }), false);
  assert.equal(c.earthHasNoTwin('earth', { random_closer_pct: 3 }), false);
  assert.equal(c.earthHasNoTwin('mars', null), false);
  assert.equal(c.top3Note('earth', 'terrain'), 'Top 3 twins on Earth, ranked by terrain shape');
  assert.equal(c.top3Note('earth', 'terrain+light'), 'Top 3 twins on Earth, ranked by terrain shape and sun together');
  assert.equal(c.top3Note('moon', 'terrain'), 'Top 3 twins on Moon, ranked by terrain shape');
});
t('misc', () => {
  assert.equal(c.pct(0.674), '67%');
  assert.equal(c.groupPlain('context'), 'the wider 36 km landscape');
  assert.equal(c.groupPlain('slope'), 'how steep the ground is');
  assert.equal(c.limits().length, 4);
  assert.match(c.limits()[1], /51\.1.*48\.5.*not yet better than chance/i);
  assert.equal(c.scope(), 'Terrain shape at about 1 km and sun pattern. Not geology, not chemistry.');
  assert.equal(c.weakNote(), 'Earth has no good twin for this site.');
  const p = c.place({ place_label: 'Atacama', lat: -24.1, lon: -69.9 });
  assert.deepEqual(p, { name: 'Atacama', coords: '24.10°S, 69.90°W' });
  const groups = [{ group: 'slope', label: 'L1', contribution: 0.5 }, { group: 'relief', label: 'L2', contribution: 0.1 }];
  assert.equal(c.pairGroup(groups, ['Closest in L2: x'], 'closest'), 'relief');
  assert.equal(c.pairGroup(groups, [], 'furthest'), 'slope');
});
t('oneIn with sampling interval', () => {
  // Jezero: 0.0925 % with 95 % interval 0.0801-0.1068 % -> narrow, 2 significant figures
  assert.equal(c.oneIn(0.0925, [0.0801, 0.1068]), '1 in 1,100');
  assert.equal(c.oneInRange([0.0801, 0.1068]), '95% range: 1 in 940 to 1,200');
  // 0.0015 % = 3 pairs of 200k: interval 0.0005-0.0044 % -> wide, 1 significant figure
  assert.equal(c.oneIn(0.0015, [0.0005, 0.0044]), '1 in 70,000');
  assert.equal(c.oneInRange(null), '');
  assert.equal(c.oneInPairs(0.0925, [0.0801, 0.1068]), '1 in 1,100 random pairs');
});
console.log(`test-stage-copy: ${n} groups passed`);
