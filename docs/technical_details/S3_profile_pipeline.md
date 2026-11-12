# S3 全量论文 Profile 生成：字段血缘、模型与 Prompt

> 当前进度补记（2026-11-12）：本文保留原实验/发布当时的协议与统计；其后已完成独立单篇 Web 审稿与任务恢复。当前汇总见 [STATUS](../STATUS.md)，新任务模型配置和部署见 [DEPLOYMENT](../DEPLOYMENT.md)。文末尚未集成 Web 的描述属于历史时点。

状态：`进行中`

本文记录 `paper_understanding_v1` 的真实生产实现。实现入口是
[`../../scripts/paper_understanding_pipeline.py`](../../scripts/paper_understanding_pipeline.py)，
模型方法复用
[`../../benchmarks/paper_understanding/benchmark.py`](../../benchmarks/paper_understanding/benchmark.py)。

## 1. 核心结论

`semantic.paper_profile.profile` 由模型根据论文证据
生成的结构化 JSON：

- `evidence[].quote` 目标是原文短引文，之后由 Python 在完整 Markdown 中定位；
- statement、summary、method、claim、risk 等都是模型抽取、改写、归纳或推断；
- 只有 `limitations[].source` 显式区分 `author` 与 `inferred`；
- 其他字段虽然 prompt 要求区分作者陈述和推断，但 schema 没有保存这种区分，这是当前
  `v1` 的数据血缘缺口；
- `provenance`、输入 hash、证据位置、质量指标和运行元数据由 Python 确定性生成。

## 1.1 生产路线的选择依据

S3 采用项目内比较选定的抽取策略。S2 在相同 50 篇论文上比较了项目内实现的 one-shot、
section-grounded hierarchical 和 DocETL-style 三条路线：

| 方法 | 综合分 | 胜出 | Token/篇 | 秒/篇 | S3 角色 |
|---|---:|---:|---:|---:|---|
| one-shot | 4.5067/5 | 22 | 18,013.6 | 60.466 | 默认 |
| hierarchical | 4.5067/5 | 21 | 62,613.6 | 194.728 | evidence/schema 失败时 fallback |
| DocETL-style | 4.0333/5 | 7 | 49,949.9 | 159.318 | 不采用 |

one-shot 与 hierarchical 的 paired 95% bootstrap CI 为 `[-0.1833, 0.1833]`，没有观察到
平均质量差异；one-shot 只使用 hierarchical 约 28.8% 的 token。hierarchical 的 correctness
和 evidence grounding 更高，因此保留为规则触发的补救路径。DocETL-style 在本次简化实现中
质量更低且成本更高，不进入生产。

方法实现、完整 Prompt、六维评分、分组稳健性和局限见
[`S2_understanding_benchmark.md`](S2_understanding_benchmark.md)。评价范围为当前模型、schema、Prompt 和样本配置。

## 2. 原始输入

数据库读取：

- `core.latest_paper_version`：title、abstract、keywords；
- `core.paper` / `core.venue`：year、accepted_main、forum_id；
- primary explicit area；
- Markdown artifact 路径；
- `semantic.paper_fulltext_index`：token count、headings、routing signals。

真正进入模型 prompt 的只有：

1. title；
2. abstract；
3. keywords；
4. 从 Markdown 生成的 section evidence。

year、accepted_main 和 area 用于构建均衡执行顺序，不进入 prompt，因此不会直接告诉模型
论文是否录用。

有 Markdown 时 `source_mode=markdown`。没有 Markdown 时只构造：

```text
# <title>

## Abstract
<abstract>
```

并标记 `source_mode=metadata_only`。当前已入库样本均为 Markdown；175 篇缺失 Markdown 的
论文被排在 manifest 最后，最终质量需要单独报告。

## 3. 确定性分段和截断

headings 按字符位置排序，再用标题关键词映射：

| 分组 | 标题关键词 |
|---|---|
| framing | abstract, introduction, background, related work, motivation |
| method | method, approach, framework, architecture, algorithm, model |
| evidence | experiment, evaluation, result, analysis, ablation, dataset, benchmark |
| conclusion | conclusion, discussion, limitation, broader impact, ethic |

