#!/usr/bin/env python3
"""Loopback-only review jobs; the Vite proxy keeps model credentials server-side."""
import argparse
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
import hmac
import fcntl
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import re
import shutil
import signal
import subprocess
import sys
import threading
from urllib.parse import urlsplit
import uuid
from manuscript_upload import extract_upload, MAX_REQUEST_BYTES

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO/'scripts'))
import compose_manuscript_skills as c
import manuscript_review_models as models
s = c.s
ROOT = Path(os.environ.get('ICLR_REVIEW_RUNS', c.s.ROOT.parent/'web_review_runs'))
SEED = c.s.ROOT.parent/'manuscript_composition_mlra_v1'
TOKEN = os.environ.get('ICLR_REVIEW_API_TOKEN', '')
POOL = ThreadPoolExecutor(max_workers=1)
LOCK = threading.RLock()
CHILDREN = set()


def read(path, default=None):
    return s.read(path) if path.exists() else default


def save_job(path, **changes):
    with LOCK:
        record = read(path/'job.json', {}); record.update(changes, updated_at=s.now())
        temporary = path/'job.tmp'; s.write(temporary, record); temporary.replace(path/'job.json')
        return record


def job_path(identifier):
    if not re.fullmatch(r'[a-f0-9]{32}', identifier): raise ValueError('任务标识无效')
    path = ROOT/identifier
    if not (path/'job.json').exists(): raise ValueError('任务不存在')
    return path


def public_composition(path):
    value = deepcopy(read(path/'composition.json'))
    if value:
        for selected in value['selected']:
            for example in selected['historical_sources']['display_examples']:
                example.pop('source_input', None); example.pop('source_case', None)
    return value


def public_job(job):
    value = dict(job); value.pop('provider_identity', None)
    if not value.get('review_provider'):
        value['review_provider'] = dict(id='legacy-openai-weak', label='OpenAI 弱模型（历史记录）', model=s.MODEL)
    return value


def result(path):
    job = read(path/'job.json'); attempt = path/f'attempt-{job["attempt"]}'
    composition = attempt/'compose'; review = attempt/'review'
    progress = read((review if job['phase'] == 'reviewing' or job['state'] == 'completed' else composition)/'progress.json', {})
    manuscript = read(composition/'manuscript.json', {})
    return dict(job=public_job(job), progress={key:progress.get(key) for key in ['phase', 'run_state', 'usage', 'active_requests']},
        profile=read(composition/'profile.json'), composition=public_composition(composition),
        checks=read(composition/'checks.json'), review=read(review/'review.json'), evidence=read(review/'evidence.json'),
        recovery=read(review/'LOCAL_RECOVERY.json'),
        manuscript=dict(title=manuscript.get('title'), coverage=manuscript.get('coverage'), passages=manuscript.get('passages', [])))


def command(args, path):
    with (path/'worker.log').open('ab') as log:
        child = subprocess.Popen([sys.executable, '-X', 'pycache_prefix=/tmp/iclr-web-review-pycache', *map(str,args)],
            cwd=REPO, stdout=log, stderr=log)
        with LOCK: CHILDREN.add(child)
        try:
            if child.wait():
                # Detailed provider failures stay in local logs, never expose credentials to the browser.
                details = (path/'worker.log').read_text(errors='replace')[-5000:]
                reason = '当前阶段未完成；已保留输入和成功结果，可重试。'
                if 'Target overlaps a library source' in details: reason = '这篇论文参与了当前规则库的提炼，请选择未参与提炼的稿件。历史经验仍可在 Skill 库中查看。'
                elif 'Domain uncertain or outside' in details: reason = '稿件领域尚不确定或不在当前大语言模型规则库范围内，未加载规则。'
                elif 'exceeds input budget' in details: reason = '完整稿件超出本次模型输入预算，原文已保留；请使用可支持更长正文的流程。'
                elif 'No manuscript available' in details: reason = '这篇论文尚无可用正文，请上传完整文本。'
                elif 'Quote must be verbatim' in details: reason = '审稿返回的原文引文未通过逐字核验，结果已保留，请重试本阶段。'
                raise RuntimeError(reason)
        finally:
            with LOCK: CHILDREN.discard(child)


