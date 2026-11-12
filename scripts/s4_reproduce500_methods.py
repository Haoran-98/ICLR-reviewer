"""Four controlled local-Qwen adaptations; see the frozen experiment protocol."""
from __future__ import annotations

import ast
from collections import Counter, defaultdict, deque
from contextlib import redirect_stdout
import importlib.util
from itertools import combinations
import json
from pathlib import Path
import sys
import time
import types

import numpy as np
from scipy.optimize import linear_sum_assignment
from sklearn.cluster import KMeans
from sklearn.mixture import GaussianMixture
from sklearn.metrics import (accuracy_score, adjusted_rand_score, f1_score,
                             normalized_mutual_info_score)
from sklearn.model_selection import StratifiedKFold
from s4_reproduce500 import (ROOT, SEED, VERSION, MODEL, REASONING_EFFORT, CONTEXT, Qwen, digest, embed_texts, log,
                             now, paper_text, read, write)

K = 23  # cardinality only, never the per-paper gold labels
DIMENSIONS = ['tasks', 'datasets', 'methodologies', 'evaluation_methods', 'real_world_domains']


def load_module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def node(nid, name, description='', parents=(), papers=(), facet='topic', container=False):
    return dict(id=str(nid), name=name, description=description,
                parent_ids=list(map(str, parents)), paper_ids=list(papers),
                facet=facet, container=container)


def graph_stats(nodes):
    """Count unique DAG nodes, using longest root path; artificial roots cost zero."""
    byid = {n['id']: n for n in nodes}
    if len(byid) != len(nodes):
        raise ValueError('Duplicate graph node IDs')
    children = defaultdict(list)
    for n in nodes:
        for parent in n['parent_ids']:
            if parent not in byid:
                raise ValueError('Unknown parent')
            children[parent].append(n['id'])
    levels, visiting = {}, set()
    def depth(nid):
        if nid in visiting:
            raise ValueError('Taxonomy contains a cycle')
        if nid not in levels:
            visiting.add(nid)
            n = byid[nid]
            parent_depth = max((depth(p) for p in n['parent_ids']), default=0)
            levels[nid] = parent_depth + int(not n.get('container', False))
            visiting.remove(nid)
        return levels[nid]
    for nid in byid:
        depth(nid)
    semantic = [n for n in nodes if not n.get('container', False)]
    supported = [n for n in semantic if n['paper_ids']]
    widths = Counter(levels[n['id']] for n in semantic)
    supported_widths = Counter(levels[n['id']] for n in supported)
    branches = [len(children[n['id']]) for n in semantic if children[n['id']]]
    all_branches = [len(children[n['id']]) for n in nodes if children[n['id']]]
    return dict(depth=max((levels[n['id']] for n in semantic), default=0),
                supported_depth=max((levels[n['id']] for n in supported), default=0),
                nodes=len(semantic), supported_nodes=len(supported),
                widths=dict(sorted(widths.items())),
                supported_widths=dict(sorted(supported_widths.items())),
                max_width=max(widths.values(), default=0),
                mean_branching=float(np.mean(branches)) if branches else 0.,
                mean_branching_including_containers=float(np.mean(all_branches)) if all_branches else 0.,
                leaves=sum(not children[n['id']] for n in semantic),
                levels=levels)


def membership_features(nodes, inputs):
    """Equal facet weights, equal terminal membership weights within each facet."""
    stats = graph_stats(nodes)
    semantic = [n for n in nodes if not n.get('container', False)]
    ids = [n['id'] for n in semantic]
    row = {p['paper_id']: i for i, p in enumerate(inputs)}
    index = {nid: j for j, nid in enumerate(ids)}
    support = {n['id']: set(n['paper_ids']) for n in nodes}
    children = defaultdict(list)
    for n in nodes:
        for parent in n['parent_ids']:
            children[parent].append(n['id'])
    terminals = defaultdict(lambda: defaultdict(list))
    for n in semantic:
        for pid in n['paper_ids']:
            if not any(pid in support[c] for c in children[n['id']]):
                terminals[pid][n['facet']].append(n['id'])
    X = np.zeros((len(inputs), len(ids)), dtype=np.float32)
    for pid, facets in terminals.items():
        for members in facets.values():
            for nid in members:
                X[row[pid], index[nid]] = 1 / len(facets) / len(members)
    return ids, X


def save_method(name, args, nodes, metadata, features=None, topic_ids=None, extras=None):
    inputs = read(args.root / 'inputs.json')
    if features is None:
        topic_ids, features = membership_features(nodes, inputs)
    assert features.shape == (len(inputs), len(topic_ids))
    assert np.isfinite(features).all() and np.min(features) >= 0
    sums = features.sum(1, keepdims=True)
    features = features / np.maximum(sums, 1e-12)
    output = args.root / 'methods' / name
    output.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(output / 'representations.npz', features=features,
                        paper_ids=np.array([p['paper_id'] for p in inputs]), topic_ids=np.array(topic_ids))
    write(output / 'result.json', dict(method=name, version=VERSION, completed_at=now(),
        input_hash=digest(inputs), nodes=nodes, metadata=dict(model=MODEL,
        reasoning_effort=REASONING_EFFORT, context_per_slot=CONTEXT,
        embedding='topic-membership' if name == 'taxoadapt' else 'BAAI/bge-m3', **metadata),
        structure=graph_stats(nodes), coverage=float(np.mean(sums[:, 0] > 0)), **(extras or {})))
    result = read(output / 'result.json')
    result['facet_structures'] = {facet: graph_stats([n for n in nodes if n['facet'] == facet])
                                  for facet in sorted({n['facet'] for n in nodes})}
    write(output / 'result.json', result)
    log('method_complete', method=name, nodes=len(nodes), coverage=float(np.mean(sums[:, 0] > 0)))


