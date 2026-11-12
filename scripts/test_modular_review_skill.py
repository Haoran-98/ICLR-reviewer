#!/usr/bin/env python3
"""Offline checks for the paid-call boundary, cache, isolation and version replay."""
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import patch
import threading
import time

import jsonschema
import modular_review_skill as s
import recover_modular_review_skill as recovery


def main():
    s.self_check()
    row=dict(paper_id=9,paper_passages=[dict(passage_id='T9:P1')])
    schema=s.review_schema(row,['R0001'])
    evidence=schema['properties']['concerns']['items']['properties']['evidence_ids']
    try:jsonschema.validate(['H1R:P1'],evidence)
    except jsonschema.ValidationError:pass
    else:raise AssertionError('Historical review citation accepted in target review')
    candidates={str(i):dict(paper_id=i,area='A' if i<3 else 'B',paired_source=True) for i in range(1,5)}
    rule=dict(title='budget',level='domain',scope_terms=['sampling'],applies_when='comparison',
              steps=['align budget'],issue_when='unequal',cleared_when='equal',significance='attribution',
              exceptions=[],candidate_ids=['1','2'])
    start=dict(version=1,next_id=1,rules={})
    add=dict(type='ADD',target_ids=[],rules=[rule],evidence_candidate_ids=['1','2'],reason='paired')
    state,entries,rejected=s.apply_delta(start,dict(operations=[add]),candidates,set(candidates),set())
    children=[deepcopy(rule),deepcopy(rule)]
    children[0]['title']='sampling steps';children[1]['title']='candidate counts'
    split=dict(type='SPLIT',target_ids=['R0001'],rules=children,evidence_candidate_ids=['1','2'],reason='different checks')
    final,entries,rejected=s.apply_delta(state,dict(operations=[split]),candidates,set(candidates),{'R0001'})
    assert not rejected and final['rules']['R0001']['status']=='deprecated' and len(final['rules'])==3
    replay=deepcopy(state['rules'])
    for entry in entries:replay.update(entry['after'])
    assert replay==final['rules']
    with TemporaryDirectory() as temporary:
        root=Path(temporary)
        auth=root/'auth';auth.write_text('export OPENAI_BASE_URL="https://example.invalid"\n'
            'export OPENAI_API_KEY="test-only"\nexport OPENAI_WEAK_MODEL_ID="gpt-6-luna"\n')
        s.write(root/'config.json',dict(concurrency_limit=3))
        client=s.Client(SimpleNamespace(root=root,auth=auth,concurrency=3))
        counts=dict(active=0,peak=0,calls=0);lock=threading.Lock()
        class Response:
            ok=True;status_code=200;headers={'content-type':'application/json'}
            def __enter__(self):return self
            def __exit__(self,*args):pass
            def json(self):
                time.sleep(.04)
                with lock:counts['active']-=1
                return dict(model=s.MODEL,reasoning=dict(effort='medium'),status='completed',
                    output=[dict(type='message',content=[dict(type='output_text',text='{"value":1}')])],
                    usage=dict(input_tokens=10,output_tokens=5))
        def post(*args,**kwargs):
            with lock:
                counts['calls']+=1;counts['active']+=1;counts['peak']=max(counts['peak'],counts['active'])
            return Response()
        output=s.obj(dict(value=dict(type='integer')))
        with patch.object(s.requests,'post',side_effect=post):
            with ThreadPoolExecutor(max_workers=6) as pool:
                results=list(pool.map(lambda i:client.ask('mock',i,dict(index=i),output,8000,100),range(6)))
            assert results==[dict(value=1)]*6 and counts['peak']==3
            assert client.ask('mock',0,dict(index=0),output,8000,100)==dict(value=1)
            assert counts['calls']==6
        with patch.object(s.requests,'post',side_effect=AssertionError('No paid request permitted')):
            try:client.ask('mock',0,dict(index='changed'),output,8000,100)
            except ValueError:pass
            else:raise AssertionError('Changed cached request accepted')
        bad=root/'requests/mock/failed';bad.mkdir()
        # A schema failure is not automatically repaired or billed a second time.
        with patch.object(s.requests,'post',side_effect=post):
            try:client.ask('mock','failed',{},s.obj(dict(different=s.STRING)),8000,100)
            except RuntimeError:pass
            else:raise AssertionError('Invalid provider output accepted')
        before=counts['calls']
        with patch.object(s.requests,'post',side_effect=AssertionError('Failed cache must stop')):
            try:client.ask('mock','failed',{},s.obj(dict(different=s.STRING)),8000,100)
            except ValueError:pass
            else:raise AssertionError('Non-retryable failure resumed')
        assert counts['calls']==before
        class RateLimited(Response):
            ok=False;status_code=429;text='Rate limited'
        with patch.object(s.requests,'post',return_value=RateLimited()) as limited, patch.object(s.time,'sleep'):
            try:client.ask('mock','bounded',{},output,8000,100)
            except RuntimeError:pass
            else:raise AssertionError('Rate limit did not stop')
            assert limited.call_count==2
            try:client.ask('mock','bounded',{},output,8000,100)
            except ValueError:pass
            else:raise AssertionError('Attempt ceiling reset on resume')
            assert limited.call_count==2
        source=dict(paper_id=42,paper_passages=[dict(passage_id=f'P{i}') for i in range(4)],
                    review_passages=[dict(passage_id='R1')])
        source_schema=s.extraction_schema(source)
        parsed=dict(paper_id=42,cases=[dict(case_id='c1',kind='concern',observation='a review observation',
            historical_status='unknown',review_evidence_ids=['R1'],paper_evidence_ids=['P0','P1','P2','P3'])],candidate_checks=[])
        record=dict(started_at=s.now(),finished_at=s.now(),request_hash='unused-in-this-unit-test',ok=False,
            response=dict(status='completed',model=s.MODEL,reasoning=dict(effort='medium'),
                output=[dict(type='message',content=[dict(type='output_text',text=s.json.dumps(parsed))])]))
        folder=root/'requests/extract/42'
        s.write(folder/'request.json',dict(body=dict(input=s.json.dumps(dict(schema=source_schema)))))
        s.write(folder/'attempt_1.json',record)
        assert recovery.recover(root)==['42']
        assert s.read(folder/'result.json')['parsed']==parsed and not s.read(folder/'attempt_1.json')['ok']
        invalid=deepcopy(record)
        bad_parsed=deepcopy(parsed);bad_parsed['cases'][0]['paper_evidence_ids'][0]='UNKNOWN'
        invalid['response']['output'][0]['content'][0]['text']=s.json.dumps(bad_parsed)
        other=root/'requests/extract/43'
        s.write(other/'request.json',s.read(folder/'request.json'));s.write(other/'attempt_1.json',invalid)
        assert recovery.recover(root)==[] and not (other/'result.json').exists()
        target_schema=s.obj(dict(paper_id={'const':9},strengths=s.arr(s.obj(dict(
            evidence_ids=s.arr(dict(type='string',enum=['T9:P0014']))))),concerns=s.arr(s.obj(dict(
            evidence_ids=s.arr(dict(type='string',enum=['T9:P0014'])))))))
        for key,reference in [('valid','T0014'),('unknown','T9999'),('other_target','T8:P0014')]:
            target_parsed=dict(paper_id=9,strengths=[],concerns=[dict(evidence_ids=[reference])])
            target_record=deepcopy(record)
            target_record['response']['output'][0]['content'][0]['text']=s.json.dumps(target_parsed)
            target_folder=root/f'requests/review/{key}'
            s.write(target_folder/'request.json',dict(body=dict(input=s.json.dumps(dict(
                schema=target_schema,data=dict(manuscript=dict(paper_passages=[dict(passage_id='T9:P0014')])))))))
            s.write(target_folder/'attempt_1.json',target_record)
        assert recovery.recover_reviews(root)==['valid']
        fixed=s.read(root/'requests/review/valid/result.json')['parsed']
        assert fixed['concerns'][0]['evidence_ids']==['T9:P0014']
        assert not s.read(root/'requests/review/valid/attempt_1.json')['ok']
        assert not (root/'requests/review/unknown/result.json').exists()
        assert not (root/'requests/review/other_target/result.json').exists()
    print('offline checks passed: target isolation, split/replay, three-call gate, idempotent cache, failed-output stop, bounded retries across resume')


if __name__=='__main__':main()