reference/bibliography 被排除；不匹配关键词的标题段不会进入模型输入。若一个匹配段超过
15,000 字符，保留前 72% 和后 28%，中间插入 `[...] middle omitted [...]`。若完全没有可识别
标题，则把全文等分为四段，分别作为四个分组。

one-shot/audit 的最终 evidence pack 再按分组限制：

| 分组 | 最大字符数 |
|---|---:|
| framing | 18,000 |
| method | 24,000 |
| evidence | 28,000 |
| conclusion | 10,000 |

因此“one-shot 全文”准确含义是“一次读取确定性筛选和截断后的跨章节 evidence pack”，
模型接收按上述规则构建的证据包。

## 4. 模型和 API 参数

生产 profile 实际记录的模型全部是 `gpt-5.6-luna`。

- API：OpenAI-compatible Responses endpoint，`POST <base_url>/responses`；
- payload：`model`、`input`、`max_output_tokens`；
- one-shot、综合和审计：`max_output_tokens=4200`；
- hierarchical 分组抽取：每组 `max_output_tokens=2600`；
- 未显式设置 temperature、top_p、seed 或 reasoning 参数，使用服务端默认值；
- 无工具调用，无网络检索，无论文外部知识库；
- JSON 解析失败时，用同一个弱模型执行一次 JSON repair；
- 强模型 `gpt-5.6-sol` 只用于 S2 的 50 篇匿名方法盲评，不用于 S3 生产。

## 5. Profile Schema

```json
{
  "summary": "<=120 words",
  "research_problem": {"statement": "", "evidence": [{"section_id": "S01", "quote": ""}], "confidence": 0.0},
  "motivation": {"statement": "", "evidence": [], "confidence": 0.0},
  "prior_work_gap": {"statement": "", "evidence": [], "confidence": 0.0},
  "key_insight": {"statement": "", "evidence": [], "confidence": 0.0},
  "contributions": [{"statement": "", "evidence": [], "confidence": 0.0}],
  "method": {"overview": "", "components": [""], "mechanism_chain": [""], "assumptions": [""]},
  "claims": [{"claim": "", "support_level": "strong|partial|weak|not_evaluated", "evidence": []}],
  "experiments": {
    "datasets": [""], "baselines": [""], "metrics": [""],
    "main_results": [{"statement": "", "evidence": []}],
    "ablations": [{"statement": "", "evidence": []}]
  },
  "limitations": [{"statement": "", "evidence": [], "source": "author|inferred"}],
  "review_risks": [{"statement": "", "evidence": [], "severity": "low|medium|high"}],
  "research_type": ["empirical|theoretical|dataset|benchmark|system|analysis|application"]
}
```

## 6. 字段级来源和推断方法