def taxoadapt(args):
    """Run the authors' DAG initialization, classification, width/depth expansion."""
    source = args.root / 'sources/taxoadapt'
    qwen = Qwen(args.root, args.concurrency)
    bridge = types.ModuleType('model_definitions')
    bridge.constructPrompt = lambda args, system, user: system + '\n\n' + user
    bridge.initializeLLM = lambda args: args
    budgets = dict(TypeClsSchema=192, ClassifySchema=384, NodeListSchema=1536,
                   WidthExpansionSchema=192, DepthExpansionSchema=192,
                   WidthClusterListSchema=2048, DepthClusterListSchema=2048)
    def prompt_llm(args, prompts, schema=None, max_new_tokens=1024, **unused):
        tag = schema.__name__ if schema else 'generic'
        outputs = qwen.map('taxoadapt_' + tag, prompts, budgets.get(tag, max_new_tokens), schema)
        return [json.dumps(o) for o in outputs]
    bridge.promptLLM = prompt_llm
    saved = {name: sys.modules.get(name) for name in
             ['model_definitions', 'prompts', 'utils', 'paper', 'enrichment', 'classification', 'taxonomy', 'expansion', 'datasets']}
    sys.modules['model_definitions'] = bridge
    # Only the authors' main module imports HuggingFace datasets. Input construction is replaced.
    datasets_stub = types.ModuleType('datasets')
    datasets_stub.load_dataset = lambda *a, **k: (_ for _ in ()).throw(RuntimeError('Frozen inputs only'))
    sys.modules['datasets'] = datasets_stub
    sys.path.insert(0, str(source))
    from types import SimpleNamespace
    cfg = SimpleNamespace(topic='machine learning', dimensions=DIMENSIONS, init_levels=1,
                          max_density=40, max_depth=3, llm='local_qwen')
    outdir = args.root / 'methods/taxoadapt'
    outdir.mkdir(parents=True, exist_ok=True)
    try:
        for name in ['prompts', 'utils', 'paper', 'classification', 'enrichment', 'taxonomy', 'expansion']:
            module_path = source / (name + '.py')
            if name == 'expansion':
                # Preserve the official source; repair its uninitialized error diagnostics locally.
                repaired = module_path.read_text().replace(
                    '    success = False\n    attempts = 0',
                    '    success = False\n    cluster_topics = cluster_outputs = None\n    attempts = 0')
                module_path = args.root / 'runtime/taxoadapt_expansion.py'
                module_path.write_text(repaired)
            load_module(name, module_path)
        original = load_module('taxoadapt_original_main', source / 'main.py')
        inputs = read(args.root / 'inputs.json')
        papers = {i: sys.modules['paper'].Paper(i, p['title'], p['abstract'], DIMENSIONS, True)
                  for i, p in enumerate(inputs)}
        roots, id2node, label2node = original.initialize_DAG(cfg)
        outputs = prompt_llm(cfg, [bridge.constructPrompt(cfg, original.type_cls_system_instruction,
                  original.type_cls_main_prompt(p)) for p in papers.values()], original.TypeClsSchema)
        for i, value in enumerate(outputs):
            papers[i].labels = {}
            for dim, present in json.loads(value).items():
                if present:
                    papers[i].labels[dim] = []
                    roots[dim].papers[i] = papers[i]
        visited, queue = set(), deque(roots.values())
        while queue:
            current = queue.popleft()
            log('taxoadapt_node', label=current.label, facet=current.dimension,
                level=current.level, papers=len(current.papers), queued=len(queue))
            if current.children:
                if current.id in visited:
                    continue
                visited.add(current.id)
                current.classify_node(cfg, label2node, visited)
                siblings = original.expandNodeWidth(cfg, current, id2node, label2node)
                if siblings:
                    current.classify_node(cfg, label2node, visited)
                for child in current.children.values():
                    if child.level < cfg.max_depth and len(child.papers) > cfg.max_density:
                        queue.append(child)
            else:
                expansion = original.expandNodeDepth(cfg, current, id2node, label2node)
                # Author code returns [] rather than ([], False) when all candidates already exist.
                new_children, success = expansion if isinstance(expansion, tuple) else ([], False)
                if new_children and success:
                    queue.append(current)
            write(outdir / 'checkpoint_nodes.json', [node(n.id, n.label, n.description or '',
                [p.id for p in n.parents], [inputs[i]['paper_id'] for i in n.papers],
                n.dimension, n.id in {r.id for r in roots.values()}) for n in id2node.values()])
        nodes = [node(n.id, n.label, n.description or '', [p.id for p in n.parents],
                      [inputs[i]['paper_id'] for i in n.papers], n.dimension,
                      n.id in {r.id for r in roots.values()}) for n in id2node.values()]
        save_method('taxoadapt', args, nodes, dict(implementation='official DAG/classification/expansion modules + local bridge',
            dimensions=DIMENSIONS, max_density=40, max_depth=3, init_levels=1,
            deviations=[f'{MODEL} ({REASONING_EFFORT} thinking) replaces both teacher and student; see runtime/selected_config.json for sampling settings',
                        'depth cap 3 instead of repository default 2',
                        'handle inconsistent empty return in expandNodeDepth',
                        'initialize official expansion error diagnostics in a local source copy']))
    finally:
        sys.path.remove(str(source))
        for key, value in saved.items():
            if value is None:
                sys.modules.pop(key, None)
            else:
                sys.modules[key] = value


