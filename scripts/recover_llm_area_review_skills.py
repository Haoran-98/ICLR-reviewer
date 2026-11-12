#!/usr/bin/env python3
"""Recover frozen unresolved checks with a separate, bounded API/local epoch."""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor, wait, FIRST_COMPLETED
from copy import deepcopy
import fcntl
from functools import lru_cache
import json
from pathlib import Path
import shutil
import signal
import sqlite3
import threading
from types import SimpleNamespace

import parallel_llm_area_review_skills as p

f, s = p.f, p.s
SOURCE = p.area.ROOT
ROOT = SOURCE.parent/'modular_skill_llm_area_recovery_v1'
POLICY = (
    'Recover an unresolved historical review mechanism, not a factual accusation against its paper. '
    'Copy candidate IDs EXACTLY from supplied candidates; never normalize zero padding or invent IDs. '
    'All rules in this request share one mechanism family. REFINE one existing equivalent rule to retain '
    'the focus candidate in its provenance; duplicate/incorporated require that exact candidate ID in '
    'the active referenced rule. A similar rule without that citation is NOT credited coverage. '
    'ADD a specific conditional check if existing rules have a different object, mechanism or boundary. '
    'MERGE needs at least two targets; REFINE needs exactly one. Do not echo omitted provenance IDs: '
    'the transaction inherits prior provenance. Emit at most 12 supplied candidate IDs per rule; '
    'for REFINE, citing the focus IDs suffices while all original provenance is inherited. '
    'Single-source or unverified historical opinions may '
    'yield CANDIDATE rules; lack of a second paper alone is not needs_evidence. Additional manuscript '
    'spans are from the sealed current manuscript, whose date is NOT aligned to the initial review. '
    'They do not prove a historical defect, resolve a rebuttal, or upgrade paired_source. '
    'Use needs_evidence only when a defensible conditional check cannot yet be formulated, specifying '
    'the exact missing information. Do not relax factual, mechanism, scope or source validation.'
)


def category(q):
    if q.get('recovery_epoch', {}).get('original_status', q['status']) == 'needs_evidence': return 'needs_evidence'
    reason = q.get('reason', '')
    if reason.startswith('结构或来源校验未通过'): return 'validation'
    if reason.startswith('程序重新入队'): return 'coverage'
    if reason.startswith('API 失败'): return 'api'
    return 'other'


def select_pilot(queue):
    groups = defaultdict(list)
    for cid, q in sorted(queue.items()):
        if q['status'] in ['unresolved', 'needs_evidence']: groups[category(q)].append(cid)
    # A diagnostic batch, not a scientific comparison: include each failure category.
    selected = [cid for group in sorted(groups) for cid in groups[group][:20]]
    return selected, {cid: ('openai' if i % 2 == 0 else 'local') for i, cid in enumerate(selected)}


def read_db(root):
    with sqlite3.connect(root/'curation.sqlite3') as db:
        queue = {cid: json.loads(v) for cid, v in db.execute('SELECT id,value FROM queue')}
        state = dict(json.loads(db.execute("SELECT value FROM meta WHERE key='state'").fetchone()[0]),
                     rules={rid: json.loads(v) for rid, v in db.execute('SELECT id,value FROM rules')})
    return state, queue


def available_candidates(queue, provider, claimed, assist_local=False):
    pending = {cid: q for cid, q in queue.items()
               if cid not in claimed and q['status'] in ['pending', 'deferred']}
    def owner(q):
        first = q['recovery_epoch']['first_provider']
        last = q.get('recovery_last_provider', first)
        return first if q['attempts'] == 0 else ('local' if last == 'openai' else 'openai')
    preferred = {cid: q for cid, q in pending.items() if owner(q) == provider}
    if preferred or provider != 'openai' or not assist_local: return preferred
    # Take only unclaimed first visits: in-flight work and provider-switch retries keep their owner.
    return {cid: q for cid, q in pending.items() if q['attempts'] == 0 and owner(q) == 'local'}


