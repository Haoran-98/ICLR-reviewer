"""S4 failure-boundary tests; no GPU, API or real corpus writes."""
from argparse import Namespace
from datetime import datetime
import importlib.util
import json
from io import BytesIO
from http.client import IncompleteRead
import threading
from pathlib import Path
import tempfile
import unittest
from unittest.mock import MagicMock, patch
from urllib.error import HTTPError

import numpy as np

REPO = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location('s4', REPO/'scripts/s4_taxonomy_pipeline.py')
s4 = importlib.util.module_from_spec(spec)
spec.loader.exec_module(s4)


def response_for(body):
    response=MagicMock()
    response.__enter__.return_value.getcode.return_value=200
    response.__enter__.return_value.headers={'Content-Type':'application/json'}
    response.__enter__.return_value.read.return_value=body if isinstance(body,bytes) else json.dumps(body).encode()
    return response


class PipelineTests(unittest.TestCase):
    def test_title_group_stays_together_across_years(self):
        rows = [{'paper_id':i,'year':2024+i%3,'canonical_key':'a','title':f'Paper {i}'} for i in range(120)]
        rows.append({'paper_id':200,'year':2026,'canonical_key':'b','title':' PAPER 0! '})
        one = s4.split_corpus(rows)
        self.assertEqual(one[0], one[200])
        self.assertEqual(one, s4.split_corpus(list(reversed(rows))))

    def test_sample_count_and_every_stratum(self):
        rows = [{'paper_id':i,'year':2024+i%3,'canonical_key':str(i%2),'title':str(i)} for i in range(300)]
        selected = s4.stratified_sample(rows,120)
        self.assertEqual(len(selected),120)
        self.assertEqual(selected,s4.stratified_sample(list(reversed(rows)),120))
        counts = s4.Counter((r['year'],r['canonical_key']) for r in selected)
        self.assertTrue(all(n>=10 for n in counts.values()))

    def test_200_sample_keeps_coverage_and_a_clustering_panel(self):
        rows=[{'paper_id':i,'year':2024+i%3,'canonical_key':str(i%20),'title':str(i)} for i in range(6000)]
        selected=s4.stratified_sample(rows,200)
        self.assertEqual(len(selected),200)
        self.assertEqual(selected,s4.stratified_sample(list(reversed(rows)),200))
        self.assertEqual(len({(r['year'],r['canonical_key']) for r in selected}),60)
        self.assertGreaterEqual(max(s4.Counter(r['canonical_key'] for r in selected).values()),100)

    def test_feature_content_excludes_review_and_confidence(self):
        paper={'title':'A','abstract':'B','profile':{'research_problem':{'statement':'C','confidence':.99},
               'method':{'overview':'D','assumptions':['SECRET']},'review_risks':[{'statement':'SECRET'}],
               'claims':[{'support_level':'SECRET'}],'experiments':{'main_results':['SECRET']}}}
        values=s4.inputs(paper)
        self.assertNotIn('SECRET',json.dumps(values))
        self.assertNotIn('confidence',json.dumps(values))

    def test_window_claim_and_hard_boundaries(self):
        def state(h,m,s=0):return s4.window_state(datetime(2026,10,15,h,m,s,tzinfo=s4.CST))
        self.assertFalse(state(0,59,59)['active'])
        self.assertTrue(state(1,0)['claim'])
        self.assertTrue(state(4,49,59)['claim'])
        self.assertFalse(state(4,50)['claim'])
        self.assertTrue(state(4,59,59)['active'])
        self.assertFalse(state(5,0)['active'])
        self.assertEqual(state(4,59,59)['remaining'],1)

    def test_outside_window_does_not_read_auth_or_call_api(self):
        with tempfile.TemporaryDirectory() as d:
            args=Namespace(root=Path(d),auth=Path(d)/'missing')
            with patch.object(s4,'window_state',return_value={'active':False}), patch.object(s4,'load_auth') as auth:
                s4.night_run(args)
                auth.assert_not_called()

    def test_immediate_execution_ignores_night_window_but_honors_deadline(self):
        args=Namespace(command='run',deadline=110)
        with patch.object(s4,'window_state',return_value={'active':False,'claim':False}), \
                patch.object(s4.time,'monotonic',return_value=100):
            self.assertTrue(s4.execution_state(args)['claim'])
            self.assertEqual(s4.execution_state(args)['remaining'],10)
            args.deadline=99
            self.assertFalse(s4.execution_state(args)['active'])
            self.assertFalse(s4.wait_for_retry(0,args))

    def test_jobs_run_concurrently_and_keep_failure_accounting(self):
        barrier=threading.Barrier(3,timeout=5)
        def run(args,job,auth):
            barrier.wait()
            return job['job_id']!='failed'
        failures=set()
        pending=[{'job_id':key,'kind':'node'} for key in ('one','two','failed')]
        with patch.object(s4,'retry_job',side_effect=run):
            s4.run_jobs(Namespace(concurrency=3),pending,{},failures)
        self.assertEqual(failures,{'failed'})

    def test_concurrency_comes_from_auth_case_insensitively(self):
        with tempfile.TemporaryDirectory() as d:
            path=Path(d)/'auth'
            base='\n'.join(f'export {key}=test' for key in
                ('DeepSeek_base_url','DeepSeek_api_key','DeepSeek_strong_model','DeepSeek_weak_model'))
            for key in ('deepseek_concurrency','DeepSeek_CONCURRENCY'):
                path.write_text(base+f'\nexport {key}="50"\n')
                self.assertEqual(s4.load_auth(path)['deepseek_concurrency'],50)
            for value in ('0','101','invalid'):
                path.write_text(base+f'\nexport deepseek_concurrency={value}\n')
                with self.assertRaisesRegex(ValueError,'concurrency'):
                    s4.load_auth(path)
            path.write_text(base)
            with self.assertRaisesRegex(ValueError,'concurrency'):
                s4.load_auth(path)

    def test_test_profiles_are_sealed(self):
        with tempfile.TemporaryDirectory() as d:
            with self.assertRaisesRegex(ValueError,'sealed'):
                s4.snapshot_profiles(Namespace(root=Path(d)),True)

    def test_manifest_tamper_is_detected(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d)
            s4.write(root/'manifest.json',{'papers':[{'paper_id':1}],'manifest_hash':s4.digest([])})
            with self.assertRaisesRegex(ValueError,'altered'):
                s4.manifest(Namespace(root=root))

    def test_queue_idempotence_and_facet_validation(self):
        with tempfile.TemporaryDirectory() as d:
            args=Namespace(root=Path(d))
            s4.enqueue(args,'assignment','one',{'a':1})
            s4.enqueue(args,'assignment','one',{'a':1})
            self.assertEqual(len(s4.jobs(args)),1)
        j={'kind':'edge','data':{'source_facet':'task','target_facet':'method'}}
        with self.assertRaisesRegex(ValueError,'method source'):
            s4.validate_verdict(j,{'accepted':True,'relation_type':'method_used_in','score':.9})
        s4.validate_verdict(j,{'accepted':True,'relation_type':'method_used_in','score':.9,'reverse_direction':True})

    def test_bad_json_shape_not_accepted(self):
        with self.assertRaises(ValueError):
            s4.validate_verdict({'kind':'assignment'}, {'accepted':'true'})
        with self.assertRaises(ValueError):
            s4.validate_verdict({'kind':'neighbor_pair'}, {'winner':'C'})
        with self.assertRaisesRegex(ValueError,'quotes'):
            s4.validate_verdict({'kind':'assignment'}, {'accepted':True,'supporting_quotes':['invalid']})
        with self.assertRaisesRegex(ValueError,'reverse_direction'):
            s4.validate_verdict({'kind':'edge'}, {'accepted':True,'reverse_direction':'false'})
        s4.validate_verdict({'kind':'node'}, {'accepted':False,'rationale':'Incoherent cluster'})

    def test_assignment_quotes_must_exist_in_original_abstract(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);args=Namespace(root=root)
            s4.write(root/'profiles.json',{'1':{'abstract':'The method learns a compact representation.',
                'markdown_path':'/nonexistent/file','profile':{'method':'An invented profile quote.'}}})
            auth={'DeepSeek_strong_model':'fixture','DeepSeek_api_key':'fixture','DeepSeek_base_url':'https://fixture.invalid'}
            for job_id,quote,accepted in [('original','learns a compact representation',True),
                    ('generated','An invented profile quote.',False)]:
                verdict={'accepted':True,'supporting_quotes':[{'paper_id':1,'quote':quote}]}
                response=response_for({'choices':[{'finish_reason':'stop','message':{'content':json.dumps(verdict)}}]})
                with patch.object(s4,'window_state',return_value={'claim':True,'remaining':60}), \
                        patch.object(s4,'urlopen',return_value=response) as transport:
                    self.assertTrue(s4.call_job(args,{'job_id':job_id,'kind':'assignment','model':'strong','data':{}},auth))
                    transport.assert_called_once()
                self.assertEqual(s4.read(root/'results'/(job_id+'.json'))['verdict']['accepted'],accepted)

    def test_response_diagnostics_and_finish_reason_classification(self):
        cases=[('outer',b'not JSON','response_json_invalid',True),
               ('truncated',{'finish_reason':'length','message':{'content':'{"accepted":'}},'output_truncated',True),
               ('empty',{'finish_reason':'stop','message':{'content':''}},'empty_content',True),
               ('bad_json',{'finish_reason':'stop','message':{'content':'{"accepted":'}},'content_json_invalid',True),
               ('filtered',{'finish_reason':'content_filter','message':{'content':''}},'content_filtered',False),
               ('interrupted',{'finish_reason':'insufficient_system_resource','message':{'content':''}},'provider_interrupted',True),
               ('schema',{'finish_reason':'stop','message':{'content':'{"accepted":"yes"}'}},'verdict_schema_invalid',True)]
        with tempfile.TemporaryDirectory() as d:
            args=Namespace(root=Path(d));auth={'DeepSeek_strong_model':'fixture','DeepSeek_api_key':'test-api-key','DeepSeek_base_url':'https://fixture.invalid'}
            for key,body,kind,retryable in cases:
                with self.subTest(key=key):
                    envelope=body if isinstance(body,bytes) else {'choices':[body],'model':'actual-model','usage':{'completion_tokens':123}}
                    job={'job_id':key,'kind':'assignment','model':'strong','data':{}}
                    with patch.object(s4,'window_state',return_value={'claim':True,'remaining':60}), \
                            patch.object(s4,'urlopen',return_value=response_for(envelope)):
                        with self.assertRaises(s4.JobFailure) as caught:s4.call_job(args,job,auth)
                    self.assertEqual(caught.exception.kind,kind)
                    record=s4.read(args.root/'attempts'/key/'01.json')
                    self.assertEqual(record['http_status'],200)
                    self.assertEqual(record['retryable'],retryable)
                    self.assertTrue(record['response_body'])
                    self.assertFalse((args.root/'results'/(key+'.json')).exists())
                    if not isinstance(body,bytes):self.assertEqual(record['usage']['completion_tokens'],123)
                    if kind.endswith('json_invalid'):self.assertIn('parse_error',record)

    def test_retry_limit_persists_and_legacy_failure_counts(self):
        with tempfile.TemporaryDirectory() as d:
            args=Namespace(root=Path(d));auth={'DeepSeek_strong_model':'fixture','DeepSeek_api_key':'test-api-key','DeepSeek_base_url':'https://fixture.invalid'}
            for legacy,expected_calls in [(False,6),(True,5)]:
                job={'job_id':str(legacy),'kind':'assignment','model':'strong','data':{}}
                if legacy:s4.write(args.root/'errors'/(job['job_id']+'.json'),{'kind':'JSONDecodeError'})
                body={'choices':[{'finish_reason':'stop','message':{'content':''}}]}
                with patch.object(s4,'window_state',return_value={'claim':True,'remaining':60}), \
                        patch.object(s4,'wait_for_retry',return_value=True), \
                        patch.object(s4,'urlopen',return_value=response_for(body)) as transport:
                    self.assertFalse(s4.retry_job(args,job,auth))
                    self.assertEqual(transport.call_count,expected_calls)
                    self.assertFalse(s4.retry_job(args,job,auth))
                    self.assertEqual(transport.call_count,expected_calls)
                self.assertEqual(s4.retry_state(args,job)[0],6)

    def test_partial_body_and_connection_reset_are_retryable(self):
        with tempfile.TemporaryDirectory() as d:
            args=Namespace(root=Path(d));auth={'DeepSeek_strong_model':'fixture','DeepSeek_api_key':'test-api-key','DeepSeek_base_url':'https://fixture.invalid'}
            for key,error in [('partial',IncompleteRead(b'{"choices":',20)),('reset',ConnectionResetError())]:
                job={'job_id':key,'kind':'assignment','model':'strong','data':{}}
                response=response_for({});response.__enter__.return_value.read.side_effect=error
                with patch.object(s4,'window_state',return_value={'claim':True,'remaining':60}), \
                        patch.object(s4,'urlopen',return_value=response):
                    with self.assertRaises(s4.JobFailure) as caught:s4.call_job(args,job,auth)
                self.assertTrue(caught.exception.retryable)
                saved=s4.read(args.root/'attempts'/key/'01.json')
                if key=='partial':
                    self.assertEqual(saved['response_body'],'{"choices":')
                    self.assertTrue(saved['partial_body'])

    def test_http_retry_and_permanent_errors_with_redaction(self):
        with tempfile.TemporaryDirectory() as d:
            args=Namespace(root=Path(d));s4.write(args.root/'profiles.json',{})
            auth={'DeepSeek_strong_model':'fixture','DeepSeek_api_key':'test-api-key','DeepSeek_base_url':'https://fixture.invalid'}
            success={'choices':[{'finish_reason':'stop','message':{'content':'{"accepted":false}'}}]}
            for code in (401,402,422,429,500,503):
                job={'job_id':str(code),'kind':'assignment','model':'strong','data':{}}
                error=HTTPError('https://fixture.invalid',code,'fixture',{'Content-Type':'application/json'},BytesIO(b'{"error":"test-api-key"}'))
                with patch.object(s4,'window_state',return_value={'claim':True,'remaining':60}), \
                        patch.object(s4,'wait_for_retry',return_value=True), \
                        patch.object(s4,'urlopen',side_effect=[error,response_for(success)]) as transport:
                    expected=code in (429,500,503)
                    self.assertEqual(s4.retry_job(args,job,auth),expected)
                    self.assertEqual(transport.call_count,2 if expected else 1)
                    self.assertEqual(s4.retry_job(args,job,auth),expected)
                    self.assertEqual(transport.call_count,2 if expected else 1)
                saved=s4.read(args.root/'attempts'/str(code)/'01.json')
                self.assertEqual(saved['http_status'],code)
                self.assertIn('[REDACTED]',saved['response_body'])
                self.assertNotIn('test-api-key',json.dumps(saved))

    def test_request_policy_and_retry_window(self):
        with tempfile.TemporaryDirectory() as d:
            args=Namespace(root=Path(d));s4.write(args.root/'profiles.json',{})
            auth={'DeepSeek_strong_model':'pro','DeepSeek_weak_model':'flash','DeepSeek_api_key':'test-api-key','DeepSeek_base_url':'https://fixture.invalid'}
            for model in ('strong','weak'):
                job={'job_id':model,'kind':'assignment','model':model,'data':{}}
                body={'choices':[{'finish_reason':'stop','message':{'content':'{"accepted":false}'}}]}
                with patch.object(s4,'window_state',return_value={'claim':True,'remaining':60}), \
                        patch.object(s4,'urlopen',return_value=response_for(body)) as transport:
                    self.assertTrue(s4.retry_job(args,job,auth))
                    payload=json.loads(transport.call_args.args[0].data)
                    self.assertEqual(payload['thinking']['type'],'enabled' if model=='strong' else 'disabled')
                    self.assertEqual(payload['max_tokens'],32768 if model=='strong' else 8192)
            job={'job_id':'boundary','kind':'assignment','model':'strong','data':{}}
            with patch.object(s4,'window_state',return_value={'claim':False,'remaining':500}),patch.object(s4,'urlopen') as transport:
                self.assertFalse(s4.retry_job(args,job,auth));transport.assert_not_called()
            with patch.object(s4,'window_state',return_value={'claim':True,'remaining':60}), \
                    patch.object(s4,'wait_for_retry',return_value=False), \
                    patch.object(s4,'urlopen',return_value=response_for({'choices':[{'finish_reason':'length','message':{'content':''}}]})) as transport:
                self.assertFalse(s4.retry_job(args,job,auth));self.assertEqual(transport.call_count,1)
                self.assertEqual(s4.retry_state(args,job)[0],1)

    def test_offline_local_pipeline_and_test_release(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);args=Namespace(root=root,seed=1701)
            rows=[]; profiles={}; vectors=[]
            rng=np.random.default_rng(1701)
            for i in range(210):
                split='train' if i<150 else 'dev' if i<180 else 'calibration'
                rows.append({'paper_id':i,'year':2024,'canonical_key':'a','split':split})
                profiles[str(i)]={'paper_id':i,'title':str(i),'abstract':'A problem about modeling.',
                    'profile':{'research_problem':{'statement':'modeling'},'method':{'overview':'method'}}}
                center=np.zeros(16);center[0]=2;center[1+(i//25)%3]=1
                vectors.append(center+rng.normal(0,.03,16))
            s4.write(root/'manifest.json',{'papers':rows,'manifest_hash':s4.digest(rows)})
            s4.write(root/'profiles.json',profiles)
            s4.write(root/'anchors.json',[{'stable_key':'a','name':'A','years':[2024],'level':1,'facet_type':'mixed'}])
            s4.write(root/'vector_ids.json',list(range(210)))
            np.save(root/'vectors.npy',s4.normalize(np.array(vectors)))
            s4.cluster(args)
            self.assertGreater(len(s4.read(root/'clusters.json')['nodes']),0)
            s4.name(args)
            for job in s4.jobs(args):
                s4.write(root/'results'/(job['job_id']+'.json'),{'verdict':{'name':'Modeling','definition':'Modeling task',
                    'facet_type':'task','inclusion_criteria':[],'exclusion_criteria':[],'supporting_quotes':[]}})
            self.assertFalse(s4.harvest_names(args))
            for job in s4.jobs(args):
                if job['kind']=='node':
                    s4.write(root/'results'/(job['job_id']+'.json'),{'verdict':{'accepted':True,'name':'Modeling',
                        'definition':'Modeling task','facet_type':'task','inclusion_criteria':[],
                        'exclusion_criteria':[],'supporting_quotes':[]}})
            self.assertTrue(s4.harvest_names(args))
            s4.assignments(args);s4.relate(args);s4.judge(args)
            assignments=s4.read(root/'assignments.json')
            self.assertTrue(any('/L2/' in a['stable_key'] for a in assignments))
            self.assertTrue(all(a['split']!='test' for a in assignments))
            self.assertTrue(all(a['score_type']=='similarity' for a in assignments))
            with self.assertRaisesRegex(ValueError,'complete'):
                s4.finalize(args)


if __name__=='__main__':
    unittest.main()
