"""Evidence and budget invariants for the v4 experiment (no API calls)."""
import importlib.util
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

SCRIPT = Path(__file__).resolve().parents[2]/'scripts/s4_llm_taxonomy.py'
spec = importlib.util.spec_from_file_location('s4_llm4',SCRIPT)
s4 = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = s4
spec.loader.exec_module(s4)
sys.path.insert(0,str(SCRIPT.parent))
import s4_crowd_fusion as fusion
import numpy as np


class EvidenceTests(unittest.TestCase):
    def test_historical_candidates_remain_and_replacement_votes_are_masked_once(self):
        with tempfile.TemporaryDirectory() as directory:
            source=Path(directory)/'source'
            target=Path(directory)/'retained'
            s4.write(source/'manifest.json',{'version':'source','papers':[{'paper_id':1,'canonical_key':'area'}]})
            for provider in s4.PROVIDERS:
                node={'node_id':'root','name':'Kimi only' if provider=='kimi' else 'Shared field',
                    'definition':'A domain','facet':'task','level':1,'status':'candidate',
                    'parent_id':None,'supporting_quotes':[]}
                s4.write(source/'generated'/provider/'1.json',{'1':[node],'2':[],'3':[]})
                s4.write(source/'official_votes'/provider/'1.json',{'canonical_key':'area'})
            original=fusion.canonicalize(SimpleNamespace(root=source))
            ids=list(original['nodes'])
            for provider in ('deepseek','openai','qwen'):
                s4.write(source/'crosslabels'/provider/'1.json',[{'id':cid,'vote':'yes'} for cid in ids])
            s4.write(source/'raw/1.json',{'metadata':{'keywords':[]}})
            np.savez_compressed(source/'section_vectors.npz',paper_ids=np.array([1]),
                vectors=np.ones((1,6,2)),masks=np.ones((1,6),dtype=bool))
            np.savez_compressed(source/'label_vectors.npz',ids=np.array(ids),vectors=np.eye(2))
            args=SimpleNamespace(root=target,source_root=source,providers=s4.PROVIDERS,
                                 replace_kimi_with_openai=True,auth=Path(directory)/'auth')
            fusion.prepare_branch(args)
            canonical=fusion.canonicalize(args)
            self.assertEqual(set(canonical['nodes']),set(original['nodes']))
            self.assertTrue(any(n['name']=='Kimi only' for n in canonical['nodes'].values()))
            def run_all(args,callback):
                for provider in s4.PROVIDERS:
                    callback(provider,1)
            with patch.object(fusion,'parallel_providers',side_effect=run_all), \
                    patch.object(fusion.s4,'credentials',return_value={'openai':{'model':'gpt-6-luna'}}), \
                    patch.object(fusion,'evaluate_batches',side_effect=AssertionError('Must reuse existing votes')):
                fusion.crosslabel(args)
            replacement=s4.read(target/'crosslabels/kimi/1.json')
            self.assertTrue(all(v['actual_model']=='gpt-6-luna' for v in replacement))
            data=fusion.load_data(args)
            self.assertTrue((data['coarse']>=0).all())  # Historical Kimi coarse votes remain.
            self.assertTrue((data['votes'][:,s4.PROVIDERS.index('kimi')]==-1).all())
            self.assertTrue((data['votes'][:,s4.PROVIDERS.index('openai')]==1).all())
            self.assertEqual(s4.read(target/'vote_independence.json')['duplicate_replacement_observations_masked'],{'kimi':2})

    def test_replacement_keeps_historical_kimi_and_routes_only_missing_jobs(self):
        with tempfile.TemporaryDirectory() as directory:
            args=SimpleNamespace(root=Path(directory),auth=Path(directory)/'auth')
            s4.write(args.root/'manifest.json',{'role_replacement':{'kimi':'openai'}})
            config={p:{'model':'kimi-k2.6' if p=='kimi' else 'gpt-6-luna',
                       'base_url':'http://unused','key':'secret','concurrency':1} for p in ('kimi','openai')}
            payload={'items':[{'id':'a'}]}
            value={'votes':[{'id':'a','vote':'yes'}]}
            with patch.object(fusion.s4,'credentials',return_value=config), \
                    patch.object(fusion.s4,'request_job',return_value=value) as request, \
                    patch.object(fusion.kimi_batch,'request_many',side_effect=AssertionError('No new Kimi inference')):
                result=fusion.evaluate_batches(args,'kimi','align',[payload],1)
                request.assert_called_once_with(args,'openai','align',payload)
                self.assertEqual(result[0]['votes'][0]['actual_provider'],'openai')
                self.assertEqual(result[0]['votes'][0]['actual_model'],'gpt-6-luna')
                old,_=fusion.s4.build_job(config['kimi'],'kimi','align',payload)
                s4.write(args.root/'results'/f'{old["job_id"]}.json',{'value':value})
                request.reset_mock()
                retained=fusion.evaluate_batches(args,'kimi','align',[payload],1)
                self.assertEqual(retained,[value])
                self.assertNotIn('actual_provider',retained[0]['votes'][0])
                request.assert_not_called()
            entries={p:{'vote':'yes'} for p in s4.PROVIDERS}
            self.assertEqual(len(fusion.independent_votes(entries)),4)
            entries['kimi']=result[0]['votes'][0]
            self.assertEqual(len(fusion.independent_votes(entries)),3)
            self.assertEqual(fusion.independent_votes(entries)['openai'],entries['openai'])

    def test_three_provider_branch_excludes_kimi_candidates_and_filters_source_votes(self):
        with tempfile.TemporaryDirectory() as directory:
            source=Path(directory)/'source'
            target=Path(directory)/'three'
            selected=('deepseek','openai','qwen')
            s4.write(source/'manifest.json',{'version':'source','papers':[{'paper_id':1}]})
            for provider in s4.PROVIDERS:
                node={'node_id':'root','name':'Kimi only' if provider=='kimi' else 'Shared field',
                      'definition':'A domain','facet':'task','level':1,'status':'candidate',
                      'parent_id':None,'supporting_quotes':[]}
                s4.write(source/'generated'/provider/'1.json',{'1':[node],'2':[],'3':[]})
            original=fusion.canonicalize(SimpleNamespace(root=source))
            all_ids=list(original['nodes'])
            for provider in selected:
                s4.write(source/'crosslabels'/provider/'1.json',[{'id':cid,'vote':'yes'} for cid in all_ids])
            # The historical Kimi error must not block complete retained-provider files.
            s4.write(source/'postprocess_execution.json',{'status':'failed'})
            args=SimpleNamespace(root=target,source_root=source,providers=selected)
            fusion.prepare_branch(args)
            canonical=fusion.canonicalize(args)
            self.assertEqual(len(canonical['nodes']),1)
            node=next(iter(canonical['nodes'].values()))
            self.assertEqual({m['provider'] for m in node['members']},set(selected))
            def run_selected(args,callback):
                for provider in selected:
                    callback(provider,1)
            with patch.object(fusion,'evaluate_batches',side_effect=AssertionError('No repeated inference')), \
                    patch.object(fusion,'parallel_providers',side_effect=run_selected):
                fusion.crosslabel(args)
            for provider in selected:
                self.assertEqual([v['id'] for v in s4.read(target/'crosslabels'/provider/'1.json')],list(canonical['nodes']))
            self.assertFalse((target/'crosslabels/kimi').exists())
            self.assertTrue((target/'attempts').is_symlink())
            self.assertEqual(fusion.providers(SimpleNamespace(root=target)),selected)

    def test_combined_embedding_inputs_and_features_exclude_other_sections(self):
        sections={field:{'missing':False,'text':field+' ORIGINAL'} for field in s4.FIELDS}
        text=fusion.representation_text(sections,('title','abstract'))
        self.assertEqual(text,'title:\ntitle ORIGINAL\n\nabstract:\nabstract ORIGINAL')
        self.assertNotIn('keywords',text)
        rng=np.random.default_rng(1)
        n=20
        data={'masks':np.ones((n,6),dtype='float32'),'pv':rng.normal(size=(n,6,8)),
              'nv':rng.normal(size=(n,8)),'fine_paper':np.arange(n),'rows':[(i,'a') for i in range(n)],
              'nodes':{'a':{'level':1,'facet':'task'}},'keywords':[['k'] for _ in range(n)],
              'representations':{name:rng.normal(size=(n,8)).astype('float32') for name in fusion.PAPER_REPRESENTATIONS}}
        before=fusion.features(data,np.arange(16),'title_abstract')
        changed={**data,'masks':data['masks'].copy(),'pv':data['pv']*100}
        changed['masks'][:,[s4.FIELDS.index(f) for f in ('keywords','introduction','conclusion','related_work')]]=0
        after=fusion.features(changed,np.arange(16),'title_abstract')
        np.testing.assert_array_equal(before[0],after[0])
        np.testing.assert_array_equal(before[1],after[1])
        tak=fusion.features(data,np.arange(16),'title_abstract_keywords')
        self.assertEqual(tak[0].shape[1],before[0].shape[1]+1)

    def test_invalid_vote_id_is_missing_not_a_guessed_label(self):
        import json
        def raw(votes,finish='stop'):
            return {'choices':[{'finish_reason':finish,'message':{'content':json.dumps({'votes':votes})}}]}
        votes=[{'id':'a','vote':'yes'},{'id':'typo-b','vote':'yes'}]
        value=s4.validate_response(raw(votes),'align',{'items':[{'id':'a'},{'id':'b'}]})
        self.assertEqual(value['rejected_votes'],[votes[1]])
        self.assertEqual(value['votes'][0],votes[0])
        self.assertEqual(value['votes'][1]['id'],'b')
        self.assertEqual(value['votes'][1]['vote'],'abstain')
        self.assertTrue(value['votes'][1]['synthetic_abstention'])
        for invalid in ([votes[0],votes[0]],[votes[1]],[{'id':'a','vote':'invalid'}]):
            with self.assertRaises(ValueError):
                s4.validate_response(raw(invalid),'crosslabel',{'items':[{'id':'a'}]})
        with self.assertRaises(s4.JobFailure):
            s4.validate_response(raw(votes,'length'),'align',{'items':[{'id':'a'}]})

    def test_analysis_output_budget_preserves_job_identity(self):
        config={'model':'test','key':'secret','base_url':'http://unused','concurrency':1}
        job,request=s4.build_job(config,'qwen','align',{'items':[]})
        self.assertEqual(request['max_tokens'],12288)
        self.assertEqual(job['job_id'],s4.digest({'provider':'qwen','kind':'align',
            'payload':{'items':[]},'model':'test','prompt':s4.PROMPT_VERSION}))

    def test_official_vote_only_normalizes_duplicate_tokens_to_an_allowed_key(self):
        raw={'choices':[{'finish_reason':'stop','message':{'content':
            '{"canonical_key":"alignment_fairness_safety_privacy_privacy","rationale":"privacy"}'}}]}
        payload={'allowed_classes':['alignment_fairness_safety_privacy']}
        value=s4.validate_response(raw,'official_vote',payload)
        self.assertEqual(value['canonical_key'],'alignment_fairness_safety_privacy')
        self.assertEqual(value['original_canonical_key'],'alignment_fairness_safety_privacy_privacy')
        with self.assertRaisesRegex(ValueError,'Unknown official class'):
            s4.validate_response(raw,'official_vote',{'allowed_classes':['generative_models']})

    def test_explicit_repair_round_preserves_previous_job_identity(self):
        config={'model':'test','key':'secret','base_url':'http://unused','concurrency':1}
        original,_=s4.build_job(config,'openai','generate',{'test':True})
        repair,_=s4.build_job({**config,'repair_round':'user-authorized'},'openai','generate',{'test':True})
        self.assertNotEqual(original['job_id'],repair['job_id'])
        self.assertEqual(repair['previous_job_id'],original['job_id'])
        self.assertEqual(repair['repair_round'],'user-authorized')

    def test_fusion_kimi_analysis_uses_batch_instead_of_realtime(self):
        args=SimpleNamespace()
        payloads=[{'items':[]}]
        with patch.object(fusion.kimi_batch,'request_many',return_value=[{'votes':[]}]) as batch, \
                patch.object(fusion.s4,'request_job') as realtime:
            self.assertEqual(fusion.evaluate_batches(args,'kimi','align',payloads,1),[{'votes':[]}])
            batch.assert_called_once_with(args,'align',payloads)
            realtime.assert_not_called()

    def test_kimi_auth_model_and_thinking_strength_override_legacy_names(self):
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'auth'
            path.write_text('\n'.join([
                'export DeepSeek_base_url=https://deepseek.invalid/v1',
                'export DeepSeek_api_key=deepseek-secret', 'export DeepSeek_weak_model=flash',
                'export OPENAI_BASE_URL=https://openai.invalid/v1',
                'export OPENAI_API_KEY=openai-secret', 'export OPENAI_WEAK_MODEL_ID=gpt-test',
                'export Kimi_base_url=https://provider.invalid/v1',
                'export Kimi_api_key=kimi-secret', 'export Kimi_weak_model=old-model',
                'export Kimi_model=kimi-for-coding', 'export Kimi_think_strength=low',
                'export Kimi_concurrency=2']))
            config=s4.credentials(path)['kimi']
            self.assertEqual(config['model'],'kimi-for-coding')
            self.assertEqual(config['reasoning_effort'],'low')
            self.assertEqual(config['concurrency'],2)
            self.assertEqual(config['base_url'],'https://provider.invalid/v1')

    def test_kimi_request_sends_reasoning_effort_and_hides_credentials(self):
        with tempfile.TemporaryDirectory() as directory:
            args=SimpleNamespace(root=Path(directory),auth=Path(directory)/'auth')
            config={'kimi':{'model':'kimi-for-coding','base_url':'https://provider.invalid/v1',
                            'key':'test-secret','concurrency':1,'reasoning_effort':'low'}}
            response=SimpleNamespace(status_code=200,text='{"choices":[{"finish_reason":"stop","message":{"content":"{\\"ok\\":true}"}}]}',
                json=lambda:{'choices':[{'finish_reason':'stop','message':{'content':'{"ok":true}'}}],'model':'actual-model'})
            with patch.object(s4,'credentials',return_value=config),patch.object(s4.requests,'post',return_value=response) as post:
                result=s4.request_job(args,'kimi','preflight',{'instruction':'Return JSON'})
                self.assertTrue(result['ok'])
                self.assertEqual(post.call_args.kwargs['json']['reasoning_effort'],'low')
                self.assertNotIn('thinking',post.call_args.kwargs['json'])
            for path in args.root.glob('**/*.json'):
                self.assertNotIn('test-secret',path.read_text())

    def test_selected_provider_generation_does_not_invoke_other_providers(self):
        args=SimpleNamespace(root=Path('/unused'),auth=Path('/unused-auth'),providers=['kimi'])
        with patch.object(s4,'credentials',return_value={'kimi':{'concurrency':1}}),patch.object(s4,'generate_one') as generate:
            s4.generate(args,[{'paper_id':1}])
            generate.assert_called_once_with(args,'kimi',{'paper_id':1})

    def test_spaced_headings_original_offsets_and_missing_masks(self):
        raw='Title\n1 I NTRODUCTION\nOur contribution.\n2 M ETHOD\nDo it.\n3 C ONCLUSION\nWe conclude.\nREFERENCES\nCitation'
        sections=s4.extract_sections(raw,[],{'title':'Title','abstract':'A','keywords':['K']})
        self.assertEqual(sections['introduction']['text'],'Our contribution.\n')
        self.assertEqual(sections['conclusion']['text'],'We conclude.\n')
        self.assertTrue(sections['related_work']['missing'])
        for field in ('introduction','conclusion'):
            section=sections[field]
            self.assertEqual(raw[section['char_start']:section['char_end']],section['text'])
            for span in section['spans']:
                self.assertEqual(raw[span['char_start']:span['char_end']],span['text'])

    def test_related_work_alone_never_proves_contribution(self):
        payload={'level':1,'parents':[],'evidence':[{'span_id':'related_work:0','section_id':'related_work','text':'Prior work'}]}
        value={'nodes':[{'node_id':'r','name':'Prior task','definition':'A task','facet':'task',
                         'parent_id':None,'evidence_refs':['related_work:0']}]}
        node=s4.validate_nodes(value,payload)['nodes'][0]
        self.assertEqual(node['status'],'pruned')
        self.assertEqual(node['supporting_quotes'][0]['text'],'Prior work')

    def test_unknown_evidence_preserved_as_rejection(self):
        payload={'level':1,'parents':[],'evidence':[]}
        node={'node_id':'r','name':'Task','definition':'A task','facet':'task','evidence_refs':['made-up']}
        result=s4.validate_nodes({'nodes':[node]},payload)['nodes'][0]
        self.assertEqual(result['status'],'pruned')
        self.assertIn('made-up',result['evidence_refs'])

    def test_unknown_parent_pruned_with_audit_record(self):
        payload={'level':2,'parents':[{'node_id':'p'}],'evidence':[]}
        node={'node_id':'c','name':'Task','definition':'A task','facet':'task','parent_id':'unknown'}
        result=s4.validate_nodes({'nodes':[node]},payload)['nodes'][0]
        self.assertEqual(result['status'],'pruned')
        self.assertEqual(result['rejection_reason'],'unknown_parent')

    def test_restarts_do_not_reset_attempt_limit(self):
        with tempfile.TemporaryDirectory() as directory:
            args=SimpleNamespace(root=Path(directory),auth=Path(directory)/'auth')
            config={p:{'model':'test','key':'secret','base_url':'http://unused','concurrency':1} for p in s4.PROVIDERS}
            payload={'test':True}
            job_id=s4.digest({'provider':'kimi','kind':'test','payload':payload,'model':'test','prompt':s4.PROMPT_VERSION})
            for attempt in range(1,7):
                s4.write(args.root/'attempts'/job_id/f'{attempt:02d}.json',{'retryable':True})
            with patch.object(s4,'credentials',return_value=config),patch.object(s4.requests,'post') as post:
                with self.assertRaises(s4.JobFailure):
                    s4.request_job(args,'kimi','test',payload)
                post.assert_not_called()

    def test_fallback_uses_only_remaining_attempts_across_restarts(self):
        with tempfile.TemporaryDirectory() as directory:
            args = SimpleNamespace(root=Path(directory), auth=Path(directory)/'auth', max_attempts=2)
            config = {'openai': {'model': 'test', 'key': 'secret', 'base_url': 'http://unused', 'concurrency': 1}}
            payload = {'test': True}
            job, _ = s4.build_job(config['openai'], 'openai', 'test', payload)
            # Four primary attempts plus these two fallback attempts exhaust the shared six.
            for attempt in (1, 2):
                s4.write(args.root/'attempts'/job['job_id']/f'{attempt:02d}.json', {'retryable': True})
            with patch.object(s4, 'credentials', return_value=config), patch.object(s4.requests, 'post') as post:
                with self.assertRaises(s4.JobFailure):
                    s4.request_job(args, 'openai', 'test', payload)
                post.assert_not_called()
                args.max_attempts = 7
                with self.assertRaises(ValueError):
                    s4.request_job(args, 'openai', 'test', payload)
                post.assert_not_called()

    def test_retained_earlier_valid_response_is_recovered_without_new_request(self):
        import json
        with tempfile.TemporaryDirectory() as directory:
            args = SimpleNamespace(root=Path(directory), auth=Path(directory)/'auth')
            config = {'openai': {'model': 'test', 'key': 'secret', 'base_url': 'http://unused', 'concurrency': 1}}
            payload = {'test': True}
            job, _ = s4.build_job(config['openai'], 'openai', 'test', payload)
            for attempt in range(1, 7):
                raw = {'choices': [{'finish_reason': 'stop', 'message': {'content': '{"ok":true}' if attempt == 1 else 'invalid'}}]}
                s4.write(args.root/'attempts'/job['job_id']/f'{attempt:02d}.json',
                         {'attempt': attempt, 'status': 'failed', 'http_status': 200,
                          'retryable': True, 'response_body': json.dumps(raw)})
            with patch.object(s4, 'credentials', return_value=config), patch.object(s4.requests, 'post') as post:
                self.assertEqual(s4.request_job(args, 'openai', 'test', payload), {'ok': True})
                post.assert_not_called()
            result = s4.read(args.root/'results'/f'{job["job_id"]}.json')
            self.assertEqual(result['original_attempt'], 1)
            self.assertTrue(result['local_revalidation'])

    def test_missing_generation_is_not_negative_vote(self):
        self.assertEqual(s4.validate_nodes({'nodes':[]},{'level':1,'parents':[],'evidence':[]}),{'nodes':[]})

    def test_feature_views_hide_the_target_annotator(self):
        votes=np.array([[1,0,-1,1]])
        changed=votes.copy()
        changed[0,0]=0
        original=fusion.masked_views(np.zeros((1,2),dtype='float32'),votes,2)
        updated=fusion.masked_views(np.zeros((1,2),dtype='float32'),changed,2)
        np.testing.assert_array_equal(original[:,0],updated[:,0])
        self.assertFalse(np.array_equal(original[:,1],updated[:,1]))

    def test_ds_recovers_a_reliable_and_random_annotator_with_missing_votes(self):
        rng=np.random.default_rng(42)
        truth=rng.integers(0,2,2000)
        votes=np.tile(truth[:,None],(1,4))
        for j,error in enumerate((.02,.10,.20,.48)):
            wrong=rng.random(len(truth))<error
            votes[wrong,j]=1-votes[wrong,j]
        votes[rng.random(votes.shape)<.1]=-1
        posterior,confusion=fusion.dawid_skene(votes)
        self.assertGreater(((posterior>.5)==truth).mean(),.94)
        self.assertGreater(np.diagonal(confusion,axis1=1,axis2=2).mean(1)[0],
                           np.diagonal(confusion,axis1=1,axis2=2).mean(1)[3])

    def test_crowd_network_trains_without_gold_in_features(self):
        rng=np.random.default_rng(2)
        n=30
        truth=np.arange(n)%3
        coarse=np.tile(truth[:,None],(1,4))
        fine=np.tile((np.arange(n*2)%2)[:,None],(1,4))
        data={'classes':['a','b','c'],'gold':truth,'coarse':coarse,'votes':fine,
              'masks':np.ones((n,6),dtype='float32'),'pv':rng.normal(size=(n,6,8)).astype('float32'),
              'nv':rng.normal(size=(n*2,8)).astype('float32'),'fine_paper':np.repeat(np.arange(n),2),
              'rows':[(i,c) for i in range(n) for c in ('a','b')],
              'keywords':[['task'] for i in range(n)],
              'nodes':{'a':{'level':1,'facet':'task','parents':[]},'b':{'level':2,'facet':'task','parents':['a']}}}
        before=fusion.features(data,np.arange(18),False)
        changed={**data,'gold':(truth+1)%3}
        after=fusion.features(changed,np.arange(18),False)
        np.testing.assert_array_equal(before[0],after[0])
        np.testing.assert_array_equal(before[1],after[1])
        result,state=fusion.train_network(data,np.arange(18),np.arange(18,24),np.arange(24,30),1701,False)
        self.assertEqual(result['coarse'].shape,(n,3))
        self.assertEqual(result['fine'].shape,(n*2,))
        self.assertTrue(np.isfinite(result['fine']).all())
        np.testing.assert_allclose(result['coarse'].sum(1),1,atol=1e-6)
        embedded=fusion.features(data,np.arange(18),True)
        self.assertGreater(embedded[0].shape[1],before[0].shape[1])
        self.assertGreater(embedded[1].shape[1],before[1].shape[1])
        three={**data,'coarse':coarse[:,:3],'votes':fine[:,:3]}
        result,_=fusion.train_network(three,np.arange(18),np.arange(18,24),np.arange(24,30),1701,False)
        self.assertEqual(result['fine_noise'].shape,(n*2,3,2,2))
        self.assertEqual(result['coarse_confusion'].shape,(3,3,3))
        self.assertTrue(np.isfinite(result['fine']).all())

    def test_four_repair_arms_recompute_merge_and_preserve_parent_closure(self):
        with tempfile.TemporaryDirectory() as directory:
            args=SimpleNamespace(root=Path(directory))
            nodes={cid:{'id':cid,'name':cid,'definition':cid,'facet':'task',
                        'level':1 if cid=='a' else 2,'parents':[] if cid=='a' else ['a'],
                        'members':[{'paper_id':pid,'provider':provider,'evidence':[]}
                                   for pid in (1,2) for provider in ('kimi','qwen')]}
                   for cid in ('a','b','c')}
            s4.write(args.root/'canonical.json',{'nodes':nodes})
            rows=[(pid,cid) for pid in (1,2) for cid in nodes]
            s4.write(args.root/'fusion_rows.json',rows)
            s4.write(args.root/'alignment_pairs.json',[{'id':'bc','a':'b','b':'c','cosine':.99}])
            s4.write(args.root/'alignment_votes.json',{p:[{'id':'bc','vote':'yes'}] for p in s4.PROVIDERS})
            edges=[{'id':'ab','parent_id':'a','child_id':'b'},{'id':'ac','parent_id':'a','child_id':'c'}]
            s4.write(args.root/'hierarchy_votes.json',{'edges':edges,'votes':{
                p:[{'id':'ab','vote':'yes'},{'id':'ac','vote':'yes'}] for p in s4.PROVIDERS}})
            np.savez_compressed(args.root/'label_vectors.npz',ids=np.array(['a','b','c']),vectors=np.eye(3))
            noise=np.tile(np.array([[.9,.1],[.1,.9]]),(len(rows),4,1,1))
            for e in (0,1):
                np.savez_compressed(args.root/f'posterior_E{e}.npz',fine=np.full(len(rows),.99),
                                    fine_prior=np.full(len(rows),.5),fine_noise=noise)
            with patch.object(fusion,'load_data',return_value={'votes':np.ones((len(rows),4),dtype=int)}):
                fusion.repair(args)
                before={arm:s4.read(args.root/f'taxonomy_{arm}.json') for arm in ('E0R0','E1R0','E0R1','E1R1')}
                fusion.repair(args)
            self.assertEqual(len(before['E0R0']['nodes']),3)
            self.assertEqual(len(before['E0R1']['nodes']),2)
            for arm,result in before.items():
                self.assertEqual(result,s4.read(args.root/f'taxonomy_{arm}.json'))
                assigned={(x['paper_id'],x['node_id']) for x in result['assignments']}
                for pid,cid in assigned:
                    for parent in result['nodes'][cid]['parents']:
                        self.assertIn((pid,parent),assigned)


if __name__=='__main__':
    unittest.main()
