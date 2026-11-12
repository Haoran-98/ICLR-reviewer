#!/usr/bin/env python3
"""Real DKTA/LLM comparison: pinned ACM projection, matched LLM, blind proxy judging."""
import argparse
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
import hashlib
import json
from pathlib import Path
import time
import threading
from types import SimpleNamespace
import xml.etree.ElementTree as ET

import numpy as np

import s4_dkta as dkta
import s4_llm_taxonomy as s4


ROOT = Path('/data_big/iclr-s4/experiments/dkta4060_200_v1')
HISTORICAL = ('historical_deepseek', 'historical_openai', 'historical_qwen')


def core_methods(args):
    papers = s4.read(args.root / 'manifest.json')['papers_manifest']
    return (*dkta.METHODS, *(f'llm_{provider}' for provider in ('deepseek', 'openai') if all(
        (args.root / 'fused' / f'llm_{provider}' / f'{p["paper_id"]}.json').exists() for p in papers)))


def acm(args):
    path = args.root / 'assets' / 'acm_ccs_mirror.xml'
    raw = path.read_bytes()
    blob = hashlib.sha1(b'blob ' + str(len(raw)).encode() + b'\0' + raw).hexdigest()
    if blob != '99a4e9be680153e3f51c536b15d948140aa2a690':
        raise ValueError('ACM mirror blob differs from the two inspected public mirrors')
    ns = {'skos': 'http://www.w3.org/2004/02/skos/core#', 'rdf': 'http://www.w3.org/1999/02/22-rdf-syntax-ns#'}
    concepts = {}
    for item in ET.fromstring(raw).findall('.//skos:Concept', ns):
        cid = item.attrib['{' + ns['rdf'] + '}about']
        name = item.find('skos:prefLabel', ns).text.strip()
        parents = [x.attrib['{' + ns['rdf'] + '}resource'] for x in item.findall('skos:broader', ns)]
        concepts[cid] = {'name': name, 'parents': parents}

    def original_paths(cid, active=()):
        if cid in active:
            raise ValueError('Cycle in original ACM taxonomy')
        item = concepts[cid]
        if not item['parents']:
            return [[cid]]
        return [p + [cid] for parent in item['parents'] for p in original_paths(parent, (*active, cid))]

    projected = {}
    projections = []
    # Preserve original leaf depth: root / first branch / leaf, with skipped intermediates audited.
    # Equal concepts occurring in multiple levels get level-qualified IDs, not guessed levels.
    for cid in concepts:
        for chain in original_paths(cid):
            if len(chain) < 3:
                continue
            selected = [chain[0], chain[1], chain[-1]]
            ids = [f'acm:{level}:{original}' for level, original in enumerate(selected, 1)]
            for level, (node_id, original) in enumerate(zip(ids, selected), 1):
                node = projected.setdefault(node_id, {'id': node_id, 'name': concepts[original]['name'],
                    'description': 'ACM CCS concept: ' + concepts[original]['name'],
                    'level': level, 'parent_ids': [], 'source_concept_id': original})
                if level > 1 and ids[level - 2] not in node['parent_ids']:
                    node['parent_ids'].append(ids[level - 2])
            projections.append({'original_path': chain, 'projected_path': ids})
    taxonomy = {'version': 'acm_ccs_2012_root_branch_descendant_v1', 'source': {
        'kind': 'ACM_CCS_2012_public_mirror', 'official_endpoint_http': 403,
        'mirror': 'https://github.com/filpia/acm-computing_classification_system',
        'independent_matching_mirror': 'https://github.com/cli99/acm-ccs',
        'git_blob_sha1': blob, 'sha256': hashlib.sha256(raw).hexdigest(),
        'projection': 'original root / first branch / each deeper descendant; skipped intermediate nodes retained in audit',
        'llm_expansion': False}, 'nodes': list(projected.values())}
    paths = dkta.taxonomy_paths(taxonomy)
    s4.write(args.root / 'assets' / 'acm_projection.json', {'projections': projections, 'original_concepts': concepts})
    s4.write(args.root / 'assets' / 'taxonomy_acm.json', taxonomy)
    s4.log('acm_imported', concepts=len(concepts), nodes=len(projected), paths=len(paths))


