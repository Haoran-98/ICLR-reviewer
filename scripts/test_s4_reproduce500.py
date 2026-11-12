"""Small invariant checks; no model quality is inferred from these checks."""
import sys
from threading import Condition, Event, Thread
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))
import numpy as np
from s4_reproduce500 import generation_payload, recovery_payload, MODEL, MODEL_PATH, ROOT, CONTEXT, Qwen
from s4_reproduce500_methods import (node, graph_stats, membership_features,
                                     max_weight_selection, calibrated_predictions, nearest)


def main():
    payload = generation_payload('Return a topic as JSON.', 192)
    assert payload['model'] == MODEL and 'qwen38' in MODEL
    assert MODEL_PATH.name.endswith('UD-Q3_K_XL.gguf')
    assert payload['reasoning_effort'] == 'medium'
    assert payload['chat_template_kwargs'] == {'enable_thinking': True, 'reasoning_effort': 'medium'}
    assert payload['max_tokens'] > 8192 and CONTEXT == 65536
    assert 'Do not include reasoning' not in payload['messages'][0]['content']
    assert ROOT.name != 'repro500_qwen_v1'
    recovered = recovery_payload(dict(payload), {'error': 'ReadTimeout: timed out'}, CONTEXT)
    assert recovered['reasoning_effort'] == 'medium'
    assert recovered['reasoning_budget_tokens'] == 8192
    assert 'reasoning_budget_tokens' not in payload  # Existing successful caches stay valid.
    truncated = {'request': payload, 'response': {'choices': [{'finish_reason': 'length'}],
                                                'usage': {'prompt_tokens': 1000}}}
    recovered = recovery_payload(dict(payload), truncated, CONTEXT)
    assert recovered['max_tokens'] == 2 * payload['max_tokens']
    assert recovered['reasoning_budget_tokens'] == 8192
    qwen = object.__new__(Qwen)
    qwen._context_condition, qwen._reserved_context = Condition(), 0
    attempting, admitted = Event(), Event()
    def second_request():
        attempting.set()
        with qwen.reserve_context(30000):
            admitted.set()
    with qwen.reserve_context(40000):
        thread = Thread(target=second_request)
        thread.start()
        assert attempting.wait(1) and not admitted.wait(.05)
    assert admitted.wait(1)
    thread.join(1)
    assert qwen._reserved_context == 0
    try:
        with qwen.reserve_context(1000):
            raise RuntimeError('simulated request failure')
    except RuntimeError:
        pass
    assert qwen._reserved_context == 0
    nodes = [node('r', 'root', papers=[10, 20], container=True),
             node('a', 'A', parents=['r'], papers=[10, 20]),
             node('b', 'B', parents=['r'], papers=[10]),
             node('c', 'C', parents=['a', 'b'], papers=[10])]
    stats = graph_stats(nodes)
    assert stats['depth'] == 2 and stats['widths'] == {1: 2, 2: 1}
    assert stats['nodes'] == 3 and stats['leaves'] == 1
    ids, X = membership_features(nodes, [{'paper_id': 10}, {'paper_id': 20}, {'paper_id': 30}])
    assert ids == ['a', 'b', 'c']
    assert np.array_equal(X, [[0, 0, 1], [1, 0, 0], [0, 0, 0]])
    cyclic = [node('a', 'A', parents=['b']), node('b', 'B', parents=['a'])]
    try:
        graph_stats(cyclic)
    except ValueError:
        pass
    else:
        raise AssertionError('Cycle was not rejected')
    W = np.array([[.9, .1, .6], [.1, .9, .6]])
    assignment, selected, score = max_weight_selection(W, 2)
    assert selected == [0, 1] and score == 1.8 and assignment.tolist() == [0, 1]
    X = np.array([[1., 0.], [0., 1.], [1., 0.], [0., 1.]])
    y = np.array(['a', 'b', 'a', 'b'])
    # Swap ONLY the held-out labels. Their predicted classes must remain identical.
    fold = [(np.array([0, 1]), np.array([2, 3]))]
    p1 = calibrated_predictions(X, y, fold)
    p2 = calibrated_predictions(X, np.array(['a', 'b', 'b', 'a']), fold)
    assert np.array_equal(p1[2:], p2[2:]) and p1[2:].tolist() == ['a', 'b']
    neighbors = nearest(np.zeros((5, 3)), 2)
    assert all(i not in row for i, row in enumerate(neighbors))
    print('PASS: shared-context admission and release, Qwen3.8 medium request settings, thinking budget, cache isolation, DAG depth/width, terminal coverage, exact aspect selection, held-out mapping isolation')


if __name__ == '__main__':
    main()
