const NS = 'http://www.w3.org/2000/svg';
const format = (n) => n.toLocaleString('zh-CN');
const statuses = { all: ['全部决定', '#526078'], accepted: ['录用', '#087f8c'], rejected: ['拒稿', '#c15b40'] };
export const metrics = {
  mean: { label: '论文均分', max: 10, step: 0.25, axis: '每篇论文的有效评分均值', minimum: 1 },
  sd: { label: '篇内评分标准差', max: 7, step: 0.25, axis: '篇内样本标准差（分母 n−1）', minimum: 2 },
  range: { label: '篇内评分极差', max: 9, step: 0.5, axis: '同篇最高评分 − 最低评分', minimum: 2 },
};

export function paperScore(ratings) {
  const values = ratings.filter((x) => typeof x === 'number' && Number.isFinite(x));
  const n = values.length;
  if (!n) return { n, mean: null, sd: null, range: null };
  const mean = values.reduce((a, b) => a + b, 0) / n;
  return { n, mean, sd: n < 2 ? null : Math.sqrt(values.reduce((a, x) => a + (x - mean) ** 2, 0) / (n - 1)),
    range: n < 2 ? null : Math.max(...values) - Math.min(...values) };
}

// R's default type-7 quantile, shared with ggdist::median_qi.
export function quantile(sorted, p) {
  if (!sorted.length) return null;
  const index = (sorted.length - 1) * p, low = Math.floor(index), high = Math.ceil(index);
  return sorted[low] + (sorted[high] - sorted[low]) * (index - low);
}

export function distribution(values, max, step) {
  const sorted = values.filter(Number.isFinite).sort((a, b) => a - b);
  const bins = Array.from({ length: Math.round(max / step) }, () => 0);
  for (const value of sorted) bins[Math.max(0, Math.min(bins.length - 1, Math.floor(value / step)))]++;
  return { n: sorted.length, sorted, median: quantile(sorted, 0.5),
    q05: quantile(sorted, 0.05), q25: quantile(sorted, 0.25), q75: quantile(sorted, 0.75), q95: quantile(sorted, 0.95),
    density: bins.map((count) => sorted.length ? count / sorted.length / step : 0),
    dots: sorted.length <= 40 ? sorted : Array.from({ length: 40 }, (_, i) => quantile(sorted, (i + 0.5) / 40)) };
}

function svg(tag, attrs = {}, text) {
  const node = document.createElementNS(NS, tag);
  for (const [key, value] of Object.entries(attrs)) node.setAttribute(key, value);
  if (text !== undefined) node.textContent = text;
  return node;
}