def max_weight_selection(W, l):
    """Exact author objective, vectorized over papers; deterministic lexicographic ties."""
    best_score, best_columns = -np.inf, None
    for columns in combinations(range(W.shape[1]), l):
        score = W[:, columns].max(axis=1).sum()
        if score > best_score:
            best_score, best_columns = score, columns
    chosen = np.array(best_columns)
    return chosen[np.argmax(W[:, chosen], axis=1)], list(best_columns), float(best_score)


def representatives(indices, vectors, limit=24):
    if len(indices) <= limit:
        return list(indices)
    # Deterministic diverse medoids; only limits aggregate LLM prompts, not clustering membership.
    local = vectors[indices]
    kmeans = KMeans(n_clusters=limit, random_state=SEED, n_init=10).fit(local)
    result = []
    for c in range(limit):
        members = np.flatnonzero(kmeans.labels_ == c)
        if len(members):
            distances = np.linalg.norm(local[members] - kmeans.cluster_centers_[c], axis=1)
            result.append(indices[members[np.argmin(distances)]])
    return result


def context(args):
    prompts = load_module('context_original_prompts', args.root / 'sources/context/src/Prompt.py')
    inputs = read(args.root / 'inputs.json')
    vectors = np.load(args.root / 'embeddings/title_abstract.npz')['vectors']
    qwen = Qwen(args.root, args.concurrency)
    queue = deque([('root', list(range(len(inputs))), 0, 'machine learning', '')])
    nodes = [node('root', 'machine learning', papers=[p['paper_id'] for p in inputs], container=True)]
    diagnostics = []
    while queue:
        parent, indices, level, heading, parent_aspect = queue.popleft()
        if level >= 3 or len(indices) < 16:
            continue
        sample = representatives(indices, vectors, 24)
        if level == 0:
            prompt = prompts.generate_aspect_prompt_high_sys + '\n' + prompts.generate_aspect_prompt_high_user.replace(
                '[TITLE]', heading).replace('[TITLE_LIST]', '\n'.join(inputs[i]['title'] for i in sample))
        else:
            descriptions = '\n'.join(f"{inputs[i]['title']}: {inputs[i]['abstract'][:400]}" for i in sample)
            prompt = prompts.generate_aspect_prompt_specific_sys + '\n' + prompts.generate_aspect_prompt_specific_user.replace(
                '[TITLE]', heading).replace('[TOPIC]', parent_aspect).replace('[PAPERS]', descriptions)
        aspects = qwen.ask('context_aspects', prompt, 1024)
        if not 2 <= len(aspects) <= 10 or not all(isinstance(v, str) for v in aspects.values()):
            raise ValueError('Invalid dynamic aspect output')
        keys = list(aspects)
        summary_prompts = []
        for i in indices:
            prompt = prompts.extract_aspect_prompt_user.replace('[TITLE]', inputs[i]['title']).replace(
                '[ABSTRACT]', inputs[i]['abstract']).replace('[INTRODUCTION]', 'Not provided').replace(
                '[ASPECTS]', json.dumps(aspects))
            summary_prompts.append(prompts.extract_aspect_prompt_sys + '\n' + prompt +
                                   '\nKeep each dimension description to at most 35 words.')
        schema = dict(type='object', properties={a: {'type': 'string'} for a in keys}, required=keys,
                      additionalProperties=False)
        summaries = qwen.map('context_summaries', summary_prompts, 1536, schema)
        summary_file = args.root / f'methods/context/node_{parent}_summaries.json'
        write(summary_file, dict(indices=indices, aspects=aspects, summaries=summaries))
        embedding_texts = [inputs[i]['title'] + '; ' + a + ': ' + s[a]
                           for a in keys for i, s in zip(indices, summaries)]
        embedded = embed_texts(embedding_texts, args.root / f'embeddings/context_{parent}.npz', args.device, 8)
        matrices, column_aspects = [], []
        for ai, aspect in enumerate(keys):
            E = embedded[ai * len(indices):(ai + 1) * len(indices)]
            # GMM follows paper eq. 5; tied covariance regularization stabilizes n << dimension.
            gmm = GaussianMixture(n_components=4, covariance_type='tied', reg_covar=1e-2,
                                  n_init=2, random_state=SEED).fit(E)
            matrices.append(gmm.predict_proba(E))
            column_aspects.extend([aspect] * 4)
        assignment, selected, objective = max_weight_selection(np.hstack(matrices), 4)
        groups = [(col, [i for i, assigned in zip(indices, assignment) if assigned == col]) for col in selected]
        groups = [(c, ids) for c, ids in groups if ids]
        diagnostics.append(dict(parent=parent, papers=len(indices), aspects=aspects,
                                selected_columns=selected, actual_children=len(groups), objective=objective))
        if len(groups) <= 1:
            log('context_stop_unsplit', node=parent, papers=len(indices))
            continue
        heading_prompts = []
        for col, members in groups:
            aspect = column_aspects[col]
            local_sample = representatives(members, vectors, 12)
            local_by_id = {i: j for j, i in enumerate(indices)}
            text = '\n'.join(inputs[i]['title'] + ': ' + summaries[local_by_id[i]][aspect] for i in local_sample)
            heading_prompts.append(prompts.gen_heading_prompt_sys.replace('[TITLE]', 'machine learning').replace(
                '[TOPIC]', heading + ' -> ' + aspect).replace('[PAPERS]', text) + '\n' +
                prompts.gen_heading_prompt_user.replace('[ TITLE ]', 'machine learning').replace(
                    '[ TOPIC ]', heading + ' -> ' + aspect).replace('[PAPERS]', text))
        headings = qwen.map('context_headings', heading_prompts, 512,
            dict(type='object', properties={'Cluster Name': {'type': 'string'}, 'Summary': {'type': 'string'}},
                 required=['Cluster Name', 'Summary'], additionalProperties=False))
        for (col, members), title in zip(groups, headings):
            nid = str(len(nodes))
            nodes.append(node(nid, title['Cluster Name'], title['Summary'], [parent],
                              [inputs[i]['paper_id'] for i in members]))
            queue.append((nid, members, level + 1, heading + ' -> ' + title['Cluster Name'], column_aspects[col]))
        write(args.root / 'methods/context/checkpoint_nodes.json', nodes)
        log('context_node', node=parent, papers=len(indices), children=len(groups), level=level)
    save_method('context', args, nodes, dict(implementation='paper GMM + exact multi-aspect search, official prompt templates',
        aspect_clusters=4, children_per_parent=4, max_depth=3, minimum_split_size=16,
        deviations=['Qwen and BGE replace original LLMs and encoder',
            'GMM rather than released-code hardcoded KMeans; tied covariance reg=0.01',
            '24 diverse representative papers for aspect generation; 12 for naming',
            '35-word summary budget per aspect; no per-paper title/abstract truncation']),
        extras={'search_diagnostics': diagnostics})


