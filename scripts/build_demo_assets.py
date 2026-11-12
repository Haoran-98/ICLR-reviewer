#!/usr/bin/env python3
"""Build deterministic public demo packages from immutable research artifacts."""
import argparse
from copy import deepcopy
import gzip
import hashlib
import json
from pathlib import Path
import re
import shutil
import tarfile


def sha(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            h.update(block)
    return h.hexdigest()


def digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True).encode()).hexdigest()


def read(path):
    return json.loads(Path(path).read_text())


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n')


PRIVATE_KEYS = {'api_key', 'base_url', 'endpoint', 'password', 'password_hash', 'salt',
                'source_input', 'source_case', 'source_manuscript', 'manuscript_path',
                's4_path', 'source_root', 'reused_from'}


def sanitized(value):
    if isinstance(value, dict):
        return {k: sanitized(v) for k, v in value.items() if k.lower() not in PRIVATE_KEYS}
    if isinstance(value, list):
        return [sanitized(v) for v in value]
    return value


def inventory(root):
    return {str(p.relative_to(root)): sha(p) for p in sorted(root.rglob('*')) if p.is_file()}


def check_public(root):
    # Credentials/configuration are excluded structurally; reject machine paths and secret syntax too.
    forbidden = re.compile(rb'/data_big/|/home/[^/\s]+/|(?<![a-zA-Z0-9])sk-[a-zA-Z0-9_-]{20,}|(?i:bearer [a-z0-9_-]{20,})')
    failures = []
    for path in root.rglob('*'):
        if path.is_symlink():
            failures.append(str(path.relative_to(root)))
        elif path.is_file() and forbidden.search(path.read_bytes()):
            failures.append(str(path.relative_to(root)))
    if failures:
        raise ValueError('Public asset audit failed: ' + ', '.join(failures[:15]))


def rules_package(source, dest):
    upstream = read(source/'RELEASE.json')
    seal = read(source/'FROZEN.json')
    assert sha(source/'RELEASE.json') == seal['release_sha256']
    for name, checksum in upstream['files'].items():
        assert sha(source/name) == checksum, 'Changed upstream artifact: ' + name
    for name in ['rule_library.json', 'registry.json', 'candidates.json', 'queue.json',
                 'unresolved.json', 'AUDIT.json', 'EXPORT_REPAIRS.json']:
        shutil.copyfile(source/name, dest/name)
    assert digest(read(dest/'rule_library.json')) == upstream['library_hash']
    for name in upstream['files']:
        if name.startswith('skills/'):
            target = dest/name
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source/name, target)
    original_root = Path(upstream['source_root'])
    original_index = read(source/'PROVENANCE.json')['sources'][str(original_root)]
    identities = []
    origins = {}
    candidates = read(dest/'candidates.json')
    required_cases = {f'cases/{c["job_id"]}.json' for c in candidates.values() if c['paired_source']}
    for name, checksum in sorted(original_index.items()):
        if not re.fullmatch(r'inputs/\d+\.json', name) and name not in required_cases:
            continue
        path = original_root/name
        assert sha(path) == checksum, 'Changed source: ' + name
        row = read(path)
        if name.startswith('inputs/'):
            text = Path(row['manuscript_path']).read_text()
            assert hashlib.sha256(text.encode()).hexdigest() == row['manuscript_sha256']
            identities.append(dict(paper_id=row['paper_id'], forum_id=row['forum_id'],
                manuscript_sha256=row['manuscript_sha256'], text_digest=digest(text)))
            keep = ['paper_id', 'forum_id', 'title', 'manuscript_sha256', 'review_units']
        else:
            keep = ['paper_id', 'job_id', 'manuscript_passages', 'review_unit_ids']
        write(dest/'sources'/name, {k: row[k] for k in keep if k in row})
        origins[name] = checksum
    write(dest/'source_identities.json', dict(version=1, count=len(identities), papers=identities))
    write(dest/'PROVENANCE.json', dict(sources={'sources': inventory(dest/'sources')},
        upstream_source_hashes=origins, source_identity_count=len(identities)))
    write(dest/'UPSTREAM.json', dict(version=upstream['version'],
        release_sha256=seal['release_sha256'], library_hash=upstream['library_hash'],
        source_identity_count=len(identities), protocol_hashes=upstream['protocol_hashes']))
    manifest = {k: deepcopy(upstream[k]) for k in ['version', 'created_at', 'area', 'library_hash',
        'rule_revision', 'rule_statuses', 'queue_statuses', 'unresolved_candidates', 'pending_candidates',
        'exports', 'scientific_accuracy_verified']}
    manifest.update(distribution='portable-demo-v1', source_root='sources',
        source_identities='source_identities.json', files=inventory(dest))
    write(dest/'RELEASE.json', manifest)
    write(dest/'FROZEN.json', dict(version=upstream['version'], library_hash=upstream['library_hash'],
        release_sha256=sha(dest/'RELEASE.json'), status='frozen'))