| 字段 | 来源类型 | 模型如何产生 | 当前可追溯性 |
|---|---|---|---|
| `summary` | 模型归纳 | 压缩问题、方法、实验和结论为 <=120 words | 无逐句 evidence |
| `research_problem` | 模型抽取+改写 | 从引言/摘要识别待解决问题并改写为统一陈述 | statement 配 quote，但未标 author/inferred |
| `motivation` | 模型归纳 | 从重要性、应用需求和现有困难中综合动机 | 配 quote；允许空 |
| `prior_work_gap` | 模型跨段推断 | 对 related work 和作者定位做差距归纳 | 配 quote；不独立验证相关工作真实性 |
| `key_insight` | 模型推断 | 将方法区别压缩为核心概念性步骤 | 配 quote，保留模型概括来源 |
| `contributions[]` | 模型抽取+去重 | 识别作者贡献列表或从方法/结果综合贡献 | 每项可配 quote，但空 evidence 仍可能通过 v1 |
| `method.overview` | 模型综合 | 把方法章节压缩成整体描述 | 无字段级 evidence |
| `method.components[]` | 模型抽取 | 识别模块、数据处理、训练目标和输出 | 无逐项 evidence |
| `method.mechanism_chain[]` | 模型因果式重排 | 将方法描述重写为顺序执行链 | 无逐项 evidence，可能包含解释性推断 |
| `method.assumptions[]` | 模型抽取或推断 | 识别显式假设，也可能推导隐含前提 | 无 source/evidence 标签，风险较高 |
| `claims[]` | 模型抽取+判断 | 识别论文关键 claim，并根据论文内部证据分配 support level | quote 可定位；support level 记录模型对论文内部证据的判断 |
| `experiments.datasets[]` | 模型抽取 | 从实验章节列数据集 | 无逐项 evidence |
| `experiments.baselines[]` | 模型抽取 | 从对比实验识别基线 | 无逐项 evidence |
| `experiments.metrics[]` | 模型抽取 | 从实验设计识别指标 | 无逐项 evidence |
| `experiments.main_results[]` | 模型抽取+摘要 | 提取主要数字或比较结论并改写 | 每项可配 quote；数字仍需原表复核 |
| `experiments.ablations[]` | 模型抽取+摘要 | 识别组件移除/替换/规模变化及结论 | 每项可配 quote |
| `limitations[]` | 模型抽取或审稿式推断 | 作者明确说明则 `author`；模型从边界条件推导则 `inferred` | v1 唯一明确保存推断来源的字段 |
| `review_risks[]` | 模型审稿推断 | 从未覆盖条件、比较公平性、统计、外部有效性等生成风险 | severity 为模型判断；evidence 应回指论文 |
| `research_type[]` | 模型多标签分类 | 在七个固定类型中选择多个 | Python 做 alias 归一化和非法值过滤 |
| 顶层 `confidence` | Python 派生 | 递归收集模型生成的所有 `confidence` 并取平均 | 记录模型自评均值；质量概率待校准 |
| `provenance` | Python 确定性生成 | 记录模型、方法、hash、token、evidence 定位、Gate 等 | 可审计 |

`support_level`、`severity` 和 `confidence` 没有单独的数值 rubric；它们由模型根据 prompt
和输入自由判断。不得把它们当作经过标定的概率或人工评审结论。

## 7. 生产 One-shot Prompt

下面是应用代码发送的完整模板；`PROFILE_SCHEMA`、header 和 evidence 在运行时展开。

```text
You extract a faithful structured profile from one scientific paper.
Analyze the paper in one pass.
Do not use outside knowledge. Distinguish explicit author statements from inference.
Every important statement must cite an exact short quote and section_id when evidence exists.
Use empty arrays or empty strings for unavailable information. Never invent results or limitations.
Return valid JSON only, exactly following this schema and keeping arrays concise:
{PROFILE_SCHEMA}

TITLE: {title}
ABSTRACT: {abstract}
KEYWORDS: {keywords_json}

PAPER EVIDENCE:
{evidence_pack}
```

## 8. Hierarchical Fallback Prompts

### 8.1 分组事实抽取

每个非空分组独立调用一次弱模型：

```text
Extract only evidence-grounded facts from the {group} portion of a scientific paper.
Return valid JSON only: {"facts":[{"type":"problem|motivation|gap|insight|contribution|method|assumption|claim|dataset|baseline|metric|result|ablation|limitation|risk","statement":"","evidence":[{"section_id":"S01","quote":"exact quote <=240 chars"}],"confidence":0.0}]}.
Do not infer facts unsupported by the supplied sections. Keep at most 16 high-value facts.

TITLE: {title}
ABSTRACT: {abstract}
KEYWORDS: {keywords_json}

SECTIONS:
{group_sections}
```

### 8.2 综合

把各组 facts 作为 `PAPER EVIDENCE`，使用完整 schema，并加入：

```text
Synthesize the section-level facts into one coherent profile. Preserve only evidence present in the partials.
```

### 8.3 审计和修复

再次提供 evidence pack 与候选 profile，并加入：

```text
Audit the candidate below against the paper, remove unsupported statements, repair missing evidence links, and return the corrected full profile.
CANDIDATE:
{synthesized_profile_json}
```

整个 fallback 仍只使用 `gpt-5.6-luna`。

## 9. JSON Repair Prompt

模型输出无法解析为 JSON 时，同一模型收到：

