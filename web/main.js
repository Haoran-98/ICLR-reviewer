import { drawMapLabels, pointRadius, paperInfo } from "./map-labels.js";
import { createDomainSurface, drawDomainSurface } from "./map-surface.js";
const colors = ["#2563eb", "#0f766e", "#b45309"];
const asPoint = (p) => ({ x: p.x, y: p.y, identifier: p.paper_id, text: `${p.title}\n${paperInfo(p)}`, category: p.year - 2024 });

// Canvas keeps the full corpus usable on clients without WebGPU; no per-paper DOM nodes.
function compatibleMap(host, allPapers, onSelect, probe, mapStyle) {
  const canvas = document.createElement("canvas");
  canvas.setAttribute("role", "img");
  canvas.setAttribute("aria-label", "论文文本地图。可缩放拖动；也可用下方搜索结果按钮选择论文。");
  canvas.style.cssText = "width:100%;height:420px;touch-action:none;display:block";
  host.append(canvas);
  const labels = document.createElement("div"); labels.className = "map-label-layer"; host.append(labels);
  const ctx = canvas.getContext("2d");
  let papers = allPapers, selected = new Set(), width = host.clientWidth;
  let zoom = 1, panX = 0, panY = 0, frame = 0, drag = null, positions = [];
  const xs = allPapers.map((p) => p.x), ys = allPapers.map((p) => p.y);
  const minX = Math.min(...xs), maxX = Math.max(...xs), minY = Math.min(...ys), maxY = Math.max(...ys);
  const centerX = (minX + maxX) / 2, centerY = (minY + maxY) / 2;
  function draw() {
    frame = 0;
    const ratio = Math.min(devicePixelRatio || 1, 2);
    if (canvas.width !== Math.round(width * ratio) || canvas.height !== Math.round(420 * ratio)) {
      canvas.width = Math.round(width * ratio); canvas.height = Math.round(420 * ratio);
    }
    ctx.setTransform(ratio, 0, 0, ratio, 0, 0);
    ctx.fillStyle = "white"; ctx.fillRect(0, 0, width, 420);
    const scale = Math.min((width - 40) / (maxX - minX || 1), 380 / (maxY - minY || 1)) * zoom;
    positions = papers.map((p) => ({ paper: p, paper_id: p.paper_id,
      x: width / 2 + (p.x - centerX) * scale + panX,
      y: 210 - (p.y - centerY) * scale + panY }));
    const radius = pointRadius(zoom);
    ctx.globalAlpha = 0.65;
    for (let category = 0; category < mapStyle.colors().length; category++) {
      ctx.beginPath();
      for (const p of positions) {
        if (mapStyle.category(p.paper) !== category || p.x < -5 || p.x > width + 5 || p.y < -5 || p.y > 425) continue;
        ctx.moveTo(p.x + radius, p.y); ctx.arc(p.x, p.y, radius, 0, Math.PI * 2);
      }
      ctx.fillStyle = mapStyle.colors()[category]; ctx.fill();
    }
    ctx.globalAlpha = 1;
    for (const p of positions) if (selected.has(p.paper_id)) {
      ctx.beginPath(); ctx.arc(p.x, p.y, radius + 3, 0, Math.PI * 2);
      ctx.strokeStyle = "#14243a"; ctx.lineWidth = 2; ctx.stroke();
    }
    const location = (x, y) => ({ x: width / 2 + (x - centerX) * scale + panX, y: 210 - (y - centerY) * scale + panY });
    mapStyle.drawSurface(location, width, 420);
    drawMapLabels(labels, mapStyle.annotations(), location, width, 420, zoom, mapStyle.selectPaper, probe);
    mapStyle.level(zoom);
    if (probe) {
      probe.positions = positions.map(({ paper_id, x, y }) => ({ paper_id, x, y }));
      probe.drawn = papers.length; probe.zoom = zoom;
    }
  }
  function schedule() { if (!frame) frame = requestAnimationFrame(draw); }
  function nearest(x, y) {
    let found = null, distance = Math.max(9, pointRadius(zoom) + 3);
    for (const p of positions) {
      const d = Math.hypot(p.x - x, p.y - y);
      if (d < distance) { found = p; distance = d; }
    }
    return found;
  }
  canvas.addEventListener("pointerdown", (e) => {
    drag = { x: e.clientX, y: e.clientY, panX, panY, moved: false };
    canvas.setPointerCapture(e.pointerId);
  });
  canvas.addEventListener("pointermove", (e) => {
    if (drag) {
      const dx = e.clientX - drag.x, dy = e.clientY - drag.y;
      drag.moved ||= Math.hypot(dx, dy) > 4;
      if (drag.moved) { panX = drag.panX + dx; panY = drag.panY + dy; schedule(); }
    } else {
      const rect = canvas.getBoundingClientRect();
      const p = nearest(e.clientX - rect.left, e.clientY - rect.top);
      canvas.title = p ? `${p.paper.title}\n${paperInfo(p.paper)}` : "滚轮缩放，拖动平移";
      canvas.style.cursor = p ? "pointer" : "grab";
    }
  });
  canvas.addEventListener("pointerup", (e) => {
    if (drag && !drag.moved) {
      const rect = canvas.getBoundingClientRect();
      const p = nearest(e.clientX - rect.left, e.clientY - rect.top);
      const next = e.shiftKey || e.ctrlKey || e.metaKey ? new Set(selected) : new Set();
      if (p) { if (next.has(p.paper_id)) next.delete(p.paper_id); else next.add(p.paper_id); }
      onSelect(allPapers.filter((p) => next.has(p.paper_id)).map(asPoint));
    }
    drag = null;
  });
  canvas.addEventListener("pointercancel", () => { drag = null; });
  canvas.addEventListener("wheel", (e) => {
    e.preventDefault();
    const rect = canvas.getBoundingClientRect(), oldZoom = zoom;
    zoom = Math.max(0.5, Math.min(80, zoom * Math.exp(-e.deltaY * 0.002)));
    const factor = zoom / oldZoom, x = e.clientX - rect.left - width / 2, y = e.clientY - rect.top - 210;
    panX = x - (x - panX) * factor; panY = y - (y - panY) * factor;
    schedule();
  }, { passive: false });
  return { zoomBy(factor) {
    const old = zoom; zoom = Math.max(0.5, Math.min(80, zoom * factor)); panX *= zoom / old; panY *= zoom / old; schedule();
  }, update(options = {}) {
    width = options.width ?? width;
    if (options.papers) papers = options.papers;
    if (options.selection !== undefined) selected = new Set((options.selection ?? []).map((p) => String(p.identifier)));
    if (options.viewportState === null) { zoom = 1; panX = panY = 0; }
    schedule();
  } };
}