def matched_llm(args):
    manifest = s4.read(args.root / 'manifest.json')
    provider = args.baseline_provider
    config = s4.credentials(args.auth)[provider]
    folder = 'matched_llm' if provider == 'deepseek' else 'matched_llm_openai'

    def one(entry):
        pid = entry['paper_id']
        paper = dkta.load_paper(args, entry)
        payload = {'instruction': 'Extract at most 20 ranked scientific research keyphrases (present and absent allowed) '
            'and at most 5 complete freely named research-domain paths for THIS paper. '
            'Use the same evidence: ONLY its title and abstract. L1 broad domain, L2 task/method family, '
            'L3 concrete research problem or technical route. Each child scope must fit its parent. '
            'Return {keywords:["..."],paths:[{L1:"...",L2:"...",L3:"..."}]}. '
            'Do not force unsupported branches. No conference labels, author keywords, or outside paper sections.',
            'title': paper['title'], 'abstract': paper['abstract']}
        target = args.root / folder / f'{pid}.json'
        if target.exists():
            value = s4.read(target)
            if value['input_hash'] != paper['input_hash'] or value['model'] != config['model']:
                raise ValueError('Matched LLM input/model changed; choose a new experiment root')
        else:
            started = time.monotonic()
            result = s4.request_job(args, provider, 'dkta_baseline', payload)
            value = {**result, 'paper_id': pid, 'input_hash': paper['input_hash'], 'model': config['model'],
                     'seconds': time.monotonic() - started, 'created_at': s4.now()}
            s4.write(target, value)
        phrases = [{'phrase': k} for k in value['keywords']]
        s4.write(args.root / 'fused' / f'llm_{provider}' / f'{pid}.json', {
            'phrases': dkta.rrf({f'llm_{provider}': phrases}), 'input_hash': paper['input_hash']})
        s4.log('matched_llm_complete', paper_id=pid)

    errors = []
    with ThreadPoolExecutor(max_workers=config['concurrency']) as executor:
        pending = {executor.submit(one, p): p['paper_id'] for p in manifest['papers_manifest'][:args.limit]}
        for future in as_completed(pending):
            try:
                future.result()
            except Exception as error:
                errors.append({'paper_id': pending[future], 'error': type(error).__name__, 'detail': str(error)})
    s4.write(args.root / f'{folder}_status.json', {'failures': errors, 'model': config['model'], 'created_at': s4.now()})
    if errors:
        raise RuntimeError(f'{len(errors)} matched LLM papers failed; successful results retained')


