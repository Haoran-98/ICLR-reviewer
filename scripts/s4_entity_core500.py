#!/usr/bin/env python3
"""Checkpointed 500-paper scientific extraction with two embedding models for every view."""
import argparse
from collections import Counter
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from datetime import datetime, timedelta
import hashlib
import json
from pathlib import Path
import shutil
import threading
import time

import psycopg
from psycopg.rows import dict_row

import s4_entity_core5 as pilot
import s4_taxoadapt100_api as api
from s4_reproduce500 import digest, log, now, read, write

ROOT = Path('/data_big/iclr-s4/experiments/entity_core500_gpt6luna_medium_dual_v1')
SOURCE = Path('/data_big/iclr-s4/experiments/repro500_qwen38_27b_q3_medium_64k_v2')
PILOT = pilot.ROOT


class Progress(api.Progress):
    def __init__(self, root):
        super().__init__(root)
        self.stage_started = time.monotonic()
        total=len(read(root/'inputs.json')) if (root/'inputs.json').exists() else 500
        self.last_progress_log=0
        self.data.update(papers=total,papers_completed=0,papers_failed=0,reused_pilot=0,reused_completed=0,
                         embedding_completed=0,embedding_total=4*total)
        attempts = [read(p) for p in root.glob('requests/**/*.attempt*.json')]
        self.data.update(successful_requests=sum(bool(a.get('ok')) for a in attempts),
                         failed_attempts=sum(not a.get('ok') for a in attempts))
        for key in ['input_tokens','output_tokens']:
            self.data[key] = sum(a.get('response',{}).get('usage',{}).get(key,0) for a in attempts)
        self.data['reasoning_tokens'] = sum(a.get('response',{}).get('usage',{}).get(
            'output_tokens_details',{}).get('reasoning_tokens',0) for a in attempts)

    def save(self):
        with self.lock:
            d = dict(self.data,updated_at=now(),elapsed_seconds=time.monotonic()-self.started,
                     active_requests=len(self.active),active=list(self.active.values()))
            remaining = max(0,d['batch_total']-d['batch_completed'])
            rate = None
            if d['phase'].startswith('LLM') and self.recent:
                rate = sum(self.recent)/len(self.recent)/3
            elif d.get('embedding_seconds_per_item'):
                rate = d['embedding_seconds_per_item']
            d['stage_eta'] = ((datetime.now().astimezone()+timedelta(seconds=remaining*rate))
                .isoformat(timespec='seconds') if rate and remaining and d['state']=='running' else None)
            write(self.root/'progress.json',d)
            lines = [f'# {d["papers"]:,} 篇：科学实体、核心内容与双模型 embedding', '',f'更新时间：{d["updated_at"]}', '',
                f'- 状态：{d["state"]}；阶段：{d["phase"]}',
                f'- 提取模型：gpt-6-luna / medium；API 并发上限 3，当前 {len(self.active)}，峰值 {d["concurrency_peak"]}',
                f'- 论文提取：{d["papers_completed"]}/{d["papers"]}；待处理失败：{d["papers_failed"]}；复用已有结果：{d["reused_completed"]}（含原始 5 篇试跑 {d["reused_pilot"]}）',
                f'- 向量：{d["embedding_completed"]}/{d["embedding_total"]}（两个模型 × 两个文本视图 × {d["papers"]} 篇）',
                f'- 当前阶段进度：{d["batch_completed"]}/{d["batch_total"]}',
                f'- 本阶段预计完成时间：{d["stage_eta"] or ("已完成" if d["state"]=="completed" else "采样中／阶段未启动")}',
                '- 预计时间仅覆盖当前阶段；后续向量编码按实际速度另行估计。',
                f'- 本次进程耗时：{d["elapsed_seconds"]/60:.1f} 分钟',
                f'- 累计新成功 API 请求 {d["successful_requests"]}；失败尝试 {d["failed_attempts"]}；缓存读取 {d["cached_requests"]}',
                f'- 本轮累计已返回用量：输入 {d["input_tokens"]:,}；输出 {d["output_tokens"]:,}；其中思考 {d["reasoning_tokens"]:,} token。', '',
                f'[报告]({self.root}/REPORT.md) · [日志]({self.root}/runtime/run.log) · '
                f'[逐篇检查点]({self.root}/papers/) · [实验协议]({self.root}/PROTOCOL.md)']
            if d.get('error'):
                lines += ['',d['error']]
            temp=self.root/'PROGRESS.md.tmp';temp.write_text('\n'.join(lines)+'\n');temp.replace(self.root/'PROGRESS.md')
            if d['state']=='running':
                temp=self.root/'REPORT.md.tmp';temp.write_text('\n'.join(lines)+'\n');temp.replace(self.root/'REPORT.md')
            if time.monotonic()-self.last_progress_log>=15 or d['state']!='running':
                self.last_progress_log=time.monotonic()
                line=(f'{now()} {d["phase"]} | API {d["papers_completed"]}/{d["papers"]} '
                    f'active={len(self.active)}/3 failed={d["papers_failed"]} retry_attempts={d["failed_attempts"]} '
                    f'| tokens in={d["input_tokens"]} out={d["output_tokens"]} '
                    f'| embeddings={d["embedding_completed"]}/{d["embedding_total"]} '
                    f'| stage_eta={d["stage_eta"] or d["state"]}')
                with (self.root/'runtime/progress.log').open('a') as output:output.write(line+'\n')
                print(line,flush=True)