async function main() {
  const [response, labelResponse] = await Promise.all(["sample", "map-labels"].map((name) => fetch(`/generated/${name}.json`, { cache: "no-cache" })));
  if (!response.ok) throw new Error("论文数据暂不可用，请稍后刷新");
  const { papers, meta } = await response.json();
  if (!labelResponse.ok) throw new Error("请运行 python3 web/derive_topics.py 生成主题标注");
  const mapData = await labelResponse.json();
  if (mapData.meta.source_data_version !== meta.data_version) throw new Error("地图标注快照不一致");
  const domainIndex = new Map(mapData.domains.map((d, i) => [d.id, i]));
  const domainColors = ["#a92d2d", "#2da951", "#752da9", "#a99a2d", "#2d94a9", "#a92d70", "#4ca92d", "#322da9", "#a9572d", "#2da97b", "#9f2da9", "#8fa92d", "#2d6ba9", "#a92d47", "#2da938", "#5c2da9", "#a9802d", "#2da9a4", "#a92d8a", "#66a92d", "#2d41a9", "#a93d2d", "#2da961"];
  const colorMode = document.getElementById("map-color"), mapDomain = document.getElementById("map-domain");
  const boundaryToggle = document.getElementById("map-boundaries-toggle");
  const surfaceToggle = document.getElementById("map-surface-toggle"), surfaceScale = document.getElementById("map-surface-scale");
  const surfaceLayer = document.createElement("canvas"); surfaceLayer.className = "map-surface-layer";
  surfaceLayer.setAttribute("aria-hidden", "true");
  const xs = papers.map((p) => p.x), ys = papers.map((p) => p.y);
  const range = Math.max(Math.max(...xs) - Math.min(...xs), Math.max(...ys) - Math.min(...ys)) * 1.25;
  const cx = (Math.max(...xs) + Math.min(...xs)) / 2, cy = (Math.max(...ys) + Math.min(...ys)) / 2;
  const surfaceExtent = [cx - range / 2, cy - range / 2, cx + range / 2, cy + range / 2];
  let surface = null, surfaceKey = "";
  const labelToggle = document.getElementById("map-label-toggle");
  for (const d of mapData.domains) {
    const option = document.createElement("option"); option.value = d.id; option.textContent = d.label; mapDomain.append(option);
  }
  const host = document.getElementById("atlas"), byId = new Map(papers.map((p) => [p.paper_id, p]));
  const probe = new URLSearchParams(location.search).has("smoke") ? { selections: [], positions: [] } : null;
  if (probe) window.__atlasProbe = probe;
  const totals = meta.totals;
  document.getElementById("status").textContent = `${papers.length.toLocaleString()} 篇论文 · ${totals.reviews.toLocaleString()} 条审稿 · ${totals.valid_ratings.toLocaleString()} 条有效评分`;
  document.getElementById("snapshot").textContent = `数据更新 ${meta.extracted_at.slice(0, 10)} · 版本 ${meta.content_sha256.slice(0, 12)}`;
  document.getElementById("review-coverage").textContent =
    `每条审稿取最新已采集版本：${totals.valid_ratings.toLocaleString()} 条有效评分，${(totals.reviews - totals.valid_ratings).toLocaleString()} 条缺失。`;
  const chunks = new Map();
  let view, atlasOverlay, visible = papers, selectionSerial = 0, analysisIds = null, visibleRegions = [], visibleTopicRegions = [];
  let atlasZoom = 1, atlasBaseScale = null, atlasViewport = null, initialAtlasViewport = null, atlasSizeFrame = 0, atlasRadius = 2.3;
  function updateAtlasZoom(state) {
        if (atlasBaseScale === null) { atlasBaseScale = state.scale; initialAtlasViewport = { ...state }; }
        atlasViewport = state; atlasZoom = state.scale / atlasBaseScale;
        if (!atlasSizeFrame) atlasSizeFrame = requestAnimationFrame(() => {
          atlasSizeFrame = 0; const radius = pointRadius(atlasZoom);
          if (Math.abs(radius - atlasRadius) > 0.02) { atlasRadius = radius; view?.update({ config:{ mode:"points",pointSize:radius,autoLabelEnabled:false } }); }
          atlasOverlay?.redraw();
        });
  }
  const mapStyle = {
    colors: () => colorMode.value === "year" ? colors : domainColors,
    category: (p) => colorMode.value === "year" ? p.year - 2024 : domainIndex.get(p.domain),
    annotations: () => labelToggle.checked ? {
      domains:(surface?.anchors ?? []).map((a) => ({ ...a,domainLabel:mapData.domains[domainIndex.get(a.domain)].label })),
      topics:visibleTopicRegions,
      papers:visible,
    } : { domains:[],topics:[],papers:[] },
    selectPaper: (p) => select([asPoint(p)]),
    level: (zoom) => { document.getElementById("map-level").textContent = `${zoom.toFixed(1)}× · ${zoom < 2.2 ? "投稿领域" : zoom < 5 ? "投稿领域标记 + 研究主题" : "研究主题 + 论文信息"} · 滚轮或＋/－逐级缩放`; },
    drawSurface: (location, width, height) => drawDomainSurface(surfaceLayer,
      colorMode.value === "domain" && (surfaceToggle.checked || boundaryToggle.checked) ? surface : null, location, width, height, probe, surfaceToggle.checked, boundaryToggle.checked),
  };
  function updateMapContext() {
    const ids = new Set(visible.map((p) => p.paper_id));
    surfaceToggle.disabled = boundaryToggle.disabled = colorMode.value !== "domain";
    if (surfaceToggle.checked || boundaryToggle.checked || labelToggle.checked) {
      const key = `${surfaceScale.value}:${visible.map((p) => p.paper_id).join(",")}`;
      if (key !== surfaceKey) {
        surface = createDomainSurface(visible, (p) => domainColors[domainIndex.get(p.domain)], surfaceExtent, Number(surfaceScale.value));
        surfaceKey = key;
      }
    }
    visibleRegions = mapData.regions.map((r) => {
      const members = r.paper_ids.filter((id) => ids.has(id)), counts = new Map();
      for (const id of members) { const d = byId.get(id).domain; counts.set(d, (counts.get(d) ?? 0) + 1); }
      const dominant = [...counts].sort((a, b) => b[1] - a[1])[0]?.[0] ?? r.domain;
      return { ...r, domainLabel: mapData.domains[domainIndex.get(dominant)].label,
        color: domainColors[domainIndex.get(dominant)], visibleCount: members.length, visibleDomainCount: counts.get(dominant) ?? 0,
        topics: r.topics.filter((t) => t.paper_ids.some((id) => ids.has(id))) };
    }).filter((r) => r.visibleCount > 0);
    visibleTopicRegions = (mapData.topic_regions ?? []).flatMap((r) => {
      const members = r.paper_ids.filter((id) => ids.has(id));
      const topics = r.topics.filter((t) => t.paper_ids.some((id) => ids.has(id)));
      if (!members.length || !topics.length) return [];
      return [{ ...r, domainLabel:mapData.domains[domainIndex.get(r.domain)].label,
        color:domainColors[domainIndex.get(r.domain)], visibleCount:members.length, topics,
        x:members.reduce((sum,id) => sum + byId.get(id).x,0)/members.length,
        y:members.reduce((sum,id) => sum + byId.get(id).y,0)/members.length }];
    });
    const legend = document.getElementById("map-legend"); legend.replaceChildren();
    const items = colorMode.value === "year" ? [2024,2025,2026].map((y, i) => ({ label:String(y), color:colors[i] })) :
      mapData.domains.map((d, i) => ({ ...d, color:domainColors[i] }));
    for (const item of items) {
      const button = document.createElement("button"), swatch = document.createElement("i");
      swatch.className = "swatch"; swatch.style.background = item.color; swatch.setAttribute("aria-hidden", "true");
      button.append(swatch, item.label); button.type = "button";
      button.setAttribute("aria-pressed", item.id ? String(mapDomain.value === item.id) : String(year.value === item.label));
      button.addEventListener("click", () => { if (item.id) mapDomain.value = mapDomain.value === item.id ? "" : item.id;
        else year.value = year.value === item.label ? "" : item.label; filter(); }); legend.append(button);
    }
    const index = document.getElementById("map-regions"); index.replaceChildren();
    for (const region of visibleRegions) {
      const button = document.createElement("button"); button.type = "button"; button.dataset.region = region.id;
      button.textContent = `${region.domainLabel} · ${region.topics.map((t) => t.label).join(" / ")} · 当前 ${region.visibleCount} 篇`;
      button.title = `当前区域 ${region.visibleCount} 篇，其中 ${region.visibleDomainCount} 篇属于 ${region.domainLabel}；这是二维地图的局部分区，可能包含多个投稿领域`;
      button.addEventListener("click", () => {
        analysisIds = new Set(region.paper_ids.filter((id) => ids.has(id)));
        document.getElementById("domain-active").textContent = `地图区域：${button.textContent}`;
        document.getElementById("clear-domain").hidden = false; filter();
      }); index.append(button);
    }
    if (probe) { probe.colorMode = colorMode.value; probe.mapDomain = mapDomain.value; probe.regionCount = visibleRegions.length; }
  }
  const select = async (points) => {
    const serial = ++selectionSerial, ids = (points ?? []).map((p) => String(p.identifier));
    if (probe) probe.selections.push(ids);
    view?.update({ selection: points });
    document.getElementById("selection").textContent = `已选 ${ids.length} 篇${ids.length ? ` · paper_id: ${ids.slice(0, 10).join(", ")}` : ""}`;
    const detail = document.getElementById("detail");
    detail.replaceChildren();
    const paper = byId.get(ids[0]);
    if (!paper) return;
    const title = document.createElement("h3"); title.textContent = paper.title;
    const facts = document.createElement("p");
    facts.textContent = `ICLR ${paper.year} · ${paper.decision_raw ?? "决定未知"} · ${paper.rating_count}/${paper.review_count} 条审稿有评分 · 均分 ${paper.mean_rating?.toFixed(2) ?? "缺失"}${paper.needs_review ? " · 结构化结果待复核" : ""}`;
    const loading = document.createElement("p"); loading.textContent = "正在加载论文详情…";
    detail.append(title, facts, loading);
    const reviewLink = document.createElement('a'); reviewLink.textContent = '进入单篇审稿 →';
    reviewLink.href = `/review.html?paper=${encodeURIComponent(paper.paper_id)}`;
    detail.append(reviewLink);
    try {
      if (!chunks.has(paper.detail_chunk)) chunks.set(paper.detail_chunk,
        fetch(`/generated/${meta.details_base}/${paper.detail_chunk}.json`).then((r) => {
          if (!r.ok) throw new Error("详情加载失败，请刷新重试"); return r.json();
        }).catch((error) => { chunks.delete(paper.detail_chunk); throw error; }));
      const data = (await chunks.get(paper.detail_chunk))[paper.paper_id];
      if (serial !== selectionSerial) return;
      loading.remove();
      for (const [label, text] of [["论文核心内容（模型提取）", data.summary], ["研究问题（模型提取）", data.research_problem],
        ["方法（模型提取）", data.method_overview], ["原始摘要", data.abstract]]) {
        if (!text) continue;
        const heading = document.createElement("strong"); heading.textContent = label;
        const para = document.createElement("p"); para.textContent = text; detail.append(heading, para);
      }
      const observed = document.createElement("p");
      observed.textContent = `投稿领域：${data.areas.map((a) => a.label).join("；")}。作者原始关键词：${(data.keywords ?? []).join("；") || "缺失"}`;
      detail.append(observed);
      const scores = document.createElement("p");
      scores.textContent = "审稿评分：" + (data.reviews.map((r) => `${r.rating ?? "缺失"}（confidence ${r.confidence ?? "缺失"}）`).join("；") || "暂无审稿");
      const link = document.createElement("a");
      link.href = `https://openreview.net/forum?id=${encodeURIComponent(paper.forum_id)}`;
      link.target = "_blank"; link.rel = "noopener noreferrer"; link.textContent = "查看 OpenReview 原始记录";
      detail.append(scores, link);
      if (probe) probe.detailLoaded = paper.paper_id;
    } catch (error) { if (serial === selectionSerial) loading.textContent = error.message; }
  };
  class MapOverlay {
    constructor(target, { proxy }) { atlasOverlay = this; this.target = target; target.classList.add("map-label-layer"); this.update({ proxy }); }
    update({ proxy }) { this.proxy = proxy; this.redraw(); }
    redraw() {
      const proxy = this.proxy;
      if (probe) probe.positions = visible.map((p) => ({ paper_id: p.paper_id, ...proxy.location(p.x, p.y) }));
      mapStyle.drawSurface(proxy.location, proxy.width, proxy.height);
      drawMapLabels(this.target, mapStyle.annotations(), proxy.location, proxy.width, proxy.height, atlasZoom, mapStyle.selectPaper, probe);
      mapStyle.level(atlasZoom);
    }
    destroy() { this.target.replaceChildren(); }
  }
  class PaperTooltip {
    constructor(target, props) {
      this.target = target;
      target.style.cssText += ";white-space:pre-line;background:white;border:1px solid #dce3ed;padding:6px;max-width:280px;font-size:12px";
      this.update(props);
    }
    update({ tooltip }) {
      // Dense maps put other papers beneath the tooltip; keep their clicks reachable.
      this.target.style.pointerEvents = "none";
      this.target.textContent = tooltip.text ?? "";
    }
    destroy() { this.target.replaceChildren(); }
  }
  const adapter = await navigator.gpu?.requestAdapter().catch(() => null);
  const dataFor = (rows) => ({ x: Float32Array.from(rows, (p) => p.x), y: Float32Array.from(rows, (p) => p.y),
    category: Uint8Array.from(rows, mapStyle.category) });
  if (adapter?.features.has("shader-f16")) {
    const { EmbeddingView } = await import("embedding-atlas");
    if (probe) probe.renderer = "atlas";
    view = new EmbeddingView(host, {
      customTooltip: { class: PaperTooltip },
      data: dataFor(papers), width: host.clientWidth, height: 420, categoryColors: mapStyle.colors(),
      config: { mode: "points", pointSize: 2.3, autoLabelEnabled: false },
      onViewportState: updateAtlasZoom,
      querySelection: async (x, y, unitDistance) => {
        let nearest = null, distance = unitDistance * Math.max(9, pointRadius(atlasZoom) + 3);
        for (const paper of visible) {
          const d = Math.hypot(paper.x - x, paper.y - y);
          if (d < distance) { nearest = paper; distance = d; }
        }
        return nearest ? asPoint(nearest) : null;
      },
      onSelection: select, onTooltip: (tooltip) => view.update({ tooltip }),
      customOverlay: { class: MapOverlay },
    });
    document.getElementById("map-mode").textContent = "Embedding Atlas · 滚轮缩放、拖动平移、点击查看、Shift + 点击多选";
  } else {
    if (probe) probe.renderer = "canvas";
    view = compatibleMap(host, papers, select, probe, mapStyle);
    view.update({});
    document.getElementById("map-mode").textContent = "Canvas 兼容视图 · 滚轮缩放、拖动平移、点击查看、Shift + 点击多选";
  }
  host.append(surfaceLayer);
  const search = document.getElementById("search"), year = document.getElementById("year"), decision = document.getElementById("decision");
  function filter() {
    const query = search.value.trim().toLowerCase();
    visible = papers.filter((p) => (!analysisIds || analysisIds.has(p.paper_id)) && (!year.value || String(p.year) === year.value) &&
      (!decision.value || p.decision === decision.value) && (!mapDomain.value || p.domain === mapDomain.value) &&
      (!query || `${p.title} ${p.paper_id} ${p.forum_id}`.toLowerCase().includes(query)));
    updateMapContext();
    select([]);
    view.update({ ...(probe?.renderer === "canvas" || !adapter?.features.has("shader-f16") ? { papers: visible } : { data: dataFor(visible), categoryColors: mapStyle.colors() }) });
    atlasOverlay?.redraw();
    document.getElementById("filter-count").textContent = `地图显示 ${visible.length.toLocaleString()} / ${papers.length.toLocaleString()} 篇；下方列出前 20 篇，可用键盘选择。`;
    const results = document.getElementById("results"); results.replaceChildren();
    for (const paper of visible.slice(0, 20)) {
      const button = document.createElement("button"); button.type = "button";
      button.textContent = `${paper.year} · ${paper.title}`; button.dataset.paperId = paper.paper_id;
      button.addEventListener("click", () => select([asPoint(paper)])); results.append(button);
    }
    if (probe) probe.visibleIds = visible.map((p) => p.paper_id);
  }
  let timer;
  search.addEventListener("input", () => { clearTimeout(timer); timer = setTimeout(filter, 180); });
  boundaryToggle.addEventListener("change", filter);
  surfaceToggle.addEventListener("change", filter); surfaceScale.addEventListener("change", filter);
  colorMode.addEventListener("change", filter); mapDomain.addEventListener("change", filter); labelToggle.addEventListener("change", filter);
  year.addEventListener("change", filter); decision.addEventListener("change", filter);
  const zoomBy = (factor) => {
    if (atlasViewport && adapter?.features.has("shader-f16")) {
      const state = { ...atlasViewport,scale:atlasBaseScale * Math.max(0.5, Math.min(80, atlasZoom * factor)) };
      updateAtlasZoom(state); view.update({ viewportState:state });
    } else view.zoomBy(factor);
  };
  document.getElementById("zoom-in").addEventListener("click", () => zoomBy(1.6));
  document.getElementById("zoom-out").addEventListener("click", () => zoomBy(1/1.6));
  document.getElementById("reset-map").addEventListener("click", () => { if (initialAtlasViewport) updateAtlasZoom(initialAtlasViewport); view.update({ viewportState:initialAtlasViewport ? { ...initialAtlasViewport } : null }); });
  window.addEventListener("iclr-analysis-filter", (event) => {
    analysisIds = new Set(event.detail.paperIds);
    search.value = ""; mapDomain.value = ""; year.value = event.detail.year ?? ""; decision.value = "";
    document.getElementById("domain-active").textContent = event.detail.label;
    document.getElementById("clear-domain").hidden = false;
    filter();
    if (event.detail.selectPaper) select([asPoint(byId.get(event.detail.selectPaper))]);
  });
  document.getElementById("clear-domain").addEventListener("click", () => {
    analysisIds = null;
    document.getElementById("domain-active").textContent = "";
    document.getElementById("clear-domain").hidden = true;
    filter();
  });
  filter();
  const linkedPaper = byId.get(new URLSearchParams(location.search).get("paper"));
  if (linkedPaper) select([asPoint(linkedPaper)]);
  import("./analysis.js").then(({ mountAnalysis }) => mountAnalysis(papers, meta)).catch((error) => {
    document.getElementById("analysis-status").textContent = `领域分析加载失败：${error.message}`;
    console.error(error);
  });
  new ResizeObserver(() => view.update({ width: host.clientWidth })).observe(host);
}

main().catch((error) => { document.getElementById("fatal").textContent = error.message; console.error(error); });