def nearest(E, neighbors):
    from sklearn.neighbors import NearestNeighbors
    raw = NearestNeighbors(n_neighbors=neighbors + 1).fit(E).kneighbors(E, return_distance=False)
    return np.array([[j for j in row if j != i][:neighbors] for i, row in enumerate(raw)])


def lisa(args):
    import torch
    from torch import nn
    torch.set_num_threads(8)
    torch.manual_seed(SEED)
    inputs = read(args.root / 'inputs.json')
    E = np.load(args.root / 'embeddings/title_abstract.npz')['vectors']
    qwen = Qwen(args.root, args.concurrency)
    schema = dict(type='object', properties={'topic': {'type': 'string'}, 'description': {'type': 'string'}},
                  required=['topic', 'description'], additionalProperties=False)
    candidates = qwen.map('lisa_generate', [
        'Generate a candidate topic word (a short phrase of 2-3 words) and a description '
        'of no more than two sentences for this document. Return only JSON '
        '{"topic":"...","description":"..."}. Document:\n' + paper_text(p) for p in inputs], 256, schema)
    write(args.root / 'methods/lisa/candidates.json', candidates)
    topic_names = list(dict.fromkeys(c['topic'].strip().casefold() for c in candidates))
    ti = {name: i for i, name in enumerate(topic_names)}
    candidate_index = np.array([ti[c['topic'].strip().casefold()] for c in candidates])
    description_vectors = embed_texts([c['description'] for c in candidates],
        args.root / 'embeddings/lisa_descriptions.npz', args.device, 8)
    T = np.stack([description_vectors[candidate_index == i].mean(0) for i in range(len(topic_names))])
    document_cluster = KMeans(n_clusters=K, random_state=SEED, n_init=20).fit_predict(E)
    topic_cluster = KMeans(n_clusters=K, random_state=SEED, n_init=20).fit_predict(T)
    doc_tc = topic_cluster[candidate_index]
    confusion = np.zeros((K, K))
    np.add.at(confusion, (document_cluster, doc_tc), 1)
    rows, cols = linear_sum_assignment(-confusion)
    mapping = dict(zip(rows.tolist(), cols.tolist()))
    topic_labels = qwen.map('lisa_summarize', [
        'Given these topic words, generate one general topic word describing as many of them as possible. '
        'Return JSON {"topic":"...","description":"one concise defining sentence"}. Topic words:\n' +
        ', '.join(name for name, cls in zip(topic_names, topic_cluster) if cls == k) for k in range(K)], 192, schema)
    cluster_vectors = np.stack([T[topic_cluster == k].mean(0) for k in range(K)])
    Dn = nearest(E, 15)
    wrong = np.flatnonzero(np.array([mapping[c] for c in document_cluster]) != doc_tc)
    prompts, options = [], []
    for i in wrong:
        choices = sorted({mapping[document_cluster[j]] for j in Dn[i, :5]})
        options.append(choices)
        prompts.append('Given a document and candidate topics, choose the topic that best describes it. '
            'Return JSON {"topic_id":integer}, with -1 if none apply. Candidates: ' + json.dumps(
                {k: topic_labels[k] for k in choices}) + '\nDocument:\n' + paper_text(inputs[i]))
    assignments = qwen.map('lisa_correct', prompts, 64,
        dict(type='object', properties={'topic_id': {'type': 'integer'}}, required=['topic_id'], additionalProperties=False))
    corrected = doc_tc.copy()
    rejected, changed = 0, 0
    for i, choices, assignment in zip(wrong, options, assignments):
        c = assignment['topic_id']
        if c in choices:
            changed += int(c != corrected[i])
            corrected[i] = c
        elif c == -1:
            rejected += 1
        else:
            raise ValueError('LiSA correction returned invalid topic id')
    # M1' maps documents to corrected candidate topic representations. Keep original vector
    # when unchanged; a changed cluster uses its average candidate-topic representation.
    topic_bank = list(T)
    paired_index = candidate_index.copy()
    added = {}
    for i in np.flatnonzero(corrected != doc_tc):
        cluster = int(corrected[i])
        if cluster not in added:
            label = topic_labels[cluster]['topic'].strip().casefold()
            if label in ti:
                added[cluster] = ti[label]
            else:
                added[cluster] = len(topic_bank)
                topic_bank.append(cluster_vectors[cluster])
        paired_index[i] = added[cluster]
    topic_bank = np.stack(topic_bank)
    paired_T = topic_bank[paired_index]
    # Neighbor search is over distinct topic words, not duplicated per-document copies.
    Tn = nearest(topic_bank, 15)
    def network(d):
        return nn.Sequential(nn.Linear(d, 256), nn.ReLU(), nn.Linear(256, 256), nn.ReLU(),
                             nn.Linear(256, K), nn.Softmax(dim=1))
    pd, pt = network(E.shape[1]), network(T.shape[1])
    optimizer = torch.optim.Adagrad(list(pd.parameters()) + list(pt.parameters()), lr=1e-3)
    ED, ET, EB = torch.tensor(E), torch.tensor(paired_T), torch.tensor(topic_bank)
    rng = np.random.default_rng(SEED)
    losses = []
    def neighbor_contrast(a, b):
        # Paper eqs. 8-9 compare columns (clusters), using the stated dot product.
        cross = torch.exp(a.T @ b / 1.5)
        same = torch.exp(b.T @ b / 1.5)
        denominator = cross.sum(1) + same.sum(1) - same.diag()
        return -(torch.log(cross.diag().clamp_min(1e-12)) - torch.log(denominator.clamp_min(1e-12))).sum()
    for epoch in range(30):
        nd = Dn[np.arange(len(E)), rng.integers(15, size=len(E))]
        nt = Tn[paired_index, rng.integers(15, size=len(E))]
        epoch_losses = []
        for idx in np.array_split(rng.permutation(len(E)), 4):
            optimizer.zero_grad()
            p, q = pd(ED[idx]), pt(ET[idx])
            ph, qh = pd(ED[nd[idx]]), pt(EB[nt[idx]])
            l1 = -torch.log((p * q).sum(1).mean().clamp_min(1e-12))
            l2 = neighbor_contrast(p, qh) + neighbor_contrast(q, ph)
            x, y = p.mean(0), q.mean(0)
            l3 = -(x * x.clamp_min(1e-12).log()).sum() - (y * y.clamp_min(1e-12).log()).sum()
            loss = l1 + l2 - .8 * l3
            if not torch.isfinite(loss):
                raise ValueError('Nonfinite LiSA training objective')
            loss.backward()
            optimizer.step()
            epoch_losses.append([float(v.detach()) for v in (loss, l1, l2, l3)])
        losses.append(dict(epoch=epoch + 1, loss=np.mean(epoch_losses, axis=0).tolist()))
    with torch.no_grad():
        probabilities = pd(ED).numpy()
    # TPN outputs may be permuted; align them to semantic topic clusters without gold labels.
    align = np.zeros((K, K))
    for i in range(len(E)):
        align[:, corrected[i]] += probabilities[i]
    r, c = linear_sum_assignment(-align)
    aligned = np.zeros_like(probabilities)
    aligned[:, c] = probabilities[:, r]
    hard = aligned.argmax(1)
    nodes = [node(k, topic_labels[k]['topic'], topic_labels[k]['description'],
                  papers=[p['paper_id'] for i, p in enumerate(inputs) if hard[i] == k]) for k in range(K)]
    directory = args.root / 'methods/lisa'
    directory.mkdir(parents=True, exist_ok=True)
    torch.save({'document_network': pd.state_dict(), 'topic_network': pt.state_dict()}, directory / 'networks.pt')
    write(directory / 'training.json', losses)
    write(directory / 'stages.json', dict(document_cluster=document_cluster.tolist(), topic_cluster=doc_tc.tolist(),
        corrected_topic_cluster=corrected.tolist(), tpn_semantic_permutation=dict(zip(r.tolist(), c.tolist()))))
    save_method('lisa', args, nodes, dict(implementation='paper equations 1-11; official repository has no released implementation',
        topics=K, hidden=[256, 256], epochs=30, batch_size=125, optimizer='Adagrad', learning_rate=.001,
        temperature=1.5, entropy_weight=.8, correction_neighbors=5, training_neighbors=15,
        inconsistencies=len(wrong), changed=changed, no_candidate_matches=rejected,
        deviations=['Qwen/BGE replace Llama/Mistral and MiniLM',
            'changed topic uses its cluster mean representation (paper does not specify vector of summarizing topic)',
            'TPN columns aligned to corrected clusters using gold-blind Hungarian mapping']),
        aligned, [str(k) for k in range(K)])