def prepare(root, source):
    if (root/'RECOVERY.json').exists(): return s.read(root/'RECOVERY.json')
    s.require(s.read(source/'progress.json')['run_state'] == 'completed', 'Source is still running')
    s.require(s.read(source/'AUDIT.json')['check'] == 'passed', 'Source audit missing')
    root.mkdir(parents=True, exist_ok=True)
    s.require(not (root/'curation.sqlite3').exists(), 'Partial preparation needs reconciliation')
    baseline = root/'baseline'; baseline.mkdir()
    names = ['manifest.json', 'config.json', 'parallel_curation.json', 'FROZEN.json', 'AUDIT.json',
             'progress.json', 'queue.json', 'rule_library.json', 'jobs.json', 'eligibility.json',
             'extraction_failures.json', 'extraction_summary.json', 'review_exclusions.json']
    if (source/'retry_allowances.json').exists(): names.append('retry_allowances.json')
    for name in names: shutil.copyfile(source/name, baseline/name)
    for name in ['inputs', 'cases', 'candidates.json']: (root/name).symlink_to(source/name)
    for name in ['jobs.json', 'eligibility.json', 'extraction_failures.json', 'extraction_summary.json',
                 'review_exclusions.json']: shutil.copyfile(source/name, root/name)
    if (source/'retry_allowances.json').exists():
        shutil.copyfile(source/'retry_allowances.json', root/'retry_allowances.json')
    (root/'updates').mkdir()
    for old in (source/'updates').glob('*.json'): (root/'updates'/old.name).symlink_to(old)
    with sqlite3.connect('file:'+str(source/'curation.sqlite3')+'?mode=ro', uri=True) as src, \
            sqlite3.connect(root/'curation.sqlite3') as dest: src.backup(dest)
    state, queue = read_db(root)
    targets = sorted(cid for cid, q in queue.items() if q['status'] in ['unresolved', 'needs_evidence'])
    pilot, assignments = select_pilot(queue)
    assignments.update({cid: ('openai' if i % 2 == 0 else 'local')
                        for i, cid in enumerate(cid for cid in targets if cid not in assignments)})
    pilot_set = set(pilot)
    with sqlite3.connect(root/'curation.sqlite3') as db:
        # Request caches belong to the new root; inherited task IDs must not mask new checkpoints.
        db.execute("DELETE FROM meta WHERE key LIKE 'parallel_task/%'")
        for cid in targets:
            q = queue[cid]
            q['recovery_epoch'] = dict(original_status=q['status'], original_attempts=q['attempts'],
                original_history_length=len(q['history']), original_reason=q['reason'],
                first_provider=assignments[cid], budget=2)
            q['attempts'] = 0
            if cid in pilot_set: q['status'] = 'pending'
            db.execute('UPDATE queue SET value=? WHERE id=?', (json.dumps(q, ensure_ascii=False), cid))
    config = s.read(source/p.CONFIG)
    config.update(created_at=s.now(), updated_at=s.now(), baseline_progress='baseline/new_usage_zero.json',
                  recovery_runner_sha256=s.sha(__file__), migration_record='RECOVERY.json')
    config['providers']['deepseek']['paused'] = True
    s.write(root/p.CONFIG, config)
    s.write(baseline/'new_usage_zero.json', dict(usage={}, attempts=0, failed_finished_attempts=0,
                                               attempts_without_returned_usage=0))
    manifest = s.read(source/'manifest.json')
    manifest['parallel_curation_sha256'] = s.sha(root/p.CONFIG)
    manifest['recovery_source_root'] = str(source)
    s.write(root/'manifest.json', manifest)
    s.write(root/'config.json', s.read(source/'config.json'))
    record = dict(created_at=s.now(), source_root=str(source), stage='pilot100',
        source_files={name: s.sha(source/name) for name in names},
        source_candidate_sha256=s.sha(source/'candidates.json'), runner_sha256=s.sha(__file__),
        inherited_runner_sha256=s.sha(p.__file__), protocol_hashes=f.hashes(),
        original_version=state['version'], target_ids=targets, pilot_ids=pilot,
        target_categories=dict(Counter(category(queue[cid]) for cid in targets)),
        additional_visits_per_target=2, original_history_retained=True,
        providers=config['providers'], scientific_accuracy_verified=False)
    s.write(root/'RECOVERY.json', record)
    s.write(root/'summary.json', dict(stage='pilot100', complete=False, source_root=str(source),
        recovery_targets=len(targets), pilot_candidates=len(pilot), usage_includes_original_run=False))
    (root/'SCOPE.md').write_text(
        '# LLM 领域未解决候选恢复\n\n仅恢复原版 unresolved / needs_evidence；原版冻结结果不改动。\n'
        'OpenAI gpt-6-luna / medium / 3 并发，本地 Qwen / 3 并发，DeepSeek 暂停。\n'
        '先处理分层 100 条，通过结构、来源与预算审计后自动继续其余目标。\n'
        '每个目标本轮最多两次有效访问；原始访问次数与完整 history 保留在恢复台账。\n'
        '补取原稿精确片段，版本与历史初审未对齐；不自动升级 paired_source。\n'
        '本轮用量独立记账；原始抽取不重跑，无训练、无对照、无新增审稿。\n')
    return record


