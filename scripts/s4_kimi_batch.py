#!/usr/bin/env python3
"""Resume only Kimi S4 jobs via Moonshot Batch; no realtime inference fallback.

Reference: https://platform.kimi.com/docs/guide/use-batch-api
The same job IDs, cached results and six-attempt budget are shared with realtime.
"""
from __future__ import annotations

import argparse
import fcntl
import json
import os
from pathlib import Path
import time

import requests

import s4_llm_taxonomy as s4

TERMINAL = {'completed', 'failed', 'expired', 'cancelled'}
PARSER_VERSION = 'batch_response_v2'


def api(args, config, method, path, **kwargs):
    """Only safe reads retry automatically; an ambiguous create is reconciled."""
    for attempt in range(1, s4.MAX_ATTEMPTS + 1):
        try:
            response = requests.request(method, config['base_url'] + path,
                headers={'Authorization': 'Bearer ' + config['key']}, timeout=(15, 120), **kwargs)
            if response.status_code >= 400:
                detail = response.text.replace(config['key'], '[REDACTED]')
                s4.write(args.root/'batch'/'last_api_error.json', {
                    'time': s4.now(), 'method': method, 'path': path,
                    'http_status': response.status_code, 'detail': detail})
                raise s4.JobFailure(f'batch_http_{response.status_code}',
                    response.status_code in (408, 409, 429) or response.status_code >= 500)
            return response
        except (requests.RequestException, s4.JobFailure) as error:
            retryable = not isinstance(error, s4.JobFailure) or error.retryable
            if method != 'GET' or not retryable or attempt == s4.MAX_ATTEMPTS:
                raise
            s4.log('batch_read_retry', attempt=attempt, error=type(error).__name__)
            time.sleep(min(2**attempt, 32))


def save_value(args, entry, value, provenance):
    if entry['kind'] not in ('generate', 'official_vote'):
        return  # Analysis consumers persist votes after their own evidence checks.
    paper_id = entry['paper_id']
    if entry['kind'] == 'official_vote':
        target = args.root/'official_votes'/'kimi'/f'{paper_id}.json'
        if not target.exists():
            s4.write(target, value)
        return
    target = args.root/'generated'/'kimi'/f'{paper_id}.json'
    existing = s4.read(target, {})
    level = str(entry['level'])
    if level not in existing:
        existing[level] = value['nodes']
        existing[f'pruned_{level}'] = value.get('pruned_branches', [])
        existing.setdefault('_provenance', {})[level] = provenance
        s4.write(target, existing)


def frontier(args, config):
    """Only the next missing hierarchy level per paper; votes are independent."""
    papers = s4.read(args.root/'manifest.json')['papers']
    options = sorted({p['canonical_key'] for p in papers})
    entries, blocked = [], []
    for paper in papers:
        paper_id = paper['paper_id']
        target = args.root/'generated'/'kimi'/f'{paper_id}.json'
        todo = []
        for level in (1, 2, 3):
            existing = s4.read(target, {})
            if str(level) in existing:
                continue
            payload = s4.generation_payload(args, paper_id, 'kimi', level)
            if level > 1 and not payload['parents']:
                existing[str(level)] = []
                s4.write(target, existing)
                continue
            job, body = s4.build_job(config, 'kimi', 'generate', payload)
            cached = s4.read(args.root/'results'/f'{job["job_id"]}.json')
            if cached:
                save_value(args, {'paper_id': paper_id, 'kind': 'generate', 'level': level},
                    cached['value'], {k: cached.get(k) for k in
                        ('model', 'endpoint', 'reasoning_effort', 'created_at', 'transport', 'batch_id', 'request_layout')})
                continue
            todo.append((job, body, level))
            break
        if not (args.root/'official_votes'/'kimi'/f'{paper_id}.json').exists():
            payload = s4.official_vote_payload(args, paper_id, options)
            job, body = s4.build_job(config, 'kimi', 'official_vote', payload)
            cached = s4.read(args.root/'results'/f'{job["job_id"]}.json')
            if cached:
                save_value(args, {'paper_id': paper_id, 'kind': 'official_vote'}, cached['value'], {})
            else:
                todo.append((job, body, None))
        for job, body, level in todo:
            job_id = job['job_id']
            history = sorted((args.root/'attempts'/job_id).glob('*.json'))
            if len(history) >= s4.MAX_ATTEMPTS or (history and not s4.read(history[-1]).get('retryable', True)):
                blocked.append({'paper_id': paper_id, 'job_id': job_id, 'attempts': len(history)})
                continue
            entries.append({'paper_id': paper_id, 'kind': job['kind'], 'level': level,
                'job': job, 'request': {'custom_id': job_id, 'method': 'POST',
                    'url': '/v1/chat/completions', 'body': body}, 'attempt': len(history) + 1})
    if blocked:
        s4.write(args.root/'batch'/'blocked_jobs.json', blocked)
        raise RuntimeError(f'{len(blocked)} jobs blocked by existing retry history; budget was not reset')
    return entries


