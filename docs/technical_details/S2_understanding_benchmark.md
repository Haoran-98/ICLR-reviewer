# S2 论文理解方法评测与生产方案选择

状态：`已完成`

本阶段为 S3 选择结构化论文理解方法。比较对象、Prompt、模型、样本和评测代码均固定；
embedding、聚类、taxonomy assignment 和下游 Twin 不属于本阶段。

## 1. 方法来源声明

三种方法都不是仓库中某篇顶会论文的直接复现：

- `one_shot` 是项目内实现的通用 LLM 结构化抽取；
- `grounded_hierarchical` 是项目内实现的分组抽取、综合和证据审计流程；
- `docetl_style` 只表示“先规划 extraction operations，再执行和合并”的 DocETL 风格候选，
  没有使用 DocETL 官方库、完整算子系统或论文评测协议。

Profile schema、Prompt、分段规则、0.6/0.7/0.9 阈值和质量 Gate 都是本项目的工程设计，
不是从某篇论文直接取得或由理论推导。相关方法可在论文写作时补充 related work，但当前实现
不能表述为对指定论文方法的忠实复现。

## 2. 公平比较条件

- 50 篇 ICLR 2024-2026 主会论文；
- 年份配额：2024=17、2025=17、2026=16；
- 每年平衡 accepted/rejected，总计 accepted=24、rejected=26；
- 在每个年度/录用状态内继续按显式领域和正文长度分桶；
- short `<6000` tokens，medium `<11000`，其余为 long；
- 固定随机种子 `1701`；
- 三种方法读取相同 title、abstract、keywords 和相同 Markdown section groups；
- 抽取统一使用 `gpt-5.6-luna`；
- 每种方法完成 50/50，无失败样本被排除；
- 结果由 `gpt-5.6-sol` 逐篇匿名盲评。

## 3. 方法 A：One-shot Structured Extraction

### 3.1 流程

```text
title + abstract + keywords
          +
framing/method/evidence/conclusion evidence pack
          |
          v
gpt-5.6-luna 单次生成完整 profile JSON
```

### 3.2 调用和 Prompt

- 正常情况 1 次模型调用；
- `max_output_tokens=4200`；
- JSON 无法解析时允许同一模型增加 1 次 JSON repair；
- 模型同时完成字段识别、跨章节综合、claim/evidence 选择、限制和风险推断。

核心指令：

```text
You extract a faithful structured profile from one scientific paper.
Analyze the paper in one pass.
Do not use outside knowledge. Distinguish explicit author statements from inference.
Every important statement must cite an exact short quote and section_id when evidence exists.
Use empty arrays or empty strings for unavailable information. Never invent results or limitations.
Return valid JSON only, exactly following this schema and keeping arrays concise.
```

### 3.3 预期优缺点

- 优点：调用少、全局上下文一致、成本和延迟最低；
- 风险：单次生成承担所有任务，局部证据可能遗漏或被跨段归纳过度；
- 适合：schema 完整且证据定位通过的大多数论文。

## 4. 方法 B：Section-grounded Hierarchical Extraction

### 4.1 流程

```text
framing --------> facts
method ----------> facts
evidence --------> facts  -> synthesis -> full-evidence audit -> final profile
conclusion ------> facts
```

### 4.2 Map 阶段

每个非空分组并行调用 `gpt-5.6-luna`，最多四次，每组 `max_output_tokens=2600`。
每组最多保留 16 个高价值事实，类型限制为 problem、motivation、gap、insight、
contribution、method、assumption、claim、dataset、baseline、metric、result、ablation、
limitation 和 risk。

核心指令：

```text
Extract only evidence-grounded facts from the {group} portion of a scientific paper.
Do not infer facts unsupported by the supplied sections.
Keep at most 16 high-value facts.
```

### 4.3 Synthesis 阶段

把各组 facts 作为输入，再调用一次模型生成完整 schema，`max_output_tokens=4200`：

```text
Synthesize the section-level facts into one coherent profile.
Preserve only evidence present in the partials.
```

### 4.4 Audit 阶段

将 synthesis 结果和原 evidence pack 一并交给同一模型审计，`max_output_tokens=4200`：