def recover_arbitration(args):
    """Complete only retained 402 failures with a separately recorded configured provider."""
    initial = s4.read(args.root / 'alignment_status.json')
    audit_path = args.root / 'alignment_recovery.json'
    previous = s4.read(audit_path, {})
    indexed = s4.read(args.root / 'taxonomy_index.json')
    taxonomy = s4.read(args.root / 'taxonomy.json')
    by_path = {p['id']: p for p in indexed['paths']}
    primary = s4.credentials(args.auth)['deepseek']
    fallback = s4.credentials(args.auth)['openai']
    # Match retained payloads to papers without re-encoding or changing thresholds.
    jobs = {s4.digest(v['payload']): v for p in (args.root / 'jobs').glob('*.json')
            if (v := s4.read(p))['kind'] == 'dkta_arbitrate' and v['provider'] == 'deepseek'}
    stopped, errors, completed = threading.Event(), [], []

    def one(path, row):
        # Original arbitration jobs carry exact title/abstract and keyword evidence.
        matching = [job for job in jobs.values() if job['payload']['keyphrase'] == row['phrase']
                    and [p['id'] for p in job['payload']['candidates']] == row['candidate_path_ids']]
        # Keyword+candidate IDs can repeat across documents; cache signature includes input hash.
        selected = []
        for job in matching:
            payload = job['payload']
            for entry in manifest['papers_manifest']:
                paper = inputs[entry['paper_id']]
                sentence, _ = dkta.context(paper['text'], row['phrase'])
                signature = s4.digest([run_signature, entry['input_hash'], row['phrase'], sentence])
                if path.stem == signature and payload == dkta.arbitration_payload(
                        paper, row['phrase'], [by_path[i] for i in row['candidate_path_ids']], taxonomy):
                    selected.append(job)
                    break
        if len(selected) != 1:
            raise ValueError(f'Cannot uniquely match original arbitration job for {path.name}')
        job = selected[0]
        history = list((args.root / 'attempts' / job['job_id']).glob('*.json'))
        if not any(s4.read(p).get('http_status') == 402 for p in history):
            raise ValueError('Fallback requires a retained primary HTTP 402, not a fresh budget')
        remaining = s4.MAX_ATTEMPTS - len(history)
        if remaining <= 0:
            raise ValueError('Original decision has no attempts remaining')
        if stopped.is_set():
            return False
        bounded = SimpleNamespace(**vars(args), max_attempts=remaining)
        try:
            value = s4.request_job(bounded, 'openai', 'dkta_arbitrate', job['payload'])
        except s4.JobFailure as error:
            if str(error) in ('http_401', 'http_402', 'http_403'):
                stopped.set()
            raise
        row.update(path_ids=value['selected_path_ids'], state='arbitrated' if value['selected_path_ids'] else 'unmatched',
                   arbitration={'provider': 'openai', 'model': fallback['model'], **value},
                   primary_failure={'provider': 'deepseek', 'model': primary['model'], 'http_status': 402,
                                    'job_id': job['job_id'], 'attempts_used': len(history)},
                   fallback_attempt_limit=remaining)
        s4.write(path, row)
        s4.log('arbitration_recovered', cache=path.stem, provider='openai')
        return True

    manifest = s4.read(args.root / 'manifest.json')
    inputs = {entry['paper_id']: dkta.load_paper(args, entry) for entry in manifest['papers_manifest']}
    run_signature = s4.digest([indexed['signature'], .5, .7, 'deepseek', primary['model'], 3, 2, 5])
    pending = [(p, row) for p in (args.root / 'alignment_cache').glob('*.json')
               if (row := s4.read(p))['state'] == 'pending_arbitration']
    with ThreadPoolExecutor(max_workers=fallback['concurrency']) as executor:
        futures = {executor.submit(one, p, row): p.name for p, row in pending}
        for future in as_completed(futures):
            try:
                if future.result():
                    completed.append(futures[future])
            except Exception as error:
                errors.append({'cache': futures[future], 'error': type(error).__name__, 'detail': str(error)})
    s4.write(audit_path, {'initial_status': previous.get('initial_status', initial), 'fallback_model': fallback['model'],
        'created_at': s4.now(), 'recovered_this_run': len(completed), 'errors': errors,
        'cross_provider_attempt_cap': s4.MAX_ATTEMPTS, 'thresholds_unchanged': True})
    if errors or stopped.is_set():
        raise RuntimeError('Arbitration recovery incomplete; successful cache entries retained')


def method_paths(args, pid, method):
    if method in dkta.METHODS or method.endswith('_aligned'):
        assignment_method = method.removesuffix('_aligned')
        result = s4.read(args.root / 'assignments' / assignment_method / f'{pid}.json')
        taxonomy = s4.read(args.root / 'taxonomy.json')
        names = {n['id']: n['name'] for n in taxonomy['nodes']}
        seen, paths = set(), []
        for path in result['paths']:
            leaf = path['node_ids'][-1]
            if leaf not in seen:
                seen.add(leaf)
                paths.append([names[i] for i in path['node_ids']])
        return paths[:5]
    if method in ('llm_deepseek', 'llm_openai'):
        folder = 'matched_llm' if method == 'llm_deepseek' else 'matched_llm_openai'
        return [[p[k] for k in ('L1', 'L2', 'L3')] for p in s4.read(args.root / folder / f'{pid}.json')['paths']]
    provider = method.removeprefix('historical_')
    generated = s4.read(args.source_root / 'generated' / provider / f'{pid}.json')
    levels = {level: {n['node_id']: n for n in generated[str(level)] if n['status'] == 'candidate'} for level in (1, 2, 3)}
    result = []
    for leaf in levels[3].values():
        middle = levels[2][leaf['parent_id']]
        root = levels[1][middle['parent_id']]
        result.append([root['name'], middle['name'], leaf['name']])
    return result[:5]


