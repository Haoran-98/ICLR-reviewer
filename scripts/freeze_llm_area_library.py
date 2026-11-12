#!/usr/bin/env python3
"""Package the completed LLM-area library without changing its sealed run."""
from __future__ import annotations

import argparse
from collections import Counter
import fcntl
import json
from pathlib import Path
import re
import shutil
import sqlite3
import tempfile
from types import SimpleNamespace

import recover_llm_area_review_skills as r

s = r.s


def export(root, state):
    r.p.area.export(root, state)
    registry = s.read(root/'registry.json'); repairs = []
    for module in registry['modules']:
        old = root/module['path']; name = re.sub('-+', '-', old.parent.name).strip('-')
        if name == old.parent.name: continue
        new = old.parent.with_name(name)
        s.require(not new.exists(), 'Normalized module name collision')
        text = old.read_text().replace('name: '+old.parent.name+'\n', 'name: '+name+'\n', 1)
        old.parent.rename(new); (new/'SKILL.md').write_text(text)
        path = str((new/'SKILL.md').relative_to(root))
        repairs.append(dict(module_id=module['module_id'], old_path=module['path'], path=path))
        module['path'] = path
    s.write(root/'registry.json', registry)
    s.write(root/'EXPORT_REPAIRS.json', dict(reason='Normalize consecutive hyphens in exported Skill names',
                                           changed_modules=repairs, scientific_rules_unchanged=True))


def check_modules(root, state):
    registry = s.read(root/'registry.json')
    s.require(registry['library_hash'] == s.digest(state), 'Registry library mismatch')
    expected = {rid for rid, rule in state['rules'].items() if rule['status'] != 'deprecated'}
    seen, paths = [], set()
    for module in registry['modules']:
        path = Path(module['path'])
        s.require(not path.is_absolute() and '..' not in path.parts and
                  path.parts[0] == 'skills' and path.name == 'SKILL.md', 'Unsafe module path')
        s.require(str(path) not in paths, 'Duplicate module path')
        paths.add(str(path))
        rules = s.read(root/path.parent/'rules.json')
        s.require([rule['rule_id'] for rule in rules] == module['rule_ids'], 'Module membership mismatch')
        s.require(all(rule == state['rules'][rule['rule_id']] and rule['status'] == module['status']
                      for rule in rules), 'Module differs from frozen rules')
        text = (root/path).read_text()
        name = path.parent.name
        s.require(re.fullmatch('[a-z0-9]+(?:-[a-z0-9]+)*', name) and len(name) <= 64 and
                  text.startswith('---\nname: '+name+'\n')
                  and '\ndescription: ' in text and '\n---\n' in text[4:], 'Invalid Skill frontmatter')
        s.require(all(s.rule_markdown(rule) in text and
                      '\n对象：'+rule['review_object']+'\n失效机制：'+rule['failure_mechanism']+'\n' in text
                      for rule in rules), 'Skill text differs from frozen rules')
        seen.extend(module['rule_ids'])
    s.require(len(seen) == len(set(seen)) and set(seen) == expected, 'Missing or repeated exported rules')
    files = {str(path.relative_to(root)) for path in (root/'skills').rglob('*') if path.is_file()}
    s.require(files == paths | {str(Path(path).with_name('rules.json')) for path in paths},
              'Unregistered module files')
    return dict(check='passed', modules=len(paths), rules=len(seen),
                module_statuses=dict(Counter(m['status'] for m in registry['modules'])))


def source_inventory(root, hashes=None):
    """Hash retained provenance, including inherited attempts in the original run."""
    names = ['manifest.json', 'config.json', 'parallel_curation.json', 'RECOVERY.json',
             'FROZEN.json', 'AUDIT.json', 'RECOVERY_AUDIT.json', 'SCOPE_AUDIT.json',
             'queue.json', 'rule_library.json', 'registry.json', 'candidates.json',
             'jobs.json', 'eligibility.json', 'extraction_failures.json',
             'review_exclusions.json', 'retry_allowances.json', 'extraction_summary.json']
    paths = [root/name for name in names if (root/name).is_file()]
    for name in ['inputs', 'cases', 'updates', 'evidence', 'parallel_tasks', 'requests',
                 'requests_local', 'requests_deepseek', 'baseline', 'runtime/migrations']:
        paths.extend(path for path in (root/name).rglob('*') if path.is_file())
    hashes = {} if hashes is None else hashes
    result = {}
    for path in sorted(set(paths)):
        resolved = path.resolve()
        if resolved not in hashes: hashes[resolved] = s.sha(path)
        result[str(path.relative_to(root))] = hashes[resolved]
    return result