def progress(args):
    papers = s4.read(args.root/'manifest.json')['papers']
    completed = {}
    for provider in s4.PROVIDERS:
        completed[provider] = sum(
            all(str(i) in s4.read(args.root/'generated'/provider/f'{p["paper_id"]}.json', {}) for i in (1, 2, 3))
            and (args.root/'official_votes'/provider/f'{p["paper_id"]}.json').exists() for p in papers)
    s4.write(args.root/'provider_progress.json', {'completed': completed, 'updated_at': s4.now()})
    return completed


def submit(args, config, state, path):
    # A saved input_file_id reconciles a lost POST response without another paid batch.
    if state.get('submission_started_at') and not state.get('batch_id'):
        page = api(args, config, 'GET', '/batches', params={'limit': 100}).json()
        matches = [b for b in page['data'] if b.get('input_file_id') == state['input_file_id']]
        if len(matches) != 1:
            raise RuntimeError('Ambiguous batch creation: inspect input_file_id before resubmitting; no duplicate submitted')
        state.update(batch_id=matches[0]['id'], remote=matches[0])
        s4.write(path, state)
    if state.get('batch_id'):
        return
    if not state.get('input_file_id'):
        data = ''.join(json.dumps(e['request'], ensure_ascii=False) + '\n' for e in state['entries']).encode()
        if not 0 < len(data) <= 100_000_000:
            raise ValueError('Batch JSONL must be nonempty and <=100MB')
        uploaded = api(args, config, 'POST', '/files', data={'purpose': 'batch'},
            files={'file': ('s4_kimi.jsonl', data, 'application/jsonl')}).json()
        state['input_file_id'] = uploaded['id']
        s4.write(path, state)
    state['submission_started_at'] = s4.now()
    s4.write(path, state)
    batch = api(args, config, 'POST', '/batches', json={
        'input_file_id': state['input_file_id'], 'endpoint': '/v1/chat/completions',
        'completion_window': '24h'}).json()
    state.update(batch_id=batch['id'], remote=batch)
    s4.write(path, state)
    s4.write(args.root/'batch'/f'{batch["id"]}.json', state)
    s4.log('batch_submitted', batch_id=batch['id'], requests=len(state['entries']),
           input_file_id=state['input_file_id'], completion_window='24h')


def summarize_usage(rows):
    summary = {'responses_with_usage': 0, 'cache_read_reported_responses': 0,
        'prompt_tokens': 0, 'completion_tokens': 0, 'cached_tokens': 0,
        'prompt_tokens_with_cache_reporting': 0, 'cache_write_reported_responses': 0,
        'cache_write_tokens': 0}
    for row in rows:
        raw = (row.get('response') or {}).get('body') or {}
        usage = raw.get('usage') if isinstance(raw, dict) else None
        if not usage:
            continue
        summary['responses_with_usage'] += 1
        summary['prompt_tokens'] += usage.get('prompt_tokens', 0)
        summary['completion_tokens'] += usage.get('completion_tokens', 0)
        details = usage.get('prompt_tokens_details') or {}
        cached = details.get('cached_tokens', usage.get('cached_tokens'))
        if cached is not None:
            summary['cache_read_reported_responses'] += 1
            summary['cached_tokens'] += cached
            summary['prompt_tokens_with_cache_reporting'] += usage.get('prompt_tokens', 0)
        if 'cache_write_tokens' in details:
            summary['cache_write_reported_responses'] += 1
            summary['cache_write_tokens'] += details['cache_write_tokens']
    denominator = summary['prompt_tokens_with_cache_reporting']
    summary['cache_hit_ratio_of_reported_inputs'] = summary['cached_tokens']/denominator if denominator else None
    return summary