def judge(args):
    manifest = s4.read(args.root / 'manifest.json')
    original = s4.read(args.source_root / 'manifest.json')
    years = {p['paper_id']: p['year'] for p in original['papers']}
    buckets = defaultdict(list)
    for entry in manifest['papers_manifest']:
        buckets[years[entry['paper_id']]].append(entry)
    for rows in buckets.values():
        rows.sort(key=lambda e: s4.digest([1701, e['paper_id']]))
    selected = []
    while len(selected) < min(args.judge_papers, len(manifest['papers_manifest'])):
        for year in sorted(buckets):
            if buckets[year] and len(selected) < args.judge_papers:
                selected.append(buckets[year].pop(0))
    s4.write(args.root / 'judge_sample.json', {'seed': 1701, 'stratification': 'year_round_robin', 'papers': selected})

    def one(entry):
        pid = entry['paper_id']
        paper = dkta.load_paper(args, entry)
        candidates, mapping = [], {}
        methods = core_methods(args)
        aligned = tuple(m + '_aligned' for m in methods if m.startswith('llm_'))
        for method in (*methods, *aligned, *HISTORICAL):
            for position, path in enumerate(method_paths(args, pid, method)):
                cid = s4.digest([1701, pid, method, position])[:20]
                candidates.append({'id': cid, 'L1': path[0], 'L2': path[1], 'L3': path[2]})
                mapping[cid] = method
        candidates.sort(key=lambda row: row['id'])
        payload = {'instruction': 'Blindly evaluate EVERY anonymous candidate research path against ONLY this paper title/abstract. '
            'Do not infer model identity. relevant=true only if L3 is supported by the paper central research/contribution; '
            'a dataset/tool mentioned in passing is insufficient. parent_compatible checks semantic L3⊂L2⊂L1. '
            'specificity is 1 (very broad) to 5 (concrete technical problem). For relevant=true copy a short EXACT '
            'nonempty substring from paper_text as evidence_quote. Return {evaluations:[{id,relevant:boolean,'
            'parent_compatible:boolean,specificity:integer,evidence_quote:"...",rationale:"<=20 words"}]}.',
            'paper_text': paper['text'], 'candidates': candidates}
        value = s4.request_job(args, 'openai', 'dkta_quality', payload)
        s4.write(args.root / 'quality' / f'{pid}.json', {'paper_id': pid, 'mapping': mapping, **value,
                 'judge_model': s4.credentials(args.auth)['openai']['model'],
                 'historical_openai_self_source_bias_possible': True})
        s4.log('quality_complete', paper_id=pid)

    errors = []
    with ThreadPoolExecutor(max_workers=s4.credentials(args.auth)['openai']['concurrency']) as executor:
        futures = {executor.submit(one, entry): entry['paper_id'] for entry in selected}
        for future in as_completed(futures):
            try:
                future.result()
            except Exception as error:
                errors.append({'paper_id': futures[future], 'error': type(error).__name__, 'detail': str(error)})
    s4.write(args.root / 'judge_status.json', {'errors': errors, 'selected': len(selected), 'created_at': s4.now()})
    if errors:
        raise RuntimeError(f'{len(errors)} quality jobs failed; retained attempts keep their retry budget')


