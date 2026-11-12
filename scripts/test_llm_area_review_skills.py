#!/usr/bin/env python3
"""Offline area-isolation and unpaired-domain export checks."""
from pathlib import Path
import tempfile

import llm_area_review_skills as a
from test_full_s4_review_skills import candidate


def main():
    gold=[dict(paper_id=1,area=a.AREA),dict(paper_id=2,area='another_area'),
          dict(paper_id=3,area=a.AREA),dict(paper_id=4,area=a.AREA)]
    population,eligible=a.scope_ids(gold,[1,2,3,99])
    assert population==[1,3,4] and eligible==[1,3]
    check=candidate('one',1);check.update(level='domain',area=a.AREA,paired_source=False)
    rule={k:check[k] for k in a.f.check_fields()};rule['candidate_ids']=['one']
    enriched=a.f.s.enrich(rule,{'one':check},'R0001',1)
    assert enriched['status']=='candidate' and enriched['source_areas']==[]
    state=dict(version=1,next_id=2,rules={'R0001':enriched})
    with tempfile.TemporaryDirectory() as folder:
        root=Path(folder);a.export(root,state)
        registry=a.f.s.read(root/'registry.json')
        assert registry['area']==a.AREA and len(registry['modules'])==1
        m=registry['modules'][0];assert m['status']=='candidate' and 'domain-' in m['module_id']
        exported=a.f.s.read((root/m['path']).parent/'rules.json')
        assert exported==[enriched] and exported[0]['source_areas']==[]
        assert a.AREA in (root/m['path']).read_text()
    # Within-area replication does not silently waive the existing cross-area general-rule threshold.
    checks={'one':candidate('one',1),'two':candidate('two',2)}
    for c in checks.values():c.update(area=a.AREA,level='general')
    rule={k:checks['one'][k] for k in a.f.check_fields()};rule['candidate_ids']=['one','two']
    assert a.f.s.enrich(rule,checks,'R0002',1)['status']=='candidate'
    with tempfile.TemporaryDirectory() as folder:
        root=Path(folder)
        history=[dict(effective_at='2026-01-01T00:00:00+00:00',limit=4),
                 dict(effective_at='2026-01-02T00:00:00+00:00',limit=3)]
        for i in range(4):
            a.f.s.write(root/f'requests/extract/{i}/attempt_1.json',dict(
                started_at='2026-01-01T01:00:00+00:00',finished_at='2026-01-01T01:01:00+00:00'))
        assert a.check_concurrency_history(root,history)==4
        for i in range(4):
            a.f.s.write(root/f'requests/extract/new{i}/attempt_1.json',dict(
                started_at='2026-01-02T01:00:00+00:00',finished_at='2026-01-02T01:01:00+00:00'))
        try:a.check_concurrency_history(root,history)
        except ValueError:pass
        else:raise AssertionError('Earlier four-request authorization leaked into the new three-request phase')
    print('passed: exact primary-area filter, excluded-paper retention, unpaired-domain export, unchanged provenance and support thresholds')


if __name__=='__main__':main()