class RecoveryTasks:
    def __init__(self, root, record):
        self.root = root; self.source = Path(record['source_root'])
        self.original_version = record.get('original_version', 0)
        self.assist_local = record.get('openai_assists_local', False)

    @lru_cache(maxsize=128)
    def diagnostics(self, version):
        origin = self.root if version > self.original_version else self.source
        path = origin/f'updates/{version:06d}.json'
        if not path.exists(): return []
        update = s.read(path); errors = []
        if update.get('inference_error'): errors.append(update['inference_error'])
        if update.get('parallel_task_id'):
            folder = p.request_folder(origin, dict(provider=update['provider'], task_id=update['parallel_task_id']))
        else: folder = origin/f'requests/curate/{version:06d}'
        if (folder/'recovery.json').exists():
            recovery = s.read(folder/'recovery.json').get('recovery', {})
            errors.extend(item['error'] for item in recovery.get('quarantined_operations', []))
        attempts = sorted(folder.glob('attempt_*.json'))
        if attempts:
            error = s.read(attempts[-1]).get('error')
            if error: errors.append(error)
        concise = []
        for error in errors:
            prefix = 'Rejected curation operations: '
            if error.startswith(prefix):
                try:
                    concise.extend(item['operation']['type']+': '+item['error']
                                   for item in json.loads(error[len(prefix):]))
                    continue
                except (ValueError, KeyError): pass
            concise.append(error)
        return list(dict.fromkeys(e if len(e) <= 450 else e[:220]+' … '+e[-220:] for e in concise))[:3]

    @lru_cache(maxsize=8)
    def manuscript(self, pid):
        row = s.read(self.source/f'inputs/{pid}.json')
        text = s.paper_text(dict(object_path=row['manuscript_path'], sha256=row['manuscript_sha256']))
        return row, text

    @lru_cache(maxsize=16)
    def evidence(self, cid):
        c = s.read(self.source/'candidates.json')[cid] if not hasattr(self, 'candidates') else self.candidates[cid]
        row, text = self.manuscript(c['paper_id'])
        query = ' '.join(c['scope_terms'])+' '+c['observation']
        passages = s.pack(text, 'REC'+str(c['paper_id']), 850, query=query, indexed_headings=row['headings'])
        for span in passages:
            s.require(text[span['char_start']:span['char_end']] == span['text'], 'Evidence span changed')
        units = [u for u in row['review_units'] if u['passage_id'] in c['review_evidence_ids']]
        pack = dict(candidate_id=cid, manuscript_path=row['manuscript_path'],
            manuscript_sha256=row['manuscript_sha256'], manuscript_version_date_verified=False,
            review_units=units, manuscript_passages=passages,
            meaning='Exact current-source excerpts; historical alignment and paired_source unchanged')
        s.write(self.root/'evidence'/f'{cid}.json', pack)
        return pack

    def __call__(self, task_id, provider, state, queue, candidates, retrieval, claimed):
        self.candidates = candidates
        available = available_candidates(queue, provider, claimed, self.assist_local)
        if not available: return None
        seed = min(available, key=lambda cid: (available[cid]['attempts'], cid))
        family = candidates[seed]['mechanism_family']
        same = {cid for cid in available if cid != seed and candidates[cid]['mechanism_family'] == family}
        focus = [seed]+retrieval.rank([seed], same, 1)
        view = dict(state, rules={rid: r for rid, r in state['rules'].items()
                                  if r['status'] != 'deprecated' and r['mechanism_family'] == family})
        data, _ = f.curator_request(view, {cid: available[cid] for cid in focus}, candidates, retrieval)
        focus = data['focus_ids']
        data['global_neighbors'] = [c for c in data['global_neighbors'] if c['mechanism_family'] == family][:2]
        # Exact existing citations take priority over broad similarity when reconciling coverage.
        data['existing_rules'].sort(key=lambda r: (-len(set(r['candidate_ids']) & set(focus)), r['rule_id']))
        data['instruction'] += ' '+POLICY
        data['recovery_context'] = [dict(candidate_id=cid, **queue[cid]['recovery_epoch'],
            current_reason=queue[cid]['reason'], current_visit=queue[cid]['attempts']+1,
            prior_batch_validation_errors=self.diagnostics(queue[cid]['history'][-1]['version'])
                if queue[cid]['history'] else []) for cid in focus]
        data['source_evidence'] = [deepcopy(self.evidence(cid)) for cid in focus]
        while True:
            schema = f.curate_schema(focus, [r['rule_id'] for r in data['existing_rules']])
            allowed = {c['candidate_id'] for c in data['candidates']+data['global_neighbors']}
            allowed.update(cid for rule in data['existing_rules'] for cid in rule['candidate_ids'])
            operation = schema['properties']['operations']['items']['properties']
            operation['rules']['items']['properties']['candidate_ids']['items'] = dict(type='string', enum=sorted(allowed))
            operation['rules']['items']['properties']['mechanism_family']['enum'] = [family]
            operation['evidence_candidate_ids']['items'] = dict(type='string', enum=sorted(allowed))
            size = s.tokens(s.SYSTEM)+s.tokens(dict(data=data, schema=schema))+300
            if size < f.LIMITS['curate_input']-300: break
            if data['global_neighbors']: data['global_neighbors'].pop()
            elif len(data['existing_rules']) > 1: data['existing_rules'].pop()
            elif any(e['manuscript_passages'] for e in data['source_evidence']):
                max(data['source_evidence'], key=lambda e: len(e['manuscript_passages']))['manuscript_passages'].pop()
            else: raise ValueError('Recovery source evidence exceeds budget; retain task for inspection')
        visible = {r['rule_id'] for r in data['existing_rules']}
        return dict(task_id=task_id, provider=provider, status='dispatched', created_at=s.now(),
            assisted_local=provider == 'openai' and any(queue[cid]['attempts'] == 0 and
                queue[cid]['recovery_epoch']['first_provider'] == 'local' for cid in focus),
            data=data, schema=schema, snapshot=dict(version=state['version'], next_id=state['next_id'],
                rules={rid: state['rules'][rid] for rid in visible}),
            queue={cid: dict(queue[cid], recovery_last_provider=provider) for cid in focus})


