#!/usr/bin/env python3
"""Offline checks for source conservation, failure-mechanism isolation and durable deltas."""
from copy import deepcopy
from pathlib import Path
import tempfile
from types import SimpleNamespace
from unittest.mock import patch

import jsonschema
from scipy import sparse

import full_s4_review_skills as f


def candidate(cid,pid,family='guarantee_transfer'):
    return dict(title='Relaxation preserves guarantee',level='method',scope_terms=['optimization relaxation'],
        applies_when='实现采用理论算法的近似或松弛。',steps=['对照理论与实际执行条件。'],
        issue_when='近似破坏保证成立所需条件且未提供补偿界。',cleared_when='给出近似误差控制并传递至最终结论。',
        significance='实际执行可能不满足声明的保证。',exceptions=['明确仅声明理想化算法的结果。'],
        review_object='理论算法与近似实现的关系',failure_mechanism='近似误差未经控制传递至保证',
        mechanism_family=family,candidate_id=cid,paper_id=pid,area='area'+str(pid),paired_source=True,
        observation='松弛实现与定理之间缺少论证。',historical_status='reviewer_opinion',
        job_id=str(pid),atom_id=cid,review_evidence_ids=['u'],paper_evidence_ids=['p'])


def main():
    limited=dict(status='failed',model=f.s.MODEL,output=[],
                 error=dict(code='gateway_concurrency_limit',message='retry later'))
    try:f.validate_provider_response(limited)
    except f.TransientProviderError:pass
    else:raise AssertionError('Gateway throttling was not retryable')
    assert f.retryable_record(dict(response=limited,error='Returned model/effort mismatch',retryable=False))
    success=dict(status='completed',model=f.s.MODEL,reasoning=dict(effort='medium'),
        usage=dict(input_tokens=10,output_tokens=2),output=[dict(type='message',
        content=[dict(type='output_text',text='{"value":"ok"}')])])
    class HTTPResponse:
        ok=True;status_code=200;headers={'content-type':'application/json'}
        def __init__(self,body):self.body=body
        def __enter__(self):return self
        def __exit__(self,*args):return False
        def json(self):return self.body
    with tempfile.TemporaryDirectory() as folder:
        root=Path(folder)
        f.s.write(root/'manifest.json',dict(jobs=1))
        f.s.write(root/'config.json',dict(concurrency_limit=3))
        args=SimpleNamespace(root=root,auth=root/'unused_auth',concurrency=3)
        auth=dict(OPENAI_WEAK_MODEL_ID=f.s.MODEL,OPENAI_BASE_URL='https://offline.invalid',OPENAI_API_KEY='offline-test')
        with patch.object(f.s,'load_auth',return_value=auth):client=f.Client(args)
        with patch.object(f.requests,'post',side_effect=[HTTPResponse(limited),HTTPResponse(success)]) as post,patch.object(f.time,'sleep'):
            result=client.ask('extract','test',{},f.s.obj(dict(value=f.s.STRING)),1000,100)
            assert result==dict(value='ok') and post.call_count==2 and not client.stop.is_set()
        first=f.s.read(root/'requests/extract/test/attempt_1.json')
        assert first['response']==limited and first['retryable'] and not first['ok']
        with patch.object(f.requests,'post',side_effect=AssertionError('Cached result re-inferred')):
            assert client.ask('extract','test',{},f.s.obj(dict(value=f.s.STRING)),1000,100)==result
        wrong=deepcopy(success);wrong['reasoning']['effort']='low'
        with patch.object(f.requests,'post',return_value=HTTPResponse(wrong)) as post:
            try:client.ask('extract','wrong',{},f.s.obj(dict(value=f.s.STRING)),1000,100)
            except RuntimeError:pass
            else:raise AssertionError('Real effort mismatch accepted')
            assert client.stop.is_set() and post.call_count==1
        client.lifecycle='failed';client.last_error='Offline intentional mismatch';client.save()
        assert f.s.read(root/'progress.json')['run_state']=='failed'
        assert 'failed' in (root/'PROGRESS.md').read_text()
    text=('First independent issue.\nSecond issue has a conditional follow-up.\n'*500)+'尾部不能丢失。'
    parts=list(f.spans(text,100))
    assert ''.join(text[a:b] for a,b in parts)==text
    assert all(f.s.tokens(text[a:b])<=100 for a,b in parts)
    reviews=[dict(review_id=1,fields=dict(weaknesses=text,questions='If this assumption fails, does the guarantee hold?',ethics_concerns=''))]
    units=f.review_units(reviews,7);groups=list(f.job_groups(units))
    assert [uid for group in groups for uid in group]==[u['passage_id'] for u in units]
    assert len(groups)>1
    schema=f.extraction_schema(7,['u1','u2'],['p'])
    atom=dict(atom_id='a',kind='concern',observation='具体科学关系。',historical_status='reviewer_opinion',
              review_evidence_ids=['u1'],paper_evidence_ids=[],check=None)
    raw=dict(paper_id=7,atoms=[atom],unit_coverage=[dict(unit_id='u1',disposition='extracted',atom_ids=['a'],reason='提炼')])
    try:f.validate_extraction(raw,['u1','u2'])
    except ValueError:pass
    else:raise AssertionError('Missing review unit accepted')
    fixed,details=f.recover_extraction(raw,schema,['u1','u2'])
    assert fixed['atoms']==[atom] and fixed['unit_coverage'][1]['disposition']=='unresolved'
    malformed=deepcopy(raw);malformed['atoms'][0]['historical_status']='manuscript_supported'
    fixed,details=f.recover_extraction(malformed,schema,['u1','u2'])
    assert not fixed['atoms'] and len(details['quarantined_atoms'])==1
    cs={str(i):candidate(str(i),i) for i in range(12)}
    cs['11']['scope_terms']=['rare contraction'];cs['0']['scope_terms']=['rare contraction']
    retrieval=f.Retrieval(cs)
    assert sparse.issparse(retrieval.matrix) and not hasattr(retrieval,'similarity')
    assert retrieval.rank(['0'],set(cs)-{'0'},1)==['11']
    state=dict(version=0,next_id=1,rules={})
    queue={cid:dict(status='pending',attempts=0,previously_represented=False,rule_ids=[],reason='',history=[]) for cid in cs}
    data,schema=f.curator_request(state,queue,cs,retrieval)
    focus=data['focus_ids'];rule={k:cs[focus[0]][k] for k in f.check_fields()};rule['candidate_ids']=focus
    delta=dict(operations=[dict(type='ADD',target_ids=[],rules=[rule],evidence_candidate_ids=focus,reason='同一机制')],
        decisions=[dict(candidate_id=cid,status='incorporated',rule_refs=['op:0'],reason='保留机制') for cid in focus],
        deferred_candidate_ids=[])
    jsonschema.validate(delta,schema)
    local,qs,accepted,changed=f.transition(state,queue,delta,data,cs)
    assert local['rules']['R0001']['status']=='source_supported' and len(qs)==len(focus)
    assert state['rules']=={} and all(q['attempts']==0 for q in queue.values())
    mixed=deepcopy(cs);mixed[focus[-1]]['mechanism_family']='claim_scope'
    try:f.transition(state,queue,delta,data,mixed)
    except ValueError:pass
    else:raise AssertionError('Unrelated mechanism inflated source support')
    # SQLite persists only changed entries; reconstructing it must preserve the exact next request.
    with tempfile.TemporaryDirectory() as folder:
        db=f.state_db(Path(folder))
        with db:
            db.executemany('INSERT INTO rules VALUES (?,?)',[(rid,f.json.dumps(value)) for rid,value in changed.items()])
            db.executemany('INSERT INTO queue VALUES (?,?)',[(cid,f.json.dumps(value)) for cid,value in qs.items()])
        loaded={rid:f.json.loads(value) for rid,value in db.execute('SELECT id,value FROM rules')}
        assert loaded==changed
        db.close()
    class OfflineCurator:
        calls=0
        def set_phase(self,*args):pass
        def done(self):pass
        def ask(self,stage,key,data,schema,input_limit,output_limit,validator=None):
            self.calls+=1
            focus=data['focus_ids'];check={k:cs[focus[0]][k] for k in f.check_fields()}
            check['candidate_ids']=focus
            prior=data['existing_rules'][:1]
            result=dict(operations=[dict(type='REFINE' if prior else 'ADD',
                target_ids=[prior[0]['rule_id']] if prior else [],rules=[check],evidence_candidate_ids=focus,reason='离线同机制合并')],
                decisions=[dict(candidate_id=cid,status='incorporated',rule_refs=['op:0'],reason='离线来源') for cid in focus],
                deferred_candidate_ids=[])
            jsonschema.validate(result,schema)
            if validator:validator(result)
            return result
    with tempfile.TemporaryDirectory() as folder:
        root=Path(folder);client=OfflineCurator();args=SimpleNamespace(root=root)
        state,queue=f.curate(args,dict(max_curation_requests=10),client,cs)
        assert client.calls==2 and len(state['rules'])==1
        assert all(q['status']=='incorporated' for q in queue.values())
        f.export(root,state)
        registry=f.s.read(root/'registry.json')
        assert registry['modules'] and registry['modules'][0]['status']=='source_supported'
        assert all((root/m['path']).is_file() for m in registry['modules'])
        resumed,resumed_queue=f.curate(args,dict(max_curation_requests=10),client,cs)
        assert client.calls==2 and resumed==state and resumed_queue==queue
    print('passed: full source partition, no silent loss, exact scientific-field recovery, sparse global retrieval, mechanism isolation, incremental persistence')


if __name__=='__main__':main()