def itl(args):
    import ot
    import torch
    from torch import nn
    from torch.nn import functional as F
    from sklearn.feature_extraction.text import CountVectorizer
    torch.set_num_threads(8)
    torch.manual_seed(SEED)
    rng = np.random.default_rng(SEED)
    inputs = read(args.root / 'inputs.json')
    qwen = Qwen(args.root, args.concurrency)
    vectorizer = CountVectorizer(stop_words='english', min_df=3, max_df=.7, max_features=5000,
                                token_pattern=r'(?u)\b[a-zA-Z][a-zA-Z-]{2,}\b')
    bow = vectorizer.fit_transform([paper_text(p) for p in inputs]).toarray().astype(np.float32)
    vocab = vectorizer.get_feature_names_out().tolist()
    lookup = {w: i for i, w in enumerate(vocab)}
    directory = args.root / 'methods/itl'
    directory.mkdir(parents=True, exist_ok=True)
    write(directory / 'vocabulary.json', vocab)
    word_vectors = embed_texts(vocab, args.root / 'embeddings/itl_words.npz', args.device, 16)
    class NVDM(nn.Module):
        def __init__(self):
            super().__init__()
            self.enc_vec = nn.Linear(len(vocab), 100)
            self.mean = nn.Linear(100, K)
            self.log_sigma = nn.Linear(100, K)
            self.dec_vec = nn.Linear(K, len(vocab))
        def forward(self, x):
            hidden = torch.tanh(self.enc_vec(x))
            mean, sigma = self.mean(hidden), self.log_sigma(hidden).clamp(-10, 10)
            kl = -.5 * (1 - mean.square() + 2 * sigma - (2 * sigma).exp()).sum(1)
            z = mean + sigma.exp() * torch.randn_like(mean)
            reconstruction = -(F.log_softmax(self.dec_vec(z), dim=1) * x).sum(1)
            return kl.mean(), reconstruction.mean(), mean
    model = NVDM()
    optimizer = torch.optim.Adam(model.parameters(), lr=.001)
    data = torch.tensor(bow)
    suggestions, labels, history = None, None, []
    def top_words():
        weights = model.dec_vec.weight.T
        _, idx = weights.topk(10, dim=1)
        return idx, [[vocab[j] for j in row] for row in idx.tolist()]
    def refine(topics):
        schema = dict(type='object', properties={'Topic': {'type': 'string'},
            'Words': {'type': 'array', 'items': {'type': 'string'}, 'minItems': 1, 'maxItems': 10}},
            required=['Topic', 'Words'], additionalProperties=False)
        answers = qwen.map('itl_refine', [
            'Given a set of words, summarize a topic in two words covering most of them. '
            'Remove irrelevant words; add relevant words, to obtain exactly 10 refined words. '
            'Return JSON {"Topic":"two word topic","Words":["word",...]}. '
            'Use single English vocabulary words. Input words: ' + ', '.join(words) for words in topics], 256, schema)
        refined = []
        for original, ans in zip(topics, answers):
            words = list(dict.fromkeys(w.strip().lower() for w in ans['Words']))
            conf = sum(w in words for w in original) / len(original)  # official word-intrusion confidence
            retained = [lookup[w] for w in words if w in lookup]
            refined.append((retained, conf))
        return answers, refined
    refinement_steps, nonzero_gradients = 0, 0
    for epoch in range(250):
        if epoch >= 200 and (epoch - 200) % 5 == 0:
            _, topics = top_words()
            labels, suggestions = refine(topics)
            write(directory / f'refinement_epoch{epoch + 1}.json', dict(topics=topics, answers=labels,
                filtered=[dict(indices=idx, confidence=conf) for idx, conf in suggestions]))
        values = []
        for idx in np.array_split(rng.permutation(len(inputs)), 3):
            optimizer.zero_grad()
            kl, rec, _ = model(data[idx])
            refine_loss = torch.tensor(0.)
            if suggestions is not None:
                top_idx, _ = top_words()
                for k, (target_idx, confidence) in enumerate(suggestions):
                    if target_idx and confidence > 0:
                        # Softmax makes transport masses nonnegative (author raw-logit normalization can be negative).
                        mass = model.dec_vec.weight.T[k, top_idx[k]].softmax(0).to(torch.float64)
                        target = torch.full((len(target_idx),), 1 / len(target_idx), dtype=torch.float64)
                        cost = torch.tensor(1 - word_vectors[top_idx[k].numpy()] @ word_vectors[target_idx].T,
                                            dtype=torch.float64).clamp_min(0)
                        refine_loss = refine_loss + confidence * ot.emd2(mass, target, cost)
                refinement_steps += 1
            loss = kl + rec + 200 * refine_loss
            if not torch.isfinite(loss):
                raise ValueError('Nonfinite LLM-ITL objective')
            if suggestions is not None and refine_loss.requires_grad:
                gradient = torch.autograd.grad(refine_loss, model.dec_vec.weight, retain_graph=True)[0]
                nonzero_gradients += int(gradient.abs().sum() > 0)
            loss.backward()
            optimizer.step()
            values.append([float(v.detach()) for v in (loss, kl, rec, refine_loss)])
        history.append(dict(epoch=epoch + 1, loss=np.mean(values, axis=0).tolist()))
        if (epoch + 1) % 25 == 0:
            log('itl_epoch', epoch=epoch + 1, values=history[-1]['loss'])
            write(directory / 'training.json', history)
    _, topics = top_words()
    labels, _ = refine(topics)
    model.eval()
    with torch.no_grad():
        probabilities = model(data)[2].softmax(1).numpy()
    hard = probabilities.argmax(1)
    nodes = [node(k, labels[k]['Topic'], ', '.join(topics[k]),
                  papers=[p['paper_id'] for i, p in enumerate(inputs) if hard[i] == k]) for k in range(K)]
    torch.save(model.state_dict(), directory / 'nvdm.pt')
    write(directory / 'training.json', history)
    assert nonzero_gradients > 0, 'LLM refinement must actually backpropagate'
    save_method('itl', args, nodes, dict(implementation='NVDM architecture + confidence-weighted differentiable EMD refinement',
        topics=K, vocabulary=len(vocab), epochs=250, warmup_epochs=200, refinement_epochs=50,
        feedback_refresh_epochs=5, refinement_weight=200, learning_rate=.001, batch_size=167,
        confidence='official refine_wordIntrusion: fraction of original top words retained',
        transport='POT emd2, uniform teacher word mass, BGE cosine cost',
        refinement_optimizer_steps=refinement_steps, nonzero_refinement_gradients=nonzero_gradients,
        deviations=['Qwen/BGE replace original LLM and GloVe50',
            'refresh LLM feedback every five epochs; OT feedback every minibatch',
            'Gaussian reparameterization and softmax transport mass repair repository numerical defects',
            'CountVectorizer corpus vocabulary rather than preprocessed public benchmark vocabulary']),
        probabilities, [str(k) for k in range(K)])