class RecoveryProgress(p.Progress):
    def save(self, state, queue, lifecycle='running', error=None, force=False, conflicts=0):
        before = self.last_save
        super().save(state, queue, lifecycle, error, force, conflicts)
        if self.last_save == before: return
        record = s.read(self.root/'RECOVERY.json')
        selected = record['pilot_ids'] if record['stage'] == 'pilot100' else record['target_ids']
        done = sum(queue[cid]['attempts'] > 0 and queue[cid]['status'] not in ['pending', 'deferred']
                   for cid in selected)
        progress = s.read(self.root/'progress.json')
        progress.update(recovery_stage=record['stage'], recovery_target_total=len(record['target_ids']),
                        recovery_active_scope=len(selected), recovery_completed=done,
                        recovery_remaining=len(selected)-done, usage_includes_original_run=False)
        s.write(self.root/'progress.json', progress)
        with (self.root/'PROGRESS.md').open('a') as out:
            out.write(f'\n恢复阶段：{record["stage"]}；当前恢复范围 {done}/{len(selected)}；'
                      f'全部目标 {len(record["target_ids"])}；用量仅统计本轮恢复。\n')
        summary = s.read(self.root/'summary.json')
        summary.update(recovery_stage=record['stage'], recovery_target_total=len(record['target_ids']),
                       recovery_completed=done, recovery_active_scope=len(selected),
                       usage_includes_original_run=False)
        s.write(self.root/'summary.json', summary)