def build(source, destination, version):
    s.require(re.fullmatch('[a-z0-9][a-z0-9._-]{0,63}', version), 'Invalid release version')
    s.require(not destination.exists(), 'Release already exists; verify it or choose a new version')
    record = s.read(source/'RECOVERY.json')
    s.require(record['stage'] == 'completed' and s.read(source/'progress.json')['run_state'] == 'completed',
              'Recovery is incomplete')
    state, queue = r.read_db(source)
    s.require((state, queue) == (s.read(source/'rule_library.json'), s.read(source/'queue.json')),
              'SQLite and exported state disagree')
    s.require(s.read(source/'FROZEN.json')['library_hash'] == s.digest(state), 'Frozen library mismatch')
    s.require(not s.read(source/'extraction_failures.json') and
              not any(q['status'] in ['pending', 'deferred'] for q in queue.values()), 'Pending work remains')
    s.require(record['runner_sha256'] == s.sha(r.__file__) and
              record['inherited_runner_sha256'] == s.sha(r.p.__file__), 'Runner code changed')
    destination.parent.mkdir(parents=True, exist_ok=True)
    # Work beside the destination so publication is one rename; failed builds leave no partial release.
    with tempfile.TemporaryDirectory(prefix='.freeze-', dir=destination.parent) as temporary:
        work = Path(temporary); audit_root = work/'audit'; audit_root.mkdir()
        for path in source.iterdir():
            if path.name not in ['curation.sqlite3', 'curation.sqlite3-wal', 'curation.sqlite3-shm',
                                  'AUDIT.json', 'RECOVERY_AUDIT.json', 'SCOPE_AUDIT.json', 'SCOPE.md']:
                (audit_root/path.name).symlink_to(path)
        with sqlite3.connect('file:'+str(source/'curation.sqlite3')+'?mode=ro', uri=True) as src, \
                sqlite3.connect(audit_root/'curation.sqlite3') as dest:
            src.backup(dest)
        print('Rechecking source spans, queue, support, requests and recovery history', flush=True)
        config = s.read(source/r.p.CONFIG)
        audit = r.p.area.audit(SimpleNamespace(root=audit_root, source_root=s.SOURCE,
            concurrency=config['providers']['openai']['concurrency']), s.read(source/'manifest.json'))
        audit.update(providers=config['providers'], **{provider: r.p.audit_chat(audit_root, config, provider)
                     for provider in ['deepseek', 'local']})
        r.p.area.validate_scope(audit_root)
        recovery = r.verify(audit_root, record)
        release = work/'release'; release.mkdir()
        for name in ['rule_library.json', 'queue.json', 'candidates.json']:
            shutil.copyfile(source/name, release/name)
        export(release, state)
        modules = check_modules(release, state)
        candidates = s.read(source/'candidates.json')
        unresolved = {cid: dict(disposition=q, candidate=candidates[cid]) for cid, q in queue.items()
                      if q['status'] in ['unresolved', 'needs_evidence']}
        s.write(release/'unresolved.json', unresolved)
        s.write(release/'AUDIT.json', dict(execution=audit, recovery=recovery, exports=modules,
                                         scope=s.read(audit_root/'SCOPE_AUDIT.json')))
        source_roots = [source, Path(record['source_root'])]
        print('Hashing retained source artifacts and manuscript references', flush=True)
        hash_cache = {}; inventory = {str(root): source_inventory(root, hash_cache) for root in source_roots}
        documents = {}
        for path in (source/'inputs').glob('*.json'):
            row = s.read(path)
            for path_key, hash_key in [('manuscript_path', 'manuscript_sha256'), ('s4_path', 's4_sha256')]:
                documents[row[path_key]] = row[hash_key]
        s.write(release/'PROVENANCE.json', dict(sources=inventory, external_files=documents,
            storage='Hash-addressed references to retained local run artifacts; keep both source runs available'))
        code = dict(record['protocol_hashes'])
        code.update({str(Path(path).relative_to(s.REPO)): s.sha(path)
                     for path in [r.__file__, r.p.__file__, r.p.area.__file__, __file__]})
        for name, digest in code.items():
            s.require(s.sha(s.REPO/name) == digest, 'Protocol changed: '+name)
            target = release/'protocol'/name; target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(s.REPO/name, target)
        statuses = dict(Counter(rule['status'] for rule in state['rules'].values()))
        (release/'README.md').write_text('\n'.join([
            '# LLM-area review library '+version, '',
            'Library hash: `'+s.digest(state)+'`. Rule revision: '+str(state['version'])+'.',
            'Default composition pool: `skills/source_supported/`; `skills/candidate/` requires explicit opt-in.',
            'Load modules through `registry.json`, then judge each rule against the new manuscript and a rule/token budget.',
            'Historical sources are development material; exclude every source manuscript from unseen-paper acceptance tests.',
            'All candidates have terminal dispositions. `unresolved.json` preserves unresolved and evidence-gap cases.',
            'Source spans, history, provider settings and module membership passed execution audits.',
            'Scientific correctness and improved review quality await new-paper validation.',
            'PROVENANCE.json records hashes of retained original artifacts; it is not a standalone evidence archive.', '',
            'Verify from the project: `python3 scripts/freeze_llm_area_library.py verify --release <release-dir>`.', '']))
        payload = {str(path.relative_to(release)): s.sha(path)
                   for path in sorted(release.rglob('*')) if path.is_file()}
        s.write(release/'RELEASE.json', dict(version=version, created_at=s.now(),
            area=r.p.area.AREA, library_hash=s.digest(state), rule_revision=state['version'],
            rule_statuses=statuses, queue_statuses=dict(Counter(q['status'] for q in queue.values())),
            unresolved_candidates=len(unresolved), pending_candidates=0, exports=modules,
            source_root=str(source), providers=config['providers'], protocol_hashes=code,
            scientific_accuracy_verified=False, files=payload))
        s.write(release/'FROZEN.json', dict(version=version, library_hash=s.digest(state),
            release_sha256=s.sha(release/'RELEASE.json'), status='frozen_unadjudicated'))
        verify(release)
        release.rename(destination)
    return s.read(destination/'RELEASE.json')