def snapshot(root):
    if (root/'inputs.json').exists():
        return read(root/'inputs.json')
    inputs=read(SOURCE/'inputs.json');gold={p['paper_id']:p for p in read(SOURCE/'evaluation/gold.json')}
    ids=[p['paper_id'] for p in inputs]
    assert len(ids)==len(set(ids))==500
    with psycopg.connect('postgresql://yhr@127.0.0.1:55432/iclr_reviewer',row_factory=dict_row) as c:
        c.execute('SET TRANSACTION READ ONLY')
        versions={p['paper_id']:p for p in c.execute('SELECT paper_id,paper_version_id,source_record_id,content_hash,'
            'title,abstract,keywords FROM core.latest_paper_version WHERE paper_id=ANY(%s)',(ids,)).fetchall()}
        areas={p['paper_id']:p for p in c.execute('SELECT a.paper_id,a.source_record_id,a.explicit_area_id,e.raw_label '
            'FROM core.paper_area a JOIN core.explicit_area e USING(explicit_area_id) '
            'WHERE a.paper_id=ANY(%s) AND a.is_primary',(ids,)).fetchall()}
        source_ids=sorted({p['source_record_id'] for p in versions.values()} | {p['source_record_id'] for p in areas.values()})
        sources={s['source_record_id']:s for s in c.execute('SELECT source_record_id,source_kind,source_path,sha256,'
            'fetched_at,raw_payload FROM raw.source_record WHERE source_record_id=ANY(%s)',(source_ids,)).fetchall()}
    papers=[]
    for p in inputs:
        pid=p['paper_id'];v=versions[pid];a=areas[pid];g=gold[pid]
        assert (v['title'],v['abstract'])==(p['title'],p['abstract']), f'Frozen text changed: {pid}'
        assert a['raw_label']==g['raw_label']
        row=dict(p,year=g['year'],forum_id=g['forum_id'],original_labels=dict(primary_area=a['raw_label'],keywords=v['keywords']),
            provenance=dict(paper_version_id=v['paper_version_id'],paper_source_record_id=v['source_record_id'],
                area_source_record_id=a['source_record_id'],explicit_area_id=a['explicit_area_id'],content_hash=v['content_hash']))
        source=sources[v['source_record_id']];payload=source['raw_payload']
        assert payload['title']==p['title'] and payload['abstract']==p['abstract'] and payload['keywords']==v['keywords']
        write(root/f'evidence/papers/{pid}.json',dict(paper_id=pid,provenance=row['provenance'],
            database_source={k:str(value) for k,value in source.items() if k!='raw_payload'},
            source_projection={k:payload.get(k) for k in ['year','forum','title','abstract','keywords','primary_area','area_dir','pdf_url']}))
        papers.append(row)
    write(root/'inputs.json',papers)
    write(root/'sample.json',dict(source=str(SOURCE),input_hash=digest(papers),papers=500,
        years=dict(Counter(p['year'] for p in papers)),areas=dict(Counter(p['original_labels']['primary_area'] for p in papers))))
    return papers


def extract_one(root,paper,client,pilot_raw):
    target=root/f'papers/{paper["paper_id"]}.json'
    signature=digest(dict(title=paper['title'],abstract=paper['abstract'],prompt=pilot.PROMPT))
    if target.exists():
        cached=read(target)
        if cached['extraction_provenance']['signature']!=signature or cached['original_labels']!=paper['original_labels']:
            raise ValueError('Checkpoint does not match frozen input')
        return cached
    spans=pilot.source_spans(paper)
    schema=pilot.response_schema(spans)
    schema['properties']['paper_id']={'type':'integer','const':paper['paper_id']}
    prompt=pilot.PROMPT+json.dumps(dict(paper_id=paper['paper_id'],spans=spans),ensure_ascii=False)
    reused=paper['paper_id'] in pilot_raw
    if reused:
        raw=pilot_raw[paper['paper_id']]
        api.jsonschema.validate(raw,schema)
        result=pilot.materialize(raw,paper,spans)
    else:
        raw=client.ask('scientific_entity_and_core',prompt,tokens=7168,schema=schema)
        for repair in range(3):
            try:
                result=pilot.materialize(raw,paper,spans)
                break
            except (ValueError,KeyError) as exc:
                if repair==2:
                    raise
                prompt += '\nValidation error: '+str(exc)+'. Correct the full JSON using only valid evidence IDs.\nPREVIOUS OUTPUT:\n'+json.dumps(raw,ensure_ascii=False)
                raw=client.ask('repair_core_evidence',prompt,tokens=7168,schema=schema)
    result['extraction_provenance']=dict(signature=signature,prompt_hash=digest(pilot.PROMPT),model='gpt-6-luna',
        reasoning_effort='medium',reused_pilot=reused,recorded_at=now())
    write(root/f'parsed/{paper["paper_id"]}.json',raw)
    write(target,result)
    return result


