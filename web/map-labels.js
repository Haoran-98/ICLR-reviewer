const shortNames = { 'large language model':'LLM', 'multimodal large language model':'MLLM', 'vision-language model':'VLM', 'large vision-language model':'LVLM', 'graph neural network':'GNN', 'reinforcement learning':'强化学习', 'diffusion model':'扩散模型', 'time series':'时间序列' };
const decisions = { accepted:'录用', rejected:'拒稿', withdrawn:'撤稿', desk_rejected:'直接拒稿', unknown:'决定未知' };
export const pointRadius = (zoom) => Math.min(12, 2.3 * Math.max(0.5, zoom) ** 0.55);
export const paperInfo = (p) => `ICLR ${p.year} · ${decisions[p.decision] ?? p.decision} · 均分 ${p.mean_rating?.toFixed(2) ?? '缺失'}（${p.rating_count} 条评分）`;

export function drawMapLabels(layer, annotations, location, width, height, zoom, onSelect, probe) {
  const occupied = [], shown = [], paperIds = [];
  layer.replaceChildren();
  const level = zoom < 2.2 ? 'domain' : zoom < 5 ? 'topic' : 'paper';
  function place(item, title, subtitle, className, action) {
    const point = location(item.x, item.y), w = Math.min(className === 'map-paper-label' ? 255 : 195, width - 12), h = subtitle ? 48 : 27;
    if (point.x < 0 || point.x > width || point.y < 0 || point.y > height) return false;
    const x = Math.max(3, Math.min(width - w - 3, point.x + (action ? 9 : -w / 2)));
    const y = Math.max(3, Math.min(height - h - 3, point.y - h / 2));
    if (occupied.some((r) => x < r.x + r.w + 7 && x + w + 7 > r.x && y < r.y + r.h + 7 && y + h + 7 > r.y)) return false;
    occupied.push({ x, y, w, h });
    const label = document.createElement(action ? 'button' : 'div'); label.className = `map-region-label ${className}`;
    label.dataset.region = item.id; label.dataset.domain = item.domain;
    label.style.cssText = `left:${x}px;top:${y}px;width:${w}px;height:${h}px;border-left-color:${item.color ?? '#475569'}`;
    const heading = document.createElement('strong'); heading.textContent = title;
    label.append(heading);
    if (subtitle) { const text = document.createElement('span'); text.textContent = subtitle; label.append(text); }
    if (action) { label.type = 'button'; label.dataset.paperId = item.paper_id; label.title = `${title}\n${subtitle}`; label.addEventListener('click', action); }
    layer.append(label); return true;
  }
  // Each overview label is an original submission field, positioned inside its KDE territory.
  if (level === 'domain') for (const domain of [...annotations.domains].sort((a,b) => b.count - a.count)) {
    if (place(domain, domain.domainLabel, null, 'map-domain-label')) shown.push(domain.id);
  }
  if (level !== 'domain') for (const region of [...annotations.topics].sort((a,b) => b.visibleCount - a.visibleCount)) {
    if (place(region, `● ${region.domainLabel}`, '研究主题 · ' + region.topics.map((t) => shortNames[t.label] ?? t.label).join(' · '), 'map-topic-label')) shown.push(region.id);
  }
  if (level === 'paper') {
    const center = { x:width / 2, y:height / 2 };
    const papers = annotations.papers.map((p) => ({ p, screen:location(p.x,p.y) }))
      .filter(({screen}) => screen.x >= 0 && screen.x <= width && screen.y >= 0 && screen.y <= height)
      .sort((a,b) => Math.hypot(a.screen.x-center.x,a.screen.y-center.y)-Math.hypot(b.screen.x-center.x,b.screen.y-center.y));
    for (const {p} of papers) {
      if (place({ ...p,id:p.paper_id }, p.title, paperInfo(p), 'map-paper-label', () => onSelect(p))) paperIds.push(p.paper_id);
      if (paperIds.length >= 12) break;
    }
  }
  if (probe) { probe.mapLabels = shown; probe.labelLevel = level; probe.paperLabels = paperIds; probe.zoom = zoom; probe.pointRadius = pointRadius(zoom); }
}
