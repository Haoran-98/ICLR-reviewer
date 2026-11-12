import { readFileSync } from 'node:fs';
import { homedir } from 'node:os';
import { join } from 'node:path';
import { createHash, scryptSync, timingSafeEqual } from 'node:crypto';

// One server-owned administrator; the browser's HTTPS login also protects static data.
export function siteAuth(configPath = process.env.ICLR_WEB_AUTH_FILE ?? join(homedir(), '.config/iclr-reviewer/web-auth.json')) {
  const config = JSON.parse(readFileSync(configPath, 'utf8'));
  const expected = Buffer.from(config.password_hash, 'hex');
  if (!config.username || !config.salt || expected.length !== 64) throw new Error('网站登录配置无效');
  let acceptedDigest;
  function authenticate(req, res, next) {
    const header = req.headers.authorization ?? '';
    const digest = createHash('sha256').update(header).digest();
    if (acceptedDigest && timingSafeEqual(digest, acceptedDigest)) return next();
    if (header.startsWith('Basic ') && header.length < 4096) {
      const credential = Buffer.from(header.slice(6), 'base64').toString('utf8');
      const colon = credential.indexOf(':');
      const actual = scryptSync(credential.slice(colon + 1), config.salt, 64);
      if (colon >= 0 && credential.slice(0, colon) === config.username && timingSafeEqual(actual, expected)) {
        acceptedDigest = digest;
        return next();
      }
    }
    res.writeHead(401, {
      'WWW-Authenticate': 'Basic realm="ICLR Research Workspace", charset="UTF-8"',
      'Content-Type': 'text/plain; charset=utf-8', 'Cache-Control': 'no-store',
    });
    res.end('请输入正确的管理员用户名和密码。');
  }
  return { name: 'site-auth', configureServer: server => { server.middlewares.use(authenticate); },
    configurePreviewServer: server => { server.middlewares.use(authenticate); } };
}
