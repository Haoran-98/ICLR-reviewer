#!/usr/bin/env python3
"""Check published S4 membership, evidence and scores against their original sources."""
import csv
import json
import math
import os
import sys
from collections import Counter
from pathlib import Path
import psycopg

root = Path(__file__).parent / 'public/generated'
sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'scripts'))
from deployment_paths import ENTITY as s4
sample = json.loads((root/'sample.json').read_text())
analysis = json.loads((root/'domains.json').read_text())
gold = json.loads((s4/'evaluation/gold.json').read_text())
expected_ids = {str(row['paper_id']) for row in gold}
papers = {p['paper_id']: p for p in sample['papers']}
assert len(papers) == len(sample['papers']) == len(gold) == 12964
assert set(papers) == expected_ids == {p['paper_id'] for p in analysis['papers']}
assert analysis['meta']['source_data_version'] == sample['meta']['data_version']
assert sample['meta']['semantic_projection']
details = {}
for file in (root/sample['meta']['details_base']).glob('*.json'): details.update(json.loads(file.read_text()))
assert set(details) == expected_ids
entities = {(e['type'], e['normalized']): e['id'] for e in analysis['entities']}
assert len(entities) == len(analysis['entities'])
records = {p['paper_id']: p for p in analysis['papers']}
memberships = 0
for pid in sorted(expected_ids, key=int):
    original = json.loads((s4/'papers'/f'{pid}.json').read_text())
    evidence = json.loads((root/analysis['evidence_base']/f'{pid}.json').read_text())
    assert evidence == original
    expected = {entities[(c['entity_type'], c['normalized_key'])] for c in original['entity_candidates']
                if c['literal_span_valid'] and c['salience'] == 'core'}
    assert set(records[pid]['entities']) == expected
    assert len(records[pid]['entities']) == len(expected)
    assert papers[pid]['title'] == original['title'] and details[pid]['abstract'] == original['abstract']
    assert all(math.isfinite(papers[pid][axis]) for axis in ['x','y'])
    assert records[pid]['ratings'] == [r['rating'] for r in details[pid]['reviews'] if r['rating'] is not None]
    memberships += len(expected)
with psycopg.connect(os.environ.get('ICLR_DATABASE_URL','host=127.0.0.1 port=55432 dbname=iclr_reviewer'),options='-c default_transaction_read_only=on') as conn:
    rows=conn.execute('''SELECT DISTINCT ON (r.review_id) r.paper_id::text,r.review_id::text,s.rating::float8
        FROM core.review r JOIN core.review_revision rr USING(review_id)
        LEFT JOIN core.review_score s USING(review_revision_id) WHERE r.paper_id=ANY(%s)
        ORDER BY r.review_id,rr.revision_no DESC,rr.review_revision_id DESC''',([int(pid) for pid in expected_ids],)).fetchall()
expected_scores = {(pid,rid):rating for pid,rid,rating in rows}
observed_scores = {(pid,r['review_id']):r['rating'] for pid,detail in details.items() for r in detail['reviews']}
assert observed_scores == expected_scores
csv_rows=list(csv.DictReader((root/'reviews.csv').open()))
assert len(csv_rows)==len({r['review_id'] for r in csv_rows})==len(rows)==sample['meta']['totals']['reviews']
assert sum(rating is not None for _,_,rating in rows)==sample['meta']['totals']['valid_ratings']
result={'passed':True,'data_version':sample['meta']['data_version'],'papers':len(papers),'entities':len(entities),
        'unique_paper_entity_memberships':memberships,'source_evidence_files_verified':len(papers),
        'by_year':dict(Counter(p['year'] for p in papers.values())),'totals':sample['meta']['totals'],
        'source_membership_exact':True,'original_s4_evidence_unchanged':True,'latest_scores_match_database':True}
output=Path(__file__).parents[1]/'docs/research/web-visualization-s4';output.mkdir(parents=True,exist_ok=True)
(output/'data-validation.json').write_text(json.dumps(result,indent=2)+'\n');print(json.dumps(result,indent=2))
