import { chord, ribbon } from "d3-chord";
import { arc } from "d3-shape";
import { paperScore, renderPaperDistributions } from './review-distributions.js';

const ns = "http://www.w3.org/2000/svg";
function svg(tag, attrs = {}, text) {
  const element = document.createElementNS(ns, tag);
  for (const [key, value] of Object.entries(attrs)) element.setAttribute(key, value);
  if (text !== undefined) element.textContent = text;
  return element;
}
function buttonAction(element, action) {
  element.setAttribute("tabindex", "0"); element.setAttribute("role", "button");
  element.addEventListener("click", action);
  element.addEventListener("keydown", (event) => {
    if (event.key === "Enter" || event.key === " ") { event.preventDefault(); action(); }
  });
}
const fmt = (n) => n.toLocaleString();
const percent = (a, n) => n ? `${(100 * a / n).toFixed(1)}%` : "无可用分母";
const truncate = (s, n = 42) => s.length > n ? s.slice(0, n - 1) + "…" : s;

export async function mountAnalysis(papers, meta) {
  const [response, topicResponse] = await Promise.all(["domains", "topics"].map((name) => fetch(`/generated/${name}.json`, { cache: "no-cache" })));
  if (!response.ok) throw new Error("领域数据暂不可用，请稍后刷新");
  const data = await response.json();
  if (!topicResponse.ok) throw new Error("请运行 python3 web/derive_topics.py");
  const topics = await topicResponse.json();
  if (topics.meta.source_data_version !== meta.data_version) throw new Error("主题归并数据快照不一致");
  if (data.meta.source_data_version !== meta.data_version) throw new Error("领域数据与地图快照不一致，请重新导出");
  const byId = new Map(papers.map((p) => [p.paper_id, p]));
  const records = data.papers.map((p) => ({ ...byId.get(p.paper_id), ...p, score: paperScore(p.ratings), entities: [...new Set(p.entities.map((id) => topics.entity_to_concept[id]))] }));
  const domains = data.domains, domainById = new Map(domains.map((d) => [d.id, d]));
  const keywords = topics.concepts;
  const typeLabels = { METHOD: "方法", TASK: "任务", RESEARCH_OBJECT: "研究对象", DATASET: "数据集", METRIC: "指标", OTHER_SCIENTIFIC_TERM: "其他科学术语" };
  const entityType = document.getElementById("entity-type"), chordLimit = document.getElementById("chord-limit");
  const probe = new URLSearchParams(location.search).has("smoke") ? {} : null;
  if (probe) window.__analysisProbe = probe;
  const includeGeneric = document.getElementById("include-generic");
  const year = document.getElementById("analysis-year"), domain = document.getElementById("analysis-domain");
  const topicSearch = document.getElementById("topic-search"), population = document.getElementById("score-status");
  for (const d of domains) {
    const option = document.createElement("option"); option.value = d.id; option.textContent = d.label;
    option.title = d.raw_labels.join(" / "); domain.append(option);
  }
  document.getElementById("analysis-status").textContent =
    `${fmt(records.length)} 篇论文 · ${domains.length} 个投稿领域 · ${fmt(data.entities.length)} 个原始标签 → ${fmt(keywords.length)} 个归并概念 · 与地图使用同一快照`;
  let keyword = null, pair = null, selected = records;
  const color = (index) => `hsl(${index * 137.508 % 360} 55% 45%)`;
  function stats(rows) {
    const result = { papers: rows.length, accepted: 0, rejected: 0, desk_rejected: 0, withdrawn: 0, unknown: 0, reviews: 0, valid: 0 };
    for (const p of rows) { result[p.decision]++; result.reviews += p.review_count; result.valid += p.ratings.length; }
    return result;
  }
  function titleForSelection() {
    return [year.value ? `ICLR ${year.value}` : "全部年份", domain.value ? domainById.get(domain.value).label : "全部投稿领域", pair ? pair.map((id) => keywords[id].label).join(" ↔ ") : "",
      keyword !== null ? `主题标签：${keywords[keyword].label}` : ""].filter(Boolean).join(" · ");
  }
  function showOnMap(rows = selected, label = titleForSelection(), selectPaper) {
    window.dispatchEvent(new CustomEvent("iclr-analysis-filter", { detail: {
      paperIds: rows.map((p) => p.paper_id), label, year: selectPaper ? String(rows[0].year) : year.value, selectPaper,
    } }));
  }
  const typeName = (item) => item.types.map((t) => typeLabels[t] ?? t).join(" / ");
  const aliasText = (item) => `原始词形：${item.aliases.join("；")}\n来源类型：${typeName(item)}\n原始标签 ID：${item.raw_entity_ids.join(", ")}`;
  const eligible = (id) => (!entityType.value || keywords[id].types.includes(entityType.value)) && (includeGeneric.checked || !keywords[id].generic);
  function keywordCounts(rows) {
    const counts = new Map();
    for (const p of rows) for (const id of p.entities) counts.set(id, (counts.get(id) ?? 0) + 1);
    return counts;
  }
  function renderTable(yearRows) {
    const body = document.querySelector("#domain-table tbody"); body.replaceChildren();
    for (const d of domains) {
      const s = stats(yearRows.filter((p) => p.domain === d.id));
      const row = document.createElement("tr"), cell = document.createElement("td"), button = document.createElement("button");
      button.textContent = d.label; button.title = d.raw_labels.join(" / "); button.dataset.domain = d.id;
      button.addEventListener("click", () => { domain.value = d.id; keyword = pair = null; render(); showOnMap(); });
      cell.append(button); row.append(cell);
      for (const value of [fmt(s.papers), `${percent(s.accepted, s.papers)} (${s.accepted}/${s.papers})`, s.accepted, s.rejected, s.desk_rejected, s.withdrawn, s.unknown]) {
        const td = document.createElement("td"); td.textContent = value; row.append(td);
      }
      body.append(row);
    }
  }
  function renderTopics(yearRows) {
    const parentRows = yearRows.filter((p) => !domain.value || p.domain === domain.value);
    const query = topicSearch.value.trim().toLowerCase();
    let items;
    const showDomains = !domain.value && !pair && keyword === null && !entityType.value && !query;
    if (showDomains) {
      items = domains.map((d) => ({ id: d.id, label: d.label, rows: yearRows.filter((p) => p.domain === d.id), isDomain: true }));
    } else {
      const rows = pair ? selected : parentRows;
      items = [...keywordCounts(rows)].filter(([id]) => eligible(id))
        .map(([id, count]) => ({ id, label: `${keywords[id].label} [${typeName(keywords[id])}]`, count }));
    }
    items = items.filter((item) => `${item.label} ${item.isDomain ? "" : keywords[item.id].aliases.join(" ")}`.toLowerCase().includes(query));
    items.sort((a, b) => (b.rows?.length ?? b.count) - (a.rows?.length ?? a.count) || a.label.localeCompare(b.label));
    const total = items.length; items = items.slice(0, 16);
    const root = svg("svg", { viewBox: `0 0 1000 ${Math.max(200, items.length * 34 + 60)}`, role: "group", "aria-label": "投稿领域与 实体标签关系" });
    const height = Math.max(200, items.length * 34 + 60), middle = height / 2;
    root.append(svg("rect", { x: 5, y: middle - 44, width: 205, height: 88, rx: 8, fill: "#eef5fc", stroke: "#bdd0e6" }));
    const label = pair ? "共现标签论文" : domain.value ? domainById.get(domain.value).label : "全部已处理论文";
    for (const [index, line] of (label.length > 12 ? [label.slice(0, 12), label.slice(12)] : [label]).entries())
      root.append(svg("text", { x: 18, y: middle - 12 + index * 20, "font-size": 15 }, line));
    root.append(svg("text", { x: 18, y: middle + 30, "font-size": 13, fill: "#526078" }, `${fmt((pair ? selected : parentRows).length)} 篇`));
    const maxCount = Math.max(1, ...items.map((item) => item.rows?.length ?? item.count));
    for (const [index, item] of items.entries()) {
      const rows = item.rows ?? (pair ? selected : parentRows).filter((p) => p.entities.includes(item.id));
      const s = stats(rows), y = 28 + index * 34;
      root.append(svg("path", { d: `M210,${middle} C230,${middle} 225,${y} 250,${y}`, fill: "none", stroke: "#cbd5e1" }));
      const group = svg("g", { "data-topic": item.id, "aria-label": `${item.label}，${s.papers} 篇，中稿率 ${percent(s.accepted, s.papers)}` });
      group.append(svg("rect", { x: 248, y: y - 17, width: 744, height: 30, rx: 4, fill: keyword === item.id ? "#dbeafe" : "#f5f7fa" }));
      group.append(svg("text", { x: 258, y: y + 4, "font-size": 14 }, truncate(item.label)));
      group.append(svg("rect", { x: 650, y: y - 7, width: 140 * s.papers / maxCount, height: 12, fill: "#9aadc4" }));
      group.append(svg("text", { x: 805, y: y + 4, "font-size": 12 }, `${fmt(s.papers)} 篇 · 中稿 ${percent(s.accepted, s.papers)}`));
      group.append(svg("title", {}, `${item.label}\n${s.accepted} 录用 / ${s.rejected} 拒稿 / ${s.withdrawn} 撤稿 / ${s.unknown} 未知${item.isDomain ? "\n" + domainById.get(item.id).raw_labels.join(" / ") : "\n" + aliasText(keywords[item.id])}`));
      buttonAction(group, () => {
        if (item.isDomain) { domain.value = item.id; keyword = pair = null; }
        else keyword = keyword === item.id ? null : item.id;
        render(); showOnMap();
      }); root.append(group);
    }
    document.getElementById("topic-tree").replaceChildren(root);
    document.getElementById("topic-coverage").textContent =
      `${showDomains ? "投稿领域" : "实体标签"}显示前 ${items.length} / ${total} 项（按论文数排序）。${showDomains ? "点击领域查看其 实体标签。" : "可搜索简称或全称；同义概念合并计数，来源类型保留。"}`;
  }
  function renderScores() {
    const rows = selected.filter((p) => !population.value || (population.value === 'compare' ? ['accepted', 'rejected'].includes(p.decision) : p.decision === population.value));
    const years = [2024, 2025, 2026].filter((y) => !year.value || String(y) === year.value);
    const disagreement = document.getElementById('score-disagreement').value;
    const summaries = renderPaperDistributions(document.getElementById('domain-scores'), rows, years, population.value, disagreement);
    const coverage = years.map((y) => {
      const group = rows.filter((p) => p.year === y), ratings = group.flatMap((p) => p.ratings);
      const counts = Array.from({ length: 10 }, (_, i) => ratings.filter((r) => r === i + 1).length);
      const missing = group.reduce((n, p) => n + p.review_count - p.ratings.length, 0);
      return { year: y, valid: ratings.length, missing, counts, papers: group.length,
        rated: group.filter((p) => p.score.n >= 1).length, disagreement: group.filter((p) => p.score.n >= 2).length };
    });
    document.getElementById("score-facts").textContent = `${titleForSelection()} · ${population.selectedOptions[0].textContent}：` +
      coverage.map((c) => `${c.year} 共 ${fmt(c.papers)} 篇，均分可用 ${fmt(c.rated)} 篇、分歧可用 ${fmt(c.disagreement)} 篇；有效评分 ${fmt(c.valid)}、缺失评分 ${fmt(c.missing)}`).join("；");
    const candidates = rows.filter((p) => p.score.n >= 2).sort((a, b) => b.score[disagreement] - a.score[disagreement] || b.score.n - a.score.n || a.paper_id.localeCompare(b.paper_id));
    const list = document.getElementById('score-papers'); list.replaceChildren();
    for (const p of candidates.slice(0, 10)) {
      const item = document.createElement('li'), button = document.createElement('button');
      button.type = 'button'; button.dataset.paperId = p.paper_id;
      button.textContent = `${p.year} · ${truncate(p.title, 74)}`;
      button.addEventListener('click', () => { evidencePaper.value = p.paper_id; loadEvidence(); showOnMap([p], `审稿分歧 · ${p.title}`, p.paper_id); });
      const detail = document.createElement('span'); detail.className = 'muted';
      detail.textContent = `评分 [${[...p.ratings].sort((a,b) => a-b).join('、')}] · n=${p.score.n} · 均分 ${p.score.mean.toFixed(2)} · 标准差 ${p.score.sd.toFixed(2)} · 极差 ${p.score.range.toFixed(2)}`;
      item.append(button, detail); list.append(item);
    }
    if (!candidates.length) { const item = document.createElement('li'); item.textContent = '当前集合没有至少两条有效评分的论文。'; list.append(item); }
    if (probe) { probe.scoreCoverage = coverage; probe.scoreDistributions = summaries; probe.scoreMetric = disagreement; probe.scorePaperIds = candidates.slice(0, 10).map((p) => p.paper_id); }
  }
  function renderChord(rows) {
    const counts = keywordCounts(rows);
    const all = [...counts].filter(([id]) => eligible(id))
      .sort((a, b) => b[1] - a[1] || a[0] - b[0]);
    const ids = all.slice(0, Number(chordLimit.value)).map(([id]) => id);
    for (const id of [...(pair ?? []), ...(keyword !== null ? [keyword] : [])]) if (!ids.includes(id)) ids.push(id);
    const indices = new Map(ids.map((id, index) => [id, index]));
    const matrix = ids.map(() => ids.map(() => 0));
    for (const p of rows) {
      const memberships = p.entities.filter((id) => indices.has(id)).map((id) => indices.get(id));
      for (let i = 0; i < memberships.length; i++) for (let j = i + 1; j < memberships.length; j++) {
        matrix[memberships[i]][memberships[j]]++; matrix[memberships[j]][memberships[i]]++;
      }
    }
    const layout = chord().padAngle(0.035).sortSubgroups((a, b) => b - a)(matrix);
    const measure = document.createElement("canvas").getContext("2d"); measure.font = "14px system-ui, sans-serif";
    function wrapLabel(text) {
      const lines = []; let line = "";
      for (const char of text) {
        if (line && measure.measureText(line + char).width > 236) { lines.push(line.trim()); line = ""; }
        line += char;
      }
      if (line) lines.push(line.trim());
      return lines;
    }
    const labels = layout.groups.filter((g) => g.value).map((g) => {
      const angle = (g.startAngle + g.endAngle) / 2, lines = wrapLabel(keywords[ids[g.index]].label);
      return { group: g, angle, side: Math.sin(angle) < 0 ? -1 : 1, lines, height: lines.length * 17,
        desired: -Math.cos(angle) * 330 };
    });
    const sides = [-1, 1].map((side) => labels.filter((l) => l.side === side).sort((a, b) => a.desired - b.desired));
    const halfHeight = Math.max(390, ...sides.map((side) => side.reduce((n, l) => n + l.height + 9, 0) / 2 + 35));
    for (const side of sides) {
      let bottom = -halfHeight + 25;
      for (const label of side) { label.top = Math.max(label.desired - label.height / 2, bottom); bottom = label.top + label.height + 9; }
      let top = halfHeight - 25;
      for (const label of [...side].reverse()) { label.top = Math.min(label.top, top - label.height); top = label.top - 9; }
    }
    const root = svg("svg", { viewBox: `-620 ${-halfHeight} 1240 ${halfHeight * 2}`, role: "group", "aria-label": "实体标签论文共现弦图" });
    const ribbonPath = ribbon().radius(285), arcPath = arc().innerRadius(290).outerRadius(310);
    for (const edge of layout) {
      const i = edge.source.index, j = edge.target.index, left = keywords[ids[i]], right = keywords[ids[j]];
      const path = svg("path", { d: ribbonPath(edge), fill: color(i), class: "ribbon", "data-pair": `${ids[i]}:${ids[j]}`,
        "data-count": edge.source.value, "aria-label": `${left.label} 与 ${right.label}：${edge.source.value} 篇共现论文` });
      path.append(svg("title", {}, `${left.label} [${typeName(left)}] ↔ ${right.label} [${typeName(right)}]\n${edge.source.value} 篇论文同时含两标签，每篇仅计一次`));
      buttonAction(path, () => { pair = [ids[i], ids[j]]; keyword = null; render(); showOnMap(); }); root.append(path);
    }
    for (const label of labels) {
      const { group, angle, side, lines, height, top } = label;
      const id = ids[group.index], item = keywords[id], y = top + height / 2;
      const g = svg("g", { class: "arc", "data-entity": id, "aria-label": item.label });
      g.append(svg("path", { d: arcPath(group), fill: color(group.index) }));
      g.append(svg("polyline", { class: "chord-label-leader", points: `${Math.sin(angle) * 312},${-Math.cos(angle) * 312} ${side * 328},${-Math.cos(angle) * 312} ${side * 350},${y}`,
        fill: "none", stroke: color(group.index), "stroke-width": 1, "pointer-events": "none" }));
      const text = svg("text", { class: "chord-topic-label", x: side * 360, y: top + 13,
        "text-anchor": side < 0 ? "end" : "start", "font-size": 14 });
      for (const [i, line] of lines.entries()) text.append(svg("tspan", { x: side * 360, dy: i ? 17 : 0 }, line));
      g.append(text);
      g.append(svg("title", {}, `${item.label} [${typeName(item)}]\n${aliasText(item)}\n${fmt(counts.get(id) ?? 0)} 篇论文；圆弧是与展示标签的共现权重之和 ${fmt(group.value)}`));
      buttonAction(g, () => { keyword = id; pair = null; render(); showOnMap(); }); root.append(g);
    }
    if (!layout.length) root.append(svg("text", { x: 0, y: 0, "text-anchor": "middle", "font-size": 20 }, "当前范围没有可展示的标签共现"));
    document.getElementById("domain-chord").replaceChildren(root);
    const labelList = document.getElementById("chord-labels"); labelList.replaceChildren();
    for (const id of ids) {
      const item = keywords[id], button = document.createElement("button");
      button.textContent = `${item.label} [${typeName(item)}] · ${fmt(counts.get(id) ?? 0)} 篇`;
      button.title = aliasText(item);
      button.addEventListener("click", () => { keyword = id; pair = null; render(); showOnMap(); }); labelList.append(button);
    }
    const aliases = document.getElementById("concept-aliases"); aliases.replaceChildren();
    for (const id of ids) {
      const item = keywords[id], row = document.createElement("p"), strong = document.createElement("strong");
      strong.textContent = item.label + "："; row.append(strong, aliasText(item)); aliases.append(row);
    }
    document.getElementById("chord-facts").textContent = `${year.value || "全部年份"} · ${domain.value ? domainById.get(domain.value).label : "全部投稿领域"} · ${fmt(rows.length)} 篇 · 按论文覆盖数展示前 ${chordLimit.value} 个标签（额外保留选中标签），当前 ${ids.length} 个 / ${fmt(all.length)} 个可用标签、${layout.length} 对共现关系（无共现的标签仅列在下方）。${pair ? "当前：" + titleForSelection() : "点击弦带查看共同论文。"}`;
    if (probe) { probe.chordMatrix = matrix; probe.chordEntityIds = ids; probe.chordEdges = layout.length; }
  }
  function render() {
    const yearRows = records.filter((p) => !year.value || String(p.year) === year.value);
    const baseRows = yearRows.filter((p) => !domain.value || p.domain === domain.value);
    renderChord(baseRows);
    selected = baseRows.filter((p) => (!pair || pair.every((id) => p.entities.includes(id))) &&
      (keyword === null || p.entities.includes(keyword)));
    const s = stats(selected);
    document.getElementById("domain-facts").textContent = `${titleForSelection()}：${fmt(s.papers)} 篇；录用 ${fmt(s.accepted)}、拒稿 ${fmt(s.rejected)}、直接拒稿 ${fmt(s.desk_rejected)}、撤稿 ${fmt(s.withdrawn)}、未知 ${fmt(s.unknown)}。中稿率 ${percent(s.accepted, s.papers)}（${s.accepted}/${s.papers}）。`;
    renderTable(yearRows); renderTopics(yearRows); renderScores();
    const evidence = document.getElementById("chord-evidence"); evidence.replaceChildren();
    if (pair || keyword !== null) {
      const heading = document.createElement("p"); heading.style.width = "100%";
      heading.textContent = `匹配 ${fmt(selected.length)} 篇论文；下列前 20 篇可直接查看 原文证据。`;
      evidence.append(heading);
      for (const p of selected.slice(0, 20)) {
        const button = document.createElement("button"); button.textContent = `${p.year} · ${truncate(p.title, 65)}`;
        button.dataset.paperId = p.paper_id;
        button.addEventListener("click", () => { evidencePaper.value = p.paper_id; loadEvidence(); showOnMap([p], `主题标签证据 · ${p.title}`, p.paper_id); });
        evidence.append(button);
      }
    }
    if (probe) {
      probe.ready = true; probe.selectedPaperIds = selected.map((p) => p.paper_id); probe.summary = s;
      probe.year = year.value; probe.selectedDomain = domain.value; probe.keyword = keyword; probe.pair = pair;
    }
  }
  year.addEventListener("change", () => { keyword = pair = null; render(); });
  domain.addEventListener("change", () => { keyword = pair = null; render(); });
  entityType.addEventListener("change", () => { keyword = pair = null; render(); });
  includeGeneric.addEventListener("change", () => { keyword = pair = null; render(); });
  chordLimit.addEventListener("change", render);
  population.addEventListener("change", renderScores);
  document.getElementById('score-disagreement').addEventListener('change', renderScores);
  let timer; topicSearch.addEventListener("input", () => { clearTimeout(timer); timer = setTimeout(() => renderTopics(records.filter((p) => !year.value || String(p.year) === year.value)), 150); });
  document.getElementById("clear-topic").addEventListener("click", () => { keyword = pair = null; topicSearch.value = ""; render(); });
  document.getElementById("show-analysis-map").addEventListener("click", () => showOnMap());

  const evidencePaper = document.getElementById("tree-paper"), evidenceSearch = document.getElementById("evidence-search");
  const evidenceOptions = records.map((p) => {
    const option = document.createElement("option"); option.value = p.paper_id; option.textContent = `${p.year} · ${p.title}`; return option;
  });
  // Native select supports all 12,964 papers; text search narrows the list without excluding data.
  function filterEvidenceOptions() {
    const query = evidenceSearch.value.trim().toLowerCase(), old = evidencePaper.value;
    const candidates = evidenceOptions.filter((option) => !query || `${option.textContent} ${option.value}`.toLowerCase().includes(query));
    evidencePaper.replaceChildren(...candidates);
    if (candidates.some((o) => o.value === old)) evidencePaper.value = old;
    document.getElementById("candidate-status").textContent = `收录 ${fmt(records.length)} 篇论文，当前匹配 ${fmt(candidates.length)} 篇；可查看实体类型、角色、重要性及原文位置。`;
    loadEvidence();
  }
  let serial = 0;
  const evidenceCache = new Map();
  async function loadEvidence() {
    const request = ++serial, id = evidencePaper.value, host = document.getElementById("candidate-tree");
    if (!id) { host.textContent = "没有匹配的 论文。"; return; }
    host.textContent = "正在加载 原文证据…";
    try {
      if (!evidenceCache.has(id)) evidenceCache.set(id, fetch(`/generated/${data.evidence_base}/${id}.json`).then((r) => {
        if (!r.ok) throw new Error("原文证据加载失败"); return r.json();
      }).catch((error) => { evidenceCache.delete(id); throw error; }));
      const source = await evidenceCache.get(id);
      if (request !== serial) return;
      const p = byId.get(id);
      document.getElementById("tree-paper-facts").textContent = `${p.title} · ICLR ${p.year} · ${p.decision_raw ?? "决定未知"} · ${p.rating_count} 条有效评分 · 均分 ${p.mean_rating?.toFixed(2) ?? "缺失"}`;
      host.replaceChildren();
      for (const [name, value] of [["研究问题", source.core.research_problem], ["方法", source.core.method], ["研究对象", source.core.research_object]]) {
        const paragraph = document.createElement("p"); paragraph.textContent = `${name}（模型提取）：${value.text}`; host.append(paragraph);
      }
      const eligible = source.entity_candidates.filter((c) => c.literal_span_valid && c.salience === "core");
      const ul = document.createElement("ul");
      for (const candidate of eligible) {
        const li = document.createElement("li"), disclosure = document.createElement("details"), summary = document.createElement("summary");
        disclosure.dataset.candidateId = candidate.candidate_id;
        summary.textContent = `${candidate.mention_text} [${typeLabels[candidate.entity_type] ?? candidate.entity_type}] · ${candidate.paper_role}`;
        disclosure.append(summary);
        const block = document.createElement("blockquote");
        block.textContent = `${candidate.candidate_id} · ${candidate.span_id} · core · 原文可定位\n${candidate.source_span_text}`;
        const locations = document.createElement("p"); locations.textContent = candidate.source_occurrences.map((o) => `${o.field} [${o.start}, ${o.end})`).join("；");
        disclosure.append(block, locations); li.append(disclosure); ul.append(li);
      }
      const explanation = document.createElement("p"); explanation.textContent = `展示 ${eligible.length} 条原文可定位的 core 实体记录；统计时先归并同义词，再对同论文同概念去重；本区展示原始实体。原始候选总数 ${source.entity_candidates.length}。`;
      host.append(explanation, ul);
      if (probe) probe.evidence = { paperId:id, candidates:eligible.length, sourceCandidates:source.entity_candidates.length, loaded:true };
    } catch (error) { if (request === serial) host.textContent = error.message; }
  }
  evidencePaper.addEventListener("change", loadEvidence);
  let evidenceTimer;
  evidenceSearch.addEventListener("input", () => { clearTimeout(evidenceTimer); evidenceTimer = setTimeout(filterEvidenceOptions, 180); });
  document.getElementById("tree-map").addEventListener("click", () => {
    const p = byId.get(evidencePaper.value); if (p) showOnMap([p], `论文 · ${p.title}`, p.paper_id);
  });
  render(); filterEvidenceOptions();
}
