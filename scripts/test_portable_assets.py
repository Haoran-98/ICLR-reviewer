#!/usr/bin/env python3
"""Verify portable provenance, full source exclusion and unsafe-archive rejection."""
import io
from pathlib import Path
import tarfile
import tempfile
from types import SimpleNamespace
from unittest.mock import patch

import compose_manuscript_skills as c
import deployment_paths as paths
from install_demo_assets import extract, verify_files


def rejects(call):
    try:
        call()
    except (ValueError, OSError):
        return
    raise AssertionError('Invalid artifact accepted')


def main():
    for name in ['website', 'release', 'cases']:
        verify_files(paths.DATA/name)
    lib, state = c.load_library(paths.RELEASE)
    identities = list(c.source_identities(paths.RELEASE, lib))
    assert len(identities) == 1286
    assert len({r['paper_id'] for r in identities}) == len(identities)
    candidates = c.s.read(paths.RELEASE/'candidates.json')
    supported = [r for r in state['rules'].values() if r['status'] == 'source_supported']
    for rule in supported:
        sources = c.historical_sources(paths.RELEASE, lib, rule, candidates)
        assert len(sources['display_examples']) == 2
    with tempfile.TemporaryDirectory() as folder:
        root = Path(folder)
        target = root/'target.md'
        target.write_text('A new complete low-rank attention manuscript.\n' * 20)
        args = SimpleNamespace(root=root/'new', release=paths.RELEASE, max_rules=10,
            rule_tokens=4000, shortlist=24, include_candidates=False, manuscript=target,
            paper_id=None, title='Portable target', forum_id=None)
        c.prepare(args)
        args.root = root/'catalog'; args.paper_id = 33089; args.manuscript = None
        c.prepare(args)
        assert (args.root/'MANUSCRIPT.md').read_text() == (paths.CASES/'example/manuscript.md').read_text()
        args.paper_id = None; args.manuscript = target
        for field, value in [('paper_id', identities[0]['paper_id']), ('forum_id', identities[0]['forum_id'])]:
            args.root = root/field
            setattr(args, field, value)
            rejects(lambda: c.prepare(args))
            setattr(args, field, None)
        copied = dict(identities[0], text_digest=c.s.digest(target.read_text()))
        with patch.object(c, 'source_identities', return_value=iter([copied])):
            args.root = root/'copied-text'
            rejects(lambda: c.prepare(args))
        copied = dict(identities[0], manuscript_sha256=c.s.sha(target))
        with patch.object(c, 'source_identities', return_value=iter([copied])):
            args.root = root/'copied-file'
            rejects(lambda: c.prepare(args))
        # Same identity count is insufficient when the signed index content changes.
        original_sha = c.s.sha
        with patch.object(c.s, 'sha', side_effect=lambda p: 'changed' if Path(p).name == 'source_identities.json' else original_sha(p)):
            rejects(lambda: list(c.source_identities(paths.RELEASE, lib)))
        for i, (name, kind) in enumerate([('../outside', tarfile.REGTYPE), ('/outside', tarfile.REGTYPE),
                ('link', tarfile.SYMTYPE), ('hard', tarfile.LNKTYPE)]):
            archive = root/f'unsafe-{i}.tar.gz'
            with tarfile.open(archive, 'w:gz') as tar:
                member = tarfile.TarInfo(name); member.type = kind
                member.size = 1 if kind == tarfile.REGTYPE else 0
                member.linkname = '../outside'
                tar.addfile(member, io.BytesIO(b'x') if member.size else None)
            rejects(lambda: extract(archive, root/f'unsafe-{i}'))
    print(f'passed: three inventories, {len(identities)} source identities, {len(supported)} paired rules, '
          'database-free catalog, ID/forum/file/text isolation, index tamper, traversal and link rejection')


if __name__ == '__main__':
    main()
