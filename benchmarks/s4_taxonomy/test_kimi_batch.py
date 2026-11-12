"""Batch dependency, reconciliation, import and shared-budget invariants (offline)."""
import json
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[2]/'scripts'))
import s4_kimi_batch as batch
import s4_llm_taxonomy as s4


class KimiBatchTests(unittest.TestCase):
    def test_stable_evidence_prefix_keeps_shared_identity_and_all_payload_fields(self):
        shared = {'evidence': [{'span_id': 'abstract:0', 'text': 'Long stable paper text.'}]}
        a = {'instruction': 'Generate L2', 'level': 2, **shared}
        b = {'instruction': 'Generate L3', 'level': 3, **shared}
        job, request = s4.build_job(self.config, 'kimi', 'generate', a)
        _, following = s4.build_job(self.config, 'kimi', 'generate', b)
        text = request['messages'][-1]['content']
        self.assertTrue(text.startswith('{"evidence":'))
        self.assertEqual(text.split(', "instruction"')[0],
                         following['messages'][-1]['content'].split(', "instruction"')[0])
        self.assertEqual(json.loads(text), a)
        self.assertEqual(job['request_layout'], 'evidence_prefix_v1')
        expected = s4.digest({'provider': 'kimi', 'kind': 'generate', 'payload': a,
                             'model': self.config['model'], 'prompt': s4.PROMPT_VERSION})
        self.assertEqual(job['job_id'], expected)
        self.assertNotIn('prompt_cache_options', request)
        self.assertNotIn('cache_control', request)
        _, other_provider = s4.build_job(self.config, 'openai', 'generate', a)
        self.assertTrue(other_provider['messages'][-1]['content'].startswith('{"instruction":'))

    def test_usage_missing_is_distinguished_from_zero_hits_and_legacy_is_supported(self):
        rows = [{'response': {'body': {'usage': u}}} for u in (
            {'prompt_tokens': 100, 'completion_tokens': 20, 'prompt_tokens_details': {'cached_tokens': 60}},
            {'prompt_tokens': 100, 'cached_tokens': 0},
            {'prompt_tokens': 100, 'completion_tokens': 10})]
        summary = batch.summarize_usage(rows)
        self.assertEqual(summary['prompt_tokens'], 300)
        self.assertEqual(summary['completion_tokens'], 30)
        self.assertEqual(summary['cached_tokens'], 60)
        self.assertEqual(summary['cache_read_reported_responses'], 2)
        self.assertEqual(summary['cache_hit_ratio_of_reported_inputs'], .3)
        self.assertEqual(summary['cache_write_reported_responses'], 0)
        self.assertIsNone(batch.summarize_usage([])['cache_hit_ratio_of_reported_inputs'])

    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.args = SimpleNamespace(root=Path(self.directory.name), auth=Path('/unused'))
        self.config = {'base_url': 'https://provider.invalid/v1', 'model': 'kimi-k2.6',
                       'key': 'fake-secret', 'concurrency': 1}
        self.evidence = [{'span_id': 'abstract:0', 'section_id': 'abstract', 'text': 'Our evidence.'}]
        s4.write(self.args.root/'manifest.json', {'papers': [
            {'paper_id': 1, 'canonical_key': 'a'}, {'paper_id': 2, 'canonical_key': 'b'}]})
        for pid in (1, 2):
            s4.write(self.args.root/'sections'/f'{pid}.json', {
                field: {'spans': self.evidence if field == 'abstract' else []} for field in s4.FIELDS})
        s4.write(self.args.root/'generated/kimi/1.json', {'1': [], '2': [], '3': []})
        s4.write(self.args.root/'official_votes/kimi/1.json', {'canonical_key': 'a'})
        s4.write(self.args.root/'generated/kimi/2.json', {'1': [
            {'node_id': 'root', 'name': 'Root', 'definition': 'Broad domain',
             'facet': 'task', 'parent_id': None, 'status': 'candidate'}]})

    def test_frontier_preserves_complete_papers_and_waits_for_parents(self):
        entries = batch.frontier(self.args, self.config)
        self.assertEqual([(e['paper_id'], e['kind'], e['level']) for e in entries],
                         [(2, 'generate', 2), (2, 'official_vote', None)])
        for entry in entries:
            job, body = s4.build_job(self.config, 'kimi', entry['kind'], entry['job']['payload'])
            self.assertEqual(job['job_id'], entry['request']['custom_id'])
            self.assertEqual(body['thinking'], {'type': 'disabled'})
            self.assertEqual(body['response_format'], {'type': 'json_object'})
            self.assertNotIn('temperature', body)
            self.assertNotIn('top_p', body)
        self.assertEqual(s4.read(self.args.root/'generated/kimi/1.json'), {'1': [], '2': [], '3': []})

    def test_shared_attempt_budget_is_not_reset_by_batch_transport(self):
        entry = batch.frontier(self.args, self.config)[0]
        folder = self.args.root/'attempts'/entry['job']['job_id']
        for i in range(1, 6):
            s4.write(folder/f'{i:02d}.json', {'retryable': True})
        self.assertEqual(batch.frontier(self.args, self.config)[0]['attempt'], 6)
        s4.write(folder/'06.json', {'retryable': True})
        with self.assertRaisesRegex(RuntimeError, 'budget was not reset'):
            batch.frontier(self.args, self.config)

    def test_shuffled_results_import_idempotently_with_original_quotes(self):
        entries = batch.frontier(self.args, self.config)
        node = {'node_id': 'child', 'name': 'Specific task', 'definition': 'Within root',
                'facet': 'task', 'parent_id': 'root', 'evidence_refs': ['abstract:0']}
        rows = []
        for entry in entries:
            value = {'nodes': [node]} if entry['kind'] == 'generate' else {'canonical_key': 'b'}
            rows.append({'custom_id': entry['job']['job_id'], 'error': None, 'response': {
                'status_code': 200, 'body': {'model': 'kimi-k2.6', 'choices': [{
                    'finish_reason': 'stop', 'message': {'content': json.dumps(value)}}]}}})
            s4.write(self.args.root/'attempts'/entry['job']['job_id']/'01.json',
                     {'status': 'submitted', 'retryable': True, 'attempt': 1})
        state = {'entries': entries, 'batch_id': 'batch-test', 'remote': {
            'id': 'batch-test', 'status': 'completed', 'output_file_id': 'file-test'}}
        response = SimpleNamespace(text='\n'.join(json.dumps(row) for row in reversed(rows)))
        with patch.object(batch, 'api', return_value=response):
            batch.import_results(self.args, self.config, state, self.args.root/'batch/active.json')
            first = s4.read(self.args.root/'generated/kimi/2.json')
            batch.import_results(self.args, self.config, state, self.args.root/'batch/active.json')
        self.assertEqual(first, s4.read(self.args.root/'generated/kimi/2.json'))
        self.assertEqual(first['2'][0]['supporting_quotes'], self.evidence)
        self.assertEqual(first['_provenance']['2']['transport'], 'batch')
        self.assertNotIn('3', first)
        for file in self.args.root.rglob('*.json'):
            self.assertNotIn('fake-secret', file.read_text())

    def test_ambiguous_create_reconciles_input_file_without_another_post(self):
        state = {'input_file_id': 'file-in', 'submission_started_at': 'earlier', 'entries': []}
        response = SimpleNamespace(json=lambda: {'data': [
            {'id': 'batch-existing', 'input_file_id': 'file-in'}]})
        with patch.object(batch, 'api', return_value=response) as call:
            batch.submit(self.args, self.config, state, self.args.root/'batch/active.json')
            self.assertEqual(call.call_count, 1)
            self.assertEqual(call.call_args.args[2], 'GET')
        self.assertEqual(state['batch_id'], 'batch-existing')

    def test_unresolved_create_does_not_resubmit(self):
        state = {'input_file_id': 'file-in', 'submission_started_at': 'earlier', 'entries': []}
        response = SimpleNamespace(json=lambda: {'data': []})
        with patch.object(batch, 'api', return_value=response) as call:
            with self.assertRaisesRegex(RuntimeError, 'no duplicate submitted'):
                batch.submit(self.args, self.config, state, self.args.root/'batch/active.json')
            self.assertEqual(call.call_count, 1)

    def test_http_403_result_stops_instead_of_resubmitting(self):
        entry = batch.frontier(self.args, self.config)[0]
        s4.write(self.args.root/'attempts'/entry['job']['job_id']/'01.json', {'attempt': 1})
        state = {'entries': [entry], 'batch_id': 'batch-denied', 'remote': {
            'status': 'completed', 'error_file_id': 'file-error'}}
        row = {'custom_id': entry['job']['job_id'], 'error': None,
               'response': {'status_code': 403, 'body': {'error': 'denied'}}}
        with patch.object(batch, 'api', return_value=SimpleNamespace(text=json.dumps(row))):
            with self.assertRaisesRegex(RuntimeError, 'permanent errors'):
                batch.import_results(self.args, self.config, state, self.args.root/'batch/active.json')
        with self.assertRaisesRegex(RuntimeError, 'budget was not reset'):
            batch.frontier(self.args, self.config)

    def test_zero_status_revalidates_saved_result_without_network_or_new_attempt(self):
        entry = batch.frontier(self.args, self.config)[0]
        node = {'node_id': 'child', 'name': 'Specific task', 'definition': 'Within root',
                'facet': 'task', 'parent_id': 'root', 'evidence_refs': ['abstract:0']}
        raw = {'model': 'kimi-k2.6', 'choices': [{'finish_reason': 'stop',
                'message': {'content': json.dumps({'nodes': [node]})}}]}
        row = {'custom_id': entry['job']['job_id'], 'error': None,
               'response': {'status_code': 0, 'body': raw}}
        attempt_path = self.args.root/'attempts'/entry['job']['job_id']/'01.json'
        old = {'attempt': 1, 'status': 'failed', 'retryable': False, 'error_kind': 'http_0'}
        s4.write(attempt_path, old)
        state = {'entries': [entry], 'batch_id': 'batch-zero', 'imported_at': 'yesterday',
                 'remote': {'status': 'completed', 'output_file_id': 'file-saved'}}
        s4.write(self.args.root/'batch/batch-zero_output_file_id.json', [row])
        with patch.object(batch, 'api') as api:
            batch.import_results(self.args, self.config, state, self.args.root/'batch/active.json')
            api.assert_not_called()
        saved = s4.read(attempt_path)
        self.assertEqual(saved['status'], 'success')
        self.assertEqual(saved['http_status'], 0)
        self.assertEqual(saved['status_interpretation'], 'validated_completion_with_zero_status')
        self.assertEqual(len(list(attempt_path.parent.glob('*.json'))), 1)
        audit = s4.read(self.args.root/'batch'/f'batch-zero_before_{batch.PARSER_VERSION}.json')
        self.assertEqual(audit['original_attempts'][entry['job']['job_id']], old)
        self.assertEqual(s4.read(self.args.root/'generated/kimi/2.json')['2'][0]['supporting_quotes'], self.evidence)

    def test_zero_status_malformed_json_uses_remaining_budget(self):
        entry = batch.frontier(self.args, self.config)[0]
        row = {'custom_id': entry['job']['job_id'], 'error': None, 'response': {
            'status_code': 0, 'body': {'choices': [{'finish_reason': 'stop',
                'message': {'content': '{"evidence_ref": "a", "b"}'}}]}}}
        attempt_path = self.args.root/'attempts'/entry['job']['job_id']/'01.json'
        s4.write(attempt_path, {'attempt': 1})
        state = {'entries': [entry], 'batch_id': 'batch-json-error',
                 'remote': {'status': 'completed', 'output_file_id': 'file-invalid'}}
        s4.write(self.args.root/'batch/batch-json-error_output_file_id.json', [row])
        batch.import_results(self.args, self.config, state, self.args.root/'batch/active.json')
        saved = s4.read(attempt_path)
        self.assertTrue(saved['retryable'])
        self.assertEqual(saved['error_kind'], 'JSONDecodeError')
        self.assertEqual(batch.frontier(self.args, self.config)[0]['attempt'], 2)

    def test_zero_status_does_not_accept_error_or_missing_completion_body(self):
        entry = batch.frontier(self.args, self.config)[0]
        attempt_path = self.args.root/'attempts'/entry['job']['job_id']/'01.json'
        for i, body in enumerate(({'error': {'message': 'Denied'}}, {},
                                 {'error': {'message': 'Denied'}, 'choices': [{}]})):
            with self.subTest(body=body):
                s4.write(attempt_path, {'attempt': 1})
                row = {'custom_id': entry['job']['job_id'], 'error': None,
                       'response': {'status_code': 0, 'body': body}}
                batch_id = f'batch-error-{i}'
                state = {'entries': [entry], 'batch_id': batch_id,
                         'remote': {'status': 'completed', 'output_file_id': f'error-file-{i}'}}
                s4.write(self.args.root/'batch'/f'{batch_id}_output_file_id.json', [row])
                with self.assertRaisesRegex(RuntimeError, 'permanent errors'):
                    batch.import_results(self.args, self.config, state, self.args.root/'batch/active.json')
                self.assertFalse((self.args.root/'results'/f'{entry["job"]["job_id"]}.json').exists())

    def test_analysis_batch_maps_shuffled_results_and_resumes_from_cache(self):
        payloads=[{'instruction':'Vote','items':[{'id':i}]} for i in ('one','two')]
        rows=[]
        for payload in payloads:
            job,_=s4.build_job(self.config,'kimi','align',payload)
            value={'votes':[{'id':payload['items'][0]['id'],'vote':'yes'}]}
            rows.append({'custom_id':job['job_id'],'error':None,'response':{'status_code':0,
                'body':{'choices':[{'finish_reason':'stop','message':{'content':json.dumps(value)}}]}}})
        calls=[]
        def api(args,config,method,path,**kwargs):
            calls.append((method,path))
            if path=='/files':return SimpleNamespace(json=lambda:{'id':'input'})
            if path=='/batches':return SimpleNamespace(json=lambda:{'id':'batch-analysis'})
            if path=='/batches/batch-analysis':return SimpleNamespace(json=lambda:{
                'id':'batch-analysis','status':'completed','output_file_id':'output'})
            if path=='/files/output/content':return SimpleNamespace(text='\n'.join(json.dumps(r) for r in reversed(rows)))
            self.fail(path)
        with patch.object(s4,'credentials',return_value={'kimi':self.config}),patch.object(batch,'api',side_effect=api):
            result=batch.request_many(self.args,'align',payloads)
            self.assertEqual([r['votes'][0]['id'] for r in result],['one','two'])
            count=len(calls)
            self.assertEqual(batch.request_many(self.args,'align',payloads),result)
            self.assertEqual(len(calls),count)
        self.assertFalse((self.args.root/'generated/kimi/None.json').exists())


if __name__ == '__main__':
    unittest.main()
