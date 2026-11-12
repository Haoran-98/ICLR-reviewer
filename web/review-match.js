// ponytail: browser-local phrase retrieval; semantic routing belongs to a later review backend.
const STOP = new Set('the and for with from this that model models learning data method methods using based performance evaluation analysis large language task tasks'.split(' '));
export const words = (s) => [...new Set((s.toLowerCase().match(/[\p{L}\p{N}]+/gu) ?? []).filter(t => t.length > 2 && !STOP.has(t)))];
const escapeRE = s => s.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
export function phraseHit(text, term) {
  if (!term.trim()) return null;
  const pattern = escapeRE(term.trim()).replace(/[\s-]+/g, '[\\s-]+');
  const match = new RegExp(`(?<![\\p{L}\\p{N}])${pattern}(?![\\p{L}\\p{N}])`, 'iu').exec(text);
  return match ? { term, start: match.index, end: match.index + match[0].length,
    quote: text.slice(Math.max(0, match.index - 60), Math.min(text.length, match.index + match[0].length + 100)) } : null;
}
export function rankModules(modules, text, { area = 'unknown', candidates = false } = {}) {
  if (area === 'other' || !text.trim()) return [];
  const eligible = modules.filter(m => candidates || m.status === 'source_supported');
  const target = new Set(words(text));
  const df = new Map();
  for (const m of eligible) for (const w of words(m.scopes.join(' '))) df.set(w, (df.get(w) ?? 0) + 1);
  const ranked = [];
  for (const m of eligible) {
    const overlaps = words(m.scopes.join(' ')).filter(w => target.has(w));
    const hits = m.scopes.map(t => phraseHit(text, t)).filter(Boolean);
    // No generic or unmatched module is silently promoted to an applicable specialist.
    if (!hits.length && overlaps.length < 2) continue;
    const score = overlaps.reduce((n, w) => n + Math.log(1 + eligible.length / df.get(w)), 0) + hits.length * 3;
    ranked.push({ module: m, score, overlaps, hits });
  }
  return ranked.sort((a, b) => b.score - a.score || a.module.id.localeCompare(b.module.id));
}
