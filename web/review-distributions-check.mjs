import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import { distribution, paperScore, quantile } from './review-distributions.js';

assert.deepEqual(paperScore([]), { n: 0, mean: null, sd: null, range: null });
assert.deepEqual(paperScore([5]), { n: 1, mean: 5, sd: null, range: null });
assert.deepEqual(paperScore([5, 5, 5, 5]), { n: 4, mean: 5, sd: 0, range: 0 });
const divided = paperScore([1, 5, 6, 8]);
assert.equal(divided.mean, 5); assert.equal(divided.range, 7);
assert.ok(Math.abs(divided.sd - Math.sqrt(26 / 3)) < 1e-12);
assert.deepEqual(paperScore([null, NaN, 5, Infinity, '8']), paperScore([5]));
assert.equal(quantile([1, 2, 3, 4], 0.25), 1.75);
assert.equal(quantile([], 0.5), null);
for (const values of [[], [0], [0, 0, 0], [0, 1, 5, 10], Array.from({ length: 101 }, (_, i) => i / 10)]) {
  const d = distribution(values, 10, 0.25);
  assert.equal(d.n, values.length);
  assert.ok(Math.abs(d.density.reduce((a, b) => a + b * 0.25, 0) - (values.length ? 1 : 0)) < 1e-12);
  assert.equal(d.dots.length, Math.min(40, values.length));
  if (values.length) assert.ok(d.q05 <= d.q25 && d.q25 <= d.median && d.median <= d.q75 && d.q75 <= d.q95);
}
// Independently compare browser calculations with the actual R export, including missing and single-rating papers.
const domain = JSON.parse(await readFile(new URL('./public/generated/domains.json', import.meta.url)));
const csv = (await readFile(new URL('./public/generated/paper-review-statistics.csv', import.meta.url), 'utf8')).trim().split('\n');
const columns = csv.shift().replaceAll('"', '').split(',');
const rRows = new Map(csv.map((line) => { const cells = line.replaceAll('"', '').split(','); return [cells[0], Object.fromEntries(columns.map((key, i) => [key, cells[i]]))]; }));
const totals = {};
for (const p of domain.papers) {
  const s = paperScore(p.ratings), r = rRows.get(p.paper_id);
  for (const metric of ['mean', 'sd', 'range']) {
    if (s[metric] === null) assert.equal(r[metric], '');
    else assert.ok(Math.abs(s[metric] - Number(r[metric])) < 1e-10, `${p.paper_id}: ${metric}`);
  }
  const year = r.year;
  totals[year] ??= { rated: 0, disagreement: 0 };
  totals[year].rated += Number(s.n >= 1); totals[year].disagreement += Number(s.n >= 2);
}
assert.equal(rRows.size, domain.papers.length);
console.log(JSON.stringify({ checked_papers: rRows.size, years: totals, statistics: 'JS matches R; empty, tied and single-rating groups passed' }, null, 2));
