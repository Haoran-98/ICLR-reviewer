"""Check API settings, gold isolation, subset balance, cache reuse and concurrency."""
from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
import tempfile
import threading
import time
from unittest.mock import patch

import s4_taxoadapt100_api as api


def main():
    schema = {'type': 'object', 'properties': {'ok': {'type': 'boolean'}}, 'required': ['ok']}
    body = api.request_body('paper title and abstract', 192, schema)
    assert body['model'] == 'gpt-6-luna' and body['reasoning'] == {'effort': 'low'}
    assert 'temperature' not in body and 'seed' not in body and body['store'] is False
    source = api.SOURCE
    inputs, gold = api.select_papers(api.read(source / 'inputs.json'), api.read(source / 'evaluation/gold.json'))
    assert len(inputs) == len(gold) == 100
    assert len({r['area'] for r in gold}) == 23
    assert set(inputs[0]) == {'paper_id', 'title', 'abstract'}
    assert min(api.Counter(r['area'] for r in gold).values()) == 4
    assert sorted(api.Counter(r['year'] for r in gold).values()) == [33, 33, 34]
    raw = {'model': api.MODEL, 'reasoning': {'effort': 'low'}, 'status': 'completed',
           'output': [{'content': [{'type': 'output_text', 'text': '{"ok":true}'}]}]}
    assert api.parse_response(raw, schema) == {'ok': True}
    try:
        api.parse_response(dict(raw, model='different-model'), schema)
    except ValueError:
        pass
    else:
        raise AssertionError('Wrong model accepted')
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        api.PROGRESS = api.Progress(root)
        api.GATE = threading.BoundedSemaphore(3)
        client = object.__new__(api.Luna)
        client.root, client.concurrency, client.url, client.key = root, 3, 'https://unused', 'test-secret'
        lock, active, peak = threading.Lock(), 0, 0
        def post(*args, **kwargs):
            nonlocal active, peak
            with lock:
                active += 1
                peak = max(peak, active)
            time.sleep(.03)
            with lock:
                active -= 1
            class Response:
                ok, status_code = True, 200
                def json(self):
                    return dict(raw, usage={'input_tokens': 10, 'output_tokens': 5})
            return Response()
        with patch.object(api.requests, 'post', side_effect=post) as mocked:
            prompts = [f'paper {i}' for i in range(9)]
            assert len(client.map('test', prompts, 192, schema)) == 9
            assert mocked.call_count == 9 and peak == 3
            assert len(client.map('test', prompts, 192, schema)) == 9
            assert mocked.call_count == 9
        assert api.PROGRESS.data['cached_requests'] == 9
        assert api.PROGRESS.data['batch_completed'] == 9
        assert api.PROGRESS.data['input_tokens'] == 90
        for path in root.rglob('*.json'):
            assert 'test-secret' not in path.read_text()
        status = json.loads((root / 'progress.json').read_text())
        assert status['concurrency_peak'] == 3 and status['active_requests'] == 0
    print('PASS: GPT-6 Luna low, balanced 100-paper sample, gold isolation, validation, cache reuse, max concurrency 3, secret-free artifacts')


if __name__ == '__main__':
    main()