def run(name, args):
    target = args.root / 'methods' / name / 'result.json'
    if target.exists():
        cached = read(target)
        assert cached['input_hash'] == digest(read(args.root / 'inputs.json'))
        if cached.get('version') != VERSION or cached['metadata'].get('model') != MODEL:
            raise ValueError('Cached method result belongs to another model/version; use the new experiment root')
        log('method_cached', method=name)
        return
    start = time.monotonic()
    globals()[name](args)
    result = read(target)
    result['wall_seconds'] = time.monotonic() - start
    write(target, result)


def calibrated_predictions(X, y, folds):
    """Held-out labels never enter the topic-to-area contingency table."""
    classes = np.unique(y)
    predictions = np.full(len(y), '', dtype=object)
    Y = (y[:, None] == classes[None, :]).astype(float)
    for train, test in folds:
        counts = X[train].T @ Y[train]
        distribution = counts / np.maximum(counts.sum(1, keepdims=True), 1e-12)
        scores = X[test] @ distribution
        fallback = classes[np.argmax(Y[train].sum(0))]
        predicted = classes[scores.argmax(1)].astype(object)
        predicted[scores.sum(1) == 0] = fallback
        predictions[test] = predicted
    return predictions


def bootstrap_accuracy(truth, predictions, replicates=2000):
    correct = truth == predictions
    rng = np.random.default_rng(SEED)
    groups = [np.flatnonzero(truth == c) for c in np.unique(truth)]
    means = np.array([np.concatenate([rng.choice(g, len(g), replace=True) for g in groups]) for _ in range(replicates)])
    return np.quantile(correct[means].mean(1), [.025, .975]).tolist()


