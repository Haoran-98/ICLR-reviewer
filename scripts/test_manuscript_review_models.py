"""No-network transport, model identity, cache isolation and recovery check."""
import json
import os
from pathlib import Path
import tempfile
from types import SimpleNamespace
from unittest.mock import patch

import manuscript_review_models as m
import review_composed_manuscript as reviewer


class Response:
    ok = True
    status_code = 200
    headers = {'content-type':'application/json'}
    def __init__(self, raw): self.raw = raw
    def __enter__(self): return self
    def __exit__(self, *_): pass
    def json(self): return self.raw


def main():
    supplied=dict(base_url='https://user-endpoint.invalid/v1/',api_key='user-supplied-test-key',model='alias',protocol='chat')
    cfg=m.connection(supplied)
    assert cfg['base_url']==supplied['base_url'].rstrip('/') and cfg['id']=='custom'
    assert 'user-endpoint' not in json.dumps(m.identity(cfg)) and cfg['key'] not in json.dumps(m.public(cfg))
    for invalid in [None, {}, dict(supplied,api_key=''),dict(supplied,model=''),dict(supplied,base_url='file:///tmp'),
                    dict(supplied,base_url='https://name:password@provider.invalid'),dict(supplied,base_url='https://provider.invalid?key=secret'),
                    dict(supplied,base_url='https://provider.invalid/v1/chat/completions'),dict(supplied,api_key='header\r\ninjection'),dict(supplied,protocol='anthropic')]:
        try:m.connection(invalid)
        except ValueError:pass
        else:raise AssertionError('Invalid custom connection accepted')
    with patch.dict(os.environ,{'ICLR_REVIEW_CONNECTION':json.dumps(supplied)}):
        assert m.configuration('custom')==cfg
    with patch.dict(os.environ,{'ICLR_REVIEW_CONNECTION':''}):
        try:m.configuration('custom')
        except ValueError:pass
        else:raise AssertionError('Custom configuration fell back to server credentials')
    m.validate_response({'status':'completed','model':'alias-versioned'},cfg)
    schema = {'type':'object','properties':{'ok':{'type':'boolean'}},'required':['ok']}
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        for protocol, identifier in [('responses','openai-sol'),('chat','deepseek-pro'),('anthropic','claude-opus')]:
            folder=root/identifier;folder.mkdir()
            config=dict(id=identifier,label=identifier,model='test-model',protocol=protocol,
                base_url='https://test.invalid/v1',key='test-secret',configured=True)
            content=json.dumps(dict(ok=True))
            if protocol=='responses':
                raw=dict(model='test-model',status='completed',reasoning=dict(effort='medium'),
                    output=[dict(type='message',content=[dict(type='output_text',text=content)])],
                    usage=dict(input_tokens=4,output_tokens=3))
            elif protocol=='chat':
                raw=dict(model='test-model',choices=[dict(finish_reason='stop',message=dict(content=content))],
                    usage=dict(prompt_tokens=4,completion_tokens=3))
            else:
                raw=dict(model='test-model',stop_reason='end_turn',content=[dict(type='text',text=content)],
                    usage=dict(input_tokens=4,output_tokens=3))
            with patch.object(m.requests,'post',return_value=Response(raw)) as post:
                client=m.Client(SimpleNamespace(root=folder),config)
                assert client.ask('test','target',{},schema,4096,100)==dict(ok=True)
                args=post.call_args;wire=args.kwargs['json']
                assert args.args[0].endswith({'responses':'/responses','chat':'/chat/completions','anthropic':'/messages'}[protocol])
                assert wire['model']=='test-model'
                if protocol=='chat':assert wire['thinking']==dict(type='disabled')
                if protocol=='anthropic':assert args.kwargs['headers']['x-api-key']=='test-secret'
                # An identical rerun uses the cache and makes no second HTTP call.
                assert client.ask('test','target',{},schema,4096,100)==dict(ok=True) and post.call_count==1
                changed=m.Client(SimpleNamespace(root=folder),dict(config,model='other-model'))
                try:changed.ask('test','target',{},schema,4096,100)
                except ValueError:pass
                else:raise AssertionError('Cross-model cache reuse accepted')
                assert post.call_count==1
            for file in folder.rglob('*.json'):assert 'test-secret' not in file.read_text()
        # Provider identity validation must reject a response from another model.
        bad=root/'bad';bad.mkdir()
        config=dict(config,protocol='chat')
        raw=dict(model='wrong-model',choices=[dict(finish_reason='stop',message=dict(content=content))])
        with patch.object(m.requests,'post',return_value=Response(raw)) as post:
            try:m.Client(SimpleNamespace(root=bad),config).ask('test','target',{},schema,4096,100)
            except RuntimeError:pass
            else:raise AssertionError('Wrong provider model accepted')
            assert post.call_count==1
        # Exact-evidence recovery also works for normalized non-OpenAI responses.
        recovery=root/'recovery';recovery.mkdir()
        manuscript=dict(passages=[dict(passage_id='p',text='original text',char_start=0,char_end=13)])
        data=dict(example=True);review=dict(strengths=[dict(point='good',evidence=[dict(passage_id='p',quote='original text')]),
            dict(point='bad',evidence=[dict(passage_id='p',quote='made up')])],concerns=[],rules_applied=[])
        raw=dict(model='test-model',choices=[dict(finish_reason='stop',message=dict(content=json.dumps(review)))])
        cfg=dict(config,model='test-model',id='deepseek-pro')
        with patch.object(m.requests,'post',return_value=Response(raw)):
            try:m.Client(SimpleNamespace(root=recovery),cfg).ask('review','target',data,{'type':'object'},4096,100,
                lambda value:reviewer.validate(value,manuscript,[]))
            except RuntimeError:pass
        restored=reviewer.recover(recovery,data,{'type':'object'},manuscript,[],cfg)
        assert len(restored['strengths'])==1
        try:reviewer.recover(recovery,data,{'type':'object'},manuscript,[],dict(cfg,base_url='https://other.invalid'))
        except ValueError:pass
        else:raise AssertionError('Changed recovery provider accepted')
        private=root/'custom';private.mkdir()
        cfg=m.connection(supplied)
        raw=dict(model='alias-versioned',choices=[dict(finish_reason='stop',message=dict(content=json.dumps(dict(ok=True))))],
                 diagnostic=supplied['api_key']+' '+cfg['base_url'])
        with patch.object(m.requests,'post',return_value=Response(raw)) as post:
            assert m.Client(SimpleNamespace(root=private),cfg).ask('test','target',{},schema,4096,100)==dict(ok=True)
            assert post.call_args.kwargs['headers']['Authorization']=='Bearer '+supplied['api_key']
            assert not post.call_args.kwargs['allow_redirects']
        for file in private.rglob('*.json'):
            assert supplied['api_key'] not in file.read_text() and cfg['base_url'] not in file.read_text()
    print('passed: three transports, payload routing, exact model validation, cache identity, '
          'server-only keys, normalized exact-evidence recovery and provider mismatch rejection')


if __name__=='__main__': main()
