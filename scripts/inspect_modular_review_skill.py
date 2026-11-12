#!/usr/bin/env python3
"""Render the completed pilot into evidence-linked inspection documents; no API calls."""
import argparse
from collections import Counter, defaultdict
from pathlib import Path

import audit_modular_review_skill as audit
import modular_review_skill as s


def render(root):
    checked=audit.audit(root)
    s.write(root/'AUDIT.json',checked)
    manifest=s.read(root/'manifest.json');library=s.read(root/'rule_library.json')
    cases=['# 100 篇历史论文：逐篇凝练结果','',
           '以下状态是模型对历史意见及部分正文的解释，不代表人工核实。原文与字符位置在各篇冻结输入中。','']
    areas=defaultdict(Counter);hist=Counter();coverage=[]
    for pid in manifest['source_ids']:
        source=s.read(root/f'inputs/{pid}.json');extracted=s.read(root/f'cases/{pid}.json')
        area=source['area'];areas[area]['papers']+=1;areas[area]['atomic_cases']+=len(extracted['cases'])
        areas[area]['candidate_checks']+=len(extracted['candidate_checks'])
        request=s.read(root/f'requests/extract/{pid}/request.json')['body']
        supplied=s.json.loads(request['input'])['data']['paper']['paper_passages']
        coverage.append(sum(len(p['text']) for p in supplied)/source['coverage']['manuscript_chars'])
        cases += [f'## {pid}：{source["title"]}','',f'{source["year"]} · {area}',
                  f'[冻结正文与初始 Review](inputs/{pid}.json) · [结构化案例](cases/{pid}.json)','']
        for c in extracted['cases']:
            hist[c['historical_status']]+=1
            cases += ['- **'+c['case_id']+' / '+c['kind']+' / '+c['historical_status']+'**：'+c['observation'],
                      '  Review：'+', '.join(c['review_evidence_ids'])+'；正文：'+(', '.join(c['paper_evidence_ids']) or '未配对')]
        cases += ['','候选规则：','']
        for n,c in enumerate(extracted['candidate_checks'],1):
            cases += [f'- **{pid}:K{n} · {c["title"]}**（{c["level"]}；'+', '.join(c['scope_terms'])+'）',
                      '  适用：'+c['applies_when']+'；检查：'+'；'.join(c['steps']),
                      '  成立：'+c['issue_when']+'；消除：'+c['cleared_when'],
                      '  影响：'+c['significance']+'；例外：'+'；'.join(c['exceptions'])]
        cases.append('')
    (root/'CASES.md').write_text('\n'.join(cases))
    modules=s.read(root/'registry.json')['modules']
    lines=['# 可组合审稿模块','',
           '只编译具有独立配对来源支持的规则；科学正确性仍待检查。候选与停用规则保留在完整规则库中。','',
           '| 模块 | 规则数 | 规则 ID |','|---|---:|---|']
    for module in modules:
        lines.append(f'| [{module["module_id"]}]({module["path"]}) | {len(module["rule_ids"])} | '+', '.join(module['rule_ids'])+' |')
    lines+=['','## 五篇试审的实际组合','', '| 论文 | 加载规则 | 模块 |','|---|---|---|']
    application=Counter();target_rule_sets=set()
    for pid in manifest['target_ids']:
        route=s.read(root/f'compositions/{pid}.json');review=s.read(root/f'reviews/{pid}/review.json')
        target_rule_sets.add(tuple(sorted(route['rule_ids'])))
        lines.append(f'| [{pid}](reviews/{pid}/REVIEW.md) | '+', '.join(route['rule_ids'])+' | '+
                     ', '.join(sorted({r['module_id'] for r in route['selection']}))+' |')
        application.update(a['disposition'] for a in review['rules_applied'])
    (root/'MODULES.md').write_text('\n'.join(lines)+'\n')
    changes=['# 规则增量更新记录','',
             '以下是对试运行候选库应用的局部变更，不是已发布的专家规则。原始操作、旧／新内容及版本哈希完整保留。','']
    types=Counter()
    for batch in s.read(root/'updates.json'):
        changes += [f'## 批次 {batch["batch"]}','',
                    '论文：'+', '.join(map(str,batch['source_ids'])),
                    f'接受 {len(batch["accepted"])} 项，拒绝 {len(batch["rejected"])} 项，当前批未处理候选 {len(batch["deferred_candidate_ids"])} 条。','']
        for entry in batch['accepted']:
            op=entry['operation'];types[op['type']]+=1
            changes+=['### '+op['type']+' · '+(', '.join(op['target_ids']) or '新增'),'',op['reason'],
                      '依据候选：'+', '.join(op['evidence_candidate_ids']),'']
            for rid,after in entry['after'].items():
                before=entry['before'].get(rid)
                if before:
                    changed=[k for k in ['title','level','scope_terms','applies_when','steps','issue_when','cleared_when','significance','exceptions','status']
                             if before[k]!=after[k]]
                    changes+=['变更字段：'+', '.join(changed),'']
                changes.append(s.rule_markdown(after))
        for entry in batch['rejected']:
            changes+=['拒绝：'+entry['error'],'']
    (root/'CHANGES.md').write_text('\n'.join(changes))
    summary=s.read(root/'summary.json')
    supported_levels=Counter(r['level'] for r in library['rules'].values() if r['status']=='source_supported')
    represented={cid for r in library['rules'].values() if r['status']!='deprecated' for cid in r['candidate_ids']}
    all_candidates=s.read(root/'candidates.json')
    summary.update(audit='passed',modules=len(modules),operation_types=dict(types),
                   historical_statuses=dict(hist),target_rule_dispositions=dict(application),
                   source_supported_levels=dict(supported_levels),distinct_target_rule_sets=len(target_rule_sets),
                   candidates_not_represented_in_active_rules=len(set(all_candidates)-represented),
                   recovered_without_inference=len(list(root.glob('requests/*/*/recovery.json'))),
                   mean_supplied_manuscript_char_fraction=sum(coverage)/len(coverage))
    s.write(root/'summary.json',summary)
    base=(root/'REPORT.md').read_text()
    marker='\n## 检查入口与结构统计\n'
    base=base.split(marker)[0]
    more=[marker,'',
          '[100 篇逐篇案例](CASES.md) · [可组合 Skill 与五篇路由](MODULES.md) · [逐批变更](CHANGES.md) · [执行审计](AUDIT.json)','',
          f'执行审计通过；来源支持模块 {len(modules)} 个；操作类型 {dict(types)}。',
          f'来源支持规则层次：{dict(supported_levels)}；五篇试审出现 {len(target_rule_sets)} 种不同规则集合。',
          f'{summary["candidates_not_represented_in_active_rules"]} 条候选尚未归入活跃规则，原始候选和逐篇卡片完整保留。',
          f'本地恢复 {summary["recovered_without_inference"]} 个结果：来源引用数量放宽与目标唯一引用缩写规范化分别记录。完整保留原始响应，无额外推理。',
          f'历史意见解释状态（模型标注，非准确率）：{dict(hist)}。',
          f'试审规则适用性（模型标注）：{dict(application)}。',
          f'来源稿证据包平均正文字符覆盖约 {100*sum(coverage)/len(coverage):.1f}%；这是覆盖量，不是证据质量。','',
          '| 领域 | 论文 | 原子意见 | 候选检查 |','|---|---:|---:|---:|']
    for area in s.AREAS:
        c=areas[area];more.append(f'| {area} | {c["papers"]} | {c["atomic_cases"]} | {c["candidate_checks"]} |')
    more+=['','**本轮局限：6 条来源支持规则中有 5 条通用规则和 1 条消融方法规则；领域、任务与专属规则仍在候选阶段。** '
           '五篇新稿仅形成两种规则集合，尚未展示充分的领域专业化。8 条试审 concern 均标为待核实，部分来自材料覆盖不足。'
           '五篇评分均为 6，置信度为 1/5 或 2/5；这些输出不能证明区分论文质量的能力或审稿质量提升。']
    more+=['','本轮产物是待检查的初始审稿经验库。缺少独立纠错反馈时，不将模型自评或试审意见写回冻结规则。','']
    (root/'REPORT.md').write_text(base+'\n'.join(more))
    return summary


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root',type=Path,default=s.ROOT)
    args=parser.parse_args()
    print(s.json.dumps(render(args.root),ensure_ascii=False,indent=2))
