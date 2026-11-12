"""Source isolation and original parent-path checks; no inference requests."""
import copy
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'scripts'))
import s4_export_paper_trees as trees


class PaperTreeTests(unittest.TestCase):
    def test_preserves_three_sources_and_paths_without_merging(self):
        generated = {}
        for provider in (*trees.PROVIDERS, 'kimi'):
            generated[provider] = {str(level): [{
                'node_id': f'L{level}', 'parent_id': f'L{level-1}' if level > 1 else None,
                'name': 'Same name', 'definition': 'Original definition',
                'level': level, 'status': 'candidate', 'supporting_quotes': [{'text': 'Original quote'}]
            }] for level in (1, 2, 3)}
        generated['qwen']['2'].append({'node_id': 'bad', 'parent_id': 'missing', 'level': 2,
                                       'name': 'Previously rejected', 'status': 'pruned'})
        original = copy.deepcopy(generated)
        root = trees.build_tree(1, 'Paper title', generated)
        self.assertEqual(root['name'], 'Paper title')
        self.assertEqual(len(root['children']), 3)
        self.assertNotIn('kimi', root['generation_pruned'])
        self.assertEqual(len({n['export_id'] for n in root['children']}), 3)
        for node in root['children']:
            self.assertEqual(node['children'][0]['children'][0]['level'], 3)
            self.assertEqual(node['children'][0]['parent_id'], 'L1')
            self.assertEqual(node['supporting_quotes'], [{'text': 'Original quote'}])
        self.assertEqual(root['generation_pruned']['qwen']['nodes'][0]['node_id'], 'bad')
        self.assertEqual(generated, original)
        generated['qwen']['2'][-1]['status'] = 'candidate'
        with self.assertRaisesRegex(ValueError, 'Missing original parent'):
            trees.build_tree(1, 'Paper title', generated)


if __name__ == '__main__':
    unittest.main()