def semantic_predictions(name, result, features, topic_ids, inputs, years, schemas, qwen):
    """Gold-blind mapping reads generated topic paths, never original abstracts or labels."""
    byid = {n['id']: n for n in result['nodes']}
    def path(nid, visiting=()):
        if nid in visiting:
            raise ValueError('Cycle')
        n = byid[nid]
        if n.get('container'):
            return ''
        parents = [path(p, visiting + (nid,)) for p in n['parent_ids']]
        prefix = ' / '.join(p for p in parents if p)
        return (prefix + ' -> ' if prefix else '') + n['name']
    rows = []
    for i, paper in enumerate(inputs):
        active = np.flatnonzero(features[i] > 0)
        # Flat models expose their native top1 output; taxonomy models expose all terminal memberships.
        if name in ('lisa', 'itl') and len(active):
            active = np.array([features[i].argmax()])
        descriptors = [dict(facet=byid[topic_ids[j]]['facet'], path=path(topic_ids[j]),
                            description=byid[topic_ids[j]]['description']) for j in active]
        rows.append(dict(index=i, topics=descriptors))
    predictions = np.full(len(inputs), '__unmapped__', dtype=object)
    for year in sorted(set(years)):
        area_keys = sorted(schemas[str(year)])
        options = {str(i): schemas[str(year)][key] for i, key in enumerate(area_keys)}
        indices = [i for i, y in enumerate(years) if y == year and rows[i]['topics']]
        batches = [indices[start:start + 6] for start in range(0, len(indices), 6)]
        prompts = ['Map generated scientific topic descriptions to one official primary research area per item. '
            'Use only the supplied generated topics; no original papers or true labels are provided. '
            'Choose the dominant research subject. Return JSON {"predictions":{"item index":area option integer,...}}. '
            'Official area options: ' + json.dumps(options) + '\nItems: ' + json.dumps([rows[i] for i in batch])
            for batch in batches]
        schema = dict(type='object', properties={'predictions': dict(type='object',
            additionalProperties={'type': 'integer', 'minimum': 0, 'maximum': len(area_keys) - 1})},
            required=['predictions'], additionalProperties=False)
        answers = qwen.map('evaluation_semantic_' + name, prompts, 256, schema)
        for batch, answer in zip(batches, answers):
            if set(answer['predictions']) != set(map(str, batch)):
                raise ValueError('Semantic evaluator omitted/added an item')
            for i in batch:
                predictions[i] = area_keys[answer['predictions'][str(i)]]
    return predictions


