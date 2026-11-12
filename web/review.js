import { readManuscriptFile } from './manuscript-upload.js';
const $ = id => document.getElementById(id);
const el = (tag, text, cls) => { const n = document.createElement(tag); if (text != null) n.textContent = text; if (cls) n.className = cls; return n; };
const kinds = { supported_defect:'有证据支持的缺陷', needs_verification:'待核实问题', suggestion:'修改建议' };
const states = { queued:'等待执行', running:'运行中', completed:'已完成', failed:'未完成', interrupted:'已中断' };
const dispositions = { applicable:'适用', not_applicable:'不适用', insufficient_evidence:'证据不足' };
let modelChoices = [];
let papers = [], chosen, mode = 'existing', activeId, current = {}, pollTimer, renderKey;

async function api(path, payload) {
  const response = await fetch('/api/review'+path, payload === undefined ? {} : {
    method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify(payload) });
  const data = await response.json(); if (!response.ok) throw new Error(data.error || '请求未完成'); return data;
}
function button(text, action) { const b = el('button', text); b.type='button'; b.onclick=() => Promise.resolve().then(action).catch(error => $('service-error').textContent=error.message); return b; }
function view(name) {
  for (const key of ['overview','review','evidence']) $('view-'+key).hidden = key !== name;
  for (const b of document.querySelectorAll('[data-view]')) b.setAttribute('aria-pressed', String(b.dataset.view === name));
}
function selectPaper(paper) {
  chosen=paper; $('chosen-paper').textContent = `${paper.year ?? ''} · ${paper.title} · ID ${paper.paper_id}`;
  $('paper-search').value=paper.title; $('paper-results').replaceChildren(); $('start-review').disabled=false;
}
function sourceMode(value) {
  mode=value; $('existing-input').hidden=value !== 'existing'; $('upload-input').hidden=value !== 'upload';
  $('choose-existing').setAttribute('aria-pressed',String(value==='existing'));
  $('choose-upload').setAttribute('aria-pressed',String(value==='upload'));
  $('start-review').disabled=value==='existing' ? !chosen : !$('manuscript-text').value.trim();
}
function evidence(items, caption) {
  const ids = new Set(items.map(e => e.passage_id));
  const passages = current.manuscript?.passages ?? [];
  $('evidence-caption').textContent=caption;
  $('evidence-list').replaceChildren(...passages.filter(p => ids.has(p.passage_id)).map(p => {
    const n=el('article',null,'evidence-block'); n.dataset.passageId=p.passage_id;
    n.append(el('h3',p.passage_id),el('small',`原文位置 ${p.char_start}–${p.char_end}`));
    for(const quote of items.filter(e=>e.passage_id===p.passage_id)) n.append(el('blockquote',quote.quote));
    const full=el('details'); full.append(el('summary','阅读完整段落'),el('pre',p.text)); n.append(full); return n;
  }));
  view('evidence'); $('view-evidence').scrollIntoView({behavior:'smooth',block:'start'});
}
function renderProfile(profile) {
  if (!profile) { $('profile-panel').replaceChildren(el('h2','领域、方法与技术对象'),el('p','等待完整稿件的范围识别。','muted')); return; }
  const panel=$('profile-panel'); panel.replaceChildren(el('h2','领域、方法与技术对象'),el('p',profile.domain_reason));
  for (const [key,label] of [['methods','方法'],['tasks','任务'],['technical_objects','技术对象']]) {
    const chips=el('div',null,'chips'); for(const item of profile[key]) chips.append(el('span',item.term_english,'chip'));
    panel.append(el('h3',label),chips);
  }
}
function renderComposition(composition, checks) {
  if (!composition) { $('budget').textContent='';$('decisions').hidden=true;$('skill-list').replaceChildren(el('p','等待本稿的适用性检查。','muted'));return; }
  const budget=composition.budget;
  $('budget').textContent=`${budget.loaded_rules}/${budget.max_rules} 条 · ${budget.loaded_rule_tokens_proxy.toLocaleString()}/${budget.rule_token_budget.toLocaleString()} token 预算`;
  const ruleById=new Map((checks?.rules??[]).map(r=>[r.rule_id,r]));
  $('skill-list').replaceChildren(...composition.selected.map(item=>{
    const rule=ruleById.get(item.rule_id); const card=el('article',null,'rule-card'); card.dataset.ruleId=item.rule_id;
    card.append(el('p',`${item.rule_id} · 来源支持 · 规则版本 ${item.rule_version}`,'meta'),
      el('h3',rule?.title??item.rule_id),el('p',item.applicability.reason),
      button('查看新稿依据',()=>evidence(item.verified_target_evidence,`${item.rule_id} · 加载适用性的原文依据`)));
    const definition=el('details'); definition.append(el('summary','检查内容与适用边界'));
    for(const [label,key] of [['适用条件','applies_when'],['失效机制','failure_mechanism'],['问题成立条件','issue_when'],['消除证据','cleared_when']]) definition.append(el('h3',label),el('p',rule?.[key]??''));
    card.append(definition);
    const sources=el('details'); sources.append(el('summary',`历史来源 · ${item.historical_sources.source_paper_ids.length} 篇配对论文`));
    for(const source of item.historical_sources.display_examples) {
      const box=el('div',null,'source'); const a=el('a',source.title); a.href=`/?paper=${encodeURIComponent(source.paper_id)}`; a.target='_blank'; a.rel='noopener';
      box.append(a,el('p','历史初审片段','muted small'));
      for(const span of source.review_spans) box.append(el('blockquote',span.text));
      box.append(el('p','来源稿件片段','muted small'));
      for(const span of source.manuscript_spans) box.append(el('blockquote',span.text));
      sources.append(box);
    }
    card.append(sources); return card;
  }));
  if(!composition.selected.length) $('skill-list').append(el('p','本稿没有足够依据加载领域规则。','muted'));
  $('decisions').hidden=false;
  $('decision-list').replaceChildren(...composition.evaluations.map(item=>{
    const row=el('div',null,'decision'); row.append(el('strong',`${item.rule_id} · ${dispositions[item.disposition]??item.disposition}`),el('p',item.reason));
    if(item.selection==='rule_count_budget'||item.selection==='rule_token_budget') row.append(el('small','适用，但超出本次加载预算'));
    if(item.missing_information) row.append(el('small',item.missing_information)); return row;
  }));
}
function renderReview(review) {
  const panel=$('review-panel'); panel.replaceChildren(el('h2','Review 与修改优先级'));
  if(!review) { panel.append(el('p','审稿完成后将在这里显示结果。','muted')); return; }
  panel.append(el('p',review.summary));
  const score=el('div',null,'score'); score.append(el('span',`评分 ${review.rating}/10`),el('span',`置信度 ${review.confidence}/5`)); panel.append(score,el('p',review.rating_reason,'muted small'));
  panel.append(el('h3','优点'));
  for(const item of review.strengths) { const row=el('p',item.point); row.append(document.createTextNode(' '),button('查看依据',()=>evidence(item.evidence,'审稿优点的论文依据'))); panel.append(row); }
  panel.append(el('h3','Concern 与修改顺序'));
  if(!review.concerns.length) panel.append(el('p','本次未提出 concern。','muted'));
  for(const item of [...review.concerns].sort((a,b)=>a.priority.localeCompare(b.priority))) {
    const card=el('article',null,'concern'); card.dataset.kind=item.kind;
    card.append(el('span',kinds[item.kind],'kind '+item.kind),el('span',item.priority,'kind'),el('h3',item.observation),el('p',item.impact),
      el('h3','建议行动'),el('p',item.requested_action),el('h3','何种证据可以消除问题'),el('p',item.clearing_evidence),
      button('查看论文依据',()=>evidence(item.evidence,`${kinds[item.kind]} · ${item.priority} · ${item.rule_id}`)));
    panel.append(card);
  }
  if(review.questions.length) { panel.append(el('h3','需要澄清的问题')); for(const q of review.questions) panel.append(el('p',q)); }
  if(review.limitations.length) { const d=el('details'); d.append(el('summary','本次审查的证据范围')); for(const note of review.limitations)d.append(el('p',note)); panel.append(d); }
  if(current.recovery?.quarantined_items?.length){
    const details=el('details');details.append(el('summary',`单独待核验的原始条目 · ${current.recovery.quarantined_items.length} 条`));
    for(const item of current.recovery.quarantined_items){
      const original=item.original_item;details.append(el('p',original.point??original.observation),
        el('p','原始引文未能逐字匹配，此条未作为已核实的优点或 concern 展示。','muted small'),
        button('查看相关原文',()=>evidence(original.evidence.map(e=>({passage_id:e.passage_id,quote:''})),'原始条目尚待核验，以下为引用 ID 对应的原文段落。')));
    }panel.append(details);
  }
}
function render(value) {
  current=value; const job=value.job; const state=job?.state;
  const provider=job?.review_provider;
  $('run-model').textContent=provider?`本次审稿：${provider.label} · ${provider.model}${value.composition?` · Skill 组合模型：${value.composition.model}`:''}`:value.composition?`Skill 组合模型：${value.composition.model}`:'';
  $('run-title').textContent=job?.title??value.manuscript?.title??'MLRA 组合案例';
  $('state-badge').textContent=states[state]??'组合已完成'; $('state-badge').className='badge '+(state??'');
  $('run-message').textContent=job?.error??(state==='completed'?'审稿已完成。可查看加载理由、修改优先级和逐条原文依据。':job?.phase==='reviewing'?'正在结合完整稿件核查证据并生成 Review…':job?'正在识别稿件范围并组合适用 Skill…':'这是已完成的真实规则组合。点击“开始审稿”可继续生成 Review。');
  $('retry-run').hidden=!['failed','interrupted'].includes(state);
  const stage=state==='completed'?4:job?.phase==='reviewing'?3:value.composition?2:value.profile?1:0;
  [...$('pipeline').children].forEach((li,i)=>li.className=i<stage?'done':i===stage?'active':'');
  const u=value.progress?.usage; $('usage').textContent=u?`本阶段模型用量：输入 ${(u.input_tokens??0).toLocaleString()} · 输出 ${(u.output_tokens??0).toLocaleString()} token`:'来源支持规则优先 · 最多 10 条检查';
  if(value.recovery?.original_usage){const original=value.recovery.original_usage;$('usage').textContent=`复用已有模型响应：原调用输入 ${original.input_tokens.toLocaleString()} · 输出 ${original.output_tokens.toLocaleString()} token；本次恢复未追加调用。`;}
  if(value.recovery?.quarantined_items?.length)$('usage').textContent+=` · ${value.recovery.quarantined_items.length} 条原始条目未通过引文核验，已单独保留，未作为已核实意见展示。`;
  const key=JSON.stringify([job?.id,job?.attempt,!!value.profile,!!value.composition,!!value.review]);
  if(key!==renderKey) {renderKey=key; renderProfile(value.profile); renderComposition(value.composition,value.checks); renderReview(value.review);}
}
async function listRuns() {
  const jobs=await api('/runs'); $('run-list').replaceChildren(...jobs.map(job=>{
    const b=button('',()=>openRun(job.id)); b.className='run-card'; b.dataset.runId=job.id;
    b.append(el('strong',job.title),el('small',`${states[job.state]} · 第 ${job.attempt} 次执行 · ${job.review_provider?.label??'OpenAI 弱模型（历史记录）'}`)); return b;
  })); if(!jobs.length)$('run-list').append(el('p','暂无运行记录','muted small'));
}
async function refresh() {
  clearTimeout(pollTimer); if(!activeId)return;
  try {
    const id=activeId,value=await api('/runs/'+id); if(id!==activeId)return; render(value); $('service-error').textContent='';
    if(['queued','running'].includes(value.job.state))pollTimer=setTimeout(refresh,2000); else await listRuns();
  } catch(error) { $('service-error').textContent=error.message+'；正在保留当前页面并重连。'; pollTimer=setTimeout(refresh,5000); }
}
async function openRun(id) { activeId=id; const url=new URL(location);url.searchParams.set('run',id);history.replaceState(null,'',url); renderKey=null;view('overview');$('evidence-list').replaceChildren();await refresh(); }
document.querySelectorAll('[data-view]').forEach(b=>b.onclick=()=>view(b.dataset.view));
$('choose-existing').onclick=()=>sourceMode('existing'); $('choose-upload').onclick=()=>sourceMode('upload');
$('paper-search').oninput=()=>{
  chosen=null;$('start-review').disabled=true;const q=$('paper-search').value.trim().toLowerCase();
  const matches=q?papers.filter(p=>p.title.toLowerCase().includes(q)||String(p.paper_id)===q).slice(0,12):[];
  $('paper-results').replaceChildren(...matches.map(p=>button(`${p.year} · ${p.title}`,()=>selectPaper(p))));
};
$('manuscript-text').oninput=()=>{$('start-review').disabled=!$('manuscript-text').value.trim();};
$('manuscript-file').onchange=async()=>{
  const file=$('manuscript-file').files[0];if(!file)return;
  $('input-error').textContent='';$('upload-status').textContent='正在读取稿件…';
  $('start-review').disabled=true;$('manuscript-text').value='';
  $('manuscript-file').disabled=true;$('manuscript-text').disabled=true;
  try {
    const result=await readManuscriptFile(file);
    $('manuscript-text').value=result.text;
    if(!$('upload-title').value)$('upload-title').value=file.name.replace(/\.[^.]+$/,'');
    $('upload-status').textContent=`已读取 ${file.name} · ${result.text.length.toLocaleString()} 字符。请检查正文完整性${result.converted?'，图表与扫描文字需另行核对':''}。`;
  } catch(error) {$('input-error').textContent=error.message;$('upload-status').textContent='读取未完成，请重新选择文件。';}
  finally {$('manuscript-file').disabled=false;$('manuscript-text').disabled=false;sourceMode(mode);}
};
$('paper-form').onsubmit=async event=>{
  event.preventDefault();$('input-error').textContent='';$('start-review').disabled=true;
  try{
    const payload=mode==='existing'?{paper_id:Number(chosen?.paper_id),title:chosen?.title}:{manuscript:$('manuscript-text').value,title:$('upload-title').value};
    if(mode==='upload'&&payload.manuscript.trim().length<200)throw new Error('请提供完整稿件，至少 200 字符。');
    const selected=modelChoices.find(item=>item.id===$('review-model').value);
    if(!selected?.configured)throw new Error('请选择已配置的审稿模型。');
    payload.model=selected.id;
    const job=await api('/runs',payload);await openRun(job.id);await listRuns();view('overview');
  }catch(error){$('input-error').textContent=error.message;}finally{$('start-review').disabled=false;}
};
$('retry-run').onclick=async()=>{try{await api('/runs/'+activeId+'/retry',{});await refresh();}catch(error){$('service-error').textContent=error.message;}};
$('load-example').onclick=async()=>{
  try{activeId=null;clearTimeout(pollTimer);const url=new URL(location);url.searchParams.delete('run');url.searchParams.set('paper','33089');history.replaceState(null,'',url);renderKey=null;render(await api('/example'));selectPaper(papers.find(p=>String(p.paper_id)==='33089')??{paper_id:33089,title:'Multi-Head Low-Rank Attention'});sourceMode('existing');view('overview');}
  catch(error){$('service-error').textContent=error.message;}
};
$('show-full-text').onclick=()=>evidence((current.manuscript?.passages??[]).map(p=>({passage_id:p.passage_id,quote:''})),'完整可用文本，包含文件中已有的附录；图像内容需单独核验。');
async function init(){
  const [sample,meta]=await Promise.all([fetch('/generated/sample.json').then(r=>{if(!r.ok)throw new Error('论文目录未加载');return r.json();}),api('/meta')]);
  modelChoices=meta.models;
  $('review-model').replaceChildren(...modelChoices.map(item=>{
    const option=el('option',item.label+(item.configured?'':' · 待配置'));option.value=item.id;option.disabled=!item.configured;return option;
  }));
  const savedModel=localStorage.getItem('iclr-review-model');
  $('review-model').value=modelChoices.find(m=>m.id===savedModel&&m.configured)?.id??meta.default_model;
  const describeModel=()=>{
    const selected=modelChoices.find(m=>m.id===$('review-model').value);
    $('model-status').textContent=selected?.configured?`${selected.model} · 用于领域识别、Skill 组合与审稿。Qwen / Claude 待配置接口。`:'所选接口尚未配置。';
  };
  $('review-model').onchange=()=>{localStorage.setItem('iclr-review-model',$('review-model').value);describeModel();};describeModel();
  papers=sample.papers;await listRuns();const params=new URLSearchParams(location.search);
  const paper=papers.find(p=>String(p.paper_id)===params.get('paper'));if(paper)selectPaper(paper);
  if(params.get('run'))await openRun(params.get('run'));
}
init().catch(error=>{$('service-error').textContent=error.message;});
