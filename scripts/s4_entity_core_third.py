#!/usr/bin/env python3
"""Freeze a stratified one-third corpus sample and run the established extraction pipeline."""
import argparse
from collections import Counter, defaultdict
import math
from pathlib import Path
import random
import shutil
import subprocess
import sys
import time

import psycopg
from psycopg.rows import dict_row

import s4_entity_core5 as extraction
from s4_entity_core500_audit import sha
from s4_reproduce500 import SEED, digest, log, now, read, write

ROOT=Path('/data_big/iclr-s4/experiments/entity_core_third_gpt6luna_medium_dual_v1')
PREVIOUS=Path('/data_big/iclr-s4/experiments/entity_core500_gpt6luna_medium_dual_v1')
DATABASE='postgresql://yhr@127.0.0.1:55432/iclr_reviewer'


def select_third(population, seeds):
    """Largest-remainder proportional quotas, retaining completed seeds within their stratum."""
    groups=defaultdict(list)
    for row in population:
        groups[(row['year'],row['area'])].append(row['paper_id'])
    target=math.ceil(len(population)/3)
    quotas={key:len(ids)//3 for key,ids in groups.items()}
    ranking=sorted(groups,key=lambda key:(-(len(groups[key])%3),key))
    for key in ranking[:target-sum(quotas.values())]:
        quotas[key]+=1
    selected=[];rng=random.Random(SEED)
    for key in sorted(groups):
        ids=sorted(groups[key]);retained=sorted(set(ids)&seeds)
        if len(retained)>quotas[key]:
            raise ValueError(f'Existing seeds exceed proportional stratum quota: {key}')
        remaining=[pid for pid in ids if pid not in seeds];rng.shuffle(remaining)
        selected.extend(retained+remaining[:quotas[key]-len(retained)])
    assert len(selected)==len(set(selected))==target and seeds<=set(selected)
    return sorted(selected),quotas


def prepare(root):
    if (root/'sample.json').exists():
        assert digest(read(root/'inputs.json'))==read(root/'sample.json')['input_hash']
        return
    root.mkdir(parents=True,exist_ok=True);(root/'runtime').mkdir(exist_ok=True)
    old_inputs={p['paper_id']:p for p in read(PREVIOUS/'inputs.json')}
    with psycopg.connect(DATABASE,row_factory=dict_row) as connection:
        connection.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY')
        population=connection.execute('''SELECT p.paper_id,v.year,ea.canonical_key area,
            pv.content_hash FROM core.paper p JOIN core.venue v USING(venue_id)
            JOIN core.latest_paper_version pv USING(paper_id)
            JOIN core.paper_area pa ON pa.paper_id=p.paper_id AND pa.is_primary
            JOIN core.explicit_area ea USING(explicit_area_id)
            WHERE coalesce(trim(pv.title),'')<>'' AND coalesce(trim(pv.abstract),'')<>''
            ORDER BY p.paper_id''').fetchall()
        corpus_total=connection.execute('SELECT count(*) n FROM core.paper').fetchone()['n']
        assert len(population)==corpus_total, 'Missing text/primary area needs an explicit population definition'
        ids,quotas=select_third(population,set(old_inputs))
        papers=connection.execute('''SELECT p.paper_id,p.forum_id,v.year,pv.title,pv.abstract,pv.keywords,
            pv.paper_version_id,pv.source_record_id paper_source_record_id,pv.content_hash,
            pa.source_record_id area_source_record_id,pa.explicit_area_id,ea.raw_label,ea.canonical_key area,
            sr.source_kind,sr.source_path,sr.sha256,sr.fetched_at,
            jsonb_build_object('title',sr.raw_payload->'title','abstract',sr.raw_payload->'abstract',
              'keywords',sr.raw_payload->'keywords','year',sr.raw_payload->'year','forum',sr.raw_payload->'forum',
              'primary_area',sr.raw_payload->'primary_area','area_dir',sr.raw_payload->'area_dir',
              'pdf_url',sr.raw_payload->'pdf_url') source_projection
            FROM core.paper p JOIN core.venue v USING(venue_id)
            JOIN core.latest_paper_version pv USING(paper_id)
            JOIN core.paper_area pa ON pa.paper_id=p.paper_id AND pa.is_primary
            JOIN core.explicit_area ea USING(explicit_area_id)
            JOIN raw.source_record sr ON sr.source_record_id=pv.source_record_id
            WHERE p.paper_id=ANY(%s) ORDER BY p.paper_id''',(ids,)).fetchall()
    inputs=[];gold=[]
    for p in papers:
        pid=p['paper_id']
        provenance={k:p[k] for k in ['paper_version_id','paper_source_record_id','area_source_record_id',
            'explicit_area_id','content_hash']}
        labels=dict(primary_area=p['raw_label'],keywords=p['keywords'])
        row=dict(paper_id=pid,title=p['title'],abstract=p['abstract'],year=p['year'],forum_id=p['forum_id'],
            original_labels=labels,provenance=provenance)
        projection=p['source_projection']
        assert (projection['title'],projection['abstract'],projection['keywords'])==(p['title'],p['abstract'],p['keywords'])
        write(root/f'evidence/papers/{pid}.json',dict(paper_id=pid,provenance=provenance,
            database_source={k:str(p[k]) for k in ['paper_source_record_id','source_kind','source_path','sha256','fetched_at']},
            source_projection=projection))
        if pid in old_inputs:
            old=old_inputs[pid]
            assert all(row[k]==old[k] for k in ['title','abstract','original_labels'])
            result=read(PREVIOUS/f'papers/{pid}.json')
            signature=digest(dict(title=p['title'],abstract=p['abstract'],prompt=extraction.PROMPT))
            assert result['extraction_provenance']['signature']==signature
            result.pop('embeddings',None)  # New array row order must never inherit old vector references.
            result['extraction_provenance']['reused_from']=str(PREVIOUS/f'papers/{pid}.json')
            result['extraction_provenance']['source_file_sha256']=sha(PREVIOUS/f'papers/{pid}.json')
            write(root/f'papers/{pid}.json',result)
            raw=read(PREVIOUS/f'parsed/{pid}.json')
            write(root/f'parsed/{pid}.json',raw)
            write(root/f'evidence/reuse500/parsed/{pid}.json',raw)
        inputs.append(row)
        gold.append(dict(paper_id=pid,year=p['year'],area=p['area'],raw_label=p['raw_label'],forum_id=p['forum_id']))
    assert len(inputs)==len(ids)
    write(root/'inputs.json',inputs);write(root/'evaluation/gold.json',gold)
    write(root/'population.json',population)
    archive=sorted((PREVIOUS.parent.parent/'archives').glob(PREVIOUS.name+'-*.tar.gz'))[-1]
    checksum=archive.with_name(archive.name+'.sha256').read_text().split()[0]
    assert sha(archive)==checksum
    copy=root/'evidence/reuse500'/archive.name;shutil.copyfile(archive,copy)
    write(root/'evidence/reuse500/ARCHIVE.json',dict(original=str(archive),copy=str(copy.relative_to(root)),
        sha256=checksum,papers=500,scope='Complete sealed evidence of reused extractions; embeddings reencoded in new sample order'))
    write(root/'sample.json',dict(created_at=now(),source='Read-only PostgreSQL core.latest_paper_version snapshot',
        corpus_total=corpus_total,papers=len(inputs),fraction='1/3 rounded up',seed=SEED,
        sampling='Proportional year x canonical-primary-area quotas by largest remainder; retain completed 500 within quotas; random fill',
        retained_completed=500,new_api_papers=len(inputs)-500,input_hash=digest(inputs),gold_hash=digest(gold),
        population_hash=digest(population),years=dict(Counter(p['year'] for p in inputs)),
        areas=dict(Counter(g['area'] for g in gold)),
        strata=[dict(year=k[0],area=k[1],population=sum(p['year']==k[0] and p['area']==k[1] for p in population),
            selected=quota) for k,quota in sorted(quotas.items())]))
    log('third_sample_frozen',papers=len(inputs),new_api=len(inputs)-500,years=dict(Counter(p['year'] for p in inputs)))


def run(root):
    scripts=Path(__file__).resolve().parent
    sample=read(root/'sample.json')
    assert sample['papers']==math.ceil(sample['corpus_total']/3)
    assert len(read(root/'inputs.json'))==sample['papers']
    if (root/'SEALED.json').exists():
        log('already_sealed',root=str(root));return
    for attempt in range(3):
        log('batch_run_start',attempt=attempt+1,root=str(root))
        with (root/'runtime/run.log').open('a') as output:
            result=subprocess.run([sys.executable,'-u',str(scripts/'s4_entity_core500.py'),'--root',str(root),'--stage','all'],
                stdout=output,stderr=subprocess.STDOUT)
        if result.returncode==0:
            break
        progress=read(root/'progress.json')
        if 'authentication/model endpoint rejected' in progress.get('error',''):
            raise RuntimeError('API authentication/model endpoint rejected; automatic resubmission stopped')
        if attempt==2:
            raise RuntimeError('Bounded checkpoint resumes exhausted; see progress and failures')
        time.sleep(30)
    with (root/'runtime/finalize.log').open('a') as output:
        subprocess.run([sys.executable,str(scripts/'s4_entity_core500_audit.py'),str(root)],
            stdout=output,stderr=subprocess.STDOUT,check=True)
    write(root/'SEALED.json',dict(completed_at=now(),audit='AUDIT_CHECKS.json',archive_record='runtime/finalize.log'))
    log('third_run_complete_and_archive_verified',root=str(root))


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root',type=Path,default=ROOT)
    parser.add_argument('--prepare',action='store_true')
    args=parser.parse_args()
    if args.prepare:prepare(args.root)
    else:run(args.root)
