import assert from "node:assert/strict";
import { createHash, X509Certificate } from "node:crypto";
import { mkdir, readFile, writeFile } from "node:fs/promises";
import { chromium } from "playwright";
import { createServer } from "vite";

const externalURL = process.env.ICLR_WEB_BASE_URL;
const forceCompatible = process.env.ICLR_WEB_FORCE_COMPAT === "1";
const server = externalURL ? null : await createServer({ server: { host: "127.0.0.1", port: 0 } });
const prefix = forceCompatible ? "compat" : externalURL ? "lan" : "v1";
let browser;
try {
  await server?.listen();
  const tlsCertificate = process.env.ICLR_WEB_TLS_CERT;
  const certificateArgs = tlsCertificate ? ["--ignore-certificate-errors-spki-list=" +
    createHash("sha256").update(new X509Certificate(await readFile(tlsCertificate)).publicKey.export({ type: "spki", format: "der" })).digest("base64")] : [];
  browser = await chromium.launch({
    ...(process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH ? { executablePath: process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH } : {}),
    args: [...(forceCompatible ? [] : ["--enable-unsafe-webgpu", "--ignore-gpu-blocklist", "--use-angle=vulkan", "--enable-features=Vulkan",
      "--disable-vulkan-surface", "--disable-gpu-sandbox"]), "--no-sandbox", ...certificateArgs],
  });
  const page = await browser.newPage({ viewport: { width: 1360, height: 1050 },
    ...(process.env.ICLR_WEB_USERNAME ? {httpCredentials:{username:process.env.ICLR_WEB_USERNAME,password:process.env.ICLR_WEB_PASSWORD??''}} : {}) });
  if (forceCompatible) await page.addInitScript(() => Object.defineProperty(navigator, "gpu", { value: undefined }));
  const errors = [], detailRequests = [];
  page.on("pageerror", (error) => errors.push(error.message));
  page.on("console", (message) => { if (message.type() === "error") errors.push(message.text()); });
  page.on("request", (r) => { if (/\/details-[^/]+\//.test(r.url())) detailRequests.push(r.url()); });
  const baseURL = externalURL ?? `http://127.0.0.1:${server.httpServer.address().port}`;
  const start = Date.now();
  await page.goto(new URL("/?smoke=1", baseURL).href);
  const finalOrigin = new URL(page.url()).origin;
  assert.equal(await page.evaluate(() => isSecureContext), true);
  await page.waitForFunction(() => window.__atlasProbe?.positions.length > 0, null, { timeout: 60000 });
  console.log("smoke: map-ready");
  const readyMs = Date.now() - start;
  assert.equal(detailRequests.length, 0, "Initial map must not load all abstracts/reviews");
  const renderer = await page.evaluate(() => window.__atlasProbe.renderer);
  if (forceCompatible) assert.equal(renderer, "canvas");
  const sample = JSON.parse(await readFile(new URL("./public/generated/sample.json", import.meta.url)));
  await page.waitForLoadState("networkidle");
  await page.waitForFunction(() => window.__atlasProbe.mapLabels?.length >= 4);
  assert.equal(await page.locator("#map-color").inputValue(), "domain");
  assert.equal(await page.locator("#map-legend button").count(), 23);
  assert.equal(await page.locator("#map-regions button").count(), 30);
  assert.ok((await page.locator(".map-region-label").first().textContent()).length > 8);
  await page.waitForFunction(() => window.__atlasProbe.domainSurface?.active && window.__atlasProbe.domainSurface.papers === window.__atlasProbe.positions.length);
  await page.waitForFunction(() => window.__atlasProbe.domainSurface.boundarySegments > 100);
  assert.equal(await page.locator("#atlas .map-topic-label").count(), 0);
  assert.equal(await page.locator("#atlas .map-paper-label").count(), 0);
  assert.equal(await page.evaluate(() => window.__atlasProbe.labelLevel), "domain");
  const initialMapPositions = await page.evaluate(() => window.__atlasProbe.positions.slice(0,20));
  const originalRadius = await page.evaluate(() => window.__atlasProbe.pointRadius);
  const fieldPixels = await page.locator("#atlas .map-surface-layer").evaluate((canvas) => {
    const pixels = canvas.getContext("2d").getImageData(0, 0, canvas.width, canvas.height).data;
    let colored = 0; for (let i = 3; i < pixels.length; i += 4) if (pixels[i] > 0) colored++;
    return colored;
  });
  assert.ok(fieldPixels > 1000, "The visible map must contain a real transition field");
  await page.locator("#map-boundaries-toggle").uncheck();
  await page.locator("#map-surface-toggle").uncheck();
  await page.waitForFunction(() => window.__atlasProbe.domainSurface.active === false);
  assert.ok(await page.locator("#atlas .map-surface-layer").evaluate((c) => c.getContext("2d").getImageData(0,0,c.width,c.height).data.every((n) => n === 0)));
  await page.locator("#map-surface-toggle").check();
  await page.locator("#map-surface-scale").selectOption("8");
  await page.waitForFunction(() => window.__atlasProbe.domainSurface.sigma === 8);
  await page.locator("#map-surface-scale").selectOption("5");
  await page.waitForFunction(() => window.__atlasProbe.domainSurface.sigma === 5);
  await page.locator("#map-boundaries-toggle").check();
  await page.waitForFunction(() => window.__atlasProbe.domainSurface.boundarySegments > 100);
  await page.locator("#zoom-in").click(); await page.locator("#zoom-in").click();
  await page.waitForFunction(() => window.__atlasProbe.labelLevel === "topic" && document.querySelectorAll("#atlas .map-topic-label").length > 0);
  assert.equal(await page.locator("#atlas .map-domain-label").count(), 0);
  const topicDomains = await page.locator("#atlas .map-topic-label").evaluateAll((nodes) => nodes.map((n) => n.dataset.domain));
  const domainIds = new Set(sample.papers.map((p) => p.domain));
  assert.ok(topicDomains.every((id) => domainIds.has(id)));
  assert.ok(await page.locator("#atlas .map-topic-label strong").evaluateAll((nodes) => nodes.every((n) => n.textContent.startsWith("● "))));
  await page.locator("#map-panel").screenshot({ path: `artifacts/${prefix}-map-topic-level.png` });
  await page.locator("#zoom-in").click(); await page.locator("#zoom-in").click();
  await page.waitForFunction(() => window.__atlasProbe.labelLevel === "paper" && window.__atlasProbe.paperLabels.length > 0);
  assert.ok(await page.evaluate((r) => window.__atlasProbe.pointRadius > r * 2, originalRadius));
  const infoCard = page.locator("#atlas .map-paper-label").first();
  const cardId = await infoCard.getAttribute("data-paper-id");
  const cardPaper = sample.papers.find((p) => p.paper_id === cardId);
  assert.equal(await infoCard.locator("strong").textContent(), cardPaper.title);
  assert.ok((await infoCard.textContent()).includes(`ICLR ${cardPaper.year}`));
  await page.locator("#map-panel").screenshot({ path: `artifacts/${prefix}-map-paper-level.png` });
  await infoCard.click();
  await page.waitForFunction((id) => window.__atlasProbe.detailLoaded === id, cardId);
  assert.equal(await page.locator("#detail h3").textContent(), cardPaper.title);
  await page.locator("#reset-map").click();
  await page.waitForFunction(() => Math.abs(window.__atlasProbe.zoom - 1) < 0.01 && window.__atlasProbe.labelLevel === "domain");
  const points = await page.evaluate(() => window.__atlasProbe.positions);
  assert.equal(points.length, sample.papers.length);
  const box = await page.locator("#atlas").boundingBox();
  const visible = points.filter((p) => p.x > 20 && p.x < box.width - 20 && p.y > 20 && p.y < box.height - 20);
  // Pick distinct, non-overlapping points so the browser's nearest-point selection is unambiguous.
  const isolated = [];
  for (const p of visible) {
    if (isolated.length && Math.hypot(p.x - isolated[0].x, p.y - isolated[0].y) <= 20) continue;
    if (!visible.some((q) => q.paper_id !== p.paper_id && Math.hypot(q.x - p.x, q.y - p.y) < 2)) isolated.push(p);
    if (isolated.length === 2) break;
  }
  assert.ok(isolated.length >= 2);
  const first = isolated[0], second = isolated.find((p) => Math.hypot(p.x - first.x, p.y - first.y) > 20);
  const selectionStart = Date.now();
  await page.mouse.click(box.x + first.x, box.y + first.y);
  await page.waitForFunction((id) => window.__atlasProbe.selections.at(-1)?.includes(id), first.paper_id);
  await page.keyboard.down("Shift");
  await page.mouse.click(box.x + second.x, box.y + second.y);
  await page.keyboard.up("Shift");
  await page.waitForFunction(() => window.__atlasProbe.selections.at(-1)?.length === 2).catch(async (error) => {
    console.log("Selection diagnostic", JSON.stringify({ first, second, errors, box, currentBox: await page.locator("#atlas").boundingBox(), hit: await page.evaluate(({ x,y }) => document.elementFromPoint(x,y)?.outerHTML.slice(0,1000), {x:box.x+second.x,y:box.y+second.y}), probe: await page.evaluate(() => ({ selections: window.__atlasProbe.selections, renderer: window.__atlasProbe.renderer })) }));
    await page.screenshot({path:"artifacts/atlas-diagnostic.png",fullPage:true});
    throw error;
  });
  const selected = await page.evaluate(() => window.__atlasProbe.selections.at(-1));
  assert.deepEqual(new Set(selected), new Set([first.paper_id, second.paper_id]));
  await page.waitForFunction((id) => window.__atlasProbe.detailLoaded === id, selected[0]);
  console.log("smoke: map-selected");
  const selectionMs = Date.now() - selectionStart;
  const paper = sample.papers.find((p) => p.paper_id === selected[0]);
  assert.equal(await page.locator("#detail h3").textContent(), paper.title);
  const chunk = await (await page.request.get(new URL(`/generated/${sample.meta.details_base}/${paper.detail_chunk}.json`, finalOrigin).href)).json();
  if (chunk[paper.paper_id].abstract) assert.ok((await page.locator("#detail").textContent()).includes(chunk[paper.paper_id].abstract));
  await page.waitForFunction(() => document.getElementById("plot").complete && document.getElementById("plot").naturalWidth > 0);
  const svg = await (await page.request.get(new URL("/generated/reviews.svg", finalOrigin).href)).text();
  assert.ok(svg.includes("<svg") && svg.includes("论文评分水平与审稿分歧"));
  await page.waitForLoadState("networkidle");
  const frame = await page.evaluate(() => {
    const canvas = document.querySelector("#atlas canvas"), url = canvas.toDataURL();
    return new Promise((resolve) => {
      const image = new Image(); image.src = url;
      image.onload = () => {
        const readback = document.createElement("canvas"); readback.width = canvas.width; readback.height = canvas.height;
        const context = readback.getContext("2d"); context.drawImage(image, 0, 0);
        const positions = window.__atlasProbe.positions.filter((p) => p.x > 10 && p.x < canvas.clientWidth - 10 && p.y > 10 && p.y < canvas.clientHeight - 10).slice(0, 300);
        const colored = positions.filter((p) => {
          const [r, g, b] = context.getImageData(Math.round(p.x * canvas.width / canvas.clientWidth), Math.round(p.y * canvas.height / canvas.clientHeight), 1, 1).data;
          return Math.max(r, g, b) - Math.min(r, g, b) > 20;
        }).length;
        // Headless Vulkan screenshots omit the GPU surface; retain actual readback as evidence.
        if (window.__atlasProbe.renderer === "atlas") {
          image.style.cssText = `${canvas.style.cssText}; pointer-events: none`; canvas.after(image);
        }
        resolve({ url, sampled: positions.length, colored });
      };
    });
  });
  assert.ok(frame.sampled > 0 && frame.colored >= frame.sampled * 0.9, "Actual pixel readback must contain the corpus");
  await mkdir("artifacts", { recursive: true });
  await writeFile(`artifacts/${prefix}-atlas-canvas.png`, Buffer.from(frame.url.split(",")[1], "base64"));
  await page.screenshot({ path: `artifacts/${prefix}-browser.png`, fullPage: true });
  // Remove the screenshot-only GPU readback before exercising viewport/filter changes.
  await page.evaluate(() => document.querySelector("#atlas canvas + img")?.remove());
  console.log("smoke: pixel-readback-complete");
  const filterStart = Date.now();
  await page.locator("#year").selectOption("2025");
  await page.locator("#decision").selectOption("accepted");
  const expected = sample.papers.filter((p) => p.year === 2025 && p.decision === "accepted");
  await page.waitForFunction((n) => window.__atlasProbe.visibleIds.length === n, expected.length);
  assert.deepEqual(new Set(await page.evaluate(() => window.__atlasProbe.visibleIds)), new Set(expected.map((p) => p.paper_id)));
  const filterMs = Date.now() - filterStart;
  await page.locator("#year").selectOption(""); await page.locator("#decision").selectOption("");
  await page.locator("#search").fill("zzzz-no-such-iclr-paper");
  await page.waitForFunction(() => window.__atlasProbe.visibleIds.length === 0);
  assert.equal(await page.locator("#results button").count(), 0);
  await page.locator("#search").fill(paper.forum_id);
  await page.waitForFunction(() => window.__atlasProbe.visibleIds.length === 1);
  await page.locator("#results").evaluate((e) => { e.parentElement.open = true; });
  await page.locator(`#results button[data-paper-id="${paper.paper_id}"]`).click();
  await page.waitForFunction((id) => window.__atlasProbe.detailLoaded === id && window.__atlasProbe.selections.at(-1)?.[0] === id, paper.paper_id);
  assert.equal(await page.locator("#detail h3").textContent(), paper.title);
  await page.locator("#atlas").hover(); await page.mouse.wheel(0, -400);
  await page.waitForFunction(() => window.__atlasProbe.zoom > 1 && window.__atlasProbe.pointRadius > 2.3);
  await page.locator("#reset-map").click(); await page.waitForFunction(() => Math.abs(window.__atlasProbe.zoom - 1) < 0.01);
  const resetPositions = await page.evaluate(() => window.__atlasProbe.positions);
  for (const point of resetPositions) {
    const original = initialMapPositions.find((p) => p.paper_id === point.paper_id);
    if (original) assert.ok(Math.hypot(point.x - original.x, point.y - original.y) < 1, "Reset must restore actual pixel coordinates after mouse wheel zoom");
  }
  console.log("smoke: map-filters-complete");
  await page.locator("#search").fill("");
  await page.waitForFunction((n) => window.__atlasProbe.visibleIds.length === n, sample.papers.length);
  await page.locator("#map-domain").selectOption("reinforcement_learning");
  const mapDomainPapers = sample.papers.filter((p) => p.domain === "reinforcement_learning");
  await page.waitForFunction((n) => window.__atlasProbe.visibleIds.length === n, mapDomainPapers.length);
  await page.waitForFunction(() => [...document.querySelectorAll(".map-region-label strong")].every((e) => e.textContent === "强化学习"));
  await page.locator("#map-domain").selectOption("");
  await page.locator("#map-color").selectOption("year");
  assert.equal(await page.locator("#map-legend button").count(), 3);
  await page.waitForFunction(() => window.__atlasProbe.domainSurface.active === false);
  await page.locator("#map-color").selectOption("domain");
  await page.locator("#map-label-toggle").uncheck();
  await page.waitForFunction(() => window.__atlasProbe.mapLabels.length === 0);
  await page.locator("#map-label-toggle").check();
  await page.waitForFunction(() => window.__atlasProbe.mapLabels.length >= 4);
  await page.locator("#map-regions").evaluate((e) => e.parentElement.open = true);
  const regionButton = page.locator("#map-regions button").first();
  const mapLabels = JSON.parse(await readFile(new URL("./public/generated/map-labels.json", import.meta.url)));
  const regionId = Number(await regionButton.getAttribute("data-region"));
  await regionButton.click();
  const regionPapers = mapLabels.regions.find((r) => r.id === regionId).paper_ids;
  await page.waitForFunction((n) => window.__atlasProbe.visibleIds.length === n, regionPapers.length);
  assert.deepEqual(new Set(await page.evaluate(() => window.__atlasProbe.visibleIds)), new Set(regionPapers));
  await page.locator("#clear-domain").click();
  await page.locator("#map-regions").evaluate((e) => e.parentElement.open = false);
  await page.locator("#map-panel").screenshot({ path: `artifacts/${prefix}-map-topics.png` });
  // S4 entities: verify real graph interactions against independently selected paper IDs.
  await page.waitForFunction(() => window.__analysisProbe?.ready && window.__analysisProbe.evidence?.loaded, null, { timeout: 60000 });
  console.log("smoke: analysis-ready");
  async function checkAcceptanceRate(rows) {
    const accepted = rows.filter((p) => p.decision === "accepted").length;
    const expected = rows.length ? `${(100 * accepted / rows.length).toFixed(1)}%` : "无可用分母";
    assert.ok((await page.locator("#domain-facts").textContent()).includes(`中稿率 ${expected}（${accepted}/${rows.length}）`),
      "Acceptance rate includes all submission decisions in its denominator");
  }
  await checkAcceptanceRate(sample.papers);
  const domainRows = await page.locator("#domain-table tbody tr").evaluateAll((rows) => rows.map((row) => ({
    domain:row.querySelector("button").dataset.domain, cells:[...row.cells].map((cell) => cell.textContent),
  })));
  for (const row of domainRows) {
    const submissions = sample.papers.filter((p) => p.domain === row.domain);
    const accepted = submissions.filter((p) => p.decision === "accepted").length;
    const expected = submissions.length ? `${(100 * accepted / submissions.length).toFixed(1)}%` : "无可用分母";
    assert.equal(row.cells.length, 8, "One acceptance-rate column");
    assert.equal(row.cells[2], `${expected} (${accepted}/${submissions.length})`);
  }
  async function checkChordLabels() {
    const labels = await page.locator("#domain-chord .chord-topic-label").evaluateAll((nodes) => nodes.map((n) => {
      const r = n.getBoundingClientRect(); return { text:n.textContent, x:r.x, y:r.y, right:r.right, bottom:r.bottom };
    }));
    assert.ok(labels.length > 0);
    for (let i = 0; i < labels.length; i++) for (let j = i + 1; j < labels.length; j++) {
      const a = labels[i], b = labels[j];
      assert.ok(!(a.x < b.right && a.right > b.x && a.y < b.bottom && a.bottom > b.y), `Chord labels overlap: ${a.text} / ${b.text}`);
    }
    const svg = await page.locator("#domain-chord svg").boundingBox();
    assert.ok(labels.every((r) => r.x >= svg.x && r.right <= svg.x + svg.width && r.y >= svg.y && r.bottom <= svg.y + svg.height), "All labels must fit inside the SVG");
    assert.equal(await page.locator("#domain-chord .chord-label-leader").count(), labels.length);
  }
  for (const limit of ["16", "24", "32"]) { await page.locator("#chord-limit").selectOption(limit); await checkChordLabels(); }
  await page.locator("#chord-limit").selectOption("16");
  const analysis = JSON.parse(await readFile(new URL("./public/generated/domains.json", import.meta.url)));
  assert.equal(analysis.meta.source_data_version, sample.meta.data_version);
  assert.equal(analysis.papers.length, sample.papers.length);
  assert.equal(new Set(analysis.papers.map((p) => p.paper_id)).size, sample.papers.length);
  const topicData = JSON.parse(await readFile(new URL("./public/generated/topics.json", import.meta.url)));
  // Independently union original entity IDs, rather than summing alias counts.
  const hasConcept = (p, id) => topicData.concepts[id].raw_entity_ids.some((rawId) => p.entities.includes(rawId));
  const paperById = new Map(sample.papers.map((p) => [p.paper_id, p]));
  await page.locator("#analysis-year").selectOption("2025");
  await page.locator("#analysis-domain").selectOption("reinforcement_learning");
  const analysisBase = analysis.papers.filter((p) => p.domain === "reinforcement_learning" && paperById.get(p.paper_id).year === 2025);
  await page.waitForFunction((n) => window.__analysisProbe.summary.papers === n, analysisBase.length);
  await page.locator("#entity-type").selectOption("METHOD");
  console.log("smoke: analysis-field-selected");
  await checkAcceptanceRate(analysisBase.map((p) => paperById.get(p.paper_id)));
  await checkChordLabels();
  const labelNode = page.locator("#topic-tree g[role=button]").first();
  const entityId = Number(await labelNode.getAttribute("data-topic"));
  await labelNode.focus(); await page.keyboard.press("Enter");
  console.log("smoke: entity-selected");
  const expectedTopic = analysisBase.filter((p) => hasConcept(p, entityId));
  await page.waitForFunction((n) => window.__analysisProbe.summary.papers === n && window.__atlasProbe.visibleIds.length === n, expectedTopic.length);
  assert.deepEqual(new Set(await page.evaluate(() => window.__analysisProbe.selectedPaperIds)), new Set(expectedTopic.map((p) => p.paper_id)));
  await checkAcceptanceRate(expectedTopic.map((p) => paperById.get(p.paper_id)));
  const expectedAccepted = expectedTopic.filter((p) => paperById.get(p.paper_id).decision === "accepted").length;
  assert.equal(await page.evaluate(() => window.__analysisProbe.summary.accepted), expectedAccepted);
  assert.equal(await page.evaluate(() => window.__analysisProbe.summary.valid), expectedTopic.reduce((n, p) => n + p.ratings.length, 0));
  await page.locator("#score-status").selectOption("accepted");
  const expectedAcceptedRatings = expectedTopic.filter((p) => paperById.get(p.paper_id).decision === "accepted").reduce((n, p) => n + p.ratings.length, 0);
  assert.equal(await page.evaluate(() => window.__analysisProbe.scoreCoverage.reduce((n, c) => n + c.valid, 0)), expectedAcceptedRatings);
  await page.locator("#score-status").selectOption(""); await page.locator("#clear-topic").click();
  console.log("smoke: chord-ready");
  const ribbon = page.locator("#domain-chord .ribbon").first();
  const pair = (await ribbon.getAttribute("data-pair")).split(":").map(Number);
  const chordCount = Number(await ribbon.getAttribute("data-count"));
  const expectedPair = analysisBase.filter((p) => pair.every((id) => hasConcept(p, id)));
  assert.equal(chordCount, expectedPair.length);
  await ribbon.focus(); await page.keyboard.press("Enter");
  await page.waitForFunction((n) => window.__analysisProbe.summary.papers === n && window.__atlasProbe.visibleIds.length === n, expectedPair.length);
  assert.deepEqual(new Set(await page.evaluate(() => window.__analysisProbe.selectedPaperIds)), new Set(expectedPair.map((p) => p.paper_id)));
  console.log("smoke: chord-selected");
  await checkAcceptanceRate(expectedPair.map((p) => paperById.get(p.paper_id)));
  const evidenceButton = page.locator("#chord-evidence button").first();
  const evidenceId = await evidenceButton.getAttribute("data-paper-id"); await evidenceButton.click();
  await page.waitForFunction((id) => window.__analysisProbe.evidence.paperId === id && window.__atlasProbe.detailLoaded === id, evidenceId);
  const originalEvidence = JSON.parse(await readFile(new URL(`./public/generated/${analysis.evidence_base}/${evidenceId}.json`, import.meta.url)));
  const eligible = originalEvidence.entity_candidates.filter((c) => c.literal_span_valid && c.salience === "core");
  assert.equal(await page.locator("#candidate-tree details[data-candidate-id]").count(), eligible.length);
  assert.equal(await page.locator("#tree-paper").inputValue(), evidenceId);
  console.log("smoke: evidence-loaded");
  await page.locator("#analysis-domain").selectOption("");
  await page.locator("#analysis-year").selectOption("");
  await page.locator("#entity-type").selectOption("");
  const llm = topicData.concepts.find((c) => c.key === "large language model");
  await page.locator("#topic-search").fill("LLMs");
  await page.waitForFunction((id) => !!document.querySelector(`#topic-tree g[data-topic="${id}"]`), llm.id);
  await page.locator(`#topic-tree g[data-topic="${llm.id}"]`).focus(); await page.keyboard.press("Enter");
  const llmPapers = analysis.papers.filter((p) => hasConcept(p, llm.id));
  await page.waitForFunction((n) => window.__analysisProbe.summary.papers === n, llmPapers.length);
  assert.deepEqual(new Set(await page.evaluate(() => window.__analysisProbe.selectedPaperIds)), new Set(llmPapers.map((p) => p.paper_id)));
  const chordIds = await page.evaluate(() => window.__analysisProbe.chordEntityIds);
  assert.equal(chordIds.filter((id) => id === llm.id).length, 1);
  assert.ok(chordIds.every((id) => !topicData.concepts[id].generic));
  const matrix = await page.evaluate(() => window.__analysisProbe.chordMatrix);
  assert.ok(matrix.every((row, i) => row[i] === 0));
  await page.locator("#clear-topic").click();
  await page.locator("#topic-search").fill("diffusion");
  await page.waitForFunction(() => document.querySelector("#topic-tree g[data-topic]")?.textContent.toLowerCase().includes("diffusion"));
  assert.ok((await page.locator("#topic-tree").textContent()).toLowerCase().includes("diffusion"));
  await page.locator("#topic-search").fill("");
  await page.locator("#domain-panel").screenshot({ path: `artifacts/${prefix}-s4-analysis.png` });
  await page.locator("#chord-limit").selectOption("32"); await checkChordLabels();
  await page.locator("#chord-panel").screenshot({ path: `artifacts/${prefix}-s4-chord.png` });
  await page.setViewportSize({ width: 390, height: 844 });
  await page.waitForFunction(() => document.documentElement.scrollWidth <= innerWidth, null, { timeout: 5000 }).catch(async (error) => {
    console.log("Overflow diagnostic", await page.evaluate(() => [...document.querySelectorAll("body *")].filter((e) => e.getBoundingClientRect().right > innerWidth).map((e) => ({ tag:e.tagName, id:e.id, width:e.getBoundingClientRect().width, style:e.getAttribute("style") })).slice(-15)));
    throw error;
  });
  await checkChordLabels();
  assert.equal(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth), false, "Mobile must not overflow horizontally");
  assert.equal(await page.locator("#fatal").textContent(), ""); assert.deepEqual(errors, []);
  const result = {
    passed: true, at: new Date().toISOString(), browser: browser.version(), renderer,
    webgpu_disabled_for_test: forceCompatible, base_url: baseURL, final_origin: finalOrigin,
    data_version: sample.meta.data_version, papers: sample.papers.length, reviews: sample.meta.totals.reviews,
    selected_paper_ids: selected, initial_map_ms: readyMs, selection_and_details_ms: selectionMs, filter_ms: filterMs,
    initial_detail_requests: 0, pixel_readback: { sampled: frame.sampled, colored: frame.colored },
    year_decision_filter_verified: true, empty_search_verified: true, search_selection_verified: true,
    mobile_overflow: false, page_errors: errors, semantic_projection: sample.meta.semantic_projection,
    mouse_wheel_zoom_reset_verified: true,
    mathematical_domain_boundaries_verified: true, zoom_point_growth_verified: true, progressive_s4_labels_verified: true, zoom_paper_card_verified: true,
    chord_label_collisions_verified: true, domain_transition_field_verified: true, transition_field_colored_pixels: fieldPixels,
    visible_map_labels_verified: true, map_domain_filter_verified: true, map_region_filter_verified: true, canonical_alias_union_verified: true,
    s4_entities_verified: true, chord_pair: pair, chord_joint_papers: chordCount, entity_topic_papers: expectedTopic.length, evidence_paper: evidenceId,
    screenshot: `web/artifacts/${prefix}-browser.png`, screenshot_uses_gpu_readback: renderer === "atlas",
  };
  await writeFile(`artifacts/${prefix}-smoke.json`, JSON.stringify(result, null, 2) + "\n");
  console.log(JSON.stringify(result, null, 2));
} finally { if (browser) await browser.close(); await server?.close(); }
