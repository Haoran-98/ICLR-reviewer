#!/usr/bin/env python3
"""Run the established mechanism-induction pipeline on the LLM primary area only."""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import fcntl
import json
import os
from pathlib import Path
import shutil
import signal
import threading
from types import SimpleNamespace

import full_s4_review_skills as f

AREA='foundation_or_frontier_models_including_llms'
ROOT=f.ROOT.parent/'modular_skill_llm_area_mechanisms_v1'
LABEL='基础与前沿模型（含 LLM）'


def scope_ids(gold,eligible):
    population=sorted(x['paper_id'] for x in gold if x['area']==AREA)
    allowed=set(population)
    return population,sorted(set(eligible)&allowed)


def validate_scope(root):
    manifest=f.s.read(root/'manifest.json')
    f.s.require(manifest['area']==AREA,'Changed primary area')
    f.s.require(manifest['area_runner_sha256']==f.s.sha(__file__),'Area runner changed; migrate explicitly')
    parent=Path(manifest['parent_run_root'])
    f.s.require(f.s.sha(parent/'manifest.json')==manifest['parent_manifest_sha256'],'Parent snapshot changed')
    source=Path(manifest['source_root'])
    ids,eligible=scope_ids(f.s.read(source/'evaluation/gold.json'),f.s.read(parent/'manifest.json')['source_ids'])
    f.s.require(ids==manifest['area_population_ids'] and eligible==manifest['source_ids'],'Area population mismatch')
    f.s.require(f.s.sha(root/'jobs.json')==manifest['jobs_sha256'],'Scoped jobs changed')
    f.s.require(f.s.sha(root/'eligibility.json')==manifest['eligibility_sha256'],'Scoped eligibility changed')
    jobs=f.s.read(root/'jobs.json');partitions=defaultdict(list);allowed=set(eligible)
    f.s.require({int(p.stem) for p in (root/'inputs').glob('*.json')}==allowed,'Unexpected input outside frozen scope')
    for job in jobs.values():
        f.s.require(job['paper_id'] in allowed,'Outside-area job')
        partitions[job['paper_id']].extend(job['unit_ids'])
    for pid in eligible:
        row=f.s.read(root/f'inputs/{pid}.json')
        f.s.require(row['area']==AREA and f.s.digest(row)==manifest['input_hashes'][str(pid)],'Outside-area or changed input')
        units=[x['passage_id'] for x in row['review_units']]
        f.s.require(len(partitions[pid])==len(set(partitions[pid])) and set(partitions[pid])==set(units),
                    'Scoped review units lost or duplicated')
    f.s.write(root/'SCOPE_AUDIT.json',dict(check='passed',area=AREA,population=len(ids),
        eligible_papers=len(eligible),jobs=len(jobs),outside_area_inputs=0,outside_area_jobs=0,
        all_review_units_partitioned=True))
    return manifest


