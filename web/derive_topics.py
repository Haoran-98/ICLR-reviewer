#!/usr/bin/env python3
"""Build reversible concept aliases and map annotations from the published S4 snapshot."""
import argparse
from collections import Counter, defaultdict
import hashlib
import json
import math
from pathlib import Path
import re
import unicodedata

# Explicit equivalent terms only: related methods (e.g. RL and RLHF) remain separate.
FAMILIES = [
    ('large language model', 'LLM|LLMs|large language models'),
    ('multimodal large language model', 'MLLM|MLLMs|multimodal large language models'),
    ('vision-language model', 'VLM|VLMs|vision language models|vision-language models'),
    ('large vision-language model', 'LVLM|LVLMs|large vision language models|large vision-language models'),
    ('language model', 'language models'),
    ('diffusion model', 'diffusion models'),
    ('graph neural network', 'GNN|GNNs|graph neural networks'),
    ('neural network', 'neural networks'),
    ('deep neural network', 'DNN|DNNs|deep neural networks'),
    ('vision transformer', 'ViT|ViTs|vision transformers'),
    ('transformer', 'transformers|transformer model|transformer models'),
    ('reinforcement learning', 'RL'),
    ('reinforcement learning from human feedback', 'RLHF'),
    ('reinforcement learning with verifiable rewards', 'RLVR|reinforcement learning from verifiable rewards'),
    ('supervised fine-tuning', 'SFT|supervised finetuning'),
    ('fine-tuning', 'finetuning|fine tuning'),
    ('low-rank adaptation', 'LoRA|low rank adaptation'),
    ('retrieval-augmented generation', 'RAG|retrieval augmented generation'),
    ('chain-of-thought', 'CoT|chain of thought|chain-of-thought reasoning|chain of thought reasoning'),
    ('in-context learning', 'ICL|in context learning'),
    ('out-of-distribution detection', 'OOD detection|out of distribution detection'),
    ('out-of-distribution generalization', 'OOD generalization|out of distribution generalization'),
    ('out-of-distribution', 'OOD|out of distribution'),
    ('test-time adaptation', 'TTA|test time adaptation'),
    ('test-time training', 'TTT|test time training'),
    ('parameter-efficient fine-tuning', 'PEFT|parameter efficient fine tuning|parameter-efficient finetuning'),
    ('direct preference optimization', 'DPO'),
    ('proximal policy optimization', 'PPO'),
    ('monte carlo tree search', 'MCTS|Monte-Carlo tree search'),
    ('neural ordinary differential equation', 'neural ODE|neural ODEs|neural ordinary differential equations'),
    ('neural radiance field', 'NeRF|NeRFs|neural radiance fields'),
    ('time series', 'time-series'),
    ('machine unlearning', 'machine-unlearning'),
    ('stochastic gradient descent', 'SGD'),
    ('distribution shift', 'distribution shifts'),
    ('mixture of experts', 'MoE|mixture-of-experts'),
    ('key-value cache', 'KV cache|KV caches|key value cache|key-value (KV) cache|key-value caches'),
]
GENERIC = set('framework|unified framework|theoretical framework|our approach|our method|algorithm|architecture|evaluation framework|proposed framework|general framework|training-free framework|benchmark|dataset|comprehensive benchmark|method|approach|model|task|evaluation|generation|detection|inference|optimization framework|novel framework|proposed method'.split('|'))
PLURALS = {'models':'model', 'networks':'network', 'transformers':'transformer', 'agents':'agent',
           'datasets':'dataset', 'benchmarks':'benchmark', 'representations':'representation',
           'hallucinations':'hallucination', 'graphs':'graph', 'tasks':'task', 'shifts':'shift', 'embeddings':'embedding'}


def lexical(text):
    text = unicodedata.normalize('NFKC', text).casefold()
    text = re.sub(r'[‐‑–—−_]', '-', text)
    text = re.sub(r'\s*-\s*', ' ', text)
    text = re.sub(r'\s+', ' ', text).strip().rstrip('.,;:')
    words = text.split()
    if words and words[-1] in PLURALS: words[-1] = PLURALS[words[-1]]
    return ' '.join(words)

GENERIC_KEYS = {lexical(s) for s in GENERIC}
CANONICAL_LABELS = {label for label, _ in FAMILIES}
ALIASES = {lexical(alias): label for label, aliases in FAMILIES for alias in [label, *aliases.split('|')]}


def canonical(text):
    key = lexical(text)
    if key in ALIASES: return ALIASES[key], 'explicit_alias'
    match = re.fullmatch(r'(.+?)\s*\(([^()]+)\)', text.strip())
    if match:
        full, short = (lexical(part) for part in match.groups())
        # Parenthetical strings are stripped only when both sides identify the same known concept.
        if full in ALIASES and ALIASES.get(short) == ALIASES[full]:
            return ALIASES[full], 'explicit_definition'
    match = re.fullmatch(r'(.+?)\s*\(([^()]+)\)(.+)', text.strip())
    if match:
        full, short, suffix = match.groups()
        if lexical(full) in ALIASES and ALIASES.get(lexical(short)) == ALIASES[lexical(full)]:
            return canonical(full + suffix)[0], 'explicit_definition'
    return key, 'lexical'


