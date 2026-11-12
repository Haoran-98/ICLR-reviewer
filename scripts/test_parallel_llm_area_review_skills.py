#!/usr/bin/env python3
"""Offline concurrency, optimistic commit, and exact-text decoding regressions."""
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
import json
from pathlib import Path
import tempfile
import threading
import time
from unittest.mock import patch

import parallel_llm_area_review_skills as p
from test_full_s4_review_skills import candidate


def delta_for(task, candidates):
    focus = task['data']['focus_ids']
    rule = {k: candidates[focus[0]][k] for k in p.f.check_fields()}
    rule['candidate_ids'] = focus
    return dict(operations=[dict(type='ADD', target_ids=[], rules=[rule],
                    evidence_candidate_ids=focus, reason='同一机制')],
        decisions=[dict(candidate_id=cid, status='incorporated', rule_refs=['op:0'], reason='保留来源') for cid in focus],
        deferred_candidate_ids=[])


def main():
    raw = dict(choices=[dict(message=dict(content='{"ok":<|endoftext|>true,"text":"<|endoftext|>原文\\\""}'))])
    parsed, removed = p.decode_deepseek(raw)
    assert parsed == dict(ok=True, text='<|endoftext|>原文"') and removed == 1
    raw['choices'][0]['message']['content'] = '{"ok":trux}'
    try: p.decode_deepseek(raw)
    except json.JSONDecodeError: pass
    else: raise AssertionError('Arbitrary invalid JSON was silently repaired')

    candidates = {f'c{i:02d}': candidate(f'c{i:02d}', i) for i in range(24)}
    queue = {cid: dict(status='pending', attempts=0, previously_represented=False,
                      rule_ids=[], reason='', history=[]) for cid in candidates}
    state = dict(version=0, next_id=1, rules={})
    retrieval = p.f.Retrieval(candidates)
    first = p.make_task('p000001', 'openai', state, queue, candidates, retrieval, set())
    second = p.make_task('p000002', 'deepseek', state, queue, candidates, retrieval, set(first['data']['focus_ids']))
    assert set(first['data']['focus_ids']).isdisjoint(second['data']['focus_ids'])
    first_delta = delta_for(first, candidates); second_delta = delta_for(second, candidates)
    with tempfile.TemporaryDirectory() as folder:
        root = Path(folder); db = p.f.state_db(root)
        assert p.commit(root, db, state, queue, candidates, first, first_delta)
        # Both tasks saw next_id=1: committing the second must allocate a fresh ID.
        assert p.commit(root, db, state, queue, candidates, second, second_delta)
        assert state['version'] == 2 and set(state['rules']) == {'R0001', 'R0002'}
        assert set(state['rules']['R0001']['candidate_ids']) == set(first['data']['focus_ids'])
        assert set(state['rules']['R0002']['candidate_ids']) == set(second['data']['focus_ids'])
        assert all(queue[cid]['attempts'] == 1 for cid in first['data']['focus_ids']+second['data']['focus_ids'])
        assert db.execute('SELECT value FROM meta WHERE key=?', ('parallel_task/p000002',)).fetchone()[0] == 'committed'
        third = p.make_task('p000003', 'deepseek', state, queue, candidates, retrieval, set())
        change = delta_for(third, candidates); target = next(iter(third['snapshot']['rules']))
        change['operations'][0].update(type='REFINE', target_ids=[target])
        assert p.compatible(third, change, state, queue)
        before = deepcopy(state); state['rules'][target] = dict(state['rules'][target], version=99)
        assert not p.commit(root, db, state, queue, candidates, third, change)
        assert all(queue[cid]['attempts'] == 0 for cid in third['data']['focus_ids'])
        # Conflicts cannot partially overwrite the live library or consume candidate visits.
        assert state['version'] == 2 and len(list((root/'updates').glob('*.json'))) == 2
        state.clear(); state.update(before)
        malformed = delta_for(third, candidates)
        malformed['operations'][0]['rules'][0]['mechanism_family'] = 'claim_scope'
        fixed, rejected = p.quarantine(malformed, third, candidates)
        assert not fixed['operations'] and rejected
        assert all(d['status'] == 'deferred' for d in fixed['decisions'])
        assert state == before
        pause_config = dict(providers=dict(openai=dict(concurrency=3), deepseek=dict(concurrency=50, paused=True)))
        assert p.provider_capacity(pause_config, 'deepseek') == 0 and p.provider_capacity(pause_config, 'openai') == 3
        pending = deepcopy(third); pending['status'] = 'dispatched'
        old_queue = deepcopy(queue)
        assert p.restore_backlog(root, [pending], set(), pause_config, queue) == []
        assert pending['status'] == 'paused' and queue == old_queue
        # Paused work releases its claims so an enabled provider can process those candidates.
        replacement = p.make_task('p000004', 'openai', state, queue, candidates, retrieval, set())
        assert set(replacement['data']['focus_ids']) == set(pending['data']['focus_ids'])
        pause_config['providers']['deepseek']['paused'] = False
        assert p.restore_backlog(root, [pending], set(), pause_config, queue) == [pending]
        queue[pending['data']['focus_ids'][0]]['attempts'] += 1
        assert p.restore_backlog(root, [pending], set(), pause_config, queue) == []
        assert pending['status'] == 'superseded'
        db.close()

    # Exercise the real semaphore with 53 callers and blocked fake HTTP requests.
    release = threading.Event(); reached = threading.Event(); calls = 0; lock = threading.Lock()
    class Response:
        status_code = 200; ok = True
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def iter_content(self, chunk_size=1):
            yield from (bytes([value]) for value in json.dumps(self.json()).encode())
        def json(self):
            return dict(model='deepseek-flash', choices=[dict(finish_reason='stop',
                message=dict(content='{"value":"ok"}'))], usage=dict(prompt_tokens=5, completion_tokens=2))
    def post(*args, **kwargs):
        nonlocal calls
        with lock:
            calls += 1
            if calls == 50: reached.set()
        assert release.wait(15)
        return Response()
    with tempfile.TemporaryDirectory() as folder:
        root = Path(folder)
        config = dict(model='deepseek-v4-flash', concurrency=50, accepted_response_models=['deepseek-flash'])
        client = p.ChatClient(root, dict(base_url='https://offline.invalid', key='offline-test'), config)
        with patch.object(p.requests, 'post', side_effect=post), patch.object(p.s, 'emit'):
            with ThreadPoolExecutor(max_workers=53) as pool:
                futures = [pool.submit(client.ask, 'curate', str(i), {}, p.s.obj(dict(value=p.s.STRING)), 2000, 64)
                           for i in range(53)]
                assert reached.wait(15)
                with client.lock: assert len(client.active) == 50 and client.peak == 50
                release.set()
                assert all(future.result(timeout=15) == dict(value='ok') for future in futures)
        assert calls == 53 and client.peak == 50 and not client.active
        with patch.object(p.requests, 'post', side_effect=AssertionError('Cached output was billed twice')):
            assert client.ask('curate', '0', {}, p.s.obj(dict(value=p.s.STRING)), 2000, 64) == dict(value='ok')
        assert p.audit_chat(root, dict(providers=dict(deepseek=config)), 'deepseek')['concurrency_peak'] <= 50
        config['paused'] = True
        with patch.object(p.requests, 'post', side_effect=AssertionError('Paused DeepSeek sent a request')):
            try: client.ask('curate', 'paused', {}, p.s.obj(dict(value=p.s.STRING)), 2000, 64)
            except ValueError: pass
            else: raise AssertionError('Paused provider started inference')
        assert not list((root/'requests_deepseek/curate/paused').glob('attempt_*.json'))
    with tempfile.TemporaryDirectory() as folder:
        root = Path(folder)
        config = dict(model='qwen-flash-iq3', concurrency=1, context_limit=262144,
                      read_timeout_seconds=900, accepted_response_models=['qwen-flash-iq3'])
        client = p.ChatClient(root, dict(base_url='http://127.0.0.1:18091/v1', key='local'), config, 'local')
        release.clear(); reached.clear(); local_calls = 0
        class LocalResponse(Response):
            def json(self): return dict(super().json(), model='qwen-flash-iq3')
        def local_post(url, **kwargs):
            nonlocal local_calls
            assert url == 'https://provider.invalid/v1'
            assert kwargs['json']['model'] == 'qwen-flash-iq3'
            assert kwargs['json']['chat_template_kwargs'] == dict(enable_thinking=False)
            assert 'thinking' not in kwargs['json'] and kwargs['timeout'] == (20, 900)
            with lock: local_calls += 1; reached.set()
            assert release.wait(15)
            return LocalResponse()
        with patch.object(p.requests, 'post', side_effect=local_post), patch.object(p.s, 'emit'):
            with ThreadPoolExecutor(max_workers=2) as pool:
                futures = [pool.submit(client.ask, 'curate', str(i), {}, p.s.obj(dict(value=p.s.STRING)), 2000, 64)
                           for i in range(2)]
                assert reached.wait(15)
                with client.lock: assert local_calls == 1 and len(client.active) == 1 and client.peak == 1
                release.set()
                assert all(future.result(timeout=15) == dict(value='ok') for future in futures)
        assert local_calls == 2 and client.peak == 1
        assert (root/'requests_local/curate/0/result.json').exists()
        assert not (root/'requests_deepseek').exists() and not (root/'requests').exists()
        with patch.object(p.requests, 'post', side_effect=AssertionError('Local context overflow was sent')):
            try: client.ask('curate', 'overflow', {}, {}, 1000, 262144)
            except ValueError: pass
            else: raise AssertionError('Local context limit was not enforced')
        assert p.audit_chat(root, dict(providers=dict(local=config)), 'local')['concurrency_limit'] == 1
        class NullResponse(Response):
            def json(self): return None
        with patch.object(p.requests, 'post', side_effect=[NullResponse(), LocalResponse()]), \
                patch.object(client.stop, 'wait'), patch.object(p.s, 'emit'):
            assert client.ask('curate', 'null_retry', {}, p.s.obj(dict(value=p.s.STRING)), 2000, 64) == dict(value='ok')
        first = p.s.read(root/'requests_local/curate/null_retry/attempt_1.json')
        assert first['response'] is None and first['retryable']
        p.s.write(root/'baseline.json', dict(usage={}, attempts=0))
        p.s.write(root/'summary.json', {})
        progress = p.Progress(root, dict(baseline_progress='baseline.json', providers=dict(local=config)), dict(local=client), {})
        progress.save(dict(version=0, rules={}), {}, force=True)
        assert p.s.read(root/'progress.json')['attempts'] == 4
    print('passed: disjoint claims, unique committed IDs, stale-update rejection, durable checkpoints, scientific-field quarantine, provider pause and claim release, DeepSeek cap 50, local cap 1, independent model caches, cached resume')


if __name__ == '__main__': main()