def case_package(source, dest):
    job = sanitized(read(source/'job.json'))
    assert job['state'] == 'completed'
    job['read_only'] = True
    run = dest/'runs'/job['id']
    write(run/'job.json', job)
    attempt = source/f'attempt-{job["attempt"]}'
    for stage, names in {'compose': ['profile.json', 'composition.json', 'checks.json', 'manuscript.json'],
                         'review': ['review.json', 'evidence.json', 'LOCAL_RECOVERY.json']}.items():
        for name in names:
            if (attempt/stage/name).exists():
                write(run/f'attempt-{job["attempt"]}'/stage/name, sanitized(read(attempt/stage/name)))
    text = (attempt/'compose/MANUSCRIPT.md').read_text()
    (dest/'example').mkdir()
    (dest/'example/manuscript.md').write_text(text)
    write(dest/'catalog.json', {'33089': dict(paper_id=33089, forum_id='vBJKZ19XGY',
        title=job['title'], abstract='', manuscript='example/manuscript.md',
        manuscript_sha256=sha(dest/'example/manuscript.md'))})
    write(dest/'example.json', dict(run_id=job['id'], historical=True, read_only=True,
        upstream_rule_release=read(attempt/'compose/composition.json')['release_sha256']))


def archive(root, output):
    with output.open('wb') as raw, gzip.GzipFile(filename='', mode='wb', fileobj=raw, mtime=0) as compressed:
        with tarfile.open(fileobj=compressed, mode='w|') as tar:
            for path in sorted(root.rglob('*')):
                if not path.is_file():
                    continue
                info = tar.gettarinfo(str(path), str(path.relative_to(root)))
                info.uid = info.gid = info.mtime = 0
                info.uname = info.gname = ''
                info.mode = 0o644
                with path.open('rb') as stream:
                    tar.addfile(info, stream)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--snapshot', type=Path, required=True)
    parser.add_argument('--release', type=Path, required=True)
    parser.add_argument('--case', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--version', default='demo-2026-11-12-v1')
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=False)
    staging = args.output/'staging'
    staging.mkdir()
    website = staging/'website'; website.mkdir()
    for path in sorted(args.snapshot.rglob('*')):
        if not path.is_file():
            continue
        target = website/'generated'/path.relative_to(args.snapshot)
        target.parent.mkdir(parents=True, exist_ok=True)
        if path.suffix == '.json':
            write(target, sanitized(read(path)))
        else:
            shutil.copyfile(path, target)
    rules = staging/'rules'; rules.mkdir()
    rules_package(args.release, rules)
    cases = staging/'cases'; cases.mkdir()
    case_package(args.case, cases)
    entries = []
    for name in ['website', 'rules', 'cases']:
        root = staging/name
        write(root/'PACKAGE.json', dict(version=args.version, kind=name, files=inventory(root)))
        check_public(root)
        path = args.output/f'{name}.tar.gz'
        archive(root, path)
        parts = []
        with path.open('rb') as stream:
            for i in range(100):
                block = stream.read(40 * 1024 * 1024)
                if not block:
                    break
                part = args.output/f'{name}.tar.gz.part{i:02d}'
                part.write_bytes(block)
                parts.append(dict(file=part.name, bytes=part.stat().st_size, sha256=sha(part)))
        entries.append(dict(name=name, file=path.name, bytes=path.stat().st_size, sha256=sha(path), parts=parts))
        print(f'{name}: {path.stat().st_size:,} compressed bytes, {len(parts)} parts', flush=True)
    manifest = dict(version=args.version, base_url='', packages=entries)
    write(args.output/'manifest.json', manifest)
    (args.output/'SHA256SUMS').write_text(''.join(f'{e["sha256"]}  {e["file"]}\n' for e in entries) +
        ''.join(f'{p["sha256"]}  {p["file"]}\n' for e in entries for p in e['parts']))


if __name__ == '__main__':
    main()
