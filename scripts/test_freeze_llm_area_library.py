#!/usr/bin/env python3
"""Check that release validation rejects stale modules and altered provenance."""
from pathlib import Path
import tempfile

import freeze_llm_area_library as f
from test_full_s4_review_skills import candidate


def rejects(call, message):
    try:
        call()
    except ValueError:
        return
    raise AssertionError(message)


def main():
    with tempfile.TemporaryDirectory() as folder:
        root = Path(folder)/'release'; root.mkdir()
        candidates = {cid: candidate(cid, i) for i, cid in enumerate(['a', 'b'])}
        rule = {key: candidates['a'][key] for key in f.r.f.check_fields()}
        rule['candidate_ids'] = ['a', 'b']
        rule = f.s.enrich(rule, candidates, 'R0001', 1)
        state = dict(version=1, next_id=2, rules={'R0001': rule})
        f.s.write(root/'rule_library.json', state)
        f.export(root, state)
        assert f.check_modules(root, state)['rules'] == 1
        stale = root/'skills/candidate/stale'; stale.mkdir(parents=True)
        (stale/'SKILL.md').write_text('old module')
        rejects(lambda: f.check_modules(root, state), 'Stale module accepted')
        (stale/'SKILL.md').unlink(); stale.rmdir()
        registry = f.s.read(root/'registry.json')
        skill = root/registry['modules'][0]['path']; original = skill.read_text()
        skill.write_text(original.replace('对象：', '对象已修改：'))
        rejects(lambda: f.check_modules(root, state), 'Altered scientific text accepted')
        skill.write_text(original)
        source = Path(folder)/'source'; source.mkdir()
        f.s.write(source/'manifest.json', dict(source=True))
        document = source/'paper.md'; document.write_text('original manuscript')
        f.s.write(root/'PROVENANCE.json', dict(sources={str(source): f.source_inventory(source)},
                                             external_files={str(document): f.s.sha(document)}))
        payload = {str(p.relative_to(root)): f.s.sha(p) for p in root.rglob('*') if p.is_file()}
        release = dict(version='test-v1', library_hash=f.s.digest(state), files=payload,
                       exports=f.check_modules(root, state), rule_statuses={rule['status']: 1},
                       unresolved_candidates=0)
        f.s.write(root/'RELEASE.json', release)
        f.s.write(root/'FROZEN.json', dict(version='test-v1', library_hash=f.s.digest(state),
                                         release_sha256=f.s.sha(root/'RELEASE.json')))
        assert f.verify(root)['check'] == 'passed'
        f.s.write(source/'manifest.json', dict(source=False))
        rejects(lambda: f.verify(root), 'Altered retained source accepted')
        f.s.write(source/'manifest.json', dict(source=True))
        document.write_text('altered manuscript')
        rejects(lambda: f.verify(root), 'Altered external manuscript accepted')
        document.write_text('original manuscript')
        skill.write_text(original+'tampered')
        rejects(lambda: f.verify(root), 'Altered payload accepted')
        skill.write_text(original)
        (root/'extra.json').write_text('{}')
        rejects(lambda: f.verify(root), 'Unregistered payload accepted')
        (root/'extra.json').unlink()
        # Old exporter truncates this module key on a hyphen, producing an invalid double hyphen.
        rule.update(level='method', scope_terms=['adaptive regularization'], mechanism_family='robustness_boundary')
        other = Path(folder)/'normalized'; other.mkdir()
        f.export(other, state)
        repairs = f.s.read(other/'EXPORT_REPAIRS.json')['changed_modules']
        assert len(repairs) == 1 and '--' not in Path(repairs[0]['path']).parent.name
        assert f.check_modules(other, state)['rules'] == 1
    print('passed: exact module coverage, stale-module rejection, scientific text integrity, '
          'release hashes, retained provenance integrity, external manuscript integrity, '
          'extra-file rejection and module name normalization')


if __name__ == '__main__': main()
