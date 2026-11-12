"""Run with the S4 environment; uses the frozen official PDF text and makes no API calls."""
from s4_cs2023_ai5 import extract_taxonomy, get_path, evidence_spans, validate_result


def check():
    nodes = extract_taxonomy()
    assert sum(n['kind'] == 'knowledge_unit' for n in nodes.values()) == 12
    assert nodes['AI-ML/22/a']['label'] == 'Deep feed-forward networks'
    assert nodes['AI-LRR/2']['label'] == 'Resolution and theorem proving (propositional logic only)'
    assert nodes['AI-ML/33']['label'] == 'Hardware for machine learning'
    assert all(get_path(nodes,k)[0] == 'AI' for k in nodes)
    assert not any('Illustrative Learning Outcomes' in n['label'] for n in nodes.values())
    paper = dict(paper_id=1,year=2026,title='Neural estimator',abstract='First sentence. Second sentence.',
                 original_labels={'primary_area':'machine learning','keywords':['GPU','GPU']})
    spans = evidence_spans(paper)
    anchor = {'allowed_units':['AI-ML']}
    raw = {'paper_id':1,'classifications':[{'path_index':0,'evidence_ids':['title'], 'reason_zh':'示例'}],
           'uncovered_topics_zh':''}
    paths = [get_path(nodes,'AI-ML/22/a')]
    result = validate_result(raw,paper,anchor,nodes,paths,spans)
    assert result['supplemental_labels']['keywords'] == ['GPU','GPU']
    assert result['classifications'][0]['evidence'][0]['quote'] == paper['title']
    for bad_anchor,bad_spans in [({'allowed_units':['AI-LRR']},spans),(anchor,{})]:
        try:
            validate_result(raw,paper,bad_anchor,nodes,paths,bad_spans)
        except (AssertionError, KeyError):
            pass
        else:
            raise AssertionError('Invalid guidance or nonexistent evidence was accepted')
    print('CS2023 extraction, path, evidence and original-label checks passed.')


if __name__ == '__main__':
    check()