def extract_all(root,papers,progress):
    pilot_raw={}
    if read(PILOT/'config.json')['prompt_hash']==digest(pilot.PROMPT):
        old_inputs={p['paper_id']:p for p in read(PILOT/'inputs.json')}
        current={p['paper_id']:p for p in papers}
        for r in read(PILOT/'parsed_outputs.json'):
            pid=r['paper_id']
            if pid in current and all(current[pid][k]==old_inputs[pid][k] for k in ['title','abstract']):
                pilot_raw[pid]=r
        for name in ['config.json','inputs.json','parsed_outputs.json','AUDIT_MANIFEST.json']:
            dst=root/'evidence/pilot5'/name;dst.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(PILOT/name,dst)
        shutil.copytree(PILOT/'requests',root/'evidence/pilot5/requests',dirs_exist_ok=True)
    progress.data.update(phase='LLM 科学实体候选与三字段提取',batch='extraction',batch_total=len(papers),batch_completed=0)
    client=api.Luna(root)
    failures={}
    def complete(paper,future):
        try:
            row=future.result()
            with progress.lock:
                progress.data['papers_completed']+=1
                progress.data['reused_pilot']+=bool(row['extraction_provenance']['reused_pilot'])
                progress.data['reused_completed']+=bool(row['extraction_provenance'].get('reused_from'))
        except Exception as exc:
            failures[paper['paper_id']]=dict(paper_id=paper['paper_id'],error=type(exc).__name__+': '+str(exc),at=now())
            log('paper_failed',**failures[paper['paper_id']])
        with progress.lock:
            progress.data.update(papers_failed=len(failures),batch_completed=progress.data['papers_completed']+len(failures))
            write(root/'failures.json',list(failures.values()))
            progress.save()
        log('paper_progress',completed=progress.data['papers_completed'],failed=len(failures),total=len(papers))
    # Count reusable checkpoints first so progress and ETA reflect only remaining API work.
    ordered=sorted(papers,key=lambda p:not (root/f'papers/{p["paper_id"]}.json').exists())
    with ThreadPoolExecutor(max_workers=3) as pool:
        pending={};iterator=iter(ordered)
        for _ in range(3):
            p=next(iterator);pending[pool.submit(extract_one,root,p,client,pilot_raw)]=p
        while pending:
            done,_=wait(pending,return_when=FIRST_COMPLETED)
            for future in done:
                p=pending.pop(future);complete(p,future)
                if any(f'API HTTP {status}' in item['error'] for item in failures.values() for status in [401,403,404]):
                    for other in pending:other.cancel()
                    raise RuntimeError('API authentication/model endpoint rejected; stopping further submissions')
                following=next(iterator,None)
                if following:
                    pending[pool.submit(extract_one,root,following,client,pilot_raw)]=following
    if failures:
        raise RuntimeError(f'{len(failures)} papers need retry; resume uses saved per-paper checkpoints')
    rows=[read(root/f'papers/{p["paper_id"]}.json') for p in papers]
    write(root/'extractions.json',rows)
    return rows


