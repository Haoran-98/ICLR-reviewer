#!/usr/bin/env python3
"""Exercise job persistence and HTTP input boundaries without model calls."""
import json
import os
from pathlib import Path
import tempfile
import threading
from urllib.error import HTTPError
from urllib.request import Request, urlopen
from unittest.mock import patch

import review_api as a
import review_composed_manuscript as reviewer
from test_manuscript_upload import docx_bytes, payload as upload_payload


def main():
    with tempfile.TemporaryDirectory() as folder, patch.object(a,'ROOT',Path(folder)), patch.object(a,'TOKEN','test-token'), \
            patch.object(a.POOL,'submit') as submit:
        config_file=Path(folder)/'auth'
        config_file.write_text('export OPENAI_BASE_URL=https://example.invalid/v1\nexport OPENAI_API_KEY=test-secret\nexport OPENAI_STRONG_MODEL_ID=gpt-6.1-sol\nexport DEEPSEEK_BASE_URL=https://deepseek.invalid\nexport DEEPSEEK_API_KEY=test-secret\nexport DEEPSEEK_STRONG_MODEL=deepseek-v4-pro\n')
        environment=patch.dict(os.environ,{'ICLR_AUTH_FILE':str(config_file)});environment.start()
        server=a.ThreadingHTTPServer(('127.0.0.1',0),a.Handler)
        thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
        def request(path, body=None, token='test-token'):
            data=None if body is None else json.dumps(body).encode()
            req=Request(f'http://127.0.0.1:{server.server_port}/api/review'+path,data=data,
                headers={'X-Review-Token':token,'Content-Type':'application/json'})
            try:
                with urlopen(req) as response:return response.status,json.load(response)
            except HTTPError as error:return error.code,json.load(error)
        try:
            assert request('/meta',token='wrong')[0]==403
            code,meta=request('/meta');assert code==200 and len(meta['models'])==4
            assert [m['configured'] for m in meta['models']]==[True,True,False,False]
            assert 'test-secret' not in json.dumps(meta)
            assert request('/extract', upload_payload('test.docx', docx_bytes('完整稿件正文。')), token='wrong')[0] == 403
            code, extracted = request('/extract', upload_payload('test.docx', docx_bytes('完整稿件正文。')))
            assert code == 200 and extracted['text'] == '完整稿件正文。' and submit.call_count == 0
            code, error = request('/extract', upload_payload('test.pdf', b'not PDF'))
            assert code == 400 and '有效的 PDF' in error['error']
            assert request('/runs',{'paper_id':33089,'model':'unknown'})[0]==400
            assert request('/runs',{'paper_id':33089,'model':'qwen-local'})[0]==400
            assert request('/runs',{'paper_id':33089,'model':'claude-opus'})[0]==400
            assert request('/runs',{'paper_id':True})[0]==400
            assert request('/runs',{'paper_id':-1})[0]==400
            assert request('/runs',{'manuscript':'short'})[0]==400
            code,job=request('/runs',{'manuscript':'complete manuscript '*20,'title':'<script>text only</script>'})
            assert code==202 and submit.call_count==1
            assert job['review_provider']['model']=='gpt-6.1-sol' and 'provider_identity' not in job
            path=Path(folder)/job['id'];assert (path/'manuscript.md').read_text()=='complete manuscript '*20
            assert request('/runs/'+job['id'])[1]['job']['state']=='queued'
            assert request('/runs/'+job['id']+'/retry',{})[0]==400
            a.save_job(path,state='failed',phase='reviewing',error='example failure')
            code,retried=request('/runs/'+job['id']+'/retry',{})
            assert code==202 and retried['attempt']==2 and submit.call_count==2
            assert (path/'manuscript.md').exists() and request('/runs')[1][0]['id']==job['id']
            assert request('/runs/../../auth')[0]==400
            code,deepseek=request('/runs',{'paper_id':33089,'model':'deepseek-pro'})
            assert code==202 and deepseek['review_provider']['model']=='deepseek-v4-pro'
            assert a.read(Path(folder)/deepseek['id']/'job.json')['provider_identity']['id']=='deepseek-pro'
            assert 'test-secret' not in json.dumps(request('/runs')[1])
            def stage(args, job_path):
                assert args[args.index('--review-model')+1] == 'deepseek-pro'
                if 'compose_manuscript_skills.py' in str(args[0]):
                    output=Path(args[args.index('--root')+1]);output.mkdir(parents=True)
                    a.s.write(output/'composition.json',{'model':'deepseek-v4-pro'})
                    a.s.write(output/'AUDIT.json',{'output_hashes':{'composition.json':a.s.sha(output/'composition.json')}})
            deepseek_path=Path(folder)/deepseek['id']
            with patch.object(a,'command',side_effect=stage) as worker:
                a.execute(deepseek_path)
                assert worker.call_count==2 and a.read(deepseek_path/'job.json')['state']=='completed'
                # Retry keeps the composition and sends the same model only to review.
                a.save_job(deepseek_path,attempt=2,state='queued');a.execute(deepseek_path)
                assert worker.call_count==3 and a.read(deepseek_path/'job.json')['state']=='completed'
                a.save_job(deepseek_path,attempt=3,provider_identity={})
                a.execute(deepseek_path)
                assert worker.call_count==3 and a.read(deepseek_path/'job.json')['state']=='failed'
        finally:server.shutdown();server.server_close();environment.stop()
        recovery_root=Path(folder)/'recovery';source=recovery_root/'recovery_source';source.mkdir(parents=True)
        data=dict(manuscript='example');schema=dict(type='object');body=dict(input=json.dumps(dict(data=data,schema=schema)))
        review=dict(strengths=[dict(point='valid',evidence=[dict(passage_id='p',quote='original text')]),
                              dict(point='unverified',evidence=[dict(passage_id='p',quote='invented')])],
                    concerns=[],rules_applied=[],summary='unchanged summary',rating=6)
        raw=dict(status='completed',model=a.s.MODEL,reasoning=dict(effort='medium'),
            output=[dict(type='message',content=[dict(type='output_text',text=json.dumps(review))])])
        a.s.write(source/'attempt.json',dict(response=raw,request_hash=a.s.digest(body)))
        a.s.write(source/'request.json',dict(body=body,request_hash=a.s.digest(body)))
        before=a.s.sha(source/'attempt.json')
        manuscript=dict(passages=[dict(passage_id='p',char_start=0,char_end=13,text='original text')])
        result=reviewer.recover(recovery_root,data,schema,manuscript,[])
        assert result['strengths']==review['strengths'][:1] and result['summary']==review['summary'] and result['rating']==6
        assert a.s.sha(source/'attempt.json')==before and len(a.s.read(recovery_root/'LOCAL_RECOVERY.json')['quarantined_items'])==1
    print('passed: loopback token, invalid IDs, short inputs, persistent manuscripts, queue state, retry, '
          'traversal rejection, exact-evidence recovery, invalid-item quarantine and unchanged raw response')


if __name__=='__main__':main()
