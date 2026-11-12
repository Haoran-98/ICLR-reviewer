import { rankModules } from './review-match.js';
import { readManuscriptFile } from './manuscript-upload.js';

const LEVELS = { general: '通用', domain: '领域', method: '方法', task: '任务', specialty: '专属' };
const FAMILIES = { claim_scope: '主张边界', guarantee_transfer: '保证传递', definition_inference: '定义与推导', evidence_design: '证据设计', robustness_boundary: '鲁棒性边界', comparative_attribution: '比较与归因', feasibility: '可实施性', other: '其他' };
const STATES = { source_supported: '来源支持', candidate: '候选', applied: '已应用', not_applicable: '不适用', insufficient_evidence: '材料不足', needs_verification: '待核验', supported: '有证据', major: '主要', minor: '次要' };
const AREAS = { foundation_or_frontier_models_including_llms: '基础模型与大语言模型', reinforcement_learning: '强化学习', learning_theory: '学习理论', generative_models: '生成模型', alignment_fairness_safety_privacy: '对齐、公平、安全与隐私' };
const $ = id => document.getElementById(id);
const el = (tag, text, cls) => { const n = document.createElement(tag); if (text != null) n.textContent = text; if (cls) n.className = cls; return n; };
const label = value => STATES[value] ?? value;
const fmt = n => n.toLocaleString('en-US');
let data, page = 0, detailSerial = 0, replaySerial = 0, matchSerial = 0;
const cache = new Map();
const moduleLabel = m => `${LEVELS[m.level]} · ${m.level === 'domain' ? '基础模型与大语言模型' : m.level === 'general' ? '通用检查' : m.scopes.slice(0, 2).join(' / ')} · ${FAMILIES[m.family] ?? m.family}`;
async function json(name) {
  if (!cache.has(name)) cache.set(name, fetch(`/generated/reviewers/${name}`).then(r => {
    if (!r.ok) throw new Error(`数据加载失败：${r.status}`); return r.json();
  }).catch(e => { cache.delete(name); throw e; }));
  return cache.get(name);
}
async function rule(rid) { return (await json(data.rule_shards[rid]))[rid]; }
function fail(error) { $('error').textContent = error.message; }
function action(text, callback) { const n = el('button', text); n.type = 'button'; n.onclick = () => Promise.resolve().then(callback).catch(fail); return n; }
function tag(state) { return el('span', label(state), `tag ${state === 'candidate' ? 'candidate' : ''}`); }
function fields(parent, pairs) {
  const dl = el('dl');
  for (const [name, value] of pairs) if (value != null && value !== '') { dl.append(el('dt', name), el('dd', Array.isArray(value) ? value.join('；') : String(value))); }
  parent.append(dl);
}
function sourceLinks(parent, ids) {
  const links = el('div', null, 'source-links');
  for (const pid of ids) {
    const a = el('a', `论文 ${pid}`); a.href = `/?paper=${encodeURIComponent(pid)}`; a.target = '_blank'; a.rel = 'noopener'; links.append(a);
  }
  parent.append(links);
}
function renderRule(r, open = false) {
  const box = el('details'); box.open = open; box.dataset.ruleId = r.rule_id;
  box.append(el('summary', `${r.rule_id} · ${r.title}`), tag(r.status));
  fields(box, [['审查对象', r.review_object], ['适用条件', r.applies_when], ['潜在失效机制', r.failure_mechanism],
    ['核查步骤', r.steps], ['问题成立条件', r.issue_when], ['如何消除 concern', r.cleared_when], ['影响', r.significance], ['例外', r.exceptions]]);
  box.append(el('p', `独立来源论文：${r.source_paper_ids.length}；原始候选：${r.candidate_ids.join('、')}`, 'muted'));
  sourceLinks(box, r.source_paper_ids);
  return box;
}
function tab(name) {
  for (const key of ['library', 'match', 'replay']) $('tab-' + key).hidden = key !== name;
  for (const b of document.querySelectorAll('[data-tab]')) b.setAttribute('aria-pressed', String(b.dataset.tab === name));
}
function filters() {
  const search = $('expert-search').value.toLowerCase().trim();
  return data.modules.filter(m => (!$('expert-status').value || m.status === $('expert-status').value) &&
    (!$('expert-level').value || m.level === $('expert-level').value) && (!$('expert-family').value || m.family === $('expert-family').value) &&
    (!search || `${m.id} ${m.title} ${m.scopes.join(' ')} ${LEVELS[m.level]} ${FAMILIES[m.family]}`.toLowerCase().includes(search)));
}
function overview() {
  const ns = 'http://www.w3.org/2000/svg';
  const svg = document.createElementNS(ns, 'svg'); svg.setAttribute('viewBox', '0 0 1120 310'); svg.setAttribute('aria-label', 'LLM 领域专家模块的层级与审查机制数量矩阵');
  const families = Object.keys(FAMILIES), levels = Object.keys(LEVELS);
  const state = $('expert-status').value;
  const counts = new Map();
  for (const m of data.modules) if (!state || m.status === state) { const k = `${m.level}/${m.family}`; counts.set(k, (counts.get(k) ?? 0) + 1); }
  function text(x, y, value, size = 14) { const n = document.createElementNS(ns, 'text'); n.setAttribute('x', x); n.setAttribute('y', y); n.setAttribute('font-size', size); n.textContent = value; svg.append(n); }
  text(14, 30, `LLM 领域库 · ${state ? label(state) : '全部有效'}`, 16);
  families.forEach((f, j) => text(150 + j * 120, 65, FAMILIES[f]));
  levels.forEach((l, i) => {
    text(18, 106 + i * 44, `${LEVELS[l]}模块`);
    families.forEach((f, j) => {
      const count = counts.get(`${l}/${f}`) ?? 0;
      const g = document.createElementNS(ns, 'g'); g.setAttribute('role', 'button'); g.setAttribute('tabindex', '0');
      g.setAttribute('aria-label', `${LEVELS[l]} ${FAMILIES[f]} ${count} 个模块`);
      const r = document.createElementNS(ns, 'rect');
      for (const [k, v] of Object.entries({ x: 140 + j * 120, y: 80 + i * 44, width: 112, height: 36, rx: 5, fill: count ? `hsl(214 60% ${94 - Math.min(48, Math.log2(count + 1) * 5)}%)` : '#f4f6f9' })) r.setAttribute(k, v);
      const t = document.createElementNS(ns, 'text'); t.setAttribute('x', 196 + j * 120); t.setAttribute('y', 104 + i * 44); t.setAttribute('text-anchor', 'middle'); t.setAttribute('fill', count > 200 ? 'white' : '#172b43'); t.textContent = fmt(count); g.append(r, t);
      const choose = () => { $('expert-level').value = l; $('expert-family').value = f; page = 0; renderList(); };
      g.onclick = choose; g.onkeydown = e => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); choose(); } }; svg.append(g);
    });
  });
  $('overview').replaceChildren(svg);
}
function renderList() {
  const found = filters(), total = Math.max(1, Math.ceil(found.length / 30)); page = Math.min(page, total - 1);
  $('expert-count').textContent = `匹配 ${fmt(found.length)} 个模块；每页 30 个。`; $('page-index').textContent = `${page + 1} / ${total}`;
  $('prev').disabled = page === 0; $('next').disabled = page >= total - 1;
  $('expert-list').replaceChildren(...found.slice(page * 30, (page + 1) * 30).map(m => {
    const b = action('', () => selectModule(m)); b.className = 'card'; b.dataset.moduleId = m.id;
    b.append(tag(m.status), el('strong', moduleLabel(m)), el('small', `${m.title} · ${m.rule_ids.length} 条检查 · ${m.source_count} 篇来源`)); return b;
  }));
}
async function selectModule(m) {
  const serial = ++detailSerial;
  $('expert-detail').replaceChildren(el('h2', moduleLabel(m)), el('p', '正在读取检查项…'));
  const checks = await Promise.all(m.rule_ids.map(rule)); if (serial !== detailSerial) return;
  $('expert-detail').replaceChildren(el('h2', moduleLabel(m)), tag(m.status), el('p', `模块 ID：${m.id}`, 'muted'),
    el('p', '下列是历史经验提炼的条件检查，需结合当前稿件判断是否成立。'), ...checks.map((r, i) => renderRule(r, i === 0)));
}
function stage(title, lines) { const n = el('div', null, 'stage'); n.append(el('h3', title), ...lines.map(s => el('p', s))); return n; }
async function match() {
  const serial = ++matchSerial;
  const title = $('paper-title').value, text = $('paper-text').value;
  if (!text.trim()) { $('match-status').textContent = '请先输入正文或摘要。'; return; }
  if ((title + text).length > 200000) { $('match-status').textContent = '本地预览最多处理 200,000 字符。请缩小到摘要与相关正文后再试，当前未截断或分析。'; return; }
  const manuscript = `${title}\n${text}`, area = $('paper-area').value;
  $('match-status').textContent = '正在匹配本地模块…'; await new Promise(r => setTimeout(r, 0));
  if (serial !== matchSerial) return;
  const ranked = rankModules(data.modules, manuscript, { area, candidates: $('match-candidates').checked });
  const chosen = ranked.slice(0, 6), selected = [];
  // Give every recommended module a visible check before adding a second one.
  for (let i = 0; i < 2; i++) for (const route of chosen) {
    if (route.module.rule_ids[i] && selected.length < 10) selected.push({ rid: route.module.rule_ids[i], route });
  }
  const checks = await Promise.all(selected.map(async x => ({ ...x, rule: await rule(x.rid) })));
  if (serial !== matchSerial) return;
  const hits = [...new Set(chosen.flatMap(x => x.hits.map(h => h.term)))];
  const declared = area === 'llm' ? '用户声明：基础模型与大语言模型' : area === 'other' ? '声明为其他领域；当前库未覆盖' : '领域尚未确认；以下仅为 LLM 库内匹配';
  $('match-pipeline').replaceChildren(
    stage('1 · 输入稿件', [title || '未填写标题', `${fmt(text.length)} 字符 · 浏览器本地处理`]),
    stage('2 · 领域与线索', [declared, hits.length ? `命中：${hits.slice(0, 8).join('、')}` : '未找到完整 scope 短语']),
    stage('3 · 推荐专家', [`${chosen.length} 个模块`, '按 scope 短语和词面 IDF 排序']),
    stage('4 · 检查关注点', [`${checks.length} 条待检查项`, '正式审稿时逐条判断适用性']),
    stage('5 · 审稿状态', ['未执行审稿', '实际 concern 与裁决请查看已有记录回放']));
  $('match-status').textContent = area === 'other' ? '当前版本仅覆盖 LLM 领域，不自动套用到其他领域。' : chosen.length ? `匹配预览完成：${chosen.length} 个模块，${checks.length} 条待检查项。` : '没有足够的词面依据推荐专家；可补充方法与任务描述。';
  $('match-results').replaceChildren();
  for (const x of checks) {
    const box = el('article', null, 'rule'); box.dataset.moduleId = x.route.module.id;
    box.append(el('h3', `${moduleLabel(x.route.module)} → ${x.rule.rule_id}`), tag(x.route.module.status));
    fields(box, [['加载理由', x.route.hits.length ? `命中完整 scope：${x.route.hits.map(h => h.term).join('、')}` : `命中多个 scope 词：${x.route.overlaps.join('、')}`], ['待检查', x.rule.title], ['适用条件', x.rule.applies_when], ['潜在 concern 的成立条件', x.rule.issue_when], ['所需消除证据', x.rule.cleared_when]]);
    for (const h of x.route.hits.slice(0, 2)) box.append(el('p', `输入线索位置：字符 ${h.start}—${h.end}（包含标题，零起点）`, 'muted'), el('blockquote', h.quote));
    box.append(action('在专家库查看完整规则', async () => { tab('library'); await selectModule(x.route.module); $('expert-detail').scrollIntoView({ behavior: 'smooth', block: 'start' }); }));
    $('match-results').append(box);
  }
}
async function replay(pid) {
  const serial = ++replaySerial; $('replay-detail').replaceChildren();
  if (!pid) { $('replay-status').textContent = ''; return; }
  $('replay-status').textContent = '正在读取真实运行记录…';
  const item = await json(`replay-${pid}.json`); if (serial !== replaySerial) return;
  const review = item.review, d = $('replay-detail');
  d.append(el('h2', item.title), el('p', `${item.year} · ${AREAS[item.area] ?? item.area} · 论文 ${item.paper_id}`),
    el('p', `历史规则库：${item.version} / ${item.library_hash.slice(0, 16)}…`, 'muted'),
    el('p', '本次以一次模型调用组合执行所选规则，以下展示该版本的原始 concern。', 'notice'));
  fields(d, [['审阅材料', `部分正文：${fmt(item.coverage.supplied_manuscript_chars)} / ${fmt(item.coverage.manuscript_chars)} 字符；图表及外部文献未核验`], ['论文概述', review.summary], ['当次评分与置信度', `${review.rating}；置信度 ${review.confidence}/5`], ['原记录局限', review.limitations]]);
  const pipeline = el('div', null, 'pipeline');
  const moduleIds = [...new Set(item.composition.selection.map(x => x.module_id))];
  const evidenceIds = new Set(review.concerns.flatMap(c => c.evidence_ids));
  pipeline.append(stage('1 · 真实稿件', [`论文 ${item.paper_id}`, '保留当次审阅材料范围']),
    stage('2 · 分析领域', [AREAS[item.area] ?? item.area, '来自当次输入记录']),
    stage('3 · 实际专家模块', [`${moduleIds.length} 个模块 / ${item.composition.rule_ids.length} 条规则`, moduleIds.join('、')]),
    stage('4 · 实际 concern', [`${review.concerns.length} 条`, '已应用／不适用／材料不足分别记录']),
    stage('5 · 稿件证据', [`${evidenceIds.size} 个被引用片段`, '展开下方 concern 核对原文位置']));
  d.append(pipeline);
  d.append(el('h3', `实际加载 ${item.composition.rule_ids.length} 条规则 → 产生 ${review.concerns.length} 条 concern`));
  const table = el('table'), head = el('thead'), hr = el('tr');
  for (const s of ['模块／规则', '加载理由', '实际检查结果']) hr.append(el('th', s)); head.append(hr); table.append(head); const body = el('tbody');
  for (const selected of item.composition.selection) {
    const r = item.rules[selected.rule_id], applied = review.rules_applied.find(x => x.rule_id === selected.rule_id), tr = el('tr');
    tr.dataset.ruleId = r.rule_id;
    tr.append(el('td', `${selected.module_id}\n${r.rule_id} · ${r.title}`), el('td', `原始路由分数 ${selected.score.toFixed(3)}；同领域 ${selected.same_area ? '是' : '否'}；词面命中 ${selected.scope_term_overlap.join('、') || '无'}`), el('td', `${label(applied?.disposition ?? '未记录')}：${applied?.reason ?? ''}`)); body.append(tr);
  }
  table.append(body); const scroll = el('div', null, 'table-scroll'); scroll.append(table); d.append(scroll);
  const loadedRules = el('details'); loadedRules.append(el('summary', '展开当次加载的完整规则（历史版本）'));
  loadedRules.append(...item.composition.rule_ids.map(rid => renderRule(item.rules[rid]))); d.append(loadedRules);
  if (!review.concerns.length) d.append(el('p', '本次审稿未提出 concern。可展开查看已执行的检查项。', 'notice'));
  for (const [i, c] of review.concerns.entries()) {
    const box = el('article', null, 'rule'); box.dataset.concernId = String(i + 1);
    box.append(el('h3', `C${i + 1} · ${c.check_id} · ${item.rules[c.check_id].title}`), el('p', `${label(c.severity)} / ${label(c.certainty)}`));
    fields(box, [['原始 concern', c.observation], ['影响', c.impact], ['建议核查／修改', c.requested_action], ['规则的消除条件', item.rules[c.check_id].cleared_when]]);
    for (const eid of c.evidence_ids) {
      const p = item.passages[eid], detail = el('details'); detail.className = 'evidence';
      detail.append(el('summary', `${eid} · ${p.section} · 字符 ${p.char_start}—${p.char_end}`), el('blockquote', p.text)); box.append(detail);
    }
    d.append(box);
  }
  const a = el('a', '打开 OpenReview 来源'); a.href = `https://openreview.net/forum?id=${encodeURIComponent(item.forum_id)}`; a.target = '_blank'; a.rel = 'noopener'; d.append(a);
  $('replay-status').textContent = `已回放真实记录：${item.composition.rule_ids.length} 条加载规则，${review.concerns.length} 条 concern。`;
}
async function init() {
  data = await json('index.json');
  $('load-status').textContent = `冻结版 ${data.version} · ${data.frozen_at.slice(0, 10)} · 库哈希 ${data.library_hash.slice(0, 16)}…`;
  for (const [number, text] of [[data.modules.length, '有效专家模块'], [data.module_statuses.source_supported, '来源支持模块'], [data.module_statuses.candidate, '候选模块'], [Object.keys(data.rule_shards).length, '有效检查规则']]) {
    const n = el('div', null, 'stat'); n.append(el('strong', fmt(number)), el('span', text)); $('stats').append(n);
  }
  for (const [id, dict] of [['expert-level', LEVELS], ['expert-family', FAMILIES]]) for (const [key, text] of Object.entries(dict)) { const o = el('option', text); o.value = key; $(id).append(o); }
  for (const m of data.replays) { const o = el('option', `${AREAS[m.area]} · ${m.title}`); o.value = m.paper_id; $('replay-select').append(o); }
  for (const b of document.querySelectorAll('[data-tab]')) b.onclick = () => tab(b.dataset.tab);
  for (const id of ['expert-search', 'expert-status', 'expert-level', 'expert-family']) $(id).addEventListener(id === 'expert-search' ? 'input' : 'change', () => { page = 0; renderList(); if (id === 'expert-status') overview(); });
  $('reset-library').onclick = () => { $('expert-search').value = ''; $('expert-status').value = 'source_supported'; $('expert-level').value = ''; $('expert-family').value = ''; page = 0; renderList(); overview(); };
  $('prev').onclick = () => { page--; renderList(); }; $('next').onclick = () => { page++; renderList(); };
  $('run-match').onclick = () => match().catch(fail);
  $('match-example').onclick = async () => {
    try { const item = await json('replay-32064.json'); $('paper-title').value = item.title; $('paper-text').value = item.abstract; $('paper-area').value = 'llm'; $('match-status').textContent = '已载入历史论文摘要，可预览其与当前 Skill 库的匹配结果。'; } catch (e) { fail(e); }
  };
  $('clear-match').onclick = () => { matchSerial++; $('paper-title').value = ''; $('paper-text').value = ''; $('paper-file').value = ''; $('paper-area').value = 'unknown'; $('match-pipeline').replaceChildren(); $('match-results').replaceChildren(); $('match-status').textContent = '已清除当前稿件。'; };
  $('paper-file').onchange = async () => {
    const file = $('paper-file').files[0]; if (!file) return;
    $('paper-text').value='';$('match-status').textContent='正在读取稿件…';
    $('paper-file').disabled=true;$('paper-text').disabled=true;$('run-match').disabled=true;
    try { const result=await readManuscriptFile(file);$('paper-text').value=result.text;
      $('match-status').textContent=result.converted?`已在本站服务器提取 ${file.name}；请检查文本完整性，图表与扫描文字需另行核对。`:`已在本地读取 ${file.name}；未上传。`;
    } catch (e) { $('match-status').textContent=e.message; }
    finally {$('paper-file').disabled=false;$('paper-text').disabled=false;$('run-match').disabled=false;}
  };
  $('replay-select').onchange = () => replay($('replay-select').value).catch(fail);
  overview(); renderList(); window.__reviewWorkbench = { version: data.version, modules: data.modules.length };
}
init().catch(fail);
