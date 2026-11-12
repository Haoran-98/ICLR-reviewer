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
        connection=dict(base_url='https://review-test.invalid/v1',api_key='test-review-secret',model='user-model',protocol='chat')
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
            with patch.object(a.models,'configuration',side_effect=AssertionError('Ambient credentials read')):
                code,meta=request('/meta');assert code==200 and meta['connection_required']
            assert meta['protocols']==['chat','responses'] and 'models' not in meta
            assert request('/extract', upload_payload('test.docx', docx_bytes('完整稿件正文。')), token='wrong')[0] == 403
            code, extracted = request('/extract', upload_payload('test.docx', docx_bytes('完整稿件正文。')))
            assert code == 200 and extracted['text'] == '完整稿件正文。' and submit.call_count == 0
            code, error = request('/extract', upload_payload('test.pdf', b'not PDF'))
            assert code == 400 and '有效的 PDF' in error['error']
            for invalid in [{},dict(connection=None),dict(connection={'base_url':'bad'}),dict(model='openai-sol')]:
                assert request('/runs',dict(paper_id=33089,**invalid))[0]==400
            for invalid in [dict(paper_id=True),dict(paper_id=-1),dict(manuscript='short')]:
                assert request('/runs',dict(connection=connection,**invalid))[0]==400
            body=dict(connection=connection,manuscript='complete manuscript '*20,title='<script>text only</script>')
            code,job=request('/runs',body)
            assert code==202 and submit.call_count==1
            assert job['review_provider']['model']=='user-model' and 'provider_identity' not in job
            config=submit.call_args.args[2]
            assert config['key']==connection['api_key'] and config['base_url']==connection['base_url']
            path=Path(folder)/job['id'];assert (path/'manuscript.md').read_text()=='complete manuscript '*20
            saved=(path/'job.json').read_text()
            for secret in [connection['base_url'],connection['api_key']]:
                assert secret not in saved and secret not in json.dumps(request('/runs/'+job['id'])[1])
            assert 'endpoint_sha256' in saved
            assert request('/runs/'+job['id']+'/retry',dict(connection=connection))[0]==400
            a.save_job(path,state='interrupted',phase='reviewing',error='restart')
            assert request('/runs/'+job['id']+'/retry',{})[0]==400
            assert request('/runs/'+job['id']+'/retry',dict(connection=dict(connection,model='other-model')))[0]==400
            assert a.read(path/'job.json')['attempt']==1
            # Re-entering the original endpoint/model with a refreshed key resumes an interrupted task.
            refreshed=dict(connection,api_key='refreshed-review-secret')
            code,retried=request('/runs/'+job['id']+'/retry',dict(connection=refreshed))
            assert code==202 and retried['attempt']==2 and submit.call_count==2
            assert submit.call_args.args[2]['key']==refreshed['api_key']
            assert request('/runs/../../auth')[0]==400
            def stage(args, job_path, config):
                assert args[args.index('--review-model')+1]=='custom'
                assert config['base_url']==connection['base_url'] and config['key']==connection['api_key']
                if 'compose_manuscript_skills.py' in str(args[0]):
                    output=Path(args[args.index('--root')+1]);output.mkdir(parents=True)
                    a.s.write(output/'composition.json',{'model':'user-model'})
                    a.s.write(output/'AUDIT.json',{'output_hashes':{'composition.json':a.s.sha(output/'composition.json')}})
            with patch.object(a,'command',side_effect=stage) as worker:
                a.execute(path,config)
                assert worker.call_count==2 and a.read(path/'job.json')['state']=='completed'
                a.save_job(path,attempt=3,state='queued');a.execute(path,config)
                assert worker.call_count==3 and a.read(path/'job.json')['state']=='completed'
                a.save_job(path,attempt=4,provider_identity={});a.execute(path,config)
                assert worker.call_count==3 and a.read(path/'job.json')['state']=='failed'
            # Credentials reach only the subprocess environment, never argv or worker logs.
            class Child:
                def wait(self):return 0
            with patch.object(a.subprocess,'Popen',return_value=Child()) as spawn:
                a.command(['worker.py'],path,config)
                assert connection['api_key'] not in str(spawn.call_args.args)
                child_env=spawn.call_args.kwargs['env']
                assert json.loads(child_env['ICLR_REVIEW_CONNECTION'])['api_key']==connection['api_key']
                assert 'ICLR_REVIEW_CONNECTION' not in os.environ
            for file in Path(folder).rglob('*'):
                if file.is_file():
                    text=file.read_text()
                    assert connection['api_key'] not in text and refreshed['api_key'] not in text and connection['base_url'] not in text
        finally:server.shutdown();server.server_close()
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
          'user-supplied endpoints, no ambient auth, memory-only credentials, retry identity, child-env isolation, exact-evidence recovery and quarantine')


if __name__=='__main__':main()