def proxy_scores(predicted, reference, top_k=10):
    # Exact case/token matching is an author-keyphrase proxy, never fine taxonomy gold.
    norm = lambda phrase: ' '.join(m[0].casefold() for m in dkta.WORD.finditer(phrase))
    guesses = {norm(p) for p in predicted[:top_k] if norm(p)}
    gold = {norm(p) for p in reference if norm(p)}
    overlap = len(guesses & gold)
    precision = overlap / top_k
    recall = overlap / len(gold) if gold else None
    f1 = 2 * precision * recall / (precision + recall) if recall and precision else 0.
    return {'P@10': precision, 'R@10': recall, 'F1@10': f1}


def confidence(values):
    values = np.asarray(values, dtype=float)
    if not len(values):
        return None
    rng = np.random.default_rng(1701)
    means = np.mean(values[rng.integers(len(values), size=(1000, len(values)))], axis=1)
    return {'mean': float(values.mean()), 'ci95': np.quantile(means, [.025, .975]).tolist()}


def report(args):
    manifest = s4.read(args.root / 'manifest.json')
    alignment = s4.read(args.root / 'alignment_status.json')
    judging = s4.read(args.root / 'judge_status.json')
    if alignment['pending_arbitration'] or alignment['errors'] or judging['errors']:
        raise ValueError('Comparison requires completed alignment and judging')
    sample_ids = [p['paper_id'] for p in s4.read(args.root / 'judge_sample.json')['papers']]
    quality_files = sorted((args.root / 'quality').glob('*.json'))
    if {s4.read(p)['paper_id'] for p in quality_files} != set(sample_ids):
        raise ValueError('Judged papers do not exactly match the frozen evaluation sample')
    taxonomy = s4.read(args.root / 'taxonomy.json')
    full_paths = dkta.taxonomy_paths(taxonomy)
    leaf_paths = defaultdict(set)
    for path in full_paths:
        leaf_paths[path['node_ids'][-1]].add(tuple(path['node_ids']))
    closure_checked, overflow_documents = 0, Counter()
    rows = defaultdict(list)
    for entry in manifest['papers_manifest']:
        pid = entry['paper_id']
        raw = s4.read(args.source_root / 'raw' / f'{pid}.json')
        refs = raw['metadata'].get('keywords') or []
        refs = refs if isinstance(refs, list) else refs.split(';')
        for method in core_methods(args):
            phrases = s4.read(args.root / 'fused' / method / f'{pid}.json')['phrases']
            values = proxy_scores([p['phrase'] for p in phrases], refs)
            paths = method_paths(args, pid, method + '_aligned' if method.startswith('llm_') else method)
            assignment = s4.read(args.root / 'assignments' / method / f'{pid}.json')
            included = {tuple(p['node_ids']) for p in assignment['paths']}
            for leaf in {p[-1] for p in included}:
                if not leaf_paths[leaf].issubset(included):
                    raise ValueError(f'Missing parent path: {method}/{pid}/{leaf}')
            if {n for p in included for n in p} != set(assignment['node_support']):
                raise ValueError(f'Assignment node support disagrees with paths: {method}/{pid}')
            closure_checked += 1
            overflow = assignment['topn_overflow']
            overflow_documents[method] += bool(overflow['L1'] or overflow['L2_by_parent'])
            folder = 'matched_llm_openai' if method == 'llm_openai' else 'matched_llm'
            extraction_path = (args.root / folder / f'{pid}.json') if method.startswith('llm_') else (
                args.root / 'keywords' / method / f'{pid}.json')
            timing = s4.read(extraction_path, {}) if method != 'dkta_rrf' else {}
            rows[method].append({'paper_id': pid, **values, 'has_reference': bool(refs),
                                 'paths': len(paths), 'keywords': len(phrases),
                                 'unmatched_keywords': sum(d['state'] == 'unmatched' for d in assignment['decisions']),
                                 'unresolved_keywords': sum(d['state'] == 'unresolved_budget_exhausted' for d in assignment['decisions']),
                                 'seconds': timing.get('seconds'), 'peak_gpu_bytes': timing.get('peak_gpu_bytes')})
    quality = defaultdict(list)
    for path in quality_files:
        value = s4.read(path)
        per_method = defaultdict(list)
        for verdict in value['evaluations']:
            per_method[value['mapping'][verdict['id']]].append(verdict)
        for method, verdicts in per_method.items():
            quality[method].append({'paper_id': value['paper_id'], 'paths': len(verdicts),
                'supported': float(np.mean([v['relevant'] for v in verdicts])),
                'hierarchy': float(np.mean([v['parent_compatible'] for v in verdicts])),
                'specificity': float(np.mean([v['specificity'] for v in verdicts]))})
    result = {'created_at': s4.now(), 'papers': len(manifest['papers_manifest']),
              'role': 'development_comparison_no_fine_gold', 'quality_judged_papers': len(list((args.root / 'quality').glob('*.json'))),
              'keyword_proxy': {}, 'blind_quality_proxy': {}, 'per_paper': dict(rows),
              'quality_evidence_case_resolutions': sum('evidence_resolution' in verdict for p in quality_files
                                                       for verdict in s4.read(p)['evaluations']),
              'hierarchy_audit': {'assignment_files_checked': closure_checked, 'full_parent_closure_passed': True,
                                  'topn_overflow_documents': dict(overflow_documents)},
              'taxonomy': {'version': taxonomy['version'], 'levels': dict(Counter(n['level'] for n in taxonomy['nodes'])),
                           'multi_parent_nodes': sum(len(n['parent_ids']) > 1 for n in taxonomy['nodes']),
                           'full_paths': len(full_paths), 'source': taxonomy['source']}}
    for method, records in rows.items():
        result['keyword_proxy'][method] = {metric: confidence([r[metric] for r in records if r['has_reference']])
                                          for metric in ('P@10', 'R@10', 'F1@10')}
        result['keyword_proxy'][method].update({'documents_with_paths': sum(r['paths'] > 0 for r in records),
            'unmatched_keyword_fraction': sum(r['unmatched_keywords'] for r in records) / sum(r['keywords'] for r in records),
            'terminal_unresolved_keyword_occurrences': sum(r['unresolved_keywords'] for r in records),
            'mean_extraction_seconds': float(np.mean([r['seconds'] for r in records if r['seconds'] is not None]))
                                      if any(r['seconds'] is not None for r in records) else None,
            'peak_gpu_bytes': max((r['peak_gpu_bytes'] or 0 for r in records), default=0)})
    for method, records in quality.items():
        support = {r['paper_id']: r['supported'] for r in records}
        result['blind_quality_proxy'][method] = {'judged_documents_with_paths': len(records),
            'coverage_adjusted_support': confidence([support.get(pid, 0.) for pid in sample_ids]),
            **{metric: confidence([r[metric] for r in records]) for metric in ('supported', 'hierarchy', 'specificity')}}
    result['quality_per_paper'] = dict(quality)
    recovery = s4.read(args.root / 'alignment_recovery.json', {})
    result['arbitration_recovery'] = {k: v for k, v in recovery.items() if k != 'initial_status'}
    decision_sources = Counter()
    cross_provider_max = 0
    for path in (args.root / 'alignment_cache').glob('*.json'):
        decision = s4.read(path)
        source = decision.get('arbitration')
        if source:
            decision_sources[source['provider']] += 1
        primary_failure = decision.get('primary_failure')
        if primary_failure:
            primary_job = s4.read(args.root / 'jobs' / f'{primary_failure["job_id"]}.json')
            config = s4.credentials(args.auth)['openai']
            fallback_job, _ = s4.build_job(config, 'openai', 'dkta_arbitrate', primary_job['payload'])
            fallback_count = len(list((args.root / 'attempts' / fallback_job['job_id']).glob('*.json')))
            used = primary_failure['attempts_used'] + fallback_count
            if used > s4.MAX_ATTEMPTS:
                raise ValueError('A recovered decision exceeded the cross-provider attempt budget')
            cross_provider_max = max(cross_provider_max, used)
    result['arbitration_sources'] = dict(decision_sources)
    result['terminal_abstentions'] = alignment.get('unique_terminal_abstentions', 0)
    result['recovered_decision_max_total_attempts'] = cross_provider_max
    result['paired_keyword_F1_deltas_vs_bart'] = {}
    baseline = {r['paper_id']: r['F1@10'] for r in rows['bart_one2many']}
    for method, records in rows.items():
        result['paired_keyword_F1_deltas_vs_bart'][method] = confidence([
            r['F1@10'] - baseline[r['paper_id']] for r in records if r['has_reference']])
    usage = defaultdict(Counter)
    last_requests = {}
    for path in (args.root / 'attempts').glob('*/*.json'):
        value = s4.read(path)
        provider = value['provider']
        usage[provider]['requests'] += 1
        usage[provider]['failed_requests'] += value['status'] != 'success'
        last_requests[provider] = max(last_requests.get(provider, ''), value['started_at'])
        for field in ('prompt_tokens', 'completion_tokens', 'total_tokens'):
            usage[provider][field] += (value.get('usage') or {}).get(field, 0) or 0
    result['api_usage_including_failed_attempts_when_reported'] = {k: dict(v) for k, v in usage.items()}
    result['last_request_started_at_by_provider'] = last_requests
    result['current_api_policy'] = {'provider': 'openai', 'model': s4.credentials(args.auth)['openai']['model'],
                                    'concurrency_from_auth': s4.credentials(args.auth)['openai']['concurrency']}
    s4.write(args.root / 'comparison.json', result)
    lines = ['# DKTA 与 LLM：200篇开发集对比\n',
        '关键词指标衡量作者关键词的精确匹配，OpenAI弱模型匿名评价用于开发诊断；细粒度领域准确性需人工金标准。',
        '四个关键词方法使用同一标题摘要、相同ACM对齐；LLM另报自由生成路径，隔离体系与抽取算法的影响。',
        '历史三模型另使用六板块，且只抽前5条原始L3路径，不作同输入主结论。',
        'ACM原始公开镜像经两个镜像同blob核对，投影为三层，未做LLM扩充。多父闭包优先于Top-N。\n',
        '| 方法 | 作者关键词F1@10 | ACM对齐有路径文档/200 | 抽取秒/篇（不含加载） | 峰值GPU GiB |',
        '|---|---:|---:|---:|---:|']
    for method, stats in result['keyword_proxy'].items():
        timing = stats['mean_extraction_seconds']
        lines.append(f'| {method} | {stats["F1@10"]["mean"]:.4f} | {stats["documents_with_paths"]} | {timing:.3f} | {stats["peak_gpu_bytes"]/2**30:.2f} |'
                     if timing is not None else f'| {method} | {stats["F1@10"]["mean"]:.4f} | {stats["documents_with_paths"]} | — | — |')
    lines.extend(['\n## OpenAI弱模型盲评（按论文宏平均）\n',
                  '| 方法 | 有路径且被评价的论文 | 内容支持率 | 空输出计零后的支持率 | 父子兼容率 | L3具体程度1–5 |', '|---|---:|---:|---:|---:|---:|'])
    for method, stats in result['blind_quality_proxy'].items():
        lines.append(f'| {method} | {stats["judged_documents_with_paths"]} | {stats["supported"]["mean"]:.3f} | {stats["coverage_adjusted_support"]["mean"]:.3f} | {stats["hierarchy"]["mean"]:.3f} | {stats["specificity"]["mean"]:.2f} |')
    lines.extend(['\n置信区间、逐篇结果见comparison.json。空输出由覆盖率单独报告，不能借空输出提升质量分数。',
                  '历史OpenAI结果可能存在同源评判偏差；仅作附加观察。未报告真实hierarchical F1或概率校准。',
                  f'完整父闭包已校验{closure_checked}份assignment。该结构校验与盲评的语义父子兼容率是不同指标。',
                  '本地抽取不产生API费；模糊区对齐仍调用API，不能把完整DKTA管线称为纯本地或零API成本。',
                  '抽取时延为单请求/单篇服务时间，不含模型加载，不用于直接推断不同并发配置的全流程吞吐。',
                  '\n## 分析与限制\n'])
    ranked = sorted(result['keyword_proxy'], key=lambda m: -result['keyword_proxy'][m]['F1@10']['mean'])
    lines.append(f'作者关键词一致性排名：{" > ".join(ranked)}。这是不完整作者关键词上的匹配结果，不能据此独立判断领域分类准确率。')
    lines.append(f'仲裁来源：{dict(decision_sources)}。历史DeepSeek HTTP402余额不足保留在alignment_recovery.json；剩余仲裁由OpenAI弱模型完成，后续新请求默认OpenAI。')
    lines.append(f'补齐任务跨通道最多使用{cross_provider_max}次请求，上限为初次+5次重试；未清空原失败记录。')
    lines.append(f'其中{result["terminal_abstentions"]}个词达到预算上限后仍返回非法路径ID，显式记为unknown；未猜测或修补ID，不计为成功仲裁。')
    for method, delta in result['paired_keyword_F1_deltas_vs_bart'].items():
        if method != 'bart_one2many':
            lines.append(f'- {method} 相对 BART 的逐篇配对F1差：{delta["mean"]:+.4f}，95% bootstrap区间 [{delta["ci95"][0]:+.4f}, {delta["ci95"][1]:+.4f}]。')
    lines.extend(['\nQwen路线是混合注意力Qwen3.5的适配实现；注意力分数用于候选排序，URL、代码声明及标题边界词可能排名靠前，需据科学对象核查其相关性。',
                  'RRF只融合排名，不能自动消除上述噪声；是否优于BART以本次真实比较为准。',
                  'ACM CCS 2012未在此批扩充，宽泛概念与现代ML术语存在覆盖及粒度差异；自由LLM标签与ACM路径差距同时受抽取和词表限制影响。',
                  'llm_deepseek_aligned用于控制词表影响：它与BART/Qwen共用同一索引、阈值和仲裁模型。',
                  '仲裁器可读取标题摘要，因此最终路径质量同时反映抽词、体系与仲裁，不能归结为纯关键词抽取准确率。',
                  '盲评对每个不同L3取一条代表父路径，最多5条；其他祖先路径只做完整性校验，此处语义兼容率不覆盖全部多父边。',
                  '补齐的ACM仲裁和质量评价均使用gpt-6-luna，存在同源偏好；该影响由来源记录披露，本次未做独立评判器复核。',
                  '全部200篇是开发数据；盲评样本按年份分层50篇。不能将本结果称作未见测试集或生产taxonomy验收。',
                  '\n## 样例\n'])
    for entry in manifest['papers_manifest'][:2]:
        pid = entry['paper_id']
        lines.append(f'### Paper {pid}: {dkta.load_paper(args, entry)["title"]}\n')
        for method in core_methods(args):
            phrases = s4.read(args.root / 'fused' / method / f'{pid}.json')['phrases']
            lines.append(f'- {method}关键词：' + '; '.join(p['phrase'] for p in phrases[:10]))
            lines.extend('  - ' + ' → '.join(path) for path in method_paths(args, pid, method))
    (args.root / 'comparison.md').write_text('\n'.join(lines) + '\n')
    s4.log('comparison_report_complete', papers=result['papers'], quality_papers=result['quality_judged_papers'])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('stage', choices=('acm', 'matched-llm', 'recover-arbitration', 'judge', 'report'))
    parser.add_argument('--root', type=Path, default=ROOT)
    parser.add_argument('--source-root', type=Path, default=Path('/data_big/iclr-s4/experiments/taxonomy_llm4_gpt_200_v1'))
    parser.add_argument('--auth', type=Path, default=Path('/home/yhr/auth'))
    parser.add_argument('--limit', type=int, default=200)
    parser.add_argument('--judge-papers', type=int, default=50)
    parser.add_argument('--baseline-provider', choices=('openai', 'deepseek'), default='openai')
    args = parser.parse_args()
    globals()[args.stage.replace('-', '_')](args)


if __name__ == '__main__':
    main()
