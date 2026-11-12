#!/usr/bin/env python3
"""Read-only post-run audit of frozen inputs, provenance, deltas and API records."""
import argparse
from collections import Counter
from copy import deepcopy
import json
from pathlib import Path

import jsonschema
import modular_review_skill as s


def audit(root):
    manifest=s.validate_snapshot(root)
    all_candidates=s.candidates(root,manifest)
    counts=Counter()
    for pid in manifest['source_ids']:
        source=s.read(root/f'inputs/{pid}.json')
        case=s.read(root/f'cases/{pid}.json');s.validate_extraction(case)
        folder=root/f'requests/extract/{pid}'
        payload=json.loads(s.read(folder/'request.json')['body']['input'])
        result=s.read(folder/'result.json');schema=payload['schema']
        assert all(case[k]==v for k,v in result['parsed'].items())
        assert case['supplied_paper_ids']==[p['passage_id'] for p in payload['data']['paper']['paper_passages']]
        assert result['parsed']==s.response_json(result['response'])
        if result.get('recovered_without_inference'):
            errors=list(jsonschema.Draft202012Validator(schema).iter_errors(result['parsed']))
            assert errors and all(e.validator=='maxItems' and list(e.absolute_path)[0]=='cases'
                and list(e.absolute_path)[-1] in ['paper_evidence_ids','review_evidence_ids'] for e in errors)
            schema=deepcopy(schema)
            for field in ['paper_evidence_ids','review_evidence_ids']:
                schema['properties']['cases']['items']['properties'][field]['maxItems']=8
            assert s.digest(schema)==result['recovery']['recovery_schema_hash']
            counts['recovered_without_inference']+=1
        jsonschema.validate(result['parsed'],schema)
        ids={p['passage_id'] for p in source['paper_passages']}
        rev_ids={p['passage_id'] for p in source['review_passages']}
        for observation in case['cases']:
            assert set(observation['paper_evidence_ids'])<=ids
            assert set(observation['review_evidence_ids'])<=rev_ids
        counts['source_papers']+=1;counts['atomic_cases']+=len(case['cases'])
    state=dict(version=0,next_id=1,rules={})
    for number,pids in enumerate(manifest['batches'],1):
        delta=s.read(root/f'requests/curate/{number:02d}/result.json')['parsed']
        req=s.read(root/f'requests/curate/{number:02d}/request.json')['body']
        jsonschema.validate(delta,json.loads(req['input'])['schema'])
        payload=json.loads(req['input'])['data']
        assert payload['batch']==number
        batch=payload['candidates'];existing=payload['existing_rules']
        assert {c['paper_id'] for c in batch}<=set(pids)
        assert all(state['rules'][r['rule_id']]==r for r in existing)
        allowed={c['candidate_id'] for c in batch}|{cid for r in existing for cid in r['candidate_ids']}
        log=s.read(root/'updates.json')[number-1]
        assert s.digest(state)==log['before_hash']
        state['version']=number
        state,accepted,rejected=s.apply_delta(state,delta,all_candidates,allowed,{r['rule_id'] for r in existing})
        assert accepted==log['accepted'] and rejected==log['rejected']
        assert s.digest(state)==log['after_hash']
        assert state==s.read(root/f'versions/v{number:03d}.json')
        counts['curator_batches']+=1
    assert state==s.read(root/'rule_library.json')
    assert s.digest(state)==s.read(root/'FROZEN.json')['library_hash']
    for rule in state['rules'].values():
        assert set(rule['candidate_ids'])<=set(all_candidates)
        if rule['status']=='source_supported':
            assert len(rule['source_paper_ids'])>=2
            if rule['level']=='general':assert len(rule['source_areas'])>=2
        counts['rules_'+rule['status']]+=1
    for pid in manifest['source_ids']+manifest['target_ids']:
        route=s.read(root/f'compositions/{pid}.json')
        assert route['library_hash']==s.digest(state)
        assert len(route['rule_ids'])==len(set(route['rule_ids']))<=10
        assert all(state['rules'][r]['status']=='source_supported' for r in route['rule_ids'])
        counts['compositions']+=1
    for pid in manifest['target_ids']:
        route=s.read(root/f'compositions/{pid}.json')
        request=s.read(root/f'requests/review/{pid}/request.json')['body']
        data=json.loads(request['input'])['data']
        manuscript=data['manuscript']
        assert manuscript['paper_id']==pid and 'reviews' not in manuscript and 'review_passages' not in manuscript
        assert all(p['passage_id'].startswith(f'T{pid}:') for p in manuscript['paper_passages'])
        assert {r['rule_id'] for r in data['domain_checks']}==set(route['rule_ids'])
        review=s.read(root/f'reviews/{pid}/review.json')
        schema=json.loads(request['input'])['schema'];jsonschema.validate(review,schema)
        result=s.read(root/f'requests/review/{pid}/result.json')
        assert review==result['parsed']
        if result.get('recovered_without_inference'):
            recovery=result['recovery'];assert recovery['kind']=='unique_target_alias'
            assert recovery['schema_hash']==s.digest(schema)
            original=s.response_json(result['response'])
            for mapping in recovery['mappings']:
                field,index,attr,n=mapping['path']
                assert original[field][index][attr][n]==mapping['original']
                assert mapping['canonical'] in {p['passage_id'] for p in manuscript['paper_passages']}
                assert mapping['original']=='T'+mapping['canonical'].split(':P')[1]
                original[field][index][attr][n]=mapping['canonical']
            assert original==review
            counts['target_alias_recoveries']+=1
        else:
            assert s.response_json(result['response'])==review
        for applied in review['rules_applied']:assert applied['rule_id'] in route['rule_ids']
        refs={e for x in review['strengths']+review['concerns'] for e in x['evidence_ids']}
        evidence=s.read(root/f'reviews/{pid}/verified_evidence.json')
        assert {p['passage_id'] for p in evidence['passages']}==refs
        assert evidence['passages']==[p for p in manuscript['paper_passages'] if p['passage_id'] in refs]
        assert not s.read(root/f'reviews/{pid}/update_candidates.json')['applied']
        counts['target_papers']+=1;counts['concerns']+=len(review['concerns'])
    usage=Counter();events=[]
    for path in root.glob('requests/*/*/attempt_*.json'):
        attempt=s.read(path);request=s.read(path.parent/'request.json')['body']
        assert attempt['request_hash']==s.digest(request) and attempt.get('finished_at')
        assert len(list(path.parent.glob('attempt_*.json')))<=2
        assert request['model']==s.MODEL and request['reasoning']['effort']=='medium'
        assert attempt['response']['model']==s.MODEL if 'response' in attempt else True
        if attempt.get('ok'):
            raw=attempt['response'];assert raw['status']=='completed' and raw['reasoning']['effort']=='medium'
        u=attempt.get('response',{}).get('usage',{})
        for k in ['input_tokens','output_tokens']:usage[k]+=u.get(k,0)
        usage['reasoning_tokens']+=u.get('output_tokens_details',{}).get('reasoning_tokens',0)
        events.extend([(attempt['started_at'],1),(attempt['finished_at'],-1)])
        counts['attempts']+=1
    active=peak=0
    for _,change in sorted(events,key=lambda e:(e[0],e[1])):
        active+=change;peak=max(peak,active)
    assert active==0 and peak<=3
    summary=s.read(root/'summary.json')
    assert dict(usage)==summary['usage'] and summary['state']=='awaiting_pilot_review'
    assert counts['source_papers']==100 and counts['target_papers']==5 and counts['curator_batches']==10
    return dict(check='passed',counts=dict(counts),usage=dict(usage),concurrency_peak=peak,
                scientific_accuracy='Not adjudicated; this audit checks traceability and execution only.')


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root',type=Path,default=s.ROOT)
    args=parser.parse_args()
    print(json.dumps(audit(args.root),ensure_ascii=False,indent=2))