def verify(root, record, pilot=False):
    source = Path(record['source_root']); state, queue = read_db(root)
    original = s.read(root/'baseline/queue.json'); candidates = s.read(root/'candidates.json')
    for name, digest in record['source_files'].items():
        s.require(s.sha(source/name) == digest, 'Frozen source changed: '+name)
    s.require(s.sha(root/'candidates.json') == record['source_candidate_sha256'], 'Candidate source changed')
    s.require(f.hashes() == record['protocol_hashes'], 'Scientific protocol changed')
    targets = set(record['target_ids']); outcomes = Counter(); visits = 0
    for cid, q in queue.items():
        if cid not in targets:
            s.require(q['status'] == original[cid]['status'] and q['history'] == original[cid]['history'],
                      'A non-target candidate was reprocessed')
            continue
        epoch = q['recovery_epoch']; old = original[cid]
        s.require(q['history'][:epoch['original_history_length']] == old['history'], 'Original history changed')
        s.require(epoch['original_attempts'] == old['attempts'] and q['attempts'] <= 2, 'Recovery budget changed')
        s.require(len(q['history'])-len(old['history']) == q['attempts'], 'Recovery visits miscounted')
        visits += q['attempts']
        if not pilot or cid in record['pilot_ids']: outcomes[q['status']] += 1
    active = {rid: rule for rid, rule in state['rules'].items() if rule['status'] != 'deprecated'}
    for cid, q in queue.items():
        if q['status'] in ['incorporated', 'duplicate']:
            s.require(q['rule_ids'] and all(rid in active and cid in active[rid]['candidate_ids']
                                          for rid in q['rule_ids']), 'False rule coverage')
    for rid, rule in active.items():
        s.require(all(candidates[cid]['mechanism_family'] == rule['mechanism_family']
                      for cid in rule['candidate_ids']), 'Mixed mechanism rule')
        s.require(s.enrich(rule, candidates, rid, rule['version'])['status'] == rule['status'], 'Support upgraded')
    result = dict(checked_at=s.now(), check='passed', stage='pilot100' if pilot else 'full_recovery',
        outcomes=dict(outcomes), new_valid_visits=visits, original_source_unchanged=True,
        original_histories_retained=True, additional_visits_per_target=2,
        unchanged_candidate_pairing=True, scientific_accuracy_verified=False)
    s.write(root/('PILOT_AUDIT.json' if pilot else 'RECOVERY_AUDIT.json'), result)
    return result