export function renderPaperDistributions(host, papers, years, population, disagreement = 'sd') {
  const groupIds = population === 'compare' ? ['accepted', 'rejected'] : [population || 'all'];
  const rows = papers.map((p) => ({ ...p, score: p.score ?? paperScore(p.ratings) }));
  host.replaceChildren();
  const summaries = [];
  for (const metric of ['mean', disagreement]) {
    const spec = metrics[metric], card = document.createElement('div'); card.className = 'paper-score-card';
    const title = document.createElement('h4'); title.textContent = `${metric === 'mean' ? 'A' : 'B'} · ${spec.label}`;
    const subtitle = document.createElement('p'); subtitle.className = 'muted';
    subtitle.textContent = metric === 'mean' ? '比较论文的评分水平；每篇论文等权。' : '比较同篇审稿的一致程度；至少两条有效评分。';
    const series = [];
    for (const year of years) for (const status of groupIds) {
      const group = rows.filter((p) => p.year === year && (status === 'all' || p.decision === status));
      const included = group.filter((p) => p.score[metric] !== null);
      const summary = { year, status, metric, total: group.length, excluded: group.length - included.length,
        ...distribution(included.map((p) => p.score[metric]), spec.max, spec.step) };
      series.push(summary);
      summaries.push({ ...summary, sorted: undefined, density: undefined, dots: undefined });
    }
    const width = 790, left = 126, right = 755, rowHeight = 138, top = 44;
    const height = top + series.length * rowHeight + 62, x = (value) => left + value / spec.max * (right - left);
    const root = svg('svg', { viewBox: `0 0 ${width} ${height}`, role: 'img', 'aria-label': `${spec.label}：分布主体、点阵、中位数与中央50%及90%分位区间`, 'data-metric': metric });
    const maxDensity = Math.max(1e-12, ...series.flatMap((s) => s.density));
    for (let tick = 0; tick <= spec.max; tick++) {
      root.append(svg('line', { x1: x(tick), x2: x(tick), y1: 20, y2: height - 48, stroke: '#e5eaf0' }));
      root.append(svg('text', { x: x(tick), y: height - 28, 'text-anchor': 'middle', 'font-size': 14, fill: '#526078' }, tick));
    }
    for (const [i, s] of series.entries()) {
      const baseline = top + i * rowHeight + 43, [label, color] = statuses[s.status];
      root.append(svg('text', { x: 8, y: baseline - 32, 'font-size': 16, 'font-weight': 600 }, String(s.year)));
      root.append(svg('text', { x: 8, y: baseline - 10, 'font-size': 14, fill: color }, label));
      root.append(svg('text', { x: 8, y: baseline + 12, 'font-size': 12, fill: '#526078' }, `n=${format(s.n)}`));
      root.append(svg('text', { x: 8, y: baseline + 31, 'font-size': 11, fill: '#526078' }, `排除 ${format(s.excluded)} 篇`));
      root.append(svg('line', { x1: left, x2: right, y1: baseline, y2: baseline, stroke: '#bbc7d4' }));
      if (!s.n) {
        root.append(svg('text', { x: left + 20, y: baseline - 10, 'font-size': 14, fill: '#526078' }, '当前分组暂无符合条件的论文'));
        continue;
      }
      const group = svg('g', { 'data-year': s.year, 'data-status': s.status, 'data-count': s.n });
      let path = `M${x(0)},${baseline}`;
      for (const [j, density] of s.density.entries()) {
        const y = baseline - density / maxDensity * 45;
        path += `L${x(j * spec.step)},${y}L${x((j + 1) * spec.step)},${y}`;
      }
      path += `L${x(spec.max)},${baseline}Z`;
      const slab = svg('path', { d: path, fill: color, 'fill-opacity': 0.32, stroke: color, 'stroke-width': 0.7, class: 'score-slab' });
      slab.append(svg('title', {}, `ICLR ${s.year} · ${label} · ${spec.label}\n${s.n} 篇有效论文；按0.25或0.5分箱的组内密度，同图共同缩放。`)); group.append(slab);
      const dotBuckets = new Map();
      for (const value of s.dots) {
        const bucket = Math.round((x(value) - left) / 10), count = dotBuckets.get(bucket) ?? 0;
        dotBuckets.set(bucket, count + 1);
        const dot = svg('circle', { cx: left + bucket * 10, cy: baseline + 8 + count * 8, r: 3.1, fill: color, class: 'score-dot' });
        dot.append(svg('title', {}, `${s.n <= 40 ? '单篇论文观测' : '等概率分位点（约2.5%论文）'}：${value.toFixed(3)}`)); group.append(dot);
      }
      // Ties stack vertically; reserve enough space before the interval for the largest stack.
      const stack = Math.max(1, ...dotBuckets.values()), intervalY = baseline + 13 + stack * 8;
      // Compress tied stacks to keep a constant row height, preserving the number of dots.
      if (stack > 5) for (const dot of group.querySelectorAll('.score-dot')) {
        dot.setAttribute('cy', baseline + 8 + (Number(dot.getAttribute('cy')) - baseline - 8) * 4 / (stack - 1));
        dot.setAttribute('r', Math.min(3.1, 14 / Math.sqrt(stack)));
      }
      const iy = Math.min(baseline + 57, intervalY);
      for (const [a, b, thickness] of [[s.q05, s.q95, 2.5], [s.q25, s.q75, 7]])
        group.append(svg('line', { x1: x(a), x2: x(b), y1: iy, y2: iy, stroke: color, 'stroke-width': thickness, 'stroke-linecap': 'round', class: 'score-interval' }));
      const median = svg('circle', { cx: x(s.median), cy: iy, r: 4.2, fill: '#14243a', stroke: 'white', 'stroke-width': 1, class: 'score-median' });
      median.append(svg('title', {}, `中位数 ${s.median.toFixed(3)}\n中央50% [${s.q25.toFixed(3)}, ${s.q75.toFixed(3)}]\n中央90% [${s.q05.toFixed(3)}, ${s.q95.toFixed(3)}]\n经验分位区间，不是置信区间`)); group.append(median);
      group.append(svg('text', { x: right, y: baseline + 81, 'text-anchor': 'end', 'font-size': 11, fill: '#526078' }, `中位 ${s.median.toFixed(2)} · 50% [${s.q25.toFixed(2)}, ${s.q75.toFixed(2)}] · 90% [${s.q05.toFixed(2)}, ${s.q95.toFixed(2)}]`));
      root.append(group);
    }
    root.append(svg('text', { x: (left + right) / 2, y: height - 5, 'text-anchor': 'middle', 'font-size': 14 }, spec.axis));
    card.append(title, subtitle, root); host.append(card);
  }
  return summaries;
}
