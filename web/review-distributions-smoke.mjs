import assert from 'node:assert/strict';
import { mkdtemp, writeFile, rm, mkdir, readFile } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { randomBytes, scryptSync } from 'node:crypto';
import { execFile } from 'node:child_process';
import { promisify } from 'node:util';
import { createServer } from 'vite';
import { chromium } from 'playwright';

const folder = await mkdtemp(join(tmpdir(), 'iclr-ggdist-check-'));
const username = 'visualization-check', password = randomBytes(24).toString('hex'), salt = randomBytes(16).toString('hex');
const config = join(folder, 'auth.json');
await writeFile(config, JSON.stringify({ username, salt, password_hash: scryptSync(password, salt, 64).toString('hex') }), { mode: 0o600 });
process.env.ICLR_WEB_AUTH_FILE = config;
let server, browser;
try {
  server = await createServer({ server: { host: '127.0.0.1', port: 0 } }); await server.listen();
  const origin = `http://127.0.0.1:${server.httpServer.address().port}`;
  browser = await chromium.launch({ executablePath: process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH, args: ['--no-sandbox'] });
  const page = await browser.newPage({ httpCredentials: { username, password }, viewport: { width: 1560, height: 1120 }, deviceScaleFactor: 1.5 });
  await page.addInitScript(() => Object.defineProperty(navigator, 'gpu', { value: undefined }));
  const errors = []; page.on('pageerror', (error) => errors.push(error.message));
  await page.goto(origin + '/?smoke=1');
  await page.waitForFunction(() => window.__analysisProbe?.scoreDistributions?.length === 12, null, { timeout: 60000 });
  assert.equal(await page.locator('#score-status').inputValue(), 'compare');
  assert.equal(await page.locator('#domain-scores .score-slab').count(), 12);
  assert.equal(await page.locator('#domain-scores .score-median').count(), 12);
  assert.equal(await page.locator('#domain-scores .score-interval').count(), 24);
  await page.locator('#score-status').selectOption('');
  const all = await page.evaluate(() => window.__analysisProbe.scoreDistributions);
  assert.equal(all.filter((s) => s.metric === 'mean').reduce((n, s) => n + s.n, 0), 12738);
  assert.equal(all.filter((s) => s.metric === 'sd').reduce((n, s) => n + s.n, 0), 12725);
  await page.locator('#score-disagreement').selectOption('range');
  assert.equal(await page.locator('#domain-scores svg[data-metric=range]').count(), 1);
  const quantiles = await page.evaluate(() => window.__analysisProbe.scoreDistributions);
  assert.ok(quantiles.every((s) => s.q05 <= s.q25 && s.q25 <= s.median && s.median <= s.q75 && s.q75 <= s.q95));
  await page.locator('#analysis-year').selectOption('2025');
  await page.locator('#analysis-domain').selectOption('reinforcement_learning');
  assert.equal((await page.evaluate(() => window.__analysisProbe.scoreDistributions)).length, 2);
  const ribbon = page.locator('#domain-chord .ribbon').first();
  await ribbon.focus(); await page.keyboard.press('Enter');
  await page.waitForFunction(() => window.__analysisProbe.pair && window.__analysisProbe.selectedPaperIds.length === window.__atlasProbe.visibleIds.length);
  const filtered = await page.evaluate(() => ({ ids: window.__analysisProbe.selectedPaperIds, scores: window.__analysisProbe.scoreDistributions }));
  assert.ok(filtered.ids.length > 0); assert.ok(filtered.scores.every((s) => s.total === filtered.ids.length));
  await page.locator('#score-papers').evaluate((e) => { e.closest('details').open = true; });
  const paper = page.locator('#score-papers button').first(), id = await paper.getAttribute('data-paper-id');
  await paper.click(); await page.waitForFunction((id) => window.__atlasProbe.detailLoaded === id && window.__analysisProbe.evidence?.paperId === id, id);
  assert.ok((await page.locator('#score-papers li').first().textContent()).includes('评分 ['));
  const edgeCases = await page.evaluate(async () => {
    const { renderPaperDistributions } = await import('/review-distributions.js');
    const host = document.createElement('div');
    const empty = renderPaperDistributions(host, [], [2025], 'compare');
    const emptyValid = empty.every((s) => s.n === 0 && s.median === null) && host.textContent.includes('暂无');
    const single = renderPaperDistributions(host, [{ year: 2025, decision: 'accepted', ratings: [5] }], [2025], 'accepted');
    const tied = renderPaperDistributions(host, [{ year: 2025, decision: 'accepted', ratings: [5, 5, 5] }], [2025], 'accepted');
    return { emptyValid, single: single.map((s) => s.n), tied: tied.map((s) => s.median), invalidSVG: /NaN|Infinity/.test(host.innerHTML) };
  });
  assert.deepEqual(edgeCases, { emptyValid: true, single: [1, 0], tied: [5, 0], invalidSVG: false });
  await page.locator('#clear-topic').click(); await page.locator('#analysis-domain').selectOption('');
  await page.locator('#analysis-year').selectOption(''); await page.locator('#score-status').selectOption('compare');
  await page.locator('#score-disagreement').selectOption('sd');
  await mkdir('artifacts', { recursive: true });
  await page.locator('#domain-scores').screenshot({ path: 'artifacts/ggdist-interactive.png' });
  await page.locator('#ggdist-panel').screenshot({ path: 'artifacts/ggdist-overview.png' });
  assert.equal(await page.locator('#plot').evaluate((img) => img.complete && img.naturalWidth > 0), true);
  const chart = await (await page.request.get(origin + '/generated/reviews.svg')).text();
  assert.ok(chart.includes('论文评分水平与审稿分歧') && chart.includes('不是只选40篇') && chart.includes('约2.94'));
  await page.setViewportSize({ width: 390, height: 844 });
  const mobile = await page.locator('#domain-scores').evaluate((host) => ({ width: host.clientWidth, children: [...host.children].map((c) => c.clientWidth) }));
  assert.ok(mobile.children.every((w) => w <= mobile.width));
  assert.deepEqual(errors, []);
  const result = { check: 'passed', papers_with_mean: 12738, papers_with_disagreement: 12725,
    compared_groups: ['accepted', 'rejected'], filters: ['year', 'domain', 'chord'],
    paper_replay: id, empty_single_tied_groups: edgeCases, browser_errors: errors, model_calls: 0 };
  await writeFile('artifacts/ggdist-upgrade-check.json', JSON.stringify(result, null, 2) + '\n');
  console.log(JSON.stringify(result, null, 2));
  if (process.env.ICLR_GGDIST_FULL_SMOKE === '1') {
    const { stdout } = await promisify(execFile)(process.execPath, ['smoke.mjs'], { cwd: process.cwd(), maxBuffer: 3_000_000,
      env: { ...process.env, ICLR_WEB_AUTH_FILE: config, ICLR_WEB_USERNAME: username, ICLR_WEB_PASSWORD: password, ICLR_WEB_FORCE_COMPAT: '1' } });
    console.log(stdout);
  }
} finally { await browser?.close(); await server?.close(); await rm(folder, { recursive: true, force: true }); }