def run_epoch(args, record):
    """Use the frozen inference/transaction helpers with the authorized provider capacities."""
    root = args.root; config = s.read(root/p.CONFIG)
    s.require(config['runner_sha256'] == s.sha(p.__file__), 'Inherited runner changed')
    s.require(config['recovery_runner_sha256'] == s.sha(__file__), 'Recovery runner changed')
    s.require(config['providers'] == record['providers'], 'Provider authorization changed')
    limit = config['providers']['openai']['concurrency']
    s.require(limit in [3, 4] and config['providers']['local']['concurrency'] == 3 and
              config['providers']['deepseek']['paused'], 'Unauthorized provider capacities')
    manifest = p.area.prepare(SimpleNamespace(root=root, source_root=s.SOURCE, concurrency=limit))
    s.require(manifest['parallel_curation_sha256'] == s.sha(root/p.CONFIG), 'Configuration seal changed')
    s.require(config['helper_hashes'] == {name: s.sha(s.REPO/name) for name in config['helper_hashes']},
              'Frozen helper changed')
    s.require(not s.read(root/'extraction_failures.json'), 'Extraction failures remain')
    candidates = s.read(root/'candidates.json'); db = f.state_db(root)
    s.require(db.execute("SELECT value FROM meta WHERE key='candidate_hash'").fetchone()[0] == s.digest(candidates),
              'Candidate pool changed')
    state, queue = read_db(root)
    creds = p.taxonomy.credentials(args.auth)['deepseek']
    clients = dict(openai=p.OpenAIClient(SimpleNamespace(root=root, auth=args.auth, concurrency=limit)),
        deepseek=p.ChatClient(root, creds, config['providers']['deepseek']),
        local=p.ChatClient(root, dict(base_url=config['providers']['local']['base_url'], key='local'),
                           config['providers']['local'], 'local'))
    stop = threading.Event()
    def pause(signum, frame): stop.set()
    signal.signal(signal.SIGTERM, pause); signal.signal(signal.SIGINT, pause)
    maker = RecoveryTasks(root, record); retrieval = f.Retrieval(candidates)
    progress = RecoveryProgress(root, config, clients, queue)
    folder = root/'parallel_tasks'; folder.mkdir(exist_ok=True)
    committed = {key.split('/', 1)[1] for key, value in db.execute(
        "SELECT key,value FROM meta WHERE key LIKE 'parallel_task/%'") if value == 'committed'}
    saved = [s.read(path) for path in sorted(folder.glob('*/task.json'))]
    backlog = p.restore_backlog(root, saved, committed, config, queue)
    claimed = {cid for task in backlog for cid in task['data']['focus_ids']}
    serial = max((int(t['task_id'][1:]) for t in saved), default=0)
    inflight = {}; conflicts = 0; lifecycle = 'running'; last_error = None
    progress.save(state, queue, force=True)
    try:
        with ThreadPoolExecutor(max_workers=sum(p.provider_capacity(config, name) for name in clients)) as pool:
            while True:
                if not stop.is_set():
                    for provider, client in clients.items():
                        used = sum(t['provider'] == provider for t in inflight.values())
                        while used < p.provider_capacity(config, provider) and not client.stop.is_set():
                            task = next((t for t in backlog if t['provider'] == provider), None)
                            if task: backlog.remove(task)
                            else:
                                task = maker(f'p{serial+1:06d}', provider, state, queue, candidates, retrieval, claimed)
                                if task is None: break
                                serial += 1
                                s.require(serial < manifest['max_curation_requests'], 'Request bound exhausted')
                                claimed.update(task['data']['focus_ids']); s.write(folder/task['task_id']/'task.json', task)
                            inflight[pool.submit(p.infer, root, task, client, candidates)] = task; used += 1
                            progress.save(state, queue, conflicts=conflicts)
                if not inflight:
                    if not stop.is_set():
                        s.require(not any(q['status'] in ['pending', 'deferred'] for q in queue.values()),
                                  'No enabled provider can process remaining queue')
                    break
                done, _ = wait(inflight, timeout=1, return_when=FIRST_COMPLETED)
                for future in done:
                    task = inflight.pop(future); result = future.result()
                    claimed.difference_update(task['data']['focus_ids'])
                    if result.get('provider_stopped'):
                        task.update(status='provider_stopped', error=result['error'])
                        last_error = task['provider']+': '+result['error']
                    else:
                        delta = result.get('delta') or dict(operations=[], decisions=[dict(candidate_id=cid,
                            status='deferred', rule_refs=[], reason='API 失败，保留 unknown：'+result.get('error', '')[:160])
                            for cid in task['data']['focus_ids']], deferred_candidate_ids=task['data']['focus_ids'])
                        applied = p.commit(root, db, state, queue, candidates, task, delta, result.get('error'))
                        task.update(status='committed' if applied else 'conflict', finished_at=s.now())
                        if not applied: conflicts += 1
                    s.write(folder/task['task_id']/'task.json', task)
                progress.save(state, queue, conflicts=conflicts)
        if stop.is_set(): lifecycle = 'paused'
        else:
            s.write(root/'rule_library.json', state); s.write(root/'queue.json', queue); p.area.export(root, state)
            p.area.validate_scope(root)
            audit = p.area.audit(SimpleNamespace(root=root, source_root=s.SOURCE, concurrency=limit), manifest)
            audit.update(providers=config['providers'],
                **{name: p.audit_chat(root, config, name) for name in clients if name != 'openai'})
            s.write(root/'AUDIT.json', audit)
            s.write(root/'FROZEN.json', dict(area=p.area.AREA, library_hash=s.digest(state), frozen_at=s.now(),
                status='llm_area_multi_provider_mechanisms_unadjudicated', scientific_accuracy_verified=False))
            lifecycle = 'completed'
    except BaseException as error:
        lifecycle = 'failed'; last_error = str(error); raise
    finally:
        progress.save(state, queue, lifecycle, last_error, force=True, conflicts=conflicts)
        if lifecycle == 'completed':
            summary = s.read(root/'summary.json'); summary.update(complete=True, stage='frozen'); s.write(root/'summary.json', summary)
        db.close()


