#!/usr/bin/env python3
"""Persist the CPU preparation, final embedding pass and evidence seal across UI turns."""
import argparse
from datetime import datetime, timedelta
from pathlib import Path
import shutil
import subprocess
import sys
import time

from s4_reproduce500 import log, now, read, write


def active(unit):
    return subprocess.run(['systemctl','--user','is-active',unit],capture_output=True,text=True).stdout.strip() in {
        'active','activating','deactivating'}


def running_report(root):
    p=read(root/'progress.json')
    prep=read(root/'embedding-preparation.json') if (root/'embedding-preparation.json').exists() else {}
    line=(f'{now()} API {p["papers_completed"]}/500 | active={p.get("active_requests",0)}/3 '
        f'| failed_papers={p["papers_failed"]} attempts={p["failed_attempts"]} '
        f'| tokens in={p["input_tokens"]} out={p["output_tokens"]} '
        f'| stage_eta={p.get("stage_eta") or p["state"]} '
        f'| embeddings={max(p.get("embedding_completed",0),prep.get("embedding_completed",0))}/2000')
    with (root/'runtime/progress.log').open('a') as output:
        output.write(line+'\n')
    print(line,flush=True)
    text=['# 500 篇科学实体与核心内容：运行中', '',f'更新时间：{now()}', '',
        f'- 提取：{p["papers_completed"]}/500；当前失败 {p["papers_failed"]}。',
        f'- 本阶段预计完成时间：{p.get("stage_eta") or "采样中"}（北京时间，随实际速度更新）。',
        f'- 并行摘要向量：{prep.get("embedding_completed",0)}/1000；{prep.get("phase","准备中")}。',
        '- 完成目标：原始摘要及三字段核心内容，各使用 BGE-M3 和 Qwen3-Embedding-0.6B，共 2000 条向量。',
        '- gpt-6-luna / medium；API 最大并发 3；已完成摘要向量来自 CPU，后续向量优先 4060 Ti。', '',
        '[详细进度](PROGRESS.md) · [摘要编码进度](embedding-preparation.json) · '
        '[协议](PROTOCOL.md) · [文献依据](LITERATURE.md) · [日志](runtime/run.log)', '',
        '作者原始领域和关键词独立保留；标题摘要为 LLM 内容输入。候选词条及核心字段均保留原文依据。',
        '此处预计时间覆盖提取阶段；核心向量编码和封存随后自动执行。']
    temporary=root/'REPORT.md.tmp';temporary.write_text('\n'.join(text)+'\n');temporary.replace(root/'REPORT.md')


def main(root, prepare):
    runtime=root/'runtime'
    scripts=Path(__file__).resolve().parent
    if prepare:
        from s4_dual_embeddings import encode_all
        class Progress:
            def __init__(self):
                self.data={'state':'running','started_at':now()}
            def save(self):
                remaining=self.data.get('batch_total',0)-self.data.get('batch_completed',0)
                rate=self.data.get('embedding_seconds_per_item')
                self.data['updated_at']=now()
                self.data['stage_eta']=(datetime.now().astimezone()+timedelta(seconds=remaining*rate)).isoformat(
                    timespec='seconds') if remaining and rate else None
                write(root/'embedding-preparation.json',self.data)
        progress=Progress()
        rows=read(root/'inputs.json')
        encode_all(root,rows,progress,views={'abstract':[r['abstract'] for r in rows]})
        progress.data.update(state='completed',finished_at=now());progress.save()
        return
    log('pipeline_wait_for_extraction_and_abstract_preparation')
    for unit in ['iclr-s4-entity-core500-extract.service','iclr-s4-entity-core500-abstract.service']:
        while active(unit):
            running_report(root)
            time.sleep(15)
    running_report(root)
    # Per-paper checkpoints make a bounded retry cheap if a temporary API error survived client retries.
    for retry in range(3):
        if (root/'extractions.json').exists() and len(read(root/'extractions.json'))==500:
            break
        log('pipeline_resume_extraction',retry=retry+1)
        with (runtime/'run.log').open('a') as output:
            subprocess.run([sys.executable,str(runtime/'scripts/s4_entity_core500.py'),
                '--root',str(root),'--stage','extract'],stdout=output,stderr=subprocess.STDOUT)
    else:
        raise RuntimeError('Extraction still incomplete after bounded resume; see per-paper failures')
    for name in ['config.json','PROTOCOL.md','progress.json']:
        shutil.copyfile(root/name,runtime/('extraction-'+name))
    with (runtime/'run.log').open('a') as output:
        subprocess.run([sys.executable,str(scripts/'s4_entity_core500.py'),
            '--root',str(root),'--stage','embed'],stdout=output,stderr=subprocess.STDOUT,check=True)
    with (runtime/'finalize.log').open('a') as output:
        subprocess.run([sys.executable,str(scripts/'s4_entity_core500_audit.py'),str(root)],
            stdout=output,stderr=subprocess.STDOUT,check=True)
    log('pipeline_all_stages_completed_and_archive_verified')


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('root',type=Path)
    parser.add_argument('--prepare-abstract',action='store_true')
    args=parser.parse_args();main(args.root,args.prepare_abstract)
