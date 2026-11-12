"""Check source offsets, complete candidate retention and isolation from author labels; no API."""
from copy import deepcopy
from s4_entity_core5 import source_spans, materialize, normalize


def check():
    paper=dict(paper_id=1,year=2026,title='Neural model',abstract='A model estimates entropy; entropy matters.',
        original_labels={'primary_area':'original','keywords':['GPU','GPU']})
    spans=source_spans(paper)
    candidate=dict(span_id='abstract:0',mention_text='entropy',entity_type='RESEARCH_OBJECT',
                   paper_role='evaluation_target',salience='core')
    raw=dict(paper_id=1,entity_candidates=[candidate,dict(candidate,mention_text='invented method')],
        core={'research_problem':{'text':'Estimate entropy.','evidence_ids':['abstract:0']},
              'method':{'text':'','evidence_ids':[]},'research_object':{'text':'Entropy.','evidence_ids':['abstract:0']}})
    result=materialize(raw,paper,spans)
    assert len(result['entity_candidates'])==2
    assert len(result['entity_candidates'][0]['source_occurrences'])==2
    assert not result['entity_candidates'][1]['literal_span_valid']
    assert len(result['candidate_term_groups'])==1
    assert result['original_labels']==paper['original_labels']
    assert 'GPU' not in result['core_text']
    assert normalize('  NEURAL  model ')==normalize('neural model')
    for occurrence in result['entity_candidates'][0]['source_occurrences']:
        assert paper[occurrence['field']][occurrence['start']:occurrence['end']]=='entropy'
    bad=deepcopy(raw);bad['core']['method']={'text':'Unsupported method.','evidence_ids':[]}
    try:
        materialize(bad,paper,spans)
    except ValueError:
        pass
    else:
        raise AssertionError('Core text without evidence was accepted')
    print('Candidate retention, exact offsets, evidence and author-label isolation checks passed.')


if __name__=='__main__':
    check()