def run(root, auth):
    record = s.read(root/'RECOVERY.json')
    s.require(record['runner_sha256'] == s.sha(__file__), 'Recovery code changed; migrate explicitly')
    s.require(record['inherited_runner_sha256'] == s.sha(p.__file__), 'Inherited runner changed')
    args = SimpleNamespace(root=root, auth=auth)
    while record['stage'] != 'completed':
        stage = record['stage']
        if not (root/'FROZEN.json').exists(): run_epoch(args, record)
        if not (root/'FROZEN.json').exists(): return  # Graceful pause or rejected provider.
        result = verify(root, record, pilot=stage == 'pilot100')
        if stage == 'pilot100':
            s.require(sum(result['outcomes'].values()) == len(record['pilot_ids']), 'Pilot accounting incomplete')
            s.require(result['outcomes'].get('incorporated', 0)+result['outcomes'].get('duplicate', 0) > 0,
                      'Pilot recovered no rule coverage; inspect before expansion')
            saved = root/'pilot100'; saved.mkdir(exist_ok=True)
            for name in ['FROZEN.json', 'AUDIT.json', 'summary.json', 'queue.json', 'rule_library.json',
                         'PILOT_AUDIT.json', 'progress.json']: shutil.copyfile(root/name, saved/name)
            # Independent epoch accounting: activate only targets held out of the pilot.
            with sqlite3.connect(root/'curation.sqlite3') as db:
                for cid, q in read_db(root)[1].items():
                    if cid in record['target_ids'] and cid not in record['pilot_ids']:
                        s.require(q['attempts'] == 0, 'Held target was already visited')
                        q['status'] = 'pending'
                        db.execute('UPDATE queue SET value=? WHERE id=?', (json.dumps(q, ensure_ascii=False), cid))
            (root/'FROZEN.json').unlink()
            record.update(stage='full_recovery', pilot_passed_at=s.now(), pilot_outcomes=result['outcomes'])
        else:
            record.update(stage='completed', completed_at=s.now(), outcomes=result['outcomes'])
            frozen = s.read(root/'FROZEN.json'); frozen.update(recovery_audit='RECOVERY_AUDIT.json',
                source_run=str(record['source_root']), additional_visits_per_target=2)
            s.write(root/'FROZEN.json', frozen)
        s.write(root/'RECOVERY.json', record)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=['prepare', 'run'])
    parser.add_argument('--root', type=Path, default=ROOT)
    parser.add_argument('--source', type=Path, default=SOURCE)
    parser.add_argument('--auth', type=Path, default=Path.home()/'auth')
    args = parser.parse_args(); args.root.mkdir(parents=True, exist_ok=True)
    with (args.root/'run.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        record = prepare(args.root, args.source)
        if args.command == 'run': run(args.root, args.auth)
        else: print(json.dumps(dict(targets=len(record['target_ids']), pilot=len(record['pilot_ids']),
                                   stage=record['stage']), ensure_ascii=False))


if __name__ == '__main__': main()