def reserve_attempts(args, entries):
    for entry in entries:
        job = entry['job']
        s4.write(args.root/'jobs'/f'{job["job_id"]}.json', job)
        attempt_path = args.root/'attempts'/job['job_id']/f'{entry["attempt"]:02d}.json'
        if not attempt_path.exists():
            s4.write(attempt_path, {'job_id': job['job_id'], 'provider': 'kimi',
                'attempt': entry['attempt'], 'started_at': s4.now(), 'status': 'submitted',
                'retryable': True, 'transport': 'batch',
                'request_parameters': {k: v for k, v in entry['request']['body'].items() if k != 'messages'}})


def request_many(args, kind, payloads):
    """Batch an analysis stage, retaining order, cache and per-job retry budgets."""
    if not payloads:
        return []
    config = s4.credentials(args.auth)['kimi']
    if config['model'] not in ('kimi-k2.6', 'kimi-k2.7-code') or '/coding/' in config['base_url']:
        raise ValueError('Analysis Batch requires supported Moonshot platform credentials')
    public = {k: v for k, v in config.items() if k != 'key'}
    jobs = [s4.build_job(config, 'kimi', kind, p) for p in payloads]
    all_ids = {job['job_id'] for job,_ in jobs}
    path = args.root/'batch'/'analysis_active.json'
    while True:
        pending = [(j,b) for j,b in jobs if not (args.root/'results'/f'{j["job_id"]}.json').exists()]
        if not pending:
            return [s4.read(args.root/'results'/f'{j["job_id"]}.json')['value'] for j,_ in jobs]
        state = s4.read(path)
        if not state or state.get('imported_at'):
            entries = []
            for job, body in pending:
                history = sorted((args.root/'attempts'/job['job_id']).glob('*.json'))
                if len(history) >= s4.MAX_ATTEMPTS or history and not s4.read(history[-1]).get('retryable', True):
                    raise s4.JobFailure('analysis_batch_attempt_budget_exhausted', False)
                entries.append({'paper_id': None, 'level': None, 'kind': kind,
                    'job': job, 'attempt': len(history)+1, 'request': {
                        'custom_id': job['job_id'], 'method': 'POST', 'url': '/v1/chat/completions', 'body': body}})
            state = {'created_at': s4.now(), 'purpose': 'analysis_'+kind, 'config': public, 'entries': entries}
            s4.write(path, state)
        if state['config'] != public or not {e['job']['job_id'] for e in state['entries']} <= all_ids:
            raise RuntimeError('Active analysis batch belongs to another configuration or stage; collect it first')
        reserve_attempts(args, state['entries'])
        submit(args, config, state, path)
        while True:
            remote = api(args, config, 'GET', f'/batches/{state["batch_id"]}').json()
            state['remote'] = remote
            s4.write(path, state)
            s4.write(args.root/'analysis_batch_progress.json', {'updated_at': s4.now(),
                'purpose': state['purpose'], 'batch_id': remote['id'], 'status': remote['status'],
                'request_counts': remote.get('request_counts')})
            s4.log('analysis_batch_status', batch_id=remote['id'], kind=kind,
                   status=remote['status'], counts=remote.get('request_counts'))
            if remote['status'] in TERMINAL:
                import_results(args, config, state, path)
                break
            time.sleep(30)