def derive(output):
    raw_bytes = (output/'domains.json').read_bytes()
    raw = json.loads(raw_bytes)
    sample_bytes = (output/'sample.json').read_bytes()
    sample = json.loads(sample_bytes)
    assert raw['meta']['source_data_version'] == sample['meta']['data_version']
    counts = Counter(i for p in raw['papers'] for i in p['entities'])
    groups = defaultdict(list)
    for entity in raw['entities']:
        key, reason = canonical(entity['normalized'])
        groups[key].append((entity, reason))
    concepts, mapping = [], [None]*len(raw['entities'])
    for key, members in sorted(groups.items()):
        cid = len(concepts)
        for entity, _ in members: mapping[entity['id']] = cid
        primary = max(members, key=lambda row: counts[row[0]['id']])[0]
        label = key if key in CANONICAL_LABELS else primary['label']
        concepts.append({'id':cid, 'label':label, 'key':key,
                         'aliases':sorted({e['label'] for e, _ in members} | {e['normalized'] for e, _ in members}),
                         'types':sorted({e['type'] for e, _ in members}),
                         'raw_entity_ids':[e['id'] for e, _ in members],
                         'rules':sorted({reason for _,reason in members}), 'generic':lexical(key) in GENERIC_KEYS})
    memberships = {p['paper_id']:sorted({mapping[i] for i in p['entities']}) for p in raw['papers']}
    concept_counts = Counter(i for ids in memberships.values() for i in ids)
    by_id = {p['paper_id']:p for p in sample['papers']}
    domain_totals = Counter(p['domain'] for p in sample['papers'])
    domain_concepts = defaultdict(Counter)
    for pid, ids in memberships.items(): domain_concepts[by_id[pid]['domain']].update(ids)
    topic_regions = []
    # Labels describe local neighborhoods in the fixed 2-D map, not an inferred discipline hierarchy.
    import numpy as np
    from sklearn.cluster import KMeans
    rows = sample['papers']
    xy = np.array([[p['x'],p['y']] for p in rows])
    km = KMeans(n_clusters=30, random_state=42, n_init=10).fit(xy)
    regions = []
    for index, center in enumerate(km.cluster_centers_):
        members = [p for p, cluster in zip(rows, km.labels_) if cluster == index]
        local = Counter(i for p in members for i in memberships[p['paper_id']])
        # TF-IDF over paper memberships suppresses corpus-wide catch-all labels.
        eligible = [i for i,n in local.items() if n >= 3 and not concepts[i]['generic']]
        top = sorted(eligible, key=lambda i: local[i] * math.log(1+len(rows)/concept_counts[i]), reverse=True)[:3]
        for field in sorted({p['domain'] for p in members}):
            field_members = [p for p in members if p['domain'] == field]
            if len(field_members) < 5: continue
            local_field = Counter(i for p in field_members for i in memberships[p['paper_id']])
            eligible_field = [i for i,n in local_field.items() if n >= 2 and not concepts[i]['generic']]
            top_field = sorted(eligible_field, key=lambda i: local_field[i] * math.log(1+domain_totals[field]/domain_concepts[field][i]), reverse=True)[:3]
            if not top_field: continue
            topic_regions.append({'id':f'{index}:{field}', 'domain':field,
                'x':sum(p['x'] for p in field_members)/len(field_members),
                'y':sum(p['y'] for p in field_members)/len(field_members),
                'paper_ids':[p['paper_id'] for p in field_members],
                'topics':[{'id':i,'label':concepts[i]['label'],
                           'paper_ids':[p['paper_id'] for p in field_members if i in memberships[p['paper_id']]]} for i in top_field]})
        domains = Counter(p['domain'] for p in members)
        domain, amount = domains.most_common(1)[0]
        regions.append({'id':index, 'x':round(float(center[0]),5), 'y':round(float(center[1]),5),
                        'domain':domain, 'domain_count':amount, 'count':len(members),
                        'topics':[{'id':i,'count':local[i]} for i in top],
                        'paper_ids':[p['paper_id'] for p in members]})
    meta = {'source_data_version':sample['meta']['data_version'],
            'domains_sha256':hashlib.sha256(raw_bytes).hexdigest(),
            'sample_sha256':hashlib.sha256(sample_bytes).hexdigest(),
            'rules_sha256':hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
            'policy':'Known aliases + case/spacing/hyphens + controlled terminal plurals; merge identical concepts across entity types; retain source IDs; deduplicate per paper',
            'region_method':'KMeans(k=30,seed=42,n_init=10) on fixed 2-D map; regional topics ranked by paper-frequency TF-IDF',
            'raw_entities':len(raw['entities']), 'concepts':len(concepts),
            'raw_memberships':sum(len(p['entities']) for p in raw['papers']),
            'concept_memberships':sum(map(len,memberships.values()))}
    payload = {'meta':meta,'concepts':concepts,'entity_to_concept':mapping,'regions':regions}
    (output/'topics.json').write_text(json.dumps(payload,ensure_ascii=False,separators=(',',':')))
    map_regions = [{**r, 'topics':[{**t, 'label':concepts[t['id']]['label'], 'paper_ids':[pid for pid in r['paper_ids'] if t['id'] in memberships[pid]]} for t in r['topics']]} for r in regions]
    (output/'map-labels.json').write_text(json.dumps({'meta':meta,'domains':raw['domains'],'regions':map_regions,'topic_regions':topic_regions},ensure_ascii=False,separators=(',',':')))
    print(json.dumps(meta,ensure_ascii=False,indent=2))
    return payload


if __name__ == '__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',type=Path,default=Path(__file__).parent/'public/generated')
    args=parser.parse_args(); derive(args.output)
