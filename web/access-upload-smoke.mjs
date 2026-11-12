import assert from 'node:assert/strict';
import { mkdtemp, rm, mkdir, writeFile } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { execFile } from 'node:child_process';
import { promisify } from 'node:util';
import { chromium, request } from 'playwright';

const base=process.env.ICLR_WEB_BASE_URL;
const httpCredentials={username:process.env.ICLR_WEB_USERNAME,password:process.env.ICLR_WEB_PASSWORD};
assert.ok(base && httpCredentials.username && httpCredentials.password,'Set the site URL and test credentials in the environment');
const folder=await mkdtemp(join(tmpdir(),'iclr-upload-browser-'));
const anonymous=await request.newContext({ignoreHTTPSErrors:true});
const incorrect=await request.newContext({ignoreHTTPSErrors:true,httpCredentials:{username:httpCredentials.username,password:'incorrect'}});
let browser;
try {
  for(const path of ['/','/review.html','/reviewers.html','/generated/sample.json','/api/review/meta','/api/review/example']) {
    assert.equal((await anonymous.get(base+path)).status(),401,path);
    assert.equal((await incorrect.get(base+path)).status(),401,path+' wrong password');
  }
  await promisify(execFile)('python3',['-c','from test_manuscript_upload import fixtures; import sys; fixtures(sys.argv[1])',folder]);
  browser=await chromium.launch({executablePath:process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH,args:['--no-sandbox']});
  const page=await browser.newPage({httpCredentials,ignoreHTTPSErrors:true,viewport:{width:1440,height:1050}});
  const errors=[];page.on('pageerror',error=>errors.push(error.message));
  const posts=[];page.on('request',r=>{if(r.method()==='POST')posts.push(new URL(r.url()).pathname);});
  await page.goto(base+'/review.html');
  await page.waitForFunction(()=>document.querySelector('#review-model option').value==='openai-sol');
  await page.locator('#choose-upload').click();
  for(const suffix of ['doc','docx','docs','pdf']) {
    await page.locator('#manuscript-file').setInputFiles(join(folder,'manuscript.'+suffix));
    await page.waitForFunction(()=>document.querySelector('#upload-status').textContent.startsWith('已读取'),null,{timeout:90000});
    assert.match(await page.locator('#manuscript-text').inputValue(),/Manuscript upload validation/);
    assert.equal(await page.locator('#start-review').isEnabled(),true);
    assert.equal(await page.locator('#input-error').textContent(),'');
  }
  await page.locator('#manuscript-file').setInputFiles({name:'broken.pdf',mimeType:'application/pdf',buffer:Buffer.from('not PDF')});
  await page.waitForFunction(()=>document.querySelector('#input-error').textContent.includes('有效的 PDF'));
  assert.equal(await page.locator('#manuscript-text').inputValue(),'');
  assert.equal(await page.locator('#start-review').isDisabled(),true);
  await page.locator('#manuscript-file').setInputFiles({name:'oversized.pdf',mimeType:'application/pdf',buffer:Buffer.alloc(15*1024*1024+1)});
  await page.waitForFunction(()=>document.querySelector('#input-error').textContent.includes('15 MB'));
  await page.goto(base+'/reviewers.html');
  await page.waitForFunction(()=>window.__reviewWorkbench?.modules===7795);
  await page.locator('[data-tab=match]').click();
  await page.locator('#paper-file').setInputFiles(join(folder,'manuscript.docx'));
  await page.waitForFunction(()=>document.querySelector('#match-status').textContent.includes('已在本站服务器提取'));
  assert.match(await page.locator('#paper-text').inputValue(),/Manuscript upload validation/);
  await page.addInitScript(()=>Object.defineProperty(navigator,'gpu',{value:undefined}));
  await page.goto(base+'/?smoke=1');
  await page.waitForFunction(()=>window.__atlasProbe?.positions.length===12964,null,{timeout:60000});
  assert.equal(posts.filter(path=>path==='/api/review/runs').length,0,'Extraction must not start a review');
  assert.deepEqual(errors,[]);
  await mkdir('artifacts',{recursive:true});
  const result={check:'passed',authentication:'pages, static data and API',formats:['doc','docx','docs','pdf'],
    invalid_file_rejected:true,oversize_rejected:true,stale_text_cleared:true,library_upload:true,map_papers:12964,
    model_calls:0,browser_errors:errors};
  await writeFile('artifacts/access-upload-smoke.json',JSON.stringify(result,null,2)+'\n');
  console.log(JSON.stringify(result,null,2));
} finally {await browser?.close();await anonymous.dispose();await incorrect.dispose();await rm(folder,{recursive:true,force:true});}