```text
Audit the candidate below against the paper, remove unsupported statements,
repair missing evidence links, and return the corrected full profile.
```

正常 Markdown 最多是 4 次 map + 1 次 synthesis + 1 次 audit，共 6 次调用；某分组为空时
相应 map 不调用。JSON repair 仍可能额外增加调用。

### 4.5 预期优缺点

- 优点：局部证据抽取更集中，最后还有完整证据审计；
- 风险：调用多、成本高；map 阶段可能割裂跨章节关系，综合阶段可能丢失局部事实；
- 适合：one-shot schema/核心字段/证据检查失败，或需要严格 traceability 的论文。

## 5. 方法 C：DocETL-style Planned Extraction

### 5.1 流程

```text
headings
   |
   v
模型设计恰好 3 个 extraction operations
   |
   v
3 个 operation 并行抽取 facts
   |
   v
resolve duplicate/conflict -> final profile
```

### 5.2 Planner

1 次 `gpt-5.6-luna` 调用，`max_output_tokens=1000`。模型只能选择
`framing/method/evidence/conclusion`，并必须设计三个互补 operation：

```text
Design exactly three complementary extraction operations for this paper.
Cover framing, mechanism, empirical evidence, limitations and review risks without overlap.
```

如果计划不是恰好三个合法 operation，代码退回固定计划：framing、mechanism、validation。

### 5.3 Execute 与 Resolve

- 3 个 operation 并行执行，每个 `max_output_tokens=2800`；
- operation 使用与 hierarchical map 相同的 facts schema，并增加该 operation 的 focus；
- 最后 1 次 `max_output_tokens=4200` 调用解决重复和冲突，生成完整 profile；
- 正常共 1 planner + 3 execute + 1 resolve，即 5 次调用；没有 hierarchical 的独立
  full-evidence audit。

Resolve 指令：

```text
Resolve duplicate or conflicting operation results.
Prefer exact evidence, retain uncertainty, and produce the final profile.
```

### 5.4 预期优缺点

- 优点：理论上可按论文结构自适应设计抽取任务；
- 风险：规划本身消耗 token，operation 可能重复或遗漏，最终缺少独立证据审计；
- 本实现只是工程候选，不能代表 DocETL 官方方法的性能。

## 6. 匿名强模型评测

每篇论文的三种结果用 `paper_id` 派生的固定随机顺序映射为 `candidate_A/B/C`，强模型不知道
候选方法名。强模型看到同一 evidence pack 和三个完整 profile，输出 ranking、winner、
confidence、critical errors 及六个 1-5 分维度：

- correctness；
- completeness；
- evidence grounding；
- cross-section reasoning；
- factual restraint；
- usefulness for review。

核心 Judge Prompt：

```text
Compare each structured profile only against the supplied paper evidence.
Do not reward verbosity.
Penalize invented claims, altered numbers, vague evidence,
and failure to distinguish author-stated limitations from evaluator inference.
```

每篇方法综合分为六维等权平均。方法差异使用固定种子 `1701`、20,000 次 paired bootstrap
计算 95% 区间。

## 7. 完整结果

| 方法 | 胜出 | 综合 | 正确性 | 完整性 | Grounding | 跨章节 | 克制性 | 审稿可用性 | Exact quote | Token/篇 | 秒/篇 |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| one-shot | 22 | 4.5067 | 4.38 | 4.68 | 4.30 | 4.72 | 4.30 | 4.66 | 0.5406 | 18,013.6 | 60.466 |
| hierarchical | 21 | 4.5067 | 4.52 | 4.54 | 4.70 | 4.56 | 4.30 | 4.42 | 0.5477 | 62,613.6 | 194.728 |
| DocETL-style | 7 | 4.0333 | 3.92 | 4.38 | 3.56 | 4.34 | 3.74 | 4.26 | 0.4658 | 49,949.9 | 159.318 |

成本关系：

- one-shot token 约为 hierarchical 的 28.8%；
- one-shot 延迟约为 hierarchical 的 31.1%；
- one-shot token 约为 DocETL-style 的 36.1%；
- one-shot 延迟约为 DocETL-style 的 38.0%。

`Exact quote` 只计算空白归一化后的原文精确包含，不包括 S3 生产中的 fuzzy match，因此不能
与 S3 的 item-level evidence location rate 直接比较。