def import_results(args, config, state, path):
    batch = state['remote']
    revalidating = state.get('imported_at') and state.get('parser_version') != PARSER_VERSION
    if revalidating:
        # Preserve the original http_0 misclassification and attempt numbers.
        audit = args.root/'batch'/f'{state["batch_id"]}_before_{PARSER_VERSION}.json'
        if not audit.exists():
            s4.write(audit, {'original_batch': state, 'revalidated_at': s4.now(),
                'original_attempts': {e['job']['job_id']: s4.read(
                    args.root/'attempts'/e['job']['job_id']/f'{e["attempt"]:02d}.json')
                    for e in state['entries']}})
    rows = {}
    for field in ('output_file_id', 'error_file_id'):
        file_id = batch.get(field)
        if not file_id:
            continue
        downloaded = args.root/'batch'/f'{state["batch_id"]}_{field}.json'
        parsed = s4.read(downloaded)
        if parsed is None:
            contents = api(args, config, 'GET', f'/files/{file_id}/content').text
            contents = contents.replace(config['key'], '[REDACTED]')
            parsed = [json.loads(line) for line in contents.splitlines() if line.strip()]
            s4.write(downloaded, parsed)
        for row in parsed:
            custom_id = row['custom_id']
            if custom_id in rows:
                raise ValueError('Duplicate custom_id in batch results')
            rows[custom_id] = row
    expected = {e['job']['job_id'] for e in state['entries']}
    if set(rows) - expected:
        raise ValueError('Batch output contains unknown custom_id')
    failures = []
    for entry in state['entries']:
        job, attempt = entry['job'], entry['attempt']
        job_id = job['job_id']
        record_path = args.root/'attempts'/job_id/f'{attempt:02d}.json'
        record = s4.read(record_path)
        target = args.root/'results'/f'{job_id}.json'
        result = s4.read(target)
        if not result:
            row = rows.get(job_id, {})
            response = row.get('response') or {}
            status = response.get('status_code')
            raw = response.get('body')
            record.update(http_status=status, response_body=json.dumps(raw, ensure_ascii=False),
                batch_error=row.get('error'), ended_at=s4.now(), parser_version=PARSER_VERSION)
            try:
                if not row:
                    raise s4.JobFailure('batch_missing_result', batch['status'] != 'failed')
                if row.get('error'):
                    code = row['error'].get('code', 'batch_request_error')
                    raise s4.JobFailure(str(code), code not in ('invalid_request', 'invalid_request_error', 'model_not_found'))
                # Observed Moonshot Batch output uses 0 even for valid completions.
                # Accept that sentinel ONLY with a success-shaped body, no API error,
                # and the same finish-reason/JSON/evidence checks as a 200 response.
                zero_completion = (type(status) is int and status == 0 and isinstance(raw, dict)
                    and not raw.get('error') and isinstance(raw.get('choices'), list)
                    and bool(raw['choices']))
                if not (type(status) is int and status == 200 or zero_completion):
                    raise s4.JobFailure(f'http_{status}', status in (408, 409, 429) or isinstance(status, int) and status >= 500)
                value = s4.validate_response(raw, job['kind'], job['payload'])
                record['status_interpretation'] = 'validated_completion_with_zero_status' if zero_completion else 'http_200'
                result = {'job_id': job_id, 'provider': 'kimi', 'kind': job['kind'], 'value': value,
                    'model': job['model'], 'endpoint': job['endpoint'], 'reasoning_effort': job.get('reasoning_effort'),
                    'created_at': s4.now(), 'usage': raw.get('usage', {}), 'response_model': raw.get('model'),
                    'input_hash': job['input_hash'], 'response_hash': s4.digest(raw),
                    'transport': 'batch', 'batch_id': state['batch_id'],
                    'request_layout': job.get('request_layout'), 'request_hash': job.get('request_hash'),
                    'batch_response_status': status, 'parser_version': PARSER_VERSION}
                # Cache first: an interrupted import can replay this write idempotently.
                s4.write(target, result)
            except (ValueError, KeyError, IndexError, TypeError, s4.JobFailure) as error:
                retryable = error.retryable if isinstance(error, s4.JobFailure) else True
                record.update(status='failed', retryable=retryable, detail=str(error),
                    error_kind=error.kind if isinstance(error, s4.JobFailure) else type(error).__name__)
                s4.write(record_path, record)
                failures.append({'paper_id': entry['paper_id'], 'job_id': job_id,
                    'attempt': attempt, 'retryable': retryable, 'error': record['detail']})
                continue
        record.update(status='success', retryable=False, ended_at=s4.now())
        s4.write(record_path, record)
        save_value(args, entry, result['value'], {k: result.get(k) for k in
            ('model', 'endpoint', 'reasoning_effort', 'created_at', 'transport', 'batch_id', 'request_layout')})
    state.update(imported_at=s4.now(), failures=failures, cache_usage=summarize_usage(rows.values()),
                 parser_version=PARSER_VERSION)
    s4.write(path, state)
    s4.write(args.root/'batch'/f'{state["batch_id"]}.json', state)
    s4.log('batch_imported', batch_id=state['batch_id'], failures=len(failures),
           completed=progress(args), cache_usage=state['cache_usage'])
    if batch['status'] in ('failed', 'cancelled'):
        raise RuntimeError(f'Batch {batch["status"]}; inspect saved errors before a new submission')
    if any(not f['retryable'] or f['attempt'] >= s4.MAX_ATTEMPTS for f in failures):
        raise RuntimeError('Batch jobs reached permanent errors or the six-attempt limit')


