"""Algorithm and trust-boundary checks; synthetic values, no model/API results."""
import copy
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'scripts'))
import numpy as np
import s4_dkta as dkta
import s4_llm_taxonomy as s4
import s4_dkta_compare as compare


def taxonomy():
    return {'version': 'test-v1', 'source': 'synthetic_test_fixture', 'nodes': [
        {'id': 'a', 'name': 'Root A', 'level': 1, 'parent_ids': []},
        {'id': 'b', 'name': 'Root B', 'level': 1, 'parent_ids': []},
        {'id': 'c', 'name': 'Shared task', 'level': 2, 'parent_ids': ['a', 'b']},
        {'id': 'd', 'name': 'Another task', 'level': 2, 'parent_ids': ['a']},
        {'id': 'e', 'name': 'Leaf', 'description': 'A specific route', 'level': 3, 'parent_ids': ['c', 'd']}]}


class DktaTests(unittest.TestCase):
    def test_cache_only_never_encodes_or_requests_missing_decisions(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            graph = taxonomy()
            paths = dkta.taxonomy_paths(graph)
            text = 'Title\nWe study memory.'
            paper = {'paper_id': 1, 'title': 'Title', 'abstract': 'We study memory.',
                     'text': text, 'input_hash': s4.digest(text)}
            s4.write(root/'manifest.json', {'papers_manifest': [{'paper_id': 1, 'input_hash': paper['input_hash']}]})
            s4.write(root/'inputs/1.json', paper)
            s4.write(root/'taxonomy.json', graph)
            s4.write(root/'taxonomy_index.json', {'paths': paths, 'signature': 'fixture'})
            np.savez(root/'path_vectors.npz', vectors=np.zeros((len(paths), 2)))
            s4.write(root/'fused/qwen_attention/1.json', {'input_hash': paper['input_hash'],
                     'phrases': [{'phrase': 'memory', 'score': .1}]})
            args = SimpleNamespace(root=root, auth=root/'auth', methods=['qwen_attention'],
                arbitrator='openai', cache_only=True, tau_low=.5, tau_high=.7,
                top_l1=3, top_l2=2, top_l3=5, limit=1)
            with patch.object(dkta, 'encoder') as encode, patch.object(dkta.s4, 'request_job') as request, \
                    patch.object(dkta.s4, 'credentials', return_value={'openai': {'model': 'test', 'concurrency': 1}}):
                with self.assertRaisesRegex(ValueError, 'Cache-only'):
                    dkta.align(args)
                encode.assert_not_called()
                request.assert_not_called()

    def test_author_keyword_proxy_and_quality_evidence_are_not_invented(self):
        values = compare.proxy_scores(['Agent memory', 'Planning'], ['agent memory', 'offline RL'])
        self.assertAlmostEqual(values['P@10'], .1)
        self.assertAlmostEqual(values['R@10'], .5)
        payload = {'candidates': [{'id': 'known'}], 'paper_text': 'We study agent memory.'}
        import json
        verdict = {'id': 'known', 'relevant': True, 'parent_compatible': True,
                   'specificity': 4, 'evidence_quote': 'agent memory', 'rationale': 'Supported problem'}
        raw = {'choices': [{'finish_reason': 'stop', 'message': {'content': json.dumps({'evaluations': [verdict]})}}]}
        self.assertTrue(s4.validate_response(raw, 'dkta_quality', payload)['evaluations'][0]['relevant'])
        verdict['evidence_quote'] = 'Agent Memory'
        raw['choices'][0]['message']['content'] = json.dumps({'evaluations': [verdict]})
        recovered = s4.validate_response(raw, 'dkta_quality', payload)['evaluations'][0]
        self.assertEqual(recovered['evidence_quote'], 'agent memory')
        self.assertEqual(recovered['model_evidence_quote'], 'Agent Memory')
        self.assertEqual(payload['paper_text'][recovered['evidence_char_start']:recovered['evidence_char_end']],
                         recovered['evidence_quote'])
        payload['paper_text'] = 'We study **agent** mem-\nory with efﬁciency.'
        verdict['evidence_quote'] = 'agent memory with efficiency'
        raw['choices'][0]['message']['content'] = json.dumps({'evaluations': [verdict]})
        recovered = s4.validate_response(raw, 'dkta_quality', payload)['evaluations'][0]
        self.assertEqual(recovered['model_evidence_quote'], 'agent memory with efficiency')
        self.assertIn(recovered['evidence_quote'], payload['paper_text'])
        payload['paper_text'] = 'Gram-\nSchmidt improves gradi-\nent estimates.'
        verdict['evidence_quote'] = 'Gram-Schmidt improves gradient estimates'
        raw['choices'][0]['message']['content'] = json.dumps({'evaluations': [verdict]})
        recovered = s4.validate_response(raw, 'dkta_quality', payload)['evaluations'][0]
        self.assertIn(recovered['evidence_quote'], payload['paper_text'])
        verdict['evidence_quote'] = 'invented support'
        raw['choices'][0]['message']['content'] = json.dumps({'evaluations': [verdict]})
        with self.assertRaises(ValueError):
            s4.validate_response(raw, 'dkta_quality', payload)

    def test_rrf_rank_deduplication_and_both_routes(self):
        rows = dkta.rrf({'attention': [{'phrase': 'Memory'}, {'phrase': 'memory'}],
                         'bart': [{'phrase': 'Planning'}, {'phrase': 'MEMORY'}]})
        self.assertEqual(rows[0]['phrase'], 'Memory')
        self.assertAlmostEqual(rows[0]['score'], 1 / 61 + 1 / 62)
        self.assertEqual(rows[0]['ranks'], {'attention': 1, 'bart': 2})

    def test_all_multi_parent_paths_and_no_shared_ancestor_inflation(self):
        paths = dkta.taxonomy_paths(taxonomy())
        self.assertEqual({tuple(p['node_ids']) for p in paths}, {('a', 'c', 'e'), ('b', 'c', 'e'), ('a', 'd', 'e')})
        result = dkta.aggregate([{'phrase': 'Keyword', 'weight': .02, 'path_ids': [p['id'] for p in paths]}],
                                paths, top_l1=1, top_l2=1, top_l3=1)
        self.assertEqual(len(result['paths']), 3)
        self.assertTrue(all(abs(score - .02) < 1e-9 for score in result['node_support'].values()))
        self.assertEqual(result['topn_overflow'], {'L1': 1, 'L2_by_parent': {'a': 1}})
        self.assertTrue(all(p['normalized_support'] == 1 for p in result['paths']))

    def test_invalid_parent_cycle_and_duplicates_rejected(self):
        for change in ('cycle', 'unknown', 'duplicate'):
            data = copy.deepcopy(taxonomy())
            if change == 'cycle':
                data['nodes'][0]['parent_ids'] = ['e']
            elif change == 'unknown':
                data['nodes'][-1]['parent_ids'] = ['missing']
            else:
                data['nodes'].append(copy.deepcopy(data['nodes'][0]))
            with self.assertRaises(ValueError):
                dkta.taxonomy_paths(data)

    def test_attention_is_present_only_and_cannot_cross_sentence_or_truncation(self):
        text = 'Neural memory. Agent planning'
        spans = [(m.start(), m.end()) for m in dkta.WORD.finditer(text)]
        phrases = dkta.attention_phrases(text, spans, np.array([.1, .9, .3, .2]))
        self.assertTrue(all(row['phrase'] in text for row in phrases))
        self.assertFalse(any('memory. Agent' in row['phrase'] for row in phrases))
        self.assertFalse(any('planning' in row['phrase'] for row in dkta.attention_phrases(text, spans[:-1], [.1, .9, .3])))
        rows = dkta.attention_phrases('Neural\nmemory', [(0, 6), (7, 13)], [.1, .9])
        self.assertFalse(any('\n' in row['phrase'] for row in rows))

    def test_absent_context_and_word_boundaries(self):
        self.assertIsNone(dkta.present_span('memory', 'memo'))
        self.assertEqual(dkta.context('Title\nWe study memory.', 'planning')[1], 'absent_document_context')
        self.assertEqual(dkta.context('Title\nWe study memory. Other topic.', 'memory')[0], 'We study memory.')

    def test_arbitrator_cannot_invent_a_path_or_duplicate_votes(self):
        payload = {'candidates': [{'id': 'allowed'}]}
        for chosen in (['invented'], ['allowed', 'allowed'], 'allowed'):
            raw = {'choices': [{'finish_reason': 'stop', 'message': {'content':
                    __import__('json').dumps({'selected_path_ids': chosen, 'rationale': 'Reason'})}}]}
            with self.assertRaises(ValueError):
                s4.validate_response(raw, 'dkta_arbitrate', payload)
        raw['choices'][0]['message']['content'] = '{"selected_path_ids":[],"rationale":"No supported scope"}'
        self.assertEqual(s4.validate_response(raw, 'dkta_arbitrate', payload)['selected_path_ids'], [])


if __name__ == '__main__':
    unittest.main()
