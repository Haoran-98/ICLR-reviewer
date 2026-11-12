"""Read-only export of the frozen S6 library and versioned historical review replays."""
import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
RELEASE = Path('/data_big/iclr-review/releases/llm-area-v1')
PILOT = Path('/data_big/iclr-review/experiments/modular_skill100_automanual_ace_v1')


def read(path):
    return json.loads(path.read_text())


def digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True).encode()).hexdigest()


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, separators=(',', ':')) + '\n')


def export(release, pilot, out):
    manifest = read(release/'RELEASE.json')
    seal = read(release/'FROZEN.json')
    if hashlib.sha256((release/'RELEASE.json').read_bytes()).hexdigest() != seal['release_sha256']:
        raise ValueError('Release manifest hash mismatch')
    for name in ['registry.json', 'rule_library.json']:
        if hashlib.sha256((release/name).read_bytes()).hexdigest() != manifest['files'][name]:
            raise ValueError(f'Release file hash mismatch: {name}')
    library = read(release/'rule_library.json')
    if digest(library) != manifest['library_hash']:
        raise ValueError('Library identity mismatch')
    rules = library['rules']
    modules = read(release/'registry.json')['modules']
    membership = [rid for m in modules for rid in m['rule_ids']]
    active = {rid for rid, r in rules.items() if r['status'] != 'deprecated'}
    if set(membership) != active or len(membership) != len(active):
        raise ValueError('Every active rule must occur in exactly one exported module')
    shard_map, shards = {}, {}
    for n, rid in enumerate(sorted(active)):
        shard = f'rules-{n // 100:03}.json'
        shard_map[rid] = shard
        shards.setdefault(shard, {})[rid] = rules[rid]
    for name, content in shards.items():
        write(out/name, content)
    index = []
    for m in modules:
        group = [rules[rid] for rid in m['rule_ids']]
        if any(r['status'] != m['status'] for r in group):
            raise ValueError('Module/rule status mismatch')
        first = group[0]
        index.append(dict(id=m['module_id'], status=m['status'], level=first['level'],
                          family=first.get('mechanism_family', 'other'), rule_ids=m['rule_ids'],
                          scopes=sorted({t for r in group for t in r['scope_terms']}),
                          title=first['title'],
                          source_count=len({pid for r in group for pid in r['source_paper_ids']})))
    replays = []
    replay_concerns = 0
    old_library = read(pilot/'rule_library.json')
    old_hash = digest(old_library)
    for pid in [32064, 40652, 36957, 33499, 23305]:
        inp = read(pilot/f'inputs/{pid}.json')
        composition = read(pilot/f'compositions/{pid}.json')
        review = read(pilot/f'reviews/{pid}/review.json')
        replay_concerns += len(review['concerns'])
        if composition['library_hash'] != old_hash:
            raise ValueError('Historical composition must retain its own library version')
        passages = {p['passage_id']: p for p in inp['paper_passages']}
        raw_text = Path(inp['manuscript_path']).read_text()
        for p in passages.values():
            if raw_text[p['char_start']:p['char_end']] != p['text']:
                raise ValueError('Replay passage offset mismatch')
        evidence_ids = {eid for c in review['concerns'] for eid in c['evidence_ids']}
        if not evidence_ids <= passages.keys():
            raise ValueError('Replay concern references absent evidence')
        if any(c['check_id'] not in composition['rule_ids'] for c in review['concerns']):
            raise ValueError('Replay concern references unloaded rule')
        item = dict(paper_id=pid, title=inp['title'], area=inp['area'], forum_id=inp['forum_id'],
                    year=inp['year'], abstract=inp['abstract'], coverage=inp['coverage'],
                    version=pilot.name, library_hash=old_hash, composition=composition, review=review,
                    rules={rid: old_library['rules'][rid] for rid in composition['rule_ids']},
                    passages=passages)
        write(out/f'replay-{pid}.json', item)
        replays.append({k: item[k] for k in ['paper_id', 'title', 'area', 'version']})
    result = dict(version=manifest['version'], library_hash=manifest['library_hash'],
                  frozen_at=manifest['created_at'], area=manifest['area'],
                  scientific_accuracy_verified=manifest['scientific_accuracy_verified'],
                  rule_statuses=manifest['rule_statuses'], modules=index,
                  module_statuses=dict(Counter(m['status'] for m in modules)),
                  rule_shards=shard_map, replays=replays)
    write(out/'index.json', result)
    report = dict(check='passed', version=result['version'], modules=len(index),
                  active_rules=len(active), rule_statuses=result['rule_statuses'],
                  replay_count=len(replays), replay_concerns=replay_concerns,
                  release_identity_checked=True, replay_evidence_offsets_checked=True,
                  replay_versions_kept_separate=True, model_calls=0)
    write(REPO/'docs/research/web-review-workbench/data-validation.json', report)
    return report


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--release', type=Path, default=RELEASE)
    parser.add_argument('--pilot', type=Path, default=PILOT)
    parser.add_argument('--out', type=Path, default=REPO/'web/public/generated/reviewers')
    args = parser.parse_args()
    print(json.dumps(export(args.release, args.pilot, args.out), ensure_ascii=False, indent=2))
