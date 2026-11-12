#!/usr/bin/env python3
"""Offline regression for global retrieval, durable deferrals and truthful coverage."""
from copy import deepcopy
import jsonschema
import recurate_modular_review_skill as r
import modular_review_skill as s


def main():
    candidates={}
    for i in range(12):
        term='differential privacy' if i in [0,11] else f'control-{i}'
        candidates[str(i)]=dict(title=term,level='method',scope_terms=[term],applies_when=term,
            steps=[term],issue_when=term,cleared_when=term,significance=term,exceptions=[],
            candidate_id=str(i),paper_id=i,area='A',paired_source=True,case_ids=['c'])
    retrieval=r.Retrieval(candidates)
    assert retrieval.rank(['0'],set(candidates)-{'0'})[0]=='11'
    queue={cid:dict(status='pending',attempts=0,previously_represented=False,rule_ids=[],reason='',history=[])
           for cid in candidates}
    state=dict(version=0,next_id=1,rules={})
    data,output_schema=r.make_request(state,queue,candidates,retrieval)
    assert '11' in data['focus_ids'] and len(data['focus_ids'])==8
    small,_=r.make_request(state,queue,candidates,retrieval,focus_limit=4)
    assert len(small['focus_ids'])==4 and all(q['status']=='pending' for q in queue.values())
    delta=dict(operations=[],deferred_candidate_ids=data['focus_ids'],decisions=[dict(
        candidate_id=cid,status='deferred',rule_refs=[],reason='需要进一步比对') for cid in data['focus_ids']])
    jsonschema.validate(delta,output_schema)
    next_state,next_queue,_=r.transition(state,queue,delta,data,candidates)
    assert all(next_queue[c]['status']=='deferred' for c in data['focus_ids'])
    assert all(queue[c]['status']=='pending' for c in queue)
    # Unprocessed candidates survive and outrank already deferred entries.
    following,_=r.make_request(next_state,next_queue,candidates,retrieval)
    assert next_queue[following['focus_ids'][0]]['attempts']==0
    final,twice,_=r.transition(next_state,next_queue,delta,data,candidates)
    assert all(twice[c]['status']=='unresolved' and twice[c]['attempts']==2 for c in data['focus_ids'])
    one=dict(focus_ids=['0'],candidates=[r.projection(candidates['0'])],
             global_neighbors=[r.projection(candidates['11'])],existing_rules=[])
    rule={k:candidates['0'][k] for k in s.check_fields()};rule['candidate_ids']=['0','11']
    addition=dict(operations=[dict(type='ADD',target_ids=[],rules=[rule],evidence_candidate_ids=['0','11'],reason='同类条件')],
        deferred_candidate_ids=[],decisions=[dict(candidate_id='0',status='incorporated',rule_refs=['op:0'],reason='保留具体范围')])
    new,new_queue,_=r.transition(state,queue,addition,one,candidates)
    assert new_queue['0']['rule_ids']==['R0001'] and new_queue['11']['status']=='pending'
    assert new['rules']['R0001']['status']=='source_supported'
    wrong=deepcopy(addition);wrong['operations'][0]['rules'][0]['candidate_ids']=['11']
    guarded,requeued,_=r.transition(state,queue,wrong,one,candidates)
    assert requeued['0']['status']=='deferred' and not requeued['0']['rule_ids']
    assert guarded['rules']['R0001']['candidate_ids']==['11']
    both=deepcopy(one);both['focus_ids']=['0','11'];both['candidates']+=[both['global_neighbors'].pop()]
    malformed=deepcopy(addition)
    malformed['operations'][0]['rules']*=3
    valid=deepcopy(addition['operations'][0]);valid['rules'][0]['candidate_ids']=['11']
    malformed['operations'].append(valid)
    malformed['decisions'].append(dict(candidate_id='11',status='incorporated',rule_refs=['op:1'],reason='valid'))
    canonical,details=r.quarantine_invalid_items(malformed,state,both,r.schema(['0','11'],[]),candidates)
    assert len(canonical['operations'])==1 and len(details['quarantined_operations'])==1
    assert canonical['decisions'][0]['status']=='deferred'
    assert canonical['decisions'][1]['rule_refs']==['op:0']
    _,guarded_queue,_=r.transition(state,queue,canonical,both,candidates)
    assert guarded_queue['0']['status']=='deferred' and guarded_queue['11']['status']=='incorporated'
    missing=deepcopy(delta);missing['decisions']=missing['decisions'][:-1]
    try:r.transition(state,queue,missing,data,candidates)
    except ValueError:pass
    else:raise AssertionError('A focus candidate disappeared without a decision')
    replayed_state,replayed_queue,_=r.transition(state,queue,addition,one,candidates)
    assert replayed_state==new and replayed_queue==new_queue
    print('passed: global neighbors, deferred queue, bounded revisits, truthful coverage, replay, no silent loss')


if __name__=='__main__':main()
