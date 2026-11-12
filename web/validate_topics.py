#!/usr/bin/env python3
"""Validate alias safety, source membership unions and map-label provenance."""
from collections import Counter
import hashlib
import json
from pathlib import Path
from derive_topics import canonical

root = Path(__file__).parent/'public/generated'
raw = json.loads((root/'domains.json').read_text())
sample = json.loads((root/'sample.json').read_text())
data = json.loads((root/'topics.json').read_text())
labels = json.loads((root/'map-labels.json').read_text())
assert data['meta'] == labels['meta']
for name,field in [('domains','domains_sha256'),('sample','sample_sha256')]:
    assert hashlib.sha256((root/f'{name}.json').read_bytes()).hexdigest() == data['meta'][field]
assert hashlib.sha256((Path(__file__).parent/'derive_topics.py').read_bytes()).hexdigest() == data['meta']['rules_sha256']
assert len({canonical(s)[0] for s in ['LLM','LLMs','Large Language Models','large language model','large language models (LLMs)']}) == 1
assert len({canonical(s)[0] for s in ['GNNs','graph neural networks','graph neural network (GNN)']}) == 1
assert canonical('RL')[0] != canonical('RLHF')[0]
assert canonical('language models')[0] != canonical('large language models')[0]
assert canonical('SSL')[0] != canonical('self-supervised learning')[0]
assert canonical('CL')[0] != canonical('continual learning')[0]
assert canonical('TTS')[0] != canonical('test-time scaling')[0]
concepts = data['concepts']; mapping = data['entity_to_concept']
assert len(mapping) == len(raw['entities'])
assert sorted(i for c in concepts for i in c['raw_entity_ids']) == list(range(len(mapping)))
for e in raw['entities']:
    c = concepts[mapping[e['id']]]
    assert e['id'] in c['raw_entity_ids'] and e['type'] in c['types']
    assert e['label'] in c['aliases'] and c['key'] == canonical(e['normalized'])[0]
by_paper = {p['paper_id']:p for p in sample['papers']}
members = {p['paper_id']:{mapping[i] for i in p['entities']} for p in raw['papers']}
llm = next(c for c in concepts if c['key'] == 'large language model')
llm_source = set(llm['raw_entity_ids'])
llm_papers = {p['paper_id'] for p in raw['papers'] if set(p['entities']) & llm_source}
assert llm_papers == {pid for pid, ids in members.items() if llm['id'] in ids}
assert len(llm_papers) < sum(sum(i in llm_source for i in p['entities']) for p in raw['papers']), 'Synonym double-counts must be removed'
region_ids = [pid for r in data['regions'] for pid in r['paper_ids']]
assert len(region_ids) == len(set(region_ids)) == len(by_paper)
assert set(region_ids) == set(by_paper)
for region, label in zip(data['regions'],labels['regions']):
    assert region['count'] == len(region['paper_ids'])
    areas = Counter(by_paper[pid]['domain'] for pid in region['paper_ids'])
    assert areas[region['domain']] == region['domain_count'] == max(areas.values())
    for t, displayed in zip(region['topics'],label['topics']):
        expected = {pid for pid in region['paper_ids'] if t['id'] in members[pid]}
        assert t['count'] == len(expected) and set(displayed['paper_ids']) == expected
        assert displayed['label'] == concepts[t['id']]['label'] and not concepts[t['id']]['generic']
for region in labels['topic_regions']:
    assert all(by_paper[pid]['domain'] == region['domain'] for pid in region['paper_ids'])
    for topic in region['topics']:
        expected = {pid for pid in region['paper_ids'] if topic['id'] in members[pid]}
        assert len(expected) >= 2 and set(topic['paper_ids']) == expected
        assert topic['label'] == concepts[topic['id']]['label']
assert sum(map(len,members.values())) == data['meta']['concept_memberships']
result = {'passed':True, **data['meta'], 'llm_union_papers':len(llm_papers), 'map_regions':len(data['regions']),
          'source_ids_preserved':True, 'domain_specific_topic_regions':len(labels['topic_regions']), 's4_topic_parent_domains_verified':True, 'per_paper_concepts_deduplicated':True, 'regional_topic_memberships_verified':True}
output=Path(__file__).parents[1]/'docs/research/web-visualization-s4/topic-validation.json'
output.write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
print(json.dumps(result,ensure_ascii=False,indent=2))