def run(args):
    config = s4.credentials(args.auth)['kimi']
    if config['model'] not in ('kimi-k2.6', 'kimi-k2.7-code') or '/coding/' in config['base_url']:
        raise ValueError('Batch requires Moonshot platform credentials and a supported model')
    public = {k: v for k, v in config.items() if k != 'key'}
    while True:
        path = args.root/'batch'/'active.json'
        state = s4.read(path)
        if state and state.get('imported_at') and state.get('parser_version') != PARSER_VERSION:
            if state['config'] != public:
                raise RuntimeError('Restore the imported batch configuration before revalidating it')
            import_results(args, config, state, path)
        if not state or state.get('imported_at'):
            entries = frontier(args, config)
            if not entries:
                completed = progress(args)
                status = 'generation_complete' if all(n == 200 for n in completed.values()) else 'selected_providers_complete'
                if status == 'generation_complete':
                    s4.write(args.root/'generation_complete.json', {'papers': 200, 'completed_at': s4.now()})
                return status
            state = {'created_at': s4.now(), 'config': public, 'entries': entries}
            s4.write(path, state)
        elif state['config'] != public:
            raise RuntimeError('Active batch configuration changed; restore its model/endpoint to collect it')
        reserve_attempts(args, state['entries'])
        submit(args, config, state, path)
        batch = api(args, config, 'GET', f'/batches/{state["batch_id"]}').json()
        state['remote'] = batch
        s4.write(path, state)
        s4.write(args.root/'execution.json', {'status': 'running', 'pid': os.getpid(),
            'providers': ['kimi'], 'transport': 'batch', 'updated_at': s4.now(),
            'batch_id': batch['id'], 'batch_status': batch['status'],
            'request_counts': batch.get('request_counts'), 'completed': progress(args)})
        s4.log('batch_status', batch_id=batch['id'], status=batch['status'], counts=batch.get('request_counts'))
        if batch['status'] in TERMINAL:
            import_results(args, config, state, path)
        else:
            time.sleep(30)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, default=s4.ROOT)
    parser.add_argument('--auth', type=Path, default=Path(os.environ.get('ICLR_AUTH_FILE', Path.home()/'auth')))
    args = parser.parse_args()
    with (args.root/'run.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        s4.write(args.root/'execution.json', {'status': 'running', 'pid': os.getpid(),
            'providers': ['kimi'], 'transport': 'batch', 'started_at': s4.now()})
        try:
            status = run(args)
        except Exception as error:
            s4.write(args.root/'execution.json', {'status': 'failed', 'pid': os.getpid(),
                'providers': ['kimi'], 'transport': 'batch', 'ended_at': s4.now(),
                'error': type(error).__name__, 'message': str(error)})
            raise
        s4.write(args.root/'execution.json', {'status': status, 'providers': ['kimi'],
            'transport': 'batch', 'ended_at': s4.now(), 'completed': progress(args)})


if __name__ == '__main__':
    main()