def execute(path):
    job = read(path/'job.json'); attempt = path/f'attempt-{job["attempt"]}'; attempt.mkdir(exist_ok=True)
    composition = attempt/'compose'; review = attempt/'review'
    try:
        selection = job.get('review_provider')
        model_args = []
        if selection:
            config = models.configuration(selection['id'])
            if not config['configured']: raise RuntimeError('所选模型尚未配置，请补齐服务端配置后重试。')
            if models.identity(config) != job.get('provider_identity'): raise RuntimeError('任务模型配置已变化，请恢复原配置重试或创建新任务。')
            model_args = ['--review-model', selection['id']]
        save_job(path, state='running', phase='composing', error=None)
        previous = path/f'attempt-{job["attempt"]-1}'/'compose'
        seed = previous if (previous/'composition.json').exists() else SEED if job.get('paper_id') == 33089 and not selection else None
        if seed and not composition.exists(): shutil.copytree(seed, composition)
        if not (composition/'composition.json').exists():
            # Copy only successful inference caches on explicit retry; failed attempts remain in the earlier execution.
            if previous.exists() and not composition.exists():
                composition.mkdir()
                for name in ['MANUSCRIPT.md', 'manuscript.json', 'manifest.json', 'config.json']:
                    if (previous/name).exists(): shutil.copyfile(previous/name, composition/name)
                for cached in previous.glob('requests/*/*/result.json'):
                    dest = composition/cached.parent.relative_to(previous); shutil.copytree(cached.parent, dest)
            args = [REPO/'scripts/compose_manuscript_skills.py', 'run', '--root', composition, *model_args]
            if job.get('paper_id'): args += ['--paper-id', job['paper_id']]
            else: args += ['--manuscript', path/'manuscript.md', '--title', job['title']]
            command(args, path)
        # Check the actual composition files before forwarding them to the reviewer.
        audit = s.read(composition/'AUDIT.json')
        for name, digest in audit['output_hashes'].items():
            s.require(s.sha(composition/name) == digest, 'Composition artifact changed')
        save_job(path, phase='reviewing')
        previous_review=path/f'attempt-{job["attempt"]-1}'/'review/requests/review/target'
        old_attempts=sorted(previous_review.glob('attempt_*.json'))
        if old_attempts and (read(old_attempts[-1]).get('response') or {}).get('status')=='completed' and not review.exists():
            imported=review/'recovery_source';imported.mkdir(parents=True)
            shutil.copyfile(old_attempts[-1],imported/'attempt.json')
            shutil.copyfile(previous_review/'request.json',imported/'request.json')
        command([REPO/'scripts/review_composed_manuscript.py', '--source', composition, '--root', review, *model_args], path)
        save_job(path, state='completed', phase='completed', error=None)
    except Exception as error:
        save_job(path, state='failed', error=str(error) if isinstance(error, RuntimeError) else '任务未完成，记录已保留。可检查输入后重试。')