def prepare(args):
    root=args.root
    if (root/'manifest.json').exists():
        f.prepare(args)
        return validate_scope(root)
    parent=args.parent_run
    old=f.s.read(parent/'manifest.json')
    f.s.require(old['protocol_hashes']==f.hashes(),'Parent scientific/transport protocol changed')
    source=Path(old['source_root'])
    f.s.require(source==args.source_root,'Wrong S4 source')
    gold=f.s.read(source/'evaluation/gold.json')
    population,eligible=scope_ids(gold,old['source_ids']);selected=set(population);allowed=set(eligible)
    f.s.require(population and eligible,'No eligible LLM papers')
    jobs={key:job for key,job in f.s.read(parent/'jobs.json').items() if job['paper_id'] in allowed}
    eligibility=[x for x in f.s.read(parent/'eligibility.json') if x['paper_id'] in selected]
    root.mkdir(parents=True,exist_ok=True)
    for pid in eligible:
        target=root/f'inputs/{pid}.json';target.parent.mkdir(exist_ok=True)
        shutil.copyfile(parent/f'inputs/{pid}.json',target)
        f.s.require(f.s.digest(f.s.read(target))==old['input_hashes'][str(pid)],'Parent input changed')
    reused=[]
    for key in jobs:
        path=parent/f'cases/{key}.json'
        if not path.exists():continue
        f.s.require((parent/f'requests/extract/{key}/result.json').exists(),'Missing raw cache for reusable case')
        (root/'cases').mkdir(exist_ok=True)
        shutil.copyfile(path,root/f'cases/{key}.json')
        shutil.copytree(parent/f'requests/extract/{key}',root/f'requests/extract/{key}')
        reused.append(key)
    exclusions=[x for x in f.s.read(parent/'review_exclusions.json') if x['paper_id'] in selected]
    f.s.write(root/'jobs.json',jobs);f.s.write(root/'eligibility.json',eligibility)
    f.s.write(root/'review_exclusions.json',exclusions);f.s.write(root/'extraction_failures.json',{})
    config=f.s.read(parent/'config.json')
    config.update(area=AREA,area_population=len(population),eligible_papers=len(eligible),
        scope='one_primary_area_only',reused_extraction_jobs=len(reused),
        usage_includes_reused_requests=bool(reused),concurrency_limit=args.concurrency)
    f.s.write(root/'config.json',config)
    manifest=dict(old)
    manifest.update(created_at=f.s.now(),area=AREA,area_population_ids=population,
        source_population=len(population),full_s4_population=len(gold),source_ids=eligible,
        population_share=len(population)/len(gold),parent_run_root=str(parent),
        parent_manifest_sha256=f.s.sha(parent/'manifest.json'),area_runner_sha256=f.s.sha(__file__),
        source_years=dict(Counter(x['year'] for x in gold if x['paper_id'] in selected)),
        eligible_areas={AREA:len(eligible)},input_hashes={str(pid):old['input_hashes'][str(pid)] for pid in eligible},
        jobs=len(jobs),jobs_sha256=f.s.sha(root/'jobs.json'),eligibility_sha256=f.s.sha(root/'eligibility.json'),
        review_exclusions=dict(Counter(x['reason'] for x in exclusions)),
        max_curation_requests=2*len(jobs)*32,reused_extraction_job_ids=reused,
        protocol_hashes=f.hashes(),
        scope_policy='Only this primary area enters extraction, retrieval, curation and exported learned rules; no parent library imported')
    for key in ['retry_allowances_sha256','runtime_migrations']:manifest.pop(key,None)
    runtime=root/'runtime';runtime.mkdir(exist_ok=True)
    for name in manifest['protocol_hashes']:
        dest=runtime/name;dest.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(f.s.REPO/name,dest)
    shutil.copyfile(__file__,runtime/Path(__file__).name)
    f.s.write(root/'manifest.json',manifest)
    (root/'SCOPE.md').write_text('\n'.join(['# '+LABEL+'：独立领域版本','',
        f'S4 范围 {len(population):,} 篇，占全部 {len(gold):,} 篇的 {len(population)/len(gold):.2%}。',
        f'合格配对 {len(eligible):,} 篇，抽取任务 {len(jobs):,} 个。',
        '仅从该领域的冻结论文和 Review 快照提炼；候选检索、共享规则和模块库均限于本领域。',
        f'沿用 gpt-6-luna / medium / 最多 {args.concurrency} 并发，以及完整 Review 单元记账与来源支持门槛。',
        'general 规则的跨领域来源门槛保持不变；本领域内的重复来源不能自动将其标为 source_supported。',
        '通用流程协议可复用，其他领域已经学习的规则未导入。',
        '抽取源正文仍为定向证据片段；后续实际审稿须完整保留主文。',
        '全量运行保持暂停。本目录单独执行抽取、整理、导出和审计。','']))
    result=validate_scope(root)
    f.s.emit('area_snapshot_frozen',area=AREA,population=len(population),eligible=len(eligible),jobs=len(jobs),reused=len(reused))
    return result


class Client(f.Client):
    def save(self):
        with self.lock:
            super().save()
            path=self.root/'PROGRESS.md'
            path.write_text(path.read_text().replace('# 全量 S4 Skill 提炼进度','# '+LABEL+'：Skill 提炼进度')+
                            '\n范围：仅 '+AREA+'；全量运行保持暂停。\n')


def report(root):
    result=f.report(root)
    result.update(area=AREA,scope='one_primary_area_only')
    f.s.write(root/'summary.json',result)
    path=root/'REPORT.md';text=path.read_text()
    text=text.replace('# 全量 S4：机制级模块化审稿 Skill','# '+LABEL+'：机制级模块化审稿 Skill')
    text=text.replace('S4 全部 ',LABEL+'范围内 ')
    text=text.replace('全部年份和领域进入资格核查；此前试审样本若纳入本轮，即成为开发来源。',
                      '仅该大领域进入本轮提炼；未导入其他领域候选或已学习规则。')
    text=text.replace('最多 3 并发',f'最多 {result["concurrency_limit"]} 并发')
    path.write_text(text)
    return result


