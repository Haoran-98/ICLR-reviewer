import assert from 'node:assert/strict';
import { createServer } from 'node:http';
import { randomBytes } from 'node:crypto';
import { mkdir, writeFile } from 'node:fs/promises';
import { chromium } from 'playwright';

// An external clean deployment is required. A synthetic provider checks transport and retry;
// ICLR_REVIEW_LIVE=1 instead uses privately supplied settings for a real model run.
const base = process.env.ICLR_WEB_BASE_URL;
const live = process.env.ICLR_REVIEW_LIVE === '1';
assert.ok(base && process.env.ICLR_WEB_USERNAME && process.env.ICLR_WEB_PASSWORD);
const calls = {};
let failed = false;
function synthetic(payload) {
  const { task, data } = JSON.parse(payload.input ?? payload.messages.at(-1).content);
  calls[task] = (calls[task] ?? 0) + 1;
  const passage = data.manuscript.passages.find(p => /low.rank attention/i.test(p.text)) ?? data.manuscript.passages[0];
  const evidence = [{ passage_id: passage.passage_id, quote: passage.text.slice(0, 100) }];
  if (task === 'profile') {
    const facet = [{ term_english: 'low-rank attention key value cache', description: '兼容接口回归样例', evidence }];
    return { area_fit: 'in_scope', domain_english: 'large language models efficient inference',
      domain_reason: '兼容接口回归样例', evidence, methods: facet, tasks: facet, technical_objects: facet };
  }
  if (task === 'applicability') return { evaluations: data.candidate_rules.map((r, i) => ({
    rule_id: r.rule_id, disposition: i < 2 ? 'applicable' : 'not_applicable', priority: 2,
    matches: { method: 'match', task: 'not_required', technical_object: 'match' },
    reason: '接口回归检查适用性传递', missing_information: '', evidence,
  })) };
  assert.equal(task, 'review');
  if (!failed) { failed = true; return null; }
  return { summary: '兼容接口回归输出', strengths: [{ point: '验证完整稿件引文传递', evidence }],
    concerns: [{ rule_id: data.checks[0].rule_id, kind: 'suggestion', priority: 'P3',
      observation: '接口回归样例建议', impact: '检查结果导航', requested_action: '核对引文显示',
      clearing_evidence: '引文与原稿一致', evidence }],
    rules_applied: data.checks.map(r => ({ rule_id: r.rule_id, disposition: 'applied', reason: '接口回归' })),
    questions: [], rating: 6, confidence: 1, rating_reason: '接口回归占位评分', limitations: ['合成响应，仅验证工程链路'] };
}
const simulator = live ? null : createServer(async (req, res) => {
  try {
    const chunks = []; for await (const chunk of req) chunks.push(chunk);
    const payload = JSON.parse(Buffer.concat(chunks));
    const result = synthetic(payload);
    if (!result) { res.writeHead(400, { 'Content-Type': 'application/json' }); res.end('{}'); return; }
    res.writeHead(200, { 'Content-Type': 'application/json' });
    res.end(JSON.stringify({ model: payload.model, choices: [{ finish_reason: 'stop', message: { content: JSON.stringify(result) } }],
      usage: { prompt_tokens: 10, completion_tokens: 10 } }));
  } catch { res.writeHead(500); res.end('{}'); }
});
await new Promise(resolve => simulator ? simulator.listen(0, '127.0.0.1', resolve) : resolve());
const connection = live ? {
  base_url: process.env.ICLR_REVIEW_TEST_BASE_URL, api_key: process.env.ICLR_REVIEW_TEST_API_KEY,
  model: process.env.ICLR_REVIEW_TEST_MODEL_ID, protocol: process.env.ICLR_REVIEW_TEST_PROTOCOL ?? 'responses',
} : { base_url: `http://127.0.0.1:${simulator.address().port}/v1`, api_key: randomBytes(24).toString('hex'),
  model: 'portable-test-simulator', protocol: 'chat' };
