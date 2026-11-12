import { spawn } from 'node:child_process';
import { request as httpRequest } from 'node:http';
import { randomBytes } from 'node:crypto';
import { fileURLToPath } from 'node:url';

// Lazy local companion: browsing the existing map never starts a model service.
export function reviewAPI() {
  let child, ready;
  const token = randomBytes(24).toString('hex');
  function backend() {
    if (ready) return ready;
    ready = new Promise((resolve, reject) => {
      child = spawn(process.env.ICLR_PYTHON ?? 'python3', ['-u', '-X', 'pycache_prefix=/tmp/iclr-web-review-pycache',
        fileURLToPath(new URL('./review_api.py', import.meta.url))],
      { env: { ...process.env, ICLR_REVIEW_API_TOKEN: token }, stdio: ['ignore', 'pipe', 'inherit'] });
      let buffer = '';
      child.stdout.on('data', chunk => {
        buffer += chunk;
        const end = buffer.indexOf('\n');
        if (end >= 0) {
          try { resolve(JSON.parse(buffer.slice(0, end)).port); } catch { reject(new Error('审稿服务启动失败')); }
        }
      });
      child.once('error', reject);
      child.once('exit', () => { reject(new Error('审稿服务已停止')); child = null; ready = null; });
    });
    return ready;
  }
  function install(server) {
    server.middlewares.use('/api/review', async (req, res) => {
      const origin = req.headers.origin;
      let originHost; try { originHost = origin && new URL(origin).host; } catch { originHost = 'invalid'; }
      const authority = req.headers[':authority'] ?? req.headers.host;
      if (req.method !== 'GET' && (req.headers['sec-fetch-site'] === 'cross-site' ||
        (origin && originHost !== authority))) {
        res.writeHead(403, { 'Content-Type': 'application/json' }); res.end(JSON.stringify({ error: '请求来源不匹配' })); return;
      }
      try {
        const port = await backend();
        const proxy = httpRequest({ hostname: '127.0.0.1', port, path: '/api/review'+req.url,
          method: req.method, headers: { 'content-type': 'application/json', 'x-review-token': token,
            ...(req.headers['content-length'] ? { 'content-length': req.headers['content-length'] } : {}) } }, upstream => {
          res.writeHead(upstream.statusCode, { 'Content-Type': 'application/json; charset=utf-8', 'Cache-Control': 'no-store' });
          upstream.pipe(res);
        });
        proxy.on('error', () => { if (!res.headersSent) res.writeHead(503); res.end(JSON.stringify({ error: '审稿服务暂不可用，请重试' })); });
        req.pipe(proxy);
      } catch {
        res.writeHead(503, { 'Content-Type': 'application/json' }); res.end(JSON.stringify({ error: '审稿服务启动失败，请重试' }));
      }
    });
    server.httpServer?.once('close', () => child?.kill());
  }
  return { name: 'single-paper-review-api', configureServer: install, configurePreviewServer: install };
}
