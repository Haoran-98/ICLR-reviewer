#!/usr/bin/env python3
"""Export original paper-rooted trees without Kimi, merging or semantic repair."""
import argparse
from collections import Counter
from datetime import datetime
import hashlib
import json
from pathlib import Path

try:
    from .deployment_paths import storage_path
except ImportError:
    from deployment_paths import storage_path
from zoneinfo import ZoneInfo


PROVIDERS = ('deepseek', 'openai', 'qwen')
DEFAULT_SOURCE = storage_path('iclr-s4/experiments/taxonomy_llm4_gpt_200_v1')
DEFAULT_OUTPUT = storage_path('iclr-s4/experiments/taxonomy_llm3_paper_trees_200_v1')


def read(path):
    return json.loads(path.read_text())


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + '.tmp')
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n')
    temporary.replace(path)


def file_hash(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def build_tree(paper_id, title, generated):
    """Local IDs remain unchanged; source-qualified export IDs prevent collisions."""
    root = {'paper_id': paper_id, 'name': title, 'level': 0, 'children': [],
            'generation_pruned': {}, 'generation_provenance': {}}
    for provider in PROVIDERS:
        value = generated[provider]
        root['generation_provenance'][provider] = value.get('_provenance', {})
        root['generation_pruned'][provider] = {
            'nodes': [node for level in (1, 2, 3) for node in value[str(level)]
                      if node['status'] == 'pruned'],
            'branches': {str(level): value.get(f'pruned_{level}', []) for level in (1, 2, 3)}}
        previous = {}
        for level in (1, 2, 3):
            current = {}
            seen = set()
            for node in value[str(level)]:
                if node['node_id'] in seen:
                    raise ValueError(f'Duplicate node ID: {paper_id}/{provider}/{level}')
                seen.add(node['node_id'])
                if node['status'] not in ('candidate', 'pruned'):
                    raise ValueError(f'Unknown node status: {paper_id}/{provider}/{node["node_id"]}')
                if node['status'] == 'pruned':
                    continue
                if node.get('level') != level:
                    raise ValueError(f'Level mismatch: {paper_id}/{provider}/{node["node_id"]}')
                if level == 1 and node.get('parent_id') is not None:
                    raise ValueError(f'L1 has parent: {paper_id}/{provider}/{node["node_id"]}')
                if level > 1 and node.get('parent_id') not in previous:
                    raise ValueError(f'Missing original parent: {paper_id}/{provider}/{node["node_id"]}')
                copied = {**node, 'source_provider': provider,
                          'export_id': f'{paper_id}:{provider}:{level}:{node["node_id"]}',
                          'children': []}
                current[node['node_id']] = copied
                destination = root['children'] if level == 1 else previous[node['parent_id']]['children']
                destination.append(copied)
            previous = current
    return root


def tree_lines(root):
    def single_line(value):
        return ' '.join(value.split()).replace('```', "'''")

    yield single_line(root['name'])

    def children(nodes, prefix):
        for index, node in enumerate(nodes):
            last = index == len(nodes) - 1
            label = single_line(node['name'])
            yield f'{prefix}{"└── " if last else "├── "}[{node["source_provider"]} · L{node["level"]}] {label}'
            yield from children(node['children'], prefix + ('    ' if last else '│   '))

    yield from children(root['children'], '')


def export(source, output):
    if source.resolve() == output.resolve():
        raise ValueError('Use a separate export directory; never overwrite source artifacts')
    manifest = read(source / 'manifest.json')
    counts = Counter()
    entries = []
    output.mkdir(parents=True, exist_ok=True)
    markdown = [
        '# S4：逐篇原始三级标签树（不含 Kimi）\n',
        '每篇论文题目为根，下接 L1 → L2 → L3。来源标记不占层级。',
        '同名标签也保持独立；不做合并、语义修复或重新生成。',
        '生成阶段已标记 pruned 的输出保存在逐篇 JSON 的 generation_pruned 中，不挂入主树。',
        '以下展示原始候选标签，分类质量另行验收。\n']
    index = ['# S4 论文标签树索引\n', '[全部论文树](trees.md)\n',
             '| Paper ID | 论文题目 / 完整 JSON | L1 | L2 | L3 | 已标记 pruned |',
             '|---|---|---:|---:|---:|---:|']
    for paper in manifest['papers']:
        pid = paper['paper_id']
        raw_path = source / 'raw' / f'{pid}.json'
        generated_paths = {provider: source / 'generated' / provider / f'{pid}.json'
                           for provider in PROVIDERS}
        generated = {provider: read(path) for provider, path in generated_paths.items()}
        title = read(raw_path)['metadata']['title']
        tree = build_tree(pid, title, generated)
        tree['source_hashes'] = {'raw': file_hash(raw_path),
                                 **{provider: file_hash(path) for provider, path in generated_paths.items()}}
        tree['year'] = paper.get('year')
        local = Counter()
        for provider, value in generated.items():
            for level in (1, 2, 3):
                for node in value[str(level)]:
                    counts[(provider, level, node['status'])] += 1
                    local[f'L{level}' if node['status'] == 'candidate' else 'pruned'] += 1
        write(output / 'papers' / f'{pid}.json', tree)
        markdown.extend([f'## Paper {pid}\n', f'[完整 JSON（定义、证据和生成时排除记录）](papers/{pid}.json)\n',
                         '```text', *tree_lines(tree), '```\n'])
        safe_title = ' '.join(title.split()).replace('|', '\\|').replace('[', '\\[').replace(']', '\\]')
        index.append(f'| {pid} | [{safe_title}](papers/{pid}.json) | {local["L1"]} | {local["L2"]} | {local["L3"]} | {local["pruned"]} |')
        entries.append({'paper_id': pid, 'title': title, 'path': f'papers/{pid}.json', **local})
    for name, lines in (('trees.md', markdown), ('index.md', index)):
        temporary = output / (name + '.tmp')
        temporary.write_text('\n'.join(lines) + '\n')
        temporary.replace(output / name)
    result = {'version': output.name, 'created_at': datetime.now(ZoneInfo('Asia/Shanghai')).isoformat(timespec='seconds'),
              'source_root': str(source.resolve()), 'source_manifest_sha256': file_hash(source / 'manifest.json'),
              'providers': list(PROVIDERS), 'excluded_providers': ['kimi'], 'papers': len(entries),
              'policy': 'original_candidate_paths_no_merge_no_repair',
              'candidate_label_occurrences': sum(v for (_, _, status), v in counts.items() if status == 'candidate'),
              'generation_pruned_nodes': sum(v for (_, _, status), v in counts.items() if status == 'pruned'),
              'counts': {provider: {f'L{level}': {status: counts[(provider, level, status)]
                                                for status in ('candidate', 'pruned')}
                                    for level in (1, 2, 3)} for provider in PROVIDERS},
              'entries': entries}
    write(output / 'manifest.json', result)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source-root', type=Path, default=DEFAULT_SOURCE)
    parser.add_argument('--output-root', type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    result = export(args.source_root, args.output_root)
    print(json.dumps({key: result[key] for key in ('papers', 'candidate_label_occurrences', 'generation_pruned_nodes', 'providers')}, ensure_ascii=False))


if __name__ == '__main__':
    main()