assert.ok(connection.base_url && connection.api_key && connection.model);
let browser;
const started = Date.now();
try {
  browser = await chromium.launch({ executablePath: process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH, args: ['--no-sandbox'] });
  const page = await browser.newPage({ viewport: { width: 1440, height: 1050 }, httpCredentials: {
    username: process.env.ICLR_WEB_USERNAME, password: process.env.ICLR_WEB_PASSWORD } });
  const errors = []; page.on('pageerror', e => errors.push(e.message));
  await page.addInitScript(() => Object.defineProperty(navigator, 'gpu', { value: undefined }));
  await page.goto(base + '/?smoke=1');
  await page.waitForFunction(() => window.__atlasProbe?.count === 12964 || document.querySelector('#status')?.textContent.includes('12,964'), null, { timeout: 90000 });
  await page.locator('#atlas canvas').first().waitFor();
  await page.goto(base + '/review.html');
  for (const id of ['review-base-url', 'review-api-key', 'review-model']) assert.ok(await page.locator('#' + id).inputValue() === '', 'Connection fields must start empty');
  await page.locator('#load-example').click();
  await page.waitForFunction(() => document.querySelector('#state-badge').textContent === '已完成', null, { timeout: 60000 });
  await page.locator('[data-view=review]').click();
  assert.ok(await page.locator('.concern').count());
  await page.locator('.concern').first().getByRole('button', { name: '查看论文依据' }).click();
  await page.locator('#evidence-list blockquote').first().waitFor();
  const example = await page.evaluate(() => fetch('/api/review/example').then(r => r.json()));
  assert.equal(example.job.read_only, true);
  const fullText = example.manuscript.passages.map(p => p.text).join('');
  assert.ok(fullText.length > 80000);
  await page.locator('#choose-upload').click();
  await page.locator('#manuscript-file').setInputFiles({ name: 'mlra-portable.md', mimeType: 'text/markdown', buffer: Buffer.from(fullText) });
  await page.waitForFunction(n => document.querySelector('#manuscript-text').value.length === n, fullText.length);
  const fill = async () => {
    await page.locator('#review-base-url').fill(connection.base_url);
    await page.locator('#review-api-key').fill(connection.api_key);
    await page.locator('#review-model').fill(connection.model);
    await page.locator('#review-protocol').selectOption(connection.protocol);
  };
  const retry = process.env.ICLR_REVIEW_RETRY;
  if (retry) {
    assert.ok(live, 'Explicit task retry is for a real-model verification run');
    await page.goto(base + '/review.html?run=' + encodeURIComponent(retry));
    await page.waitForFunction(() => !document.querySelector('#retry-run').hidden);
    await fill(); await page.locator('#retry-run').click();
  } else {
    await fill(); await page.locator('#start-review').click();
  }
  await page.waitForFunction(() => new URL(location).searchParams.get('run'), null, { timeout: 30000 });
  const runId = new URL(page.url()).searchParams.get('run');
  await page.waitForFunction(() => document.querySelector('#review-api-key').value === '');
  const waitForEnd = async () => {
    for (let i = 0; i < 120; i++) {
      const job = await page.evaluate(id => fetch('/api/review/runs/' + id).then(r => r.json()), runId);
      if (['failed', 'completed', 'interrupted'].includes(job.job.state)) return job;
      if (i % 6 === 0) console.log('portable smoke:', live ? 'live' : 'simulator', job.job.phase);
      await new Promise(resolve => setTimeout(resolve, 5000));
    }
    throw new Error('Review timed out');
  };
  let result = await waitForEnd();
  if (!live) {
    assert.equal(result.job.state, 'failed');
    assert.equal(result.job.phase, 'reviewing');
    assert.ok(result.composition.rule_ids.length > 0);
    await page.reload();
    await page.waitForFunction(() => !document.querySelector('#retry-run').hidden);
    await fill(); await page.locator('#retry-run').click();
    result = await waitForEnd();
    assert.equal(result.job.attempt, 2);
    assert.deepEqual(calls, { profile: 1, applicability: 1, review: 2 });
  }
  assert.equal(result.job.state, 'completed', result.job.error);
  assert.equal(result.manuscript.coverage.full_document, true);
  assert.ok(result.composition.budget.loaded_rules <= 10 && result.composition.budget.loaded_rule_tokens_proxy <= 4000);
  assert.equal(result.composition.evaluations.length, result.composition.budget.shortlist_rules);
  for (const selected of result.composition.selected) assert.equal(selected.historical_sources.display_examples.length, 2);
  for (const refs of Object.values(result.evidence)) for (const ref of refs) assert.equal(fullText.slice(ref.char_start, ref.char_end), ref.quote);
  const serialized = JSON.stringify(result);
  assert.ok(!serialized.includes(connection.api_key) && !serialized.includes(connection.base_url));
  assert.ok(!JSON.stringify(await page.evaluate(() => ({ ...localStorage, ...sessionStorage }))).includes(connection.api_key));
  await page.reload();
  await page.waitForFunction(() => document.querySelector('#state-badge').textContent === '已完成');
  for (const id of ['review-base-url', 'review-api-key', 'review-model']) assert.ok(await page.locator('#' + id).inputValue() === '', 'Connection fields must clear on reload');
  assert.deepEqual(errors, []);
  const report = { mode: live ? 'real-model' : 'synthetic-compatible-provider', run_id: runId,
    state: result.job.state, attempts: result.job.attempt, calls, manuscript_chars: fullText.length,
    model: result.composition.model,
    selected_rules: result.composition.rule_ids, budget: result.composition.budget,
    concerns: result.review.concerns.length, evidence_items: Object.keys(result.evidence).length,
    elapsed_seconds: Math.round((Date.now() - started) / 1000), browser_errors: errors };
  await mkdir('artifacts', { recursive: true });
  await writeFile(`artifacts/portable-${live ? 'live' : 'simulator'}.json`, JSON.stringify(report, null, 2) + '\n');
  console.log(JSON.stringify(report));
} catch (error) {
  let message = String(error.stack ?? error);
  for (const secret of [connection.api_key, connection.base_url, process.env.ICLR_WEB_PASSWORD]) {
    if (secret) message = message.replaceAll(secret, '[REDACTED]');
  }
  console.error(message); process.exitCode = 1;
} finally { await browser?.close(); await new Promise(resolve => simulator ? simulator.close(resolve) : resolve()); }
