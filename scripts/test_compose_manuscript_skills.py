#!/usr/bin/env python3
"""Offline checks for target isolation, evidence and bounded rule composition."""
from copy import deepcopy
from pathlib import Path
import tempfile
from types import SimpleNamespace
from unittest.mock import patch

import compose_manuscript_skills as c
from test_full_s4_review_skills import candidate


def rejects(call):
    try: call()
    except ValueError: return
    raise AssertionError('Invalid input accepted')


def main():
    text = 'We use optimization relaxation.\nThe low-rank attention cache is partitioned.'
    manuscript = dict(passages=[dict(passage_id='M1', char_start=0, char_end=len(text), text=text)])
    evidence = [dict(passage_id='M1', quote='optimization relaxation.')]
    assert c.evidence_refs(evidence, manuscript)[0]['char_start'] == text.index('optimization')
    assert c.evidence_refs([dict(passage_id='M1', quote='relaxation. The low-rank')], manuscript)[0]['quote_policy'] == 'whitespace_only'
    rejects(lambda: c.evidence_refs([dict(passage_id='invented', quote='optimization')], manuscript))
    rejects(lambda: c.evidence_refs([dict(passage_id='M1', quote='nonexistent result')], manuscript))
    profile = dict(area_fit='in_scope', domain_english='LLM inference', domain_reason='test', evidence=evidence,
        **{key:[dict(term_english='optimization relaxation', description='近似实现', evidence=evidence)]
           for key in ['methods', 'tasks', 'technical_objects']})
    c.validate_profile(profile, manuscript)
    candidates = {cid:candidate(cid, i) for i, cid in enumerate(['a', 'b'])}
    source = {key:candidates['a'][key] for key in c.f.check_fields()}; source['candidate_ids'] = ['a', 'b']
    supported = c.s.enrich(source, candidates, 'R1', 1)
    one = deepcopy(source); one['candidate_ids'] = ['a']
    single = c.s.enrich(one, candidates, 'R2', 1)
    state = dict(rules={'R1':supported, 'R2':single})
    ranked = c.retrieve(state, profile)
    assert [r['rule_id'] for r in ranked] == ['R1']
    ranked = c.retrieve(state, profile, True)
    assert {r['rule_id'] for r in ranked} == {'R1', 'R2'}
    evaluation = dict(rule_id='R1', disposition='applicable', priority=2, reason='技术对象一致',
        missing_information='', matches=dict(method='match', task='not_required', technical_object='match'), evidence=evidence)
    other = dict(deepcopy(evaluation), rule_id='R2', priority=1)
    c.validate_assessment(dict(evaluations=[evaluation, other]), manuscript, ['R1', 'R2'])
    rejects(lambda:c.validate_assessment(dict(evaluations=[evaluation, evaluation]), manuscript, ['R1', 'R2']))
    invalid = deepcopy(evaluation); invalid['matches']['method'] = 'unknown'
    rejects(lambda:c.validate_assessment(dict(evaluations=[invalid]), manuscript, ['R1']))
    _, schema = c.assessment_request(manuscript, profile, [supported, single])
    wrong_quote = deepcopy(other); wrong_quote['evidence'][0]['quote'] = 'invented quote'
    recovered, quarantine = c.recover_assessment(dict(evaluations=[evaluation, wrong_quote]), schema, manuscript, ['R1', 'R2'])
    assert recovered['evaluations'][0] == evaluation and len(quarantine) == 1
    assert recovered['evaluations'][1]['disposition'] == 'insufficient_evidence'
    selected, decisions = c.choose(ranked, [other, evaluation], state, 1, 4000)
    assert [r['rule_id'] for r in selected] == ['R1']  # Paired sources precede candidate priority.
    assert next(r for r in decisions if r['rule_id']=='R2')['selection'] == 'rule_count_budget'
    selected, decisions = c.choose(ranked, [evaluation], state, 10, 5)
    assert not selected and decisions[0]['selection'] == 'rule_token_budget'
    assert c.profile_data(manuscript)['manuscript']['passages'][0]['text'] == text
    with tempfile.TemporaryDirectory() as folder:
        base = Path(folder); release = base/'release'; release.mkdir(); historical = base/'history'; historical.mkdir()
        (historical/'source.md').write_text('Historical source text.')
        c.s.write(historical/'inputs/7.json', dict(paper_id=7, forum_id='historical-forum',
            manuscript_path=str(historical/'source.md'), manuscript_sha256=c.s.sha(historical/'source.md')))
        c.s.write(release/'PROVENANCE.json', dict(sources={str(historical):{
            'inputs/7.json':c.s.sha(historical/'inputs/7.json')}}))
        c.s.write(release/'RELEASE.json', {})
        target = base/'target.md'; target.write_text(text)
        args = SimpleNamespace(root=base/'run', release=release, max_rules=10, rule_tokens=4000,
            shortlist=24, include_candidates=False, manuscript=target, paper_id=8, title='New target', forum_id='new-forum')
        with patch.object(c, 'load_library', return_value=(dict(source_root=str(historical)), state)):
            prepared, _, _ = c.prepare(args)
            assert (args.root/'MANUSCRIPT.md').read_text() == text
            assert c.prepare(args)[0] == prepared
            for i, changes in enumerate([dict(paper_id=7), dict(forum_id='historical-forum')]):
                changed = SimpleNamespace(**vars(args)); changed.__dict__.update(changes, root=base/f'bad-{i}')
                rejects(lambda:c.prepare(changed))
            target.write_text('Historical source text.')
            args.root = base/'bad-text'; rejects(lambda:c.prepare(args))
    print('passed: exact and whitespace-only quotes, unknown evidence rejection, per-rule completeness, '
          'scope uncertainty rejection, source-supported priority, count/token caps, full-text preservation, '
          'resumption identity, source isolation by ID/forum/full text, '
          'valid-row conservation and unverifiable-row quarantine')


if __name__ == '__main__': main()
