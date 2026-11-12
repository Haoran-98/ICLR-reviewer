import assert from 'node:assert/strict';
import { mkdir, writeFile } from 'node:fs/promises';
import { chromium } from 'playwright';
import { createServer } from 'vite';

const external = process.env.ICLR_WEB_BASE_URL;
const server = external ? null : await createServer({ server:{host:'127.0.0.1',port:0} });
let browser;
try {
  await server?.listen();
  const base = external ?? `http://127.0.0.1:${server.httpServer.address().port}`;
  browser = await chromium.launch({executablePath:process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH,args:['--no-sandbox']});
  const page = await browser.newPage({viewport:{width:1440,height:1050},ignoreHTTPSErrors:true,
    ...(process.env.ICLR_WEB_USERNAME ? {httpCredentials:{username:process.env.ICLR_WEB_USERNAME,password:process.env.ICLR_WEB_PASSWORD??''}} : {})});
  const errors=[];page.on('pageerror',e=>errors.push(e.message));
  await page.goto(base+'/review.html?paper=33089');
  await page.waitForFunction(()=>!document.querySelector('#start-review').disabled,null,{timeout:60000});
  assert.equal(await page.locator('.site-nav a').count(),3);
  assert.equal(await page.locator('#review-model option').count(),4);
  assert.equal(await page.locator('#review-model option:disabled').count(),2);
  await page.selectOption('#review-model','deepseek-pro');
  assert.match(await page.locator('#model-status').textContent(),/deepseek-v4-pro/);
  await page.selectOption('#review-model','openai-sol');
  assert.equal(await page.locator('.site-nav [aria-current=page]').textContent(),'单篇审稿');
  await page.locator('#load-example').click();
  await page.waitForFunction(()=>document.querySelectorAll('.rule-card').length===3);
  assert.match(await page.locator('#budget').textContent(),/1,605/);
  await page.locator('.rule-card').first().getByRole('button',{name:'查看新稿依据'}).click();
  assert.ok(await page.locator('#evidence-list .evidence-block').count()>0);
  const quote=await page.locator('#evidence-list blockquote').first().textContent();
  const example=await page.evaluate(()=>fetch('/api/review/example').then(r=>r.json()));
  assert.ok(example.manuscript.passages.some(p=>p.text.includes(quote)));
  await page.locator('[data-view=overview]').click();
  await page.locator('.rule-card').first().locator('details').last().locator('summary').click();
  assert.equal(await page.locator('.rule-card').first().locator('.source').count(),2);
  await mkdir('artifacts',{recursive:true});await page.screenshot({path:'artifacts/single-review-skills.png',fullPage:true});
  await page.locator('#choose-upload').click();
  await page.locator('#manuscript-file').setInputFiles({name:'test.md',mimeType:'text/markdown',buffer:Buffer.from('<img src=x onerror="window.injected=true"> short text')});
  await page.waitForFunction(()=>document.querySelector('#manuscript-text').value.includes('short text'));
  await page.locator('#start-review').click();assert.match(await page.locator('#input-error').textContent(),/完整稿件/);
  assert.equal(await page.evaluate(()=>window.injected),undefined);
  assert.equal(await page.evaluate(async()=> (await fetch('/api/review/runs',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({paper_id:-1})})).status),400);
  // Intercept one valid submission to verify the selected API without a paid review.
  let submitted;
  await page.route('**/api/review/runs',async route=>{
    if(route.request().method()!=='POST')return route.continue();
    submitted=route.request().postDataJSON();
    await route.fulfill({status:400,contentType:'application/json',body:JSON.stringify({error:'selection captured'})});
  });
  await page.selectOption('#review-model','deepseek-pro');
  await page.locator('#manuscript-text').fill('Full manuscript for UI transport validation. '.repeat(10));
  await page.locator('#start-review').click();
  await page.waitForFunction(()=>document.querySelector('#input-error').textContent==='selection captured');
  assert.equal(submitted.model,'deepseek-pro');
  await page.unroute('**/api/review/runs');
  await page.selectOption('#review-model','openai-sol');
  await page.locator('#choose-existing').click();
  let runId;
  if(process.env.ICLR_REVIEW_RETRY){
    runId=process.env.ICLR_REVIEW_RETRY;await page.goto(`${base}/review.html?run=${runId}`);
    await page.waitForFunction(()=>!document.querySelector('#retry-run').hidden,null,{timeout:30000});
    await page.locator('#retry-run').click();
    await page.waitForFunction(()=>document.querySelector('#state-badge').textContent==='已完成',null,{timeout:60000});
  } else if(process.env.ICLR_REVIEW_LIVE==='1'){
    await page.locator('#start-review').click();
    await page.waitForFunction(()=>new URL(location).searchParams.get('run'),null,{timeout:30000});
    runId=new URL(page.url()).searchParams.get('run');console.log('review smoke: live job',runId);
    await page.waitForFunction(()=>['已完成','未完成','已中断'].includes(document.querySelector('#state-badge').textContent),null,{timeout:240000});
    assert.equal(await page.locator('#state-badge').textContent(),'已完成',await page.locator('#run-message').textContent());
  } else {
    const jobs=await page.evaluate(()=>fetch('/api/review/runs').then(r=>r.json()));
    runId=jobs.find(j=>j.state==='completed')?.id;
  }
  if(runId){
    await page.goto(`${base}/review.html?run=${runId}`);
    await page.waitForFunction(()=>document.querySelector('#state-badge').textContent==='已完成',null,{timeout:30000});
    await page.locator('[data-view=review]').click();
    assert.ok((await page.locator('#review-panel').textContent()).includes('置信度'));
    if(await page.locator('.concern').count()){
      await page.locator('.concern').first().getByRole('button',{name:'查看论文依据'}).click();
      assert.ok(await page.locator('#evidence-list .evidence-block').count()>0);
      const payload=await page.evaluate(id=>fetch('/api/review/runs/'+id).then(r=>r.json()),runId);
      const shown=await page.locator('#evidence-list blockquote').first().textContent();
      assert.ok(payload.manuscript.passages.some(p=>p.text.includes(shown)));
    }
    await page.locator('[data-view=review]').click();await page.screenshot({path:'artifacts/single-review-result.png',fullPage:true});
  }
  await page.setViewportSize({width:390,height:844});
  for(const tab of ['overview','review','evidence']){
    await page.locator(`[data-view=${tab}]`).click();
    assert.ok(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1),'No mobile overflow: '+tab);
  }
  await page.screenshot({path:'artifacts/single-review-mobile.png',fullPage:true});
  await page.addInitScript(()=>Object.defineProperty(navigator,'gpu',{value:undefined}));
  await page.goto(base+'/?paper=33089&smoke=1');
  await page.waitForFunction(()=>window.__atlasProbe?.detailLoaded==='33089',null,{timeout:60000});
  assert.equal(await page.locator('#detail a[href="/review.html?paper=33089"]').count(),1);
  assert.equal(await page.locator('.site-nav [aria-current=page]').textContent(),'论文探索');
  assert.deepEqual(errors,[]);
  const report={check:'passed',run_id:runId??null,real_run:process.env.ICLR_REVIEW_LIVE==='1'||!!process.env.ICLR_REVIEW_RETRY,
    retry_from_preserved_response:!!process.env.ICLR_REVIEW_RETRY,
    independent_review_page:true,model_choices:4,configured_models:2,selected_model_forwarded:true,map_paper_handoff:true,skill_provenance:true,evidence_exact:true,
    input_upload:true,input_validation:true,mobile_overflow:false,browser_errors:errors};
  await writeFile('artifacts/single-review-smoke.json',JSON.stringify(report,null,2)+'\n');console.log(JSON.stringify(report,null,2));
} finally {await browser?.close();await server?.close();}