```text
Return only valid JSON for the requested schema. Repair this response:
{raw_model_response}
```

Repair 修复输出的可解析性；事实核验由后续证据审计完成。

## 10. 确定性后处理

### 10.1 类型归一化

`research_type` alias 由 Python 映射，例如 `experiment -> empirical`、
`datasets -> dataset`、`analytical -> analysis`。只允许：

```text
empirical, theoretical, dataset, benchmark, system, analysis, application
```

### 10.2 Schema 验证

验证根字段类型、四个 framing 字段的 statement/evidence、method 子字段、experiment 子字段
和 research_type 合法值。该验证只检查结构，不检查语义真假。

强制核心内容只有：

- `research_problem.statement` 非空；
- `key_insight.statement` 非空；
- `contributions` 非空；
- `method.overview` 非空。

### 10.3 Evidence 定位

Python 在完整原始 Markdown 上检查模型给出的 quote：

1. Unicode NFKC、casefold、空白归一化后尝试 exact match；
2. exact 失败后，从段落/句子候选中按词覆盖率选前 8；
3. 计算 `0.65 * sequence_coverage + 0.35 * word_recall`；
4. 分数 >=0.7 时记录 fuzzy match；否则 unresolved；
5. 保存 char_start、char_end、matched_text、method 和 score。

参与 item-level 证据率的字段只有 framing 四项、contributions、claims、main_results 和
ablations。summary、method、datasets、baselines、metrics、limitations 和 review_risks 不计入
当前核心证据率。

当前公式是：

```text
key_evidence_rate = 至少有一个 quote 成功定位的已引用 item / 有非空 evidence 的 item
```

完全没有 evidence 的 item 被单独计为 `uncited_key_items`，但没有进入分母。这会高估当前
报告的证据覆盖率，是 `v1` 已知缺陷。

## 11. 升级、选择和 needs_review

先运行 one-shot。以下任一条件触发 hierarchical：

- schema invalid；
- 核心必填内容缺失；
- item-level evidence rate < 0.6；
- research_problem、key_insight 或任一 contribution 没有 evidence。

one-shot 和 fallback 均通过 schema 时，选择 `key_evidence_rate` 更高者。

最终 `needs_review=true` 仅在：

- 选中结果的 evidence rate < 0.6；或
- 核心必填内容仍缺失。

因此“存在无引文核心字段但总 rate >=0.6”的结果可能未被标记，需要在下一版本修复。

## 12. 数据库存储

表：`semantic.paper_profile`

| 列 | 含义 |
|---|---|
| `paper_id` | `core.paper` 外键 |
| `profile_version` | 当前 `paper_understanding_v1` |
| `profile` | 模型最终 JSONB |
| `confidence` | Python 计算的模型 confidence 均值 |
| `provenance` | 确定性运行和证据元数据 |

`provenance` 包括 input hash、policy/model、selected method、fallback 原因、source mode、
artifact id、token、每次 attempt 的耗时和 token、evidence metrics/locations、needs_review、
阈值和创建时间。

upsert 只有在同一 version 的 `input_hash` 变化时才更新；相同输入重复运行返回 skipped。

## 13. 当前质量快照与已知风险

2026-10-14、流水线运行期间的只读抽查：

- 已有约 23.8k 个 profile；
- 报告 item-level evidence rate 约 91.5%；
- 把无 evidence item 纳入分母后约 90.2%；
- 约 7.9% profile 至少有一个核心 item 无 evidence；
- 顶层平均 confidence 约 0.965，但与 evidence rate 的相关系数约 -0.029；
- confidence 按模型自评分记录，校准需独立质量标注；
- exact/fuzzy 检查 quote 的原文位置，语义支持需单独判定；
- method、datasets、baselines、metrics、assumptions 等缺少逐项 evidence；
- 175 篇 metadata-only 论文尚未进入当前质量分布；
- API 超时、429、断连等失败需要重试，不应与内容质量失败混为一类。

S3 最终 Gate 前应至少：将 uncited item 纳入证据分母、加强核心字段 `needs_review` 规则、
对 metadata-only 单列质量、重试失败样本，并做独立人工抽检。
