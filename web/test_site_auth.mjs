import assert from 'node:assert/strict';
import { mkdtempSync, writeFileSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { scryptSync } from 'node:crypto';
import { createServer } from 'node:http';
import { siteAuth } from './site-auth.js';

const directory = mkdtempSync(join(tmpdir(), 'iclr-auth-test-'));
const config = join(directory, 'auth.json');
writeFileSync(config, JSON.stringify({ username:'root',salt:'test-salt',password_hash:scryptSync('test-password','test-salt',64).toString('hex') }), { mode:0o600 });
let authenticate;
siteAuth(config).configureServer({middlewares:{use(fn){authenticate=fn;}}});
const server=createServer((req,res)=>authenticate(req,res,()=>{res.writeHead(200);res.end('protected content');}));
await new Promise(resolve=>server.listen(0,'127.0.0.1',resolve));
try {
  const base=`http://127.0.0.1:${server.address().port}`;
  for (const path of ['/', '/review.html', '/reviewers.html', '/generated/sample.json', '/api/review/meta', '/api/review/extract']) {
    const response=await fetch(base+path);assert.equal(response.status,401);assert.match(response.headers.get('www-authenticate'),/^Basic /);
    assert.ok(!(await response.text()).includes('protected content'));
  }
  for(const credential of ['root:incorrect','other:test-password','root','']) {
    assert.equal((await fetch(base,{headers:{Authorization:'Basic '+Buffer.from(credential).toString('base64')}})).status,401);
  }
  const authorized={Authorization:'Basic '+Buffer.from('root:test-password').toString('base64')};
  assert.equal((await fetch(base,{headers:authorized})).status,200);
  assert.equal((await fetch(base+'/api/review/meta',{headers:authorized})).status,200);
  assert.equal((await fetch(base)).status,401,'An authenticated request must not unlock other clients');
  assert.throws(()=>siteAuth(join(directory,'missing.json')),'Missing configuration must fail closed');
  console.log('passed: pages, assets and API require valid credentials; missing config fails closed');
} finally {server.closeAllConnections();await new Promise(resolve=>server.close(resolve));rmSync(directory,{recursive:true});}