## 8. Paired Bootstrap

| 差值 | Mean | 95% CI | 解释 |
|---|---:|---:|---|
| one-shot - hierarchical | 0.0000 | [-0.1833, 0.1833] | 无法证明二者质量存在差异 |
| one-shot - DocETL-style | 0.4733 | [0.2700, 0.6900] | 本样本中 one-shot 明显更好 |
| hierarchical - DocETL-style | 0.4733 | [0.2400, 0.7167] | 本样本中 hierarchical 明显更好 |

## 9. 分组稳健性

### 按年份胜出

| 年份 | one-shot | hierarchical | DocETL-style |
|---|---:|---:|---:|
| 2024 | 10 | 7 | 0 |
| 2025 | 6 | 8 | 3 |
| 2026 | 6 | 6 | 4 |

### 按录用状态胜出

| 状态 | one-shot | hierarchical | DocETL-style |
|---|---:|---:|---:|
| rejected | 12 | 12 | 2 |
| accepted | 10 | 9 | 5 |

### 按正文长度胜出

| 长度 | one-shot | hierarchical | DocETL-style |
|---|---:|---:|---:|
| short | 6 | 7 | 2 |
| medium | 6 | 4 | 4 |
| long | 10 | 10 | 1 |

没有观察到“长论文必须使用 hierarchical”的证据，因此正文长度不作为生产升级条件。

## 10. 选择矩阵

| 决策维度 | one-shot | hierarchical | DocETL-style |
|---|---|---|---|
| 综合质量 | 与 hierarchical 并列最高 | 与 one-shot 并列最高 | 明显较低 |
| 正确性/Grounding | 稍弱 | 最强 | 最弱 |
| 完整性/跨章节/审稿可用性 | 最强 | 稍低 | 较低 |
| Token 和延迟 | 最低 | 最高 | 较高 |
| 生产角色 | 默认主路径 | 证据失败 fallback | 不采用 |

最终策略不是简单选择单一赢家，而是组合两条互补路径：

```text
one-shot 默认
-> Python schema/核心字段/evidence 检查
-> 通过：保存
-> 未通过：hierarchical fallback
-> 仍未通过：needs_review
```

选择理由：one-shot 在平均质量上没有显著弱于 hierarchical，同时成本约为其 29%；
hierarchical 的 correctness 和 grounding 更高，适合只在确定性检查失败时补救。

## 11. 证据强度与局限

- 样本只有 50 篇，不足以证明对全部 38,890 篇和所有领域都最优；
- Judge 是 `gpt-5.6-sol`，不是人工金标准；平均 Judge confidence 为 0.875；
- 没有多人类标注者、inter-annotator agreement 或重复模型运行稳定性；
- Exact quote match 不证明引文在语义上支持 statement；
- 比较只针对当前模型、Prompt、分段、schema 和 token budget；任一项改变都应重新评测；
- DocETL-style 是本项目的简化实现，结果不能外推到正式 DocETL 系统；
- 0.6 fallback、0.7 fuzzy 和 0.9 aggregate Gate 是工程阈值，尚未通过独立校准集优化。

因此，这份结果是当前生产路线的工程选择依据，不是通用科学结论。

## 12. 可复现入口

```bash
python3 benchmarks/paper_understanding/benchmark.py self-test
python3 benchmarks/paper_understanding/benchmark.py sample
python3 benchmarks/paper_understanding/benchmark.py run --resume --workers 3
python3 benchmarks/paper_understanding/benchmark.py judge --resume --workers 3
python3 benchmarks/paper_understanding/benchmark.py report
```

实现和结果：

- [`../../benchmarks/paper_understanding/benchmark.py`](../../benchmarks/paper_understanding/benchmark.py)
- [`../../benchmarks/paper_understanding/selected_pipeline.json`](../../benchmarks/paper_understanding/selected_pipeline.json)
- [`../../benchmarks/paper_understanding/50_paper_summary.json`](../../benchmarks/paper_understanding/50_paper_summary.json)
- [`../../benchmarks/paper_understanding/50_paper_report.md`](../../benchmarks/paper_understanding/50_paper_report.md)