def evaluate(args):
    import psycopg
    inputs, gold = read(args.root / 'inputs.json'), read(args.root / 'evaluation/gold.json')
    assert [p['paper_id'] for p in inputs] == [p['paper_id'] for p in gold]
    y = np.array([p['area'] for p in gold])
    years = np.array([p['year'] for p in gold])
    schemas_path = args.root / 'evaluation/year_area_schemas.json'
    if not schemas_path.exists():
        with psycopg.connect(args.database_url) as conn:
            rows = conn.execute('''SELECT DISTINCT v.year, ea.canonical_key, ea.raw_label
                FROM core.venue v JOIN core.paper p USING(venue_id)
                JOIN core.paper_area pa USING(paper_id) JOIN core.explicit_area ea USING(explicit_area_id)
                WHERE pa.is_primary ORDER BY v.year,ea.canonical_key''').fetchall()
        schemas = defaultdict(dict)
        for year, area, label in rows:
            schemas[str(year)][area] = label
        write(schemas_path, schemas)
    schemas = read(schemas_path)
    folds = list(StratifiedKFold(5, shuffle=True, random_state=SEED).split(np.zeros(len(y)), y))
    write(args.root / 'evaluation/folds.json', [dict(train=train.tolist(), test=test.tolist()) for train, test in folds])
    qwen = Qwen(args.root, args.concurrency)
    results, saved_predictions = {}, {}
    for name in args.methods:
        directory = args.root / 'methods' / name
        result = read(directory / 'result.json')
        assert result['input_hash'] == digest(inputs)
        data = np.load(directory / 'representations.npz')
        assert data['paper_ids'].tolist() == [p['paper_id'] for p in inputs]
        topic_ids, X = data['topic_ids'].tolist(), data['features']
        pred_cv = calibrated_predictions(X, y, folds)
        semantic = semantic_predictions(name, result, X, topic_ids, inputs, years, schemas, qwen)
        covered = X.sum(1) > 0
        cluster_ids = np.where(covered, X.argmax(1), -1)
        metrics = dict(semantic_L1_accuracy=float(accuracy_score(y, semantic)),
            semantic_L1_macro_f1=float(f1_score(y, semantic, average='macro', labels=np.unique(y), zero_division=0)),
            semantic_accuracy_95ci=bootstrap_accuracy(y, semantic),
            cv5_L1_accuracy=float(accuracy_score(y, pred_cv)),
            cv5_L1_macro_f1=float(f1_score(y, pred_cv, average='macro', zero_division=0)),
            cv5_accuracy_95ci=bootstrap_accuracy(y, pred_cv),
            nmi=float(normalized_mutual_info_score(y, cluster_ids)),
            ari=float(adjusted_rand_score(y, cluster_ids)), coverage=float(np.mean(covered)),
            actual_used_topics=len(np.unique(cluster_ids[covered])),
            structure={k: v for k, v in result['structure'].items() if k != 'levels'},
            by_year={str(year): dict(n=int(sum(years == year)),
                semantic_accuracy=float(accuracy_score(y[years == year], semantic[years == year])),
                cv5_accuracy=float(accuracy_score(y[years == year], pred_cv[years == year]))) for year in sorted(set(years))},
            by_area={area: dict(n=int(sum(y == area)),
                semantic_accuracy=float(accuracy_score(y[y == area], semantic[y == area])),
                cv5_accuracy=float(accuracy_score(y[y == area], pred_cv[y == area]))) for area in sorted(set(y))})
        write(args.root / f'evaluation/{name}_metrics.json', metrics)
        predictions = [dict(paper_id=p['paper_id'], year=int(year), gold=truth,
            semantic_prediction=sem, cv5_prediction=cv, topic_ids=[topic_ids[j] for j in np.flatnonzero(X[i] > 0)],
            top1_topic=topic_ids[int(X[i].argmax())] if covered[i] else None)
            for i, (p, year, truth, sem, cv) in enumerate(zip(inputs, years, y, semantic, pred_cv))]
        write(args.root / f'evaluation/{name}_predictions.json', predictions)
        results[name], saved_predictions[name] = metrics, semantic
        log('evaluated', method=name, semantic_accuracy=metrics['semantic_L1_accuracy'], cv5_accuracy=metrics['cv5_L1_accuracy'])
    write(args.root / 'evaluation/comparison.json', results)
    lines = [f'# S4: {len(inputs)}-paper controlled reproduction ({MODEL}, {REASONING_EFFORT})', '',
        'These are controlled model adaptations, not original-model leaderboard results. ',
        'The corpus is transductive and balanced by year/area. Author L1 labels are evaluation targets, not expert fine-topic gold.', '',
        '| Method | L1 semantic accuracy | L1 CV5 calibration accuracy | NMI | ARI | Coverage | Depth | Level widths | Mean branching |',
        '|---|---:|---:|---:|---:|---:|---:|---|---:|']
    for name, m in results.items():
        s = m['structure']
        lines.append(f"| {name} | {m['semantic_L1_accuracy']:.1%} | {m['cv5_L1_accuracy']:.1%} | {m['nmi']:.3f} | {m['ari']:.3f} | {m['coverage']:.1%} | {s['depth']} | {json.dumps(s['widths'])} | {s['mean_branching']:.2f} |")
    lines += ['', f'Semantic accuracy maps generated topic paths/descriptions to that year’s official area choices, with {MODEL} and no original text or gold labels. ',
        'CV5 accuracy fits topic→area probability tables on four folds and scores only the fifth; topic discovery itself uses the full unlabeled corpus. ',
        'Flat models remain depth 1. Artificial dimension/root nodes are excluded from semantic depth and widths. ',
        'NMI/ARI use hard top1 topic; uncovered papers receive a shared missing-topic category. ',
        'See evaluation/*_metrics.json for bootstrap 95% intervals and year/area slices; methods/*/result.json records implementation deviations.']
    (args.root / 'REPORT.md').write_text('\n'.join(lines) + '\n')
