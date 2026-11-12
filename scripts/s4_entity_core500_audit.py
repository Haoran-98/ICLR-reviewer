#!/usr/bin/env python3
"""Verify and seal the completed 500-paper extraction and all four vector arrays."""
import argparse
from collections import Counter
from datetime import datetime
import hashlib
import json
import math
from pathlib import Path
import shutil
import tarfile

import numpy as np

import s4_entity_core5 as extraction
from s4_dual_embeddings import MODELS
from s4_reproduce500 import digest, now, read, write
from s4_taxoadapt100_api import credentials


def sha(path):
    h = hashlib.sha256()
    with path.open('rb') as stream:
        for chunk in iter(lambda: stream.read(8*1024*1024), b''):
            h.update(chunk)
    return h.hexdigest()


def main(root):
    inputs, rows = read(root/'inputs.json'), read(root/'results.json')
    config, progress = read(root/'config.json'), read(root/'progress.json')
    total=len(inputs)
    assert progress['state']=='completed' and progress['embedding_completed']==4*total
    ids = [p['paper_id'] for p in inputs]
    assert len(ids)==len(set(ids))==len(rows)==config['papers'] and [r['paper_id'] for r in rows]==ids
    gold=read(root/'evaluation/gold.json')
    assert [g['paper_id'] for g in gold]==ids and len({g['area'] for g in gold})==23
    assert all(g['raw_label']==p['original_labels']['primary_area'] for g,p in zip(gold,inputs))
    sample=read(root/'sample.json')
    if 'corpus_total' in sample:
        population=read(root/'population.json')
        assert total==math.ceil(sample['corpus_total']/3)
        assert len(population)==sample['corpus_total'] and digest(population)==sample['population_hash']
        assert digest(gold)==sample['gold_hash']
        assert set(ids)<={p['paper_id'] for p in population}
        counts=Counter((g['year'],g['area']) for g in gold)
        assert all(counts[(s['year'],s['area'])]==s['selected'] for s in sample['strata'])
    assert config['input_hash']==digest(inputs)
    assert config['prompt_hash']==digest(extraction.PROMPT)==digest((root/'PROMPT.md').read_text())
    assert config['script_sha256']==sha(root/'runtime/scripts-final/s4_entity_core500.py')
    initial = read(root/'runtime/extraction-config.json')
    assert initial['script_sha256']==sha(root/'runtime/scripts/s4_entity_core500.py')
    assert initial['input_hash']==config['input_hash'] and initial['prompt_hash']==config['prompt_hash']
    candidates, valid, missing_core, reused = 0, 0, Counter(), 0
    for p,r in zip(inputs, rows):
        raw=read(root/f'parsed/{p["paper_id"]}.json')
        recomputed=extraction.materialize(raw,p,extraction.source_spans(p))
        assert all(r[k]==value for k,value in recomputed.items())
        assert read(root/f'papers/{p["paper_id"]}.json')==r
        signature=digest(dict(title=p['title'],abstract=p['abstract'],prompt=extraction.PROMPT))
        assert r['extraction_provenance']['signature']==signature
        assert r['extraction_provenance']['model']=='gpt-6-luna'
        assert r['extraction_provenance']['reasoning_effort']=='medium'
        reused+=r['extraction_provenance']['reused_pilot']
        projection=read(root/f'evidence/papers/{p["paper_id"]}.json')['source_projection']
        assert (projection['title'],projection['abstract'],projection['keywords'])==(
            p['title'],p['abstract'],p['original_labels']['keywords'])
        assert r['original_labels']==p['original_labels']
        candidates+=len(r['entity_candidates'])
        valid+=sum(c['literal_span_valid'] for c in r['entity_candidates'])
        missing_core.update(k for k,v in r['core'].items() if not v['text'].strip())
    attempts=[read(p) for p in root.glob('requests/**/*.attempt*.json')]
    successful_by_paper={}
    for attempt in attempts:
        req=attempt['request']
        assert req['model']=='gpt-6-luna' and req['reasoning']['effort']=='medium'
        body=req['input'].split('INPUT SOURCE SPANS:\n',1)[1]
        payload,_=json.JSONDecoder().raw_decode(body)
        assert set(payload)=={'paper_id','spans'}
        if attempt['ok']:
            assert attempt['response']['model']=='gpt-6-luna'
            assert attempt['response']['reasoning']['effort']=='medium'
            successful_by_paper.setdefault(payload['paper_id'],[]).append(attempt['parsed'])
    pilot_parsed={r['paper_id']:r for r in read(root/'evidence/pilot5/parsed_outputs.json')}
    for r in rows:
        pid=r['paper_id'];raw=read(root/f'parsed/{pid}.json')
        if r['extraction_provenance'].get('reused_from'):
            assert read(root/f'evidence/reuse500/parsed/{pid}.json')==raw
        elif r['extraction_provenance']['reused_pilot']:
            assert pilot_parsed[pid]==raw
        else:
            assert raw in successful_by_paper[pid]
    usage={key:sum(a.get('response',{}).get('usage',{}).get(key,0) for a in attempts)
           for key in ['input_tokens','output_tokens']}
    usage['reasoning_tokens']=sum(a.get('response',{}).get('usage',{}).get(
        'output_tokens_details',{}).get('reasoning_tokens',0) for a in attempts)
    assert all(progress[k]==v for k,v in usage.items())
    metadata=read(root/'embeddings/metadata.json')
    assert set(metadata)=={'abstract','core'}
    for view, models in metadata.items():
        assert set(models)=={m[0] for m in MODELS}
        texts=[r['abstract'] if view=='abstract' else r['core_text'] for r in rows]
        hashes=[hashlib.sha256(t.encode()).hexdigest() for t in texts]
        for slug, meta in models.items():
            path=root/meta['path']
            assert meta['file_sha256']==sha(path) and meta['input_sha256']==digest(texts)
            with np.load(path,allow_pickle=False) as data:
                assert data['vectors'].shape==(total,1024) and data['paper_ids'].tolist()==ids
                assert data['input_hashes'].tolist()==hashes
                assert np.isfinite(data['vectors']).all()
                assert np.allclose(np.linalg.norm(data['vectors'],axis=1),1,atol=2e-5)
            saved=read(root/meta['inputs'])
            assert [x['text'] for x in saved]==texts and [x['input_sha256'] for x in saved]==hashes
            assert max(x['token_length'] for x in saved)==meta['max_actual_tokens']<=8192
            assert all(r['embeddings'][view][slug]['row']==i and
                r['embeddings'][view][slug]['input_sha256']==hashes[i] for i,r in enumerate(rows))
    for slug,model_id,path,pooling in MODELS:
        assets=[]
        for file in sorted(path.rglob('*')):
            if not file.is_file() or file.name.startswith('.') or file.name.endswith('.part'):
                continue
            relative=file.relative_to(path)
            included=file.suffix in {'.json','.md'} and file.stat().st_size<100_000
            assets.append(dict(file=str(relative),bytes=file.stat().st_size,sha256=sha(file),included=included))
            if included:
                target=root/'evidence/embedding_models'/slug/relative
                target.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(file,target)
        write(root/'evidence/embedding_models'/slug/'MODEL_FILES.json',dict(
            model=model_id,revision=path.name,snapshot=str(path),files=assets))
    ref=Path('/data_big/iclr-s4/reference/qwen3-embedding-0.6b')
    for name in ['DOWNLOAD_MANIFEST.json','repository.json','source-0.json','official-github-README.md','download_model.py']:
        shutil.copyfile(ref/name,root/'evidence/embedding_models'/name)
    for item in read(root/'literature.json'):
        assert sha(root/'evidence/literature'/Path(item['source_file']).name)==item['source_sha256']
    if (root/'evidence/reuse500/ARCHIVE.json').exists():
        proof=read(root/'evidence/reuse500/ARCHIVE.json')
        assert sha(root/proof['copy'])==proof['sha256']
        with tarfile.open(root/proof['copy'],'r:gz') as archive:
            name=archive.getnames()[0].split('/',1)[0]
            old_manifest=json.load(archive.extractfile(name+'/AUDIT_MANIFEST.json'))
        old_hashes={item['path']:item['sha256'] for item in old_manifest['files']}
        reused_rows=[r for r in rows if r['extraction_provenance'].get('reused_from')]
        assert len(reused_rows)==sample['retained_completed']
        for row in reused_rows:
            pid=row['paper_id']
            assert row['extraction_provenance']['source_file_sha256']==old_hashes[f'papers/{pid}.json']
            assert sha(root/f'evidence/reuse500/parsed/{pid}.json')==old_hashes[f'parsed/{pid}.json']
    checks=dict(recorded_at=now(),papers=total,vectors=4*total,candidate_records=candidates,
        literal_valid_records=valid,literal_invalid_retained=candidates-valid,
        core_empty_fields=dict(missing_core),reused_pilot=reused,
        reused_completed=sum(bool(r['extraction_provenance'].get('reused_from')) for r in rows),api_usage_new=usage,
        successful_new_requests=sum(a['ok'] for a in attempts),failed_attempts=sum(not a['ok'] for a in attempts),
        checks=['Frozen inputs, prompt and executed scripts verified',
            'All candidates retained; original offsets and core evidence recomputed',
            'Original labels preserved; only title/abstract spans sent to API',
            'Model and medium reasoning confirmed in returned API records',
            f'Both models present for every view; all {4*total} vectors finite, unit norm, ordered and input-hash verified',
            'External model asset hashes and literature source checksums verified'],
        semantic_accuracy=None,retrieval_improvement=None)
    write(root/'AUDIT_CHECKS.json',checks)
    (root/'AUDIT_TRAIL.md').write_text(f'# {total:,} 篇实验留痕\n\n'+
        f'封存时间：{now()}。{total:,} 篇、四套各 {total}×1024 的向量。候选 {candidates:,}；'
        f'原文定位有效 {valid:,}；无效候选 {candidates-valid:,}，均保留并标记。\n\n'+
        '输入、原始标签、提示词、原始 API 请求/响应、逐篇候选与核心证据、两模型两视图的完整输入和向量、'
        '运行脚本、依赖版本、文献快照及模型校验值均保存。已有结果复用单独记录；新调用用量不含复用记录。\n\n'+
        '初始提取脚本和配置保存在 runtime/scripts 与 runtime/extraction-config.json；向量及最终导出脚本保存在 '
        'runtime/scripts-final。模型原生 pooling，完整文本、无 query instruction、float32，长度逐条预检。新视图优先 GPU，设备逐视图保存。\n\n'+
        '实体类型、角色和核心内容是模型判断；原文定位有效率不代表语义准确率、召回率或匹配收益。'
        '本实验未用人工金标准评估这些指标。文献用于自定义标注设计，并非训练复现。\n\n'+
        '文件级 SHA256 见 MANIFEST.sha256；完整大模型权重留在已固定版本的本地缓存，封存包保存外部资产校验值。\n')
    excluded={'AUDIT_MANIFEST.json','MANIFEST.sha256','pipeline.log','finalize.log'}
    files=sorted(p for p in root.rglob('*') if p.is_file() and '__pycache__' not in p.parts
        and p.name not in excluded and not p.name.endswith(('.tmp','.part')))
    _,key=credentials(Path('/home/yhr/auth'))
    for p in files:
        assert key.encode() not in p.read_bytes(), 'Credential unexpectedly present in artifact'
    listing=[dict(path=str(p.relative_to(root)),bytes=p.stat().st_size,sha256=sha(p)) for p in files]
    write(root/'AUDIT_MANIFEST.json',dict(sealed_at=now(),files=listing,file_count=len(listing),
        excluded=sorted(excluded|{'__pycache__','*.tmp','*.part','external large model assets'})))
    (root/'MANIFEST.sha256').write_text(''.join(f'{x["sha256"]}  {x["path"]}\n' for x in listing)+
        sha(root/'AUDIT_MANIFEST.json')+'  AUDIT_MANIFEST.json\n')
    target=root.parent.parent/'archives'/(root.name+'-'+datetime.now().astimezone().strftime('%Y%m%dT%H%M%S%z')+'.tar.gz')
    target.parent.mkdir(parents=True,exist_ok=True)
    with tarfile.open(target,'w:gz') as archive:
        for relative in [x['path'] for x in listing]+['AUDIT_MANIFEST.json','MANIFEST.sha256']:
            archive.add(root/relative,arcname=root.name+'/'+relative,recursive=False)
    with tarfile.open(target,'r:gz') as archive:
        for item in listing:
            assert hashlib.sha256(archive.extractfile(root.name+'/'+item['path']).read()).hexdigest()==item['sha256']
    checksum=sha(target)
    target.with_name(target.name+'.sha256').write_text(checksum+'  '+target.name+'\n')
    print(json.dumps(dict(archive=str(target),sha256=checksum,files=len(listing)+2,checks=checks),ensure_ascii=False),flush=True)


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('root',type=Path)
    main(parser.parse_args().root)
