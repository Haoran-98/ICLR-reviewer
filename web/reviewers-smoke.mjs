import assert from 'node:assert/strict';
import { readFile, mkdir, writeFile } from 'node:fs/promises';
import { chromium } from 'playwright';
import { createServer } from 'vite';

const external = process.env.ICLR_WEB_BASE_URL;
const server = external ? null : await createServer({ server: { host: '127.0.0.1', port: 0 } });
let browser;
try {
  await server?.listen();
  browser = await chromium.launch({ executablePath: process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH,
    args: ['--no-sandbox'] });
  const page = await browser.newPage({ viewport: { width: 1440, height: 1100 }, ignoreHTTPSErrors: true,
    ...(process.env.ICLR_WEB_USERNAME ? {httpCredentials:{username:process.env.ICLR_WEB_USERNAME,password:process.env.ICLR_WEB_PASSWORD??''}} : {}) });
  const errors = [], posts = [];
  page.on('pageerror', e => errors.push(e.message));
  page.on('request', r => { if (r.method() !== 'GET') posts.push(r.url()); });
  const base = external ?? `http://127.0.0.1:${server.httpServer.address().port}`;
  const start = Date.now();
  await page.goto(new URL('/reviewers.html', base).href);
  await page.waitForFunction(() => window.__reviewWorkbench?.modules === 7795);
  const readyMs = Date.now() - start;
  assert.match(await page.locator('#expert-count').textContent(), /1,636/);
  assert.equal(await page.locator('#expert-list .card').count(), 30);
  assert.equal(await page.locator('#overview svg [role=button]').count(), 40);
  await page.locator('#expert-list .card').first().click();
  await page.waitForFunction(() => document.querySelector('#expert-detail details'));
  assert.ok(await page.locator('#expert-detail').getByText('问题成立条件', { exact: true }).count());
  await page.locator('#next').click(); assert.match(await page.locator('#page-index').textContent(), /^2 /);
  await page.locator('#expert-status').selectOption('candidate'); assert.match(await page.locator('#expert-count').textContent(), /6,159/);
  await page.locator('#expert-status').selectOption(''); assert.match(await page.locator('#expert-count').textContent(), /7,795/);
  await page.locator('#expert-search').fill('no_such_scope_917283'); assert.match(await page.locator('#expert-count').textContent(), /匹配 0 /);
  await page.locator('#reset-library').click();
  await page.locator('#overview [role=button]').first().focus(); await page.keyboard.press('Enter');
  assert.equal(await page.locator('#expert-level').inputValue(), 'general');
  await page.locator('#reset-library').click();
  await mkdir('artifacts', { recursive: true });
  await page.screenshot({ path: 'artifacts/review-workbench-library.png', fullPage: true });
  await page.locator('[data-tab=match]').click();
  await page.locator('#run-match').click(); assert.match(await page.locator('#match-status').textContent(), /请先输入/);
  const input = 'We propose retrieval augmented generation for large language models with instruction tuning. We evaluate chain of thought reasoning and hallucination under distribution shift.';
  await page.locator('#paper-file').setInputFiles({ name: 'paper.md', mimeType: 'text/markdown', buffer: Buffer.from(input) });
  await page.waitForFunction(() => document.querySelector('#paper-text').value.includes('retrieval augmented'));
  await page.locator('#paper-area').selectOption('llm');
  await page.locator('#run-match').click();
  await page.waitForFunction(() => document.querySelector('#match-status').textContent.includes('匹配预览完成'));
  assert.equal(await page.locator('.stage').count(), 5);
  assert.ok(await page.locator('#match-results article').count() > 0);
  assert.equal(await page.locator('#match-results article').evaluateAll(nodes => new Set(nodes.map(n => n.dataset.moduleId)).size), 6,
    'Every recommended module must have at least one visible check');
  assert.equal(await page.locator('#match-results .candidate').count(), 0);
  assert.match(await page.locator('#match-pipeline').textContent(), /未执行审稿/);
  const quote = await page.locator('#match-results blockquote').first().textContent(); assert.ok(input.includes(quote.trim()));
  await page.screenshot({ path: 'artifacts/review-workbench-match.png', fullPage: true });
  await page.locator('#paper-area').selectOption('other'); await page.locator('#run-match').click();
  await page.waitForFunction(() => document.querySelector('#match-status').textContent.includes('不自动套用'));
  assert.equal(await page.locator('#match-results article').count(), 0);
  await page.locator('#clear-match').click(); assert.equal(await page.locator('#paper-text').inputValue(), '');
  await page.locator('#paper-text').fill('<img src=x onerror="window.__injected=true"> retrieval augmented generation');
  await page.locator('#paper-area').selectOption('llm'); await page.locator('#run-match').click();
  await page.waitForFunction(() => document.querySelector('#match-status').textContent.includes('匹配预览完成'));
  assert.equal(await page.evaluate(() => window.__injected), undefined);
  await page.locator('[data-tab=replay]').click();
  let concerns = 0;
  for (const pid of [32064, 40652, 36957, 33499, 23305]) {
    const original = JSON.parse(await readFile(`public/generated/reviewers/replay-${pid}.json`));
    await page.locator('#replay-select').selectOption(String(pid));
    await page.waitForFunction(() => document.querySelector('#replay-status').textContent.includes('已回放真实记录'));
    const boxes = page.locator('[data-concern-id]'); assert.equal(await boxes.count(), original.review.concerns.length);
    concerns += await boxes.count();
    assert.ok((await page.locator('#replay-detail').textContent()).includes(original.library_hash.slice(0, 16)));
    if (await boxes.count()) {
      await boxes.first().locator('details').first().locator('summary').click();
      const passageId = original.review.concerns[0].evidence_ids[0];
      assert.equal(await boxes.first().locator('blockquote').first().textContent(), original.passages[passageId].text);
    } else assert.match(await page.locator('#replay-detail').textContent(), /未提出 concern/);
  }
  assert.equal(concerns, 8);
  await page.screenshot({ path: 'artifacts/review-workbench-replay.png', fullPage: true });
  await page.setViewportSize({ width: 390, height: 844 });
  for (const name of ['library', 'match', 'replay']) {
    await page.locator(`[data-tab=${name}]`).click();
    assert.ok(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1), `No page overflow: ${name}`);
  }
  await page.screenshot({ path: 'artifacts/review-workbench-mobile.png', fullPage: true });
  // Trace a real rule's source back into the existing paper viewer.
  const sample = JSON.parse(await readFile('public/generated/sample.json'));
  const source = sample.papers.find(p => String(p.paper_id) === '31725'); assert.ok(source);
  await page.addInitScript(() => Object.defineProperty(navigator, 'gpu', { value: undefined }));
  await page.goto(new URL('/?paper=31725&smoke=1', base).href);
  await page.waitForFunction(() => window.__atlasProbe?.detailLoaded === '31725', null, { timeout: 60000 });
  assert.equal(posts.length, 0, 'The static preview must not upload manuscripts or call models');
  assert.deepEqual(errors, []);
  const report = { check: 'passed', modules: 7795, replay_papers: 5, replay_concerns: concerns, browser_errors: errors, uploads: posts.length,
    local_matching: true, candidates_default_excluded: true, replay_evidence_exact: true, source_map_link: true, mobile_overflow: false,
    ready_ms: readyMs, url: base };
  await writeFile('artifacts/review-workbench-smoke.json', JSON.stringify(report, null, 2) + '\n');
  console.log(JSON.stringify(report, null, 2));
} finally { await browser?.close(); await server?.close(); }