def export(root,state):
    # In a single-area run the domain key is known even without paired manuscript support.
    # Keep source_areas untouched: it counts paired provenance, not just dataset membership.
    groups=defaultdict(list)
    for rule in state['rules'].values():
        if rule['status']=='deprecated':continue
        key=('domain-'+f.s.slug(AREA) if rule['level']=='domain' else f.s.module_key(rule))
        groups[(rule['status'],key+'-'+rule['mechanism_family'].replace('_','-'))].append(rule)
    modules=[]
    for (status,key),rules in sorted(groups.items()):
        name='review-'+key[:42]+'-'+f.s.digest([status,key])[:8]
        folder=root/'skills'/status/name;folder.mkdir(parents=True,exist_ok=True)
        text='\n'.join(['---','name: '+name,
            'description: Apply conditional scientific review checks for '+key+'.','---','',
            'Scope: '+AREA+'. Status: '+status+'. Historical provenance is not scientific validation. '
            'Verify applicability, definitions, failure mechanisms and clearing evidence on the new manuscript. '
            'Missing retrieved evidence is unknown. Keep complete main text when reviewing.','',
            *[f.s.rule_markdown(rule)+'\n对象：'+rule['review_object']+'\n失效机制：'+rule['failure_mechanism']+'\n' for rule in rules]])
        (folder/'SKILL.md').write_text(text);f.s.write(folder/'rules.json',rules)
        modules.append(dict(module_id=key,status=status,path=str(folder.relative_to(root)/'SKILL.md'),
                            rule_ids=[x['rule_id'] for x in rules]))
    f.s.write(root/'registry.json',dict(area=AREA,library_hash=f.s.digest(state),modules=modules))


def check_concurrency_history(root,history):
    events=[]
    for path in root.glob('requests/*/*/attempt_*.json'):
        record=f.s.read(path)
        f.s.require(record.get('finished_at'),'Unreconciled HTTP attempt')
        events.extend([(record['started_at'],1),(record['finished_at'],-1)])
    history=sorted(history,key=lambda x:x['effective_at']);active=0;peak=0
    for timestamp,delta in sorted(events,key=lambda x:(x[0],x[1])):
        active+=delta;peak=max(peak,active)
        if delta==1:
            limits=[x['limit'] for x in history if x['effective_at']<=timestamp]
            f.s.require(limits and active<=limits[-1],'Concurrency exceeded the limit authorized at request time')
    return peak


def audit(args,manifest):
    history=manifest.get('concurrency_history',[dict(effective_at=manifest['created_at'],limit=args.concurrency)])
    # The base audit scans the entire run, including the earlier user-authorized four-request phase.
    base_args=SimpleNamespace(**vars(args));base_args.concurrency=max(x['limit'] for x in history)
    result=f.audit(base_args,manifest)
    result.update(concurrency_peak=check_concurrency_history(args.root,history),
                  current_concurrency_limit=args.concurrency,concurrency_history=history)
    f.s.write(args.root/'AUDIT.json',result)
    return result


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('command',choices=['prepare','run','report','audit'])
    p.add_argument('--root',type=Path,default=ROOT)
    p.add_argument('--parent-run',type=Path,default=f.ROOT)
    p.add_argument('--source-root',type=Path,default=f.s.SOURCE)
    p.add_argument('--concurrency',type=int,choices=[1,2,3,4],default=3)
    p.add_argument('--auth',type=Path,default=Path(os.environ.get('ICLR_AUTH_FILE',Path.home()/'auth')))
    args=p.parse_args();args.root.mkdir(parents=True,exist_ok=True)
    if args.command=='report':print(json.dumps(report(args.root),ensure_ascii=False));return
    with (args.root/'run.lock').open('a') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        manifest=prepare(args)
        if args.command=='prepare':report(args.root);return
        if args.command=='audit':print(json.dumps(audit(args,manifest),ensure_ascii=False));return
        client=Client(args);heartbeat_stop=threading.Event();pause_requested=threading.Event()
        def pause(signum,frame):
            pause_requested.set();client.stop.set();client.lifecycle='pausing'
        signal.signal(signal.SIGINT,pause);signal.signal(signal.SIGTERM,pause)
        def heartbeat():
            while not heartbeat_stop.wait(20):client.save();report(args.root)
        thread=threading.Thread(target=heartbeat,name='llm-area-progress',daemon=True);thread.start()
        try:
            failures=f.extract(args,manifest,client)
            f.s.require(not failures,'Extraction failures remain; retain them before curation')
            candidates=f.collect_candidates(args.root,manifest)
            state,queue=f.curate(args,manifest,client,candidates)
            export(args.root,state);validate_scope(args.root);audit(args,manifest)
            f.s.write(args.root/'FROZEN.json',dict(area=AREA,library_hash=f.s.digest(state),frozen_at=f.s.now(),
                status='llm_area_mechanisms_unadjudicated',scientific_accuracy_verified=False))
            client.lifecycle='completed'
        except BaseException as error:
            if pause_requested.is_set():client.lifecycle='paused';client.last_error=None
            else:client.lifecycle='failed';client.last_error=str(error);raise
        finally:
            heartbeat_stop.set();thread.join(timeout=30);client.save();report(args.root)


if __name__=='__main__':main()