def submit(payload):
    if not isinstance(payload, dict): raise ValueError('输入必须是对象')
    pid = payload.get('paper_id'); text = payload.get('manuscript')
    if pid is not None:
        if isinstance(pid, bool) or not isinstance(pid, int) or pid <= 0: raise ValueError('论文 ID 无效')
    elif not isinstance(text, str) or len(text.strip()) < 200: raise ValueError('请上传或粘贴完整稿件，至少 200 字符')
    if text is not None and (not isinstance(text, str) or len(text.encode()) > 1_500_000): raise ValueError('稿件过大')
    config = models.configuration(payload.get('model', models.DEFAULT))
    if not config['configured']: raise ValueError('所选模型尚未配置，请选择已配置的接口')
    title = str(payload.get('title') or (f'论文 {pid}' if pid else '上传稿件'))[:300]
    path = ROOT/uuid.uuid4().hex; path.mkdir(parents=True)
    if pid is None: (path/'manuscript.md').write_text(text)
    record = save_job(path, id=path.name, paper_id=pid, title=title, review_provider=models.public(config), provider_identity=models.identity(config), attempt=1, state='queued', phase='queued', error=None)
    POOL.submit(execute, path)
    return public_job(record)


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args): pass
    def respond(self, code, value):
        body = json.dumps(value, ensure_ascii=False).encode()
        self.send_response(code); self.send_header('Content-Type', 'application/json; charset=utf-8')
        self.send_header('Content-Length', str(len(body))); self.end_headers(); self.wfile.write(body)
    def dispatch(self):
        if not TOKEN or not hmac.compare_digest(self.headers.get('X-Review-Token', ''), TOKEN):
            self.respond(403, dict(error='请求未授权')); return
        route = urlsplit(self.path).path.removeprefix('/api/review').rstrip('/')
        try:
            if self.command == 'GET' and route == '/meta':
                self.respond(200, dict(model=models.configuration(models.DEFAULT)['model'], default_model=models.DEFAULT, models=models.models(), library='llm-area-v1', max_rules=10, rule_tokens=4000,
                    example=dict(paper_id=33089, title='Multi-Head Low-Rank Attention')))
            elif self.command == 'GET' and route == '/runs':
                self.respond(200, sorted([public_job(read(p)) for p in ROOT.glob('*/job.json')], key=lambda j:j['updated_at'], reverse=True)[:50])
            elif self.command == 'GET' and route == '/example':
                self.respond(200, dict(profile=read(SEED/'profile.json'), composition=public_composition(SEED),
                    checks=read(SEED/'checks.json'), manuscript=read(SEED/'manuscript.json')))
            elif self.command == 'GET' and route.startswith('/runs/'):
                self.respond(200, result(job_path(route.split('/')[-1])))
            elif self.command == 'POST':
                size = int(self.headers.get('Content-Length', '0'))
                limit = MAX_REQUEST_BYTES if route == '/extract' else 2_000_000
                if not 0 < size <= limit: raise ValueError('请求内容为空或过大')
                payload = json.loads(self.rfile.read(size))
                if route == '/extract':
                    try: self.respond(200, extract_upload(payload))
                    except ValueError as error: self.respond(400, dict(error=str(error)))
                elif route == '/runs': self.respond(202, submit(payload))
                elif re.fullmatch(r'/runs/[a-f0-9]{32}/retry', route):
                    with LOCK:
                        path = job_path(route.split('/')[-2]); job = read(path/'job.json')
                        if job['state'] not in ['failed', 'interrupted']: raise ValueError('当前任务无需重试')
                        save_job(path, attempt=job['attempt']+1, state='queued', phase='queued', error=None)
                    POOL.submit(execute, path); self.respond(202, public_job(read(path/'job.json')))
                else: self.respond(404, dict(error='接口不存在'))
            else: self.respond(404, dict(error='接口不存在'))
        except (ValueError, TypeError, json.JSONDecodeError) as error:
            message = str(error)
            self.respond(400, dict(error=message if message in ('未知审稿模型', '所选模型尚未配置，请选择已配置的接口') else '输入无效，请检查论文 ID、稿件内容或任务状态'))
        except Exception: self.respond(500, dict(error='服务未能读取此记录，请稍后重试'))
    do_GET = dispatch
    do_POST = dispatch


if __name__ == '__main__':
    parser = argparse.ArgumentParser(); parser.add_argument('--port', type=int, default=0); args = parser.parse_args()
    ROOT.mkdir(parents=True, exist_ok=True)
    coordinator_lock=(ROOT/'service.lock').open('a')
    fcntl.flock(coordinator_lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
    for saved in ROOT.glob('*/job.json'):
        if read(saved)['state'] in ['queued', 'running']: save_job(saved.parent, state='interrupted', error='服务重启，输入与已完成阶段已保留，可继续重试。')
    server = ThreadingHTTPServer(('127.0.0.1', args.port), Handler)
    def stop(*_):
        with LOCK:
            for child in list(CHILDREN): child.terminate()
        os._exit(0)
    signal.signal(signal.SIGTERM, stop)
    print(json.dumps(dict(port=server.server_port)), flush=True)
    server.serve_forever()