def verify(root):
    seal = s.read(root/'FROZEN.json'); release = s.read(root/'RELEASE.json')
    s.require(s.sha(root/'RELEASE.json') == seal['release_sha256'], 'Release manifest changed')
    actual = {str(path.relative_to(root)) for path in root.rglob('*') if path.is_file()}
    s.require(actual == set(release['files']) | {'RELEASE.json', 'FROZEN.json'}, 'Release file inventory changed')
    for name, digest in release['files'].items():
        s.require(s.sha(root/name) == digest, 'Release file changed: '+name)
    state = s.read(root/'rule_library.json')
    s.require(s.digest(state) == release['library_hash'] == seal['library_hash'] and
              release['version'] == seal['version'], 'Release identity mismatch')
    check_modules(root, state)
    provenance = s.read(root/'PROVENANCE.json'); hashes = {}
    for location, files in provenance['sources'].items():
        for name, digest in files.items():
            path = (Path(location)/name).resolve()
            if path not in hashes: hashes[path] = s.sha(path)
            s.require(hashes[path] == digest, 'Retained source changed: '+str(path))
    for path, digest in provenance.get('external_files', {}).items():
        s.require(s.sha(path) == digest, 'Source manuscript or S4 output changed: '+path)
    return dict(check='passed', version=release['version'], library_hash=release['library_hash'],
                modules=release['exports']['modules'], rule_statuses=release['rule_statuses'],
                unresolved_candidates=release['unresolved_candidates'], pending_candidates=0)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=['build', 'verify'])
    parser.add_argument('--source', type=Path, default=r.ROOT)
    parser.add_argument('--release', type=Path, required=True)
    parser.add_argument('--version', default='llm-area-v1')
    args = parser.parse_args(); source = args.source.resolve(); release = args.release.resolve()
    if args.command == 'verify': result = verify(release)
    else:
        with (source/'run.lock').open('a') as lock:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            result = build(source, release, args.version)
        result = {k: v for k, v in result.items() if k != 'files'}
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == '__main__': main()
