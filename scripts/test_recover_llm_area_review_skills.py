#!/usr/bin/env python3
"""Recovery epoch, provider handoff, evidence offsets and provenance checks."""
from copy import deepcopy
import json
from pathlib import Path
import sqlite3
import tempfile
import threading
from types import SimpleNamespace
from unittest.mock import patch

import recover_llm_area_review_skills as r
from test_full_s4_review_skills import candidate


def main():
    with tempfile.TemporaryDirectory() as folder:
        base = Path(folder); source = base/'source'; source.mkdir(); root = base/'new'; root.mkdir()
        candidates = {f'c{i}': candidate(f'c{i}', i) for i in range(4)}
        candidates['c3']['mechanism_family'] = 'claim_scope'
        history = [dict(version=1, status='deferred'), dict(version=2, status='deferred')]
        original = {cid: dict(status='unresolved', attempts=2, previously_represented=False,
                             rule_ids=[], reason='结构或来源校验未通过', history=deepcopy(history)) for cid in candidates}
        queue = deepcopy(original)
        for cid, q in queue.items():
            q.update(status='pending', attempts=0, recovery_epoch=dict(original_status='unresolved',
                original_attempts=2, original_history_length=2, original_reason=q['reason'], budget=2,
                first_provider='local' if cid == 'c2' else 'openai'))
        r.s.write(root/'baseline/queue.json', original); r.s.write(root/'candidates.json', candidates)
        r.s.write(source/'marker.json', dict(frozen=True))
        record = dict(source_root=str(source), source_files={'marker.json': r.s.sha(source/'marker.json')},
            source_candidate_sha256=r.s.sha(root/'candidates.json'), protocol_hashes=r.f.hashes(),
            target_ids=list(candidates), pilot_ids=list(candidates))
        maker = r.RecoveryTasks(root, record)
        maker.evidence = lambda cid: dict(candidate_id=cid, manuscript_passages=[], review_units=[])
        state = dict(version=2, next_id=1, rules={}); retrieval = r.f.Retrieval(candidates)
        first = maker('p000001', 'openai', state, queue, candidates, retrieval, set())
        assert set(first['data']['focus_ids']) == {'c0', 'c1'}
        assert all(c['mechanism_family'] == 'guarantee_transfer' for c in first['data']['global_neighbors'])
        second = maker('p000002', 'local', state, queue, candidates, retrieval, set(first['data']['focus_ids']))
        assert second['data']['focus_ids'] == ['c2']
        rule = {k: candidates['c0'][k] for k in r.f.check_fields()}; rule['candidate_ids'] = ['c0', 'c1']
        delta = dict(operations=[dict(type='ADD', target_ids=[], rules=[rule],
                     evidence_candidate_ids=['c0', 'c1'], reason='同一失效机制')],
            decisions=[dict(candidate_id=cid, status='incorporated', rule_refs=['op:0'], reason='来源保留')
                       for cid in first['data']['focus_ids']], deferred_candidate_ids=[])
        db = r.f.state_db(root)
        with db:
            db.execute('INSERT INTO meta VALUES (?,?)', ('state', json.dumps(dict(version=2, next_id=1))))
            db.executemany('INSERT INTO queue VALUES (?,?)', [(cid, json.dumps(q)) for cid, q in queue.items()])
        assert r.p.commit(root, db, state, queue, candidates, first, delta)
        assert queue['c0']['attempts'] == 1 and queue['c0']['history'][:2] == history
        # The second recovery visit is assigned to the other provider.
        queue['c0']['status'] = 'deferred'
        switched = maker('p000003', 'local', state, queue, candidates, retrieval, {'c2'})
        assert switched['data']['focus_ids'] == ['c0']
        assert maker('p000004', 'openai', state, queue, candidates, retrieval, {'c3'}) is None
        maker.assist_local = True
        assisted = maker('p000005', 'openai', state, queue, candidates, retrieval, {'c3'})
        assert assisted['data']['focus_ids'] == ['c2'] and assisted['assisted_local']
        assert assisted['queue']['c2']['recovery_last_provider'] == 'openai'
        assert not r.available_candidates(queue, 'openai', {'c2', 'c3'}, True)
        # A failed stolen first visit returns to Qwen, based on the actual execution provider.
        retry_queue = deepcopy(queue)
        retry_queue['c2'] = dict(assisted['queue']['c2'], attempts=1, status='deferred')
        assert 'c2' in r.available_candidates(retry_queue, 'local', set(), True)
        assert 'c2' not in r.available_candidates(retry_queue, 'openai', {'c3'}, True)
        # OpenAI keeps its own pending work ahead of otherwise available local work.
        assert set(r.available_candidates(queue, 'openai', set(), True)) == {'c3'}
        queue['c0']['status'] = 'incorporated'
        result = r.verify(root, record, pilot=True)
        assert result['outcomes']['incorporated'] == 2 and result['new_valid_visits'] == 2
        # An extra visit without matching history must fail verification.
        with db:
            changed = deepcopy(queue['c0']); changed['attempts'] = 3
            db.execute('UPDATE queue SET value=? WHERE id=?', (json.dumps(changed), 'c0'))
        try: r.verify(root, record, pilot=True)
        except ValueError: pass
        else: raise AssertionError('An over-budget recovery passed')
        db.close()

        text = '# Method\n\nOptimization relaxation requires an approximation bound.\n\n# Appendix\n\nThe bound controls the final guarantee.\n'
        manuscript = source/'paper.md'; manuscript.write_text(text)
        row = dict(manuscript_path=str(manuscript), manuscript_sha256=r.s.sha(manuscript), headings=[],
                   review_units=[dict(passage_id='u', text='Where is the approximation bound?')])
        r.s.write(source/'inputs/0.json', row)
        evidence_maker = r.RecoveryTasks(root, record); evidence_maker.candidates = candidates
        evidence = evidence_maker.evidence('c0')
        assert evidence['manuscript_passages'] and evidence['review_units']
        assert all(text[p['char_start']:p['char_end']] == p['text'] for p in evidence['manuscript_passages'])
        assert not evidence['manuscript_version_date_verified'] and candidates['c0']['paired_source']

        # A fresh recovery must carry the historical retry seal without reusing old task markers.
        frozen = base/'frozen'; frozen.mkdir()
        for name in ['manifest', 'config', 'parallel_curation', 'FROZEN', 'AUDIT', 'progress', 'queue',
                     'rule_library', 'jobs', 'eligibility', 'extraction_failures', 'extraction_summary',
                     'review_exclusions', 'retry_allowances']:
            r.s.write(frozen/(name+'.json'), {})
        r.s.write(frozen/'progress.json', dict(run_state='completed'))
        r.s.write(frozen/'AUDIT.json', dict(check='passed'))
        r.s.write(frozen/'parallel_curation.json', dict(providers=dict(deepseek=dict(concurrency=50))))
        r.s.write(frozen/'candidates.json', candidates)
        for name in ['inputs', 'cases', 'updates']: (frozen/name).mkdir()
        with r.f.state_db(frozen) as inherited:
            inherited.execute('INSERT INTO meta VALUES (?,?)', ('state', json.dumps(dict(version=2, next_id=1))))
            inherited.execute('INSERT INTO meta VALUES (?,?)', ('parallel_task/p000001', 'committed'))
            inherited.executemany('INSERT INTO queue VALUES (?,?)',
                                  [(cid, json.dumps(q)) for cid, q in original.items()])
        prepared = base/'prepared'; prepared_record = r.prepare(prepared, frozen)
        assert r.s.sha(prepared/'retry_allowances.json') == prepared_record['source_files']['retry_allowances.json']
        with sqlite3.connect(prepared/'curation.sqlite3') as inherited:
            assert inherited.execute("SELECT count(*) FROM meta WHERE key LIKE 'parallel_task/%'").fetchone()[0] == 0
        _, prepared_queue = r.read_db(prepared)
        assert prepared_queue['c0']['attempts'] == 0 and prepared_queue['c0']['history'] == history
        assert prepared_queue['c0']['recovery_epoch']['original_attempts'] == 2

        # Run the actual coordinator with seven blocked inference calls: OpenAI 4 + local 3.
        many = {f'm{i:02d}': candidate(f'm{i:02d}', i) for i in range(14)}
        initial = {cid: deepcopy(original['c0']) for cid in many}
        r.s.write(frozen/'candidates.json', many); r.s.write(frozen/'queue.json', initial)
        with sqlite3.connect(frozen/'curation.sqlite3') as inherited:
            inherited.execute('DELETE FROM queue')
            inherited.executemany('INSERT INTO queue VALUES (?,?)', [(cid, json.dumps(q)) for cid, q in initial.items()])
            inherited.execute('INSERT INTO meta VALUES (?,?)', ('candidate_hash', r.s.digest(many)))
        epoch = base/'epoch'; epoch_record = r.prepare(epoch, frozen)
        providers = dict(openai=dict(model=r.s.MODEL, reasoning_effort='medium', concurrency=4),
            deepseek=dict(model='unused', concurrency=50, paused=True),
            local=dict(model='qwen-flash-iq3', concurrency=3, base_url='http://offline.invalid'))
        epoch_record.update(providers=providers, openai_assists_local=True)
        r.s.write(epoch/'RECOVERY.json', epoch_record)
        cfg = r.s.read(epoch/r.p.CONFIG)
        cfg.update(providers=providers, runner_sha256=r.s.sha(r.p.__file__), helper_hashes={},
                   recovery_runner_sha256=r.s.sha(r.__file__))
        r.s.write(epoch/r.p.CONFIG, cfg)
        manifest = r.s.read(epoch/'manifest.json')
        manifest.update(parallel_curation_sha256=r.s.sha(epoch/r.p.CONFIG), max_curation_requests=1000)
        r.s.write(epoch/'manifest.json', manifest)
        barrier = threading.Event(); count_lock = threading.Lock(); running = {}; peaks = {}
        def fake_openai(args):
            assert args.concurrency == 4
            return SimpleNamespace(stop=threading.Event(), lock=threading.RLock(), active={}, peak=0)
        def infer(root, task, client, candidates):
            name = task['provider']; key = task['task_id']
            with client.lock:
                client.active[key] = dict(key=key, started_at=r.s.now())
                client.peak = max(client.peak, len(client.active))
            with count_lock:
                running[name] = running.get(name, 0)+1; peaks[name] = max(peaks.get(name, 0), running[name])
                if running.get('openai') == 4 and running.get('local') == 3: barrier.set()
            assert barrier.wait(15), 'The coordinator did not fill all seven authorized slots'
            focus = task['data']['focus_ids']; rule = {k: candidates[focus[0]][k] for k in r.f.check_fields()}
            rule['candidate_ids'] = focus
            delta = dict(operations=[dict(type='ADD', target_ids=[], rules=[rule],
                evidence_candidate_ids=focus, reason='同机制来源')], deferred_candidate_ids=[],
                decisions=[dict(candidate_id=cid, status='incorporated', rule_refs=['op:0'], reason='保留来源')
                           for cid in focus])
            r.f.jsonschema.validate(delta, task['schema'])
            with client.lock: client.active.pop(key)
            with count_lock: running[name] -= 1
            return dict(delta=delta)
        with patch.object(r.p.area, 'prepare', return_value=manifest), \
                patch.object(r.p.area, 'validate_scope'), \
                patch.object(r.p.area, 'audit', return_value=dict(check='passed')), \
                patch.object(r.p, 'audit_chat', return_value=dict(check='passed')), \
                patch.object(r.p.taxonomy, 'credentials', return_value=dict(deepseek={})), \
                patch.object(r.p, 'OpenAIClient', side_effect=fake_openai), \
                patch.object(r.p, 'infer', side_effect=infer), \
                patch.object(r.RecoveryTasks, 'evidence', side_effect=lambda cid:
                             dict(candidate_id=cid, manuscript_passages=[], review_units=[])):
            r.run_epoch(SimpleNamespace(root=epoch, auth=epoch/'unused'), epoch_record)
        assert peaks == dict(openai=4, local=3) and (epoch/'FROZEN.json').exists()
        epoch_state, epoch_queue = r.read_db(epoch)
        assert all(q['status'] == 'incorporated' and q['attempts'] == 1 for q in epoch_queue.values())
        assert len(epoch_state['rules']) == 8 and r.verify(epoch, epoch_record)['check'] == 'passed'
    print('passed: separate recovery visits, original history retention, provider handoff, mechanism isolation, '
          'transactional coverage, recovery budget rejection, exact evidence offsets, no pairing upgrade, '
          'OpenAI assistance priority, claim exclusion, stolen-visit provider switching, '
          'actual coordinator concurrency 4+3, unique transactional commits and final audit')


if __name__ == '__main__': main()