def report(root,rows,progress):
    count=sum(len(r['entity_candidates']) for r in rows)
    valid=sum(c['literal_span_valid'] for r in rows for c in r['entity_candidates'])
    write(root/'metrics.json',dict(papers=len(rows),candidate_records=count,literal_valid_records=valid,
        embedding_models=['BAAI/bge-m3','Qwen/Qwen3-Embedding-0.6B'],embedding_views=['abstract','core'],
        expected_vectors=4*len(rows),semantic_accuracy=None,retrieval_quality=None))
    lines=[f'# {len(rows):,} 篇科学实体与核心内容：双模型 embedding', '',f'更新时间：{now()}','',
        '标题和摘要用于实体候选及研究问题／方法／研究对象提取；作者领域与关键词独立保留，不输入 LLM。',
        f'原始摘要与三字段核心内容各使用 BGE-M3、Qwen3-Embedding-0.6B 保存一份向量，共 {4*len(rows):,} 条。',
        '提取模型 gpt-6-luna / medium，API 并发上限 3；两个嵌入模型优先使用 4060 Ti，设备逐视图记录。', '',
        f'论文 {len(rows)}；候选 {count:,}，可定位原文 {valid:,}。这不是语义准确率或召回率。', '',
        '[实验协议](PROTOCOL.md) · [文献依据](LITERATURE.md) · [进度](PROGRESS.md) · [完整结果](results.json) · [向量](embeddings/metadata.json)', '',
        '| 论文 ID | 标题 | 候选数 | 原文有效数 | 逐篇数据 |','|---|---|---:|---:|---|']
    for r in rows:
        title=r['title'].replace('|','\\|').replace('\n',' ')
        lines += [f'| {r["paper_id"]} | {title} | {len(r["entity_candidates"])} | '
            f'{sum(c["literal_span_valid"] for c in r["entity_candidates"])} | [JSON](papers/{r["paper_id"]}.json) |']
    (root/'REPORT.md').write_text('\n'.join(lines)+'\n')


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root',type=Path,default=ROOT)
    parser.add_argument('--stage',choices=['all','extract','embed'],default='all')
    args=parser.parse_args();root=args.root;root.mkdir(parents=True,exist_ok=True);(root/'runtime').mkdir(exist_ok=True)
    api.MODEL,api.EFFORT,api.VERSION='gpt-6-luna','medium',root.name
    api.AUTH,api.GATE=Path('/home/yhr/auth'),threading.BoundedSemaphore(3)
    progress=api.PROGRESS=Progress(root)
    stop=threading.Event()
    def refresh():
        while not stop.wait(15):
            progress.save()
    threading.Thread(target=refresh,daemon=True).start()
    try:
        papers=snapshot(root)
        for name in ['PROMPT.md','LITERATURE.md','literature.json']:
            shutil.copyfile(PILOT/name,root/name)
        shutil.copytree(PILOT/'evidence/literature',root/'evidence/literature',dirs_exist_ok=True)
        (root/'PROTOCOL.md').write_text(f'# {len(papers):,} 篇执行协议\n\n'+
            '使用 inputs.json 的冻结样本，抽样规则见 sample.json；标题摘要为唯一 LLM 内容输入。原始作者领域和关键词独立保存。\n\n'+
            '沿用 5 篇试验的提示词与类型；保留全部实体候选及原文位置；核心内容仅含问题、方法、对象。\n\n'+
            'gpt-6-luna / medium，最大 API 并发 3，逐篇落盘、断点续跑。输入一致的 5 篇试跑结果复用并记录来源。\n\n'+
            '所有 embedding 视图均必须同时保存 BGE-M3 与 Qwen3-Embedding-0.6B。当前视图为原始摘要和三字段核心内容。\n\n'+
            'float32 编码；已有完整视图保留原设备结果，新视图优先使用 cuda:0 / 4060 Ti。使用各自原生 pooling，完整输入上限 8192 token，逐条预检，超长报错以防静默截断；不添加 query instruction。模型、版本、输入、设备、维度和校验值独立保存。\n\n'+
            '不将原文定位通过比例当作语义准确率，不据此宣称检索或审稿人匹配提升。\n')
        write(root/'config.json',dict(model=api.MODEL,reasoning_effort=api.EFFORT,concurrency_limit=3,papers=len(papers),
            source=read(root/'sample.json').get('source',str(SOURCE)),input_hash=digest(papers),prompt_hash=digest(pilot.PROMPT),
            embedding_models=['BAAI/bge-m3','Qwen/Qwen3-Embedding-0.6B'],views=['abstract','core'],
            device='per-model/view; see embeddings/metadata.json',
            script_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest()))
        if not (root/'runtime/extraction-config.json').exists():
            shutil.copyfile(root/'config.json',root/'runtime/extraction-config.json')
        if args.stage=='embed':
            rows=read(root/'extractions.json');progress.data['papers_completed']=len(rows)
            progress.data['reused_pilot']=sum(r['extraction_provenance']['reused_pilot'] for r in rows)
            progress.data['reused_completed']=sum(bool(r['extraction_provenance'].get('reused_from')) for r in rows)
        else:
            rows=extract_all(root,papers,progress)
        if args.stage!='extract':
            from s4_dual_embeddings import encode_all
            encode_all(root,rows,progress)
            write(root/'results.json',rows)
            for row in rows:
                write(root/f'papers/{row["paper_id"]}.json',row)
            progress.data.update(state='completed',phase=f'{len(rows):,} 篇提取与四套向量全部完成',finished_at=now())
        else:
            progress.data.update(state='extraction_completed',phase=f'{len(rows):,} 篇提取完成，等待双模型向量',finished_at=now())
        report(root,rows,progress)
    except BaseException as exc:
        progress.data.update(state='failed',error=type(exc).__name__+': '+str(exc))
        raise
    finally:
        stop.set();progress.save()


if __name__=='__main__':
    main()
