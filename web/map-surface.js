import { contours } from 'd3-contour';

function blur(plane, size, kernel) {
  const radius = (kernel.length - 1) / 2, scratch = new Float32Array(plane.length);
  for (let y = 0; y < size; y++) for (let x = 0; x < size; x++) {
    let value = 0;
    for (let k = -radius; k <= radius; k++) if (x + k >= 0 && x + k < size) value += plane[y * size + x + k] * kernel[k + radius];
    scratch[y * size + x] = value;
  }
  for (let y = 0; y < size; y++) for (let x = 0; x < size; x++) {
    let value = 0;
    for (let k = -radius; k <= radius; k++) if (y + k >= 0 && y + k < size) value += scratch[(y + k) * size + x] * kernel[k + radius];
    plane[y * size + x] = value;
  }
}

// Equal-prior domain KDEs keep sample size from swallowing the smaller fields.
export function domainSurfaceGrid(papers, colorFor, extent, sigma = 5, size = 160) {
  const [minX, minY, maxX, maxY] = extent, cells = size * size;
  const domains = [...new Set(papers.map((p) => p.domain))].sort();
  const indices = new Map(domains.map((id, i) => [id, i]));
  const fields = domains.map((id) => ({ id, count:0, color:null, density:new Float32Array(cells) }));
  for (const p of papers) {
    const x = Math.max(0, Math.min(size - 1, Math.floor((p.x - minX) / (maxX - minX) * size)));
    const y = Math.max(0, Math.min(size - 1, Math.floor((p.y - minY) / (maxY - minY) * size)));
    const field = fields[indices.get(p.domain)];
    field.density[y * size + x]++; field.count++; field.color = colorFor(p);
  }
  const radius = Math.ceil(sigma * 3);
  const kernel = Array.from({ length: radius * 2 + 1 }, (_, i) => Math.exp(-0.5 * ((i - radius) / sigma) ** 2));
  const sum = kernel.reduce((a, b) => a + b, 0);
  for (let i = 0; i < kernel.length; i++) kernel[i] /= sum;
  const total = new Float32Array(cells), first = new Float32Array(cells), second = new Float32Array(cells);
  const winner = new Int16Array(cells).fill(-1);
  for (const [d, field] of fields.entries()) {
    blur(field.density, size, kernel);
    for (let i = 0; i < cells; i++) {
      total[i] += field.density[i]; field.density[i] /= field.count;
      const value = field.density[i];
      if (value > first[i]) { second[i] = first[i]; first[i] = value; winner[i] = d; }
      else if (value > second[i]) second[i] = value;
    }
  }
  const peak = total.reduce((a, b) => Math.max(a, b), 0), pixels = new Uint8ClampedArray(cells * 4);
  const rgb = fields.map((f) => [1,3,5].map((offset) => parseInt(f.color.slice(offset, offset + 2), 16)));
  let coloredCells = 0;
  for (let i = 0; i < cells; i++) {
    let density = 0, r = 0, g = 0, b = 0;
    for (const [d, field] of fields.entries()) {
      const v = field.density[i]; density += v; r += v * rgb[d][0]; g += v * rgb[d][1]; b += v * rgb[d][2];
    }
    if (!density) continue;
    pixels[i * 4] = r / density; pixels[i * 4 + 1] = g / density; pixels[i * 4 + 2] = b / density;
    pixels[i * 4 + 3] = 95 * (1 - Math.exp(-total[i] / (peak * 0.18)));
    if (pixels[i * 4 + 3]) coloredCells++;
  }
  const boundaries = [], anchors = [], supportThreshold = peak * 0.015;
  const contour = contours().size([size, size]).thresholds([0]);
  for (const [d, field] of fields.entries()) {
    const margin = new Float32Array(cells); let anchor = -1;
    for (let i = 0; i < cells; i++) {
      margin[i] = total[i] < supportThreshold || !peak ? -1 : field.density[i] - (winner[i] === d ? second[i] : first[i]);
      if (winner[i] === d && total[i] >= supportThreshold && (anchor < 0 || field.density[i] > field.density[anchor])) anchor = i;
    }
    if (anchor < 0) continue;
    const polygons = contour(margin)[0].coordinates;
    boundaries.push({ domain:field.id, polygons });
    anchors.push({ id:field.id, domain:field.id, count:field.count, color:field.color,
      x:minX + (anchor % size + 0.5) / size * (maxX - minX),
      y:minY + (Math.floor(anchor / size) + 0.5) / size * (maxY - minY) });
  }
  return { pixels, size, extent, coloredCells, papers:papers.length, sigma, boundaries, anchors,
    method:'normalized Gaussian KDE; argmax domains; marching squares at equal maximum densities; support >= 1.5% peak' };
}

export function createDomainSurface(papers, colorFor, extent, sigma) {
  const grid = domainSurfaceGrid(papers, colorFor, extent, sigma);
  const canvas = document.createElement('canvas'); canvas.width = canvas.height = grid.size;
  canvas.getContext('2d').putImageData(new ImageData(grid.pixels, grid.size, grid.size), 0, 0);
  return { ...grid, canvas };
}

export function drawDomainSurface(canvas, surface, location, width, height, probe, showFill = true, showLines = true) {
  const ratio = Math.min(devicePixelRatio || 1, 2), w = Math.round(width * ratio), h = Math.round(height * ratio);
  if (canvas.width !== w || canvas.height !== h) { canvas.width = w; canvas.height = h; }
  const ctx = canvas.getContext('2d'); ctx.setTransform(1, 0, 0, 1, 0, 0); ctx.clearRect(0, 0, w, h);
  let segments = 0;
  if (surface) {
    const [minX, minY, maxX, maxY] = surface.extent;
    const a = location(minX, minY), b = location(maxX, minY), c = location(minX, maxY);
    ctx.scale(ratio, ratio);
    if (showFill) {
      ctx.save(); ctx.transform((b.x - a.x) / surface.size, (b.y - a.y) / surface.size,
        (c.x - a.x) / surface.size, (c.y - a.y) / surface.size, a.x, a.y);
      ctx.drawImage(surface.canvas, 0, 0); ctx.restore();
    }
    if (showLines) {
      ctx.beginPath();
      for (const field of surface.boundaries) for (const polygon of field.polygons) for (const ring of polygon) {
        for (const [index, p] of ring.entries()) {
          const x = a.x + (b.x - a.x) * p[0] / surface.size + (c.x - a.x) * p[1] / surface.size;
          const y = a.y + (b.y - a.y) * p[0] / surface.size + (c.y - a.y) * p[1] / surface.size;
          if (index) { ctx.lineTo(x, y); segments++; } else ctx.moveTo(x, y);
        }
        ctx.closePath();
      }
      ctx.strokeStyle = '#ffffff'; ctx.lineWidth = 3.6; ctx.stroke();
      ctx.strokeStyle = '#253b50'; ctx.lineWidth = 1.35; ctx.stroke();
    }
  }
  if (probe) probe.domainSurface = { active:Boolean(surface), papers:surface?.papers ?? 0,
    coloredCells:surface?.coloredCells ?? 0, sigma:surface?.sigma ?? null,
    boundarySegments:segments, domainAnchors:surface?.anchors.length ?? 0, method:surface?.method };
}
