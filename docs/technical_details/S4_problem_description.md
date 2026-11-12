# S4 显式/隐式三级领域体系：问题描述

状态：`实施中；生产冻结依赖 S3`

批准的完整计划与例外以 [`S4_plan.md`](S4_plan.md) 为准：取消人工抽查，
由 DeepSeek 强模型即时执行单次代理评价，不再限制凌晨；增加独立 dev split。

本文独立描述 S4 要解决的问题、当前数据基础、主要困难、工作内容和完成标准。具体模型、
embedding、聚类算法、层级边界和阈值仍需通过 S4 小样本评测确定，不在本文件中预设为
已批准方案。

## 1. 任务目标

S4 建立一套可版本化、可解释、支持
多标签和跨领域检索的三级研究领域体系，为后续相关论文检索、Reviewer Twin 路由、
Author Twin 构建和跨年度趋势分析提供统一的领域坐标。

S4 需要同时保存四类不同信息：

1. ICLR 官方显式领域标签；
2. 从论文内容推断的 Level 1、Level 2 和 Level 3 隐式领域；
3. 一篇论文到多个领域节点的 assignment、分数和来源；
4. 领域节点之间的层级关系和跨领域关系。

官方标签属于观测事实；隐式领域、次级 assignment 和跨领域关系属于派生结果。两者必须
分开保存，不能用模型推断覆盖官方记录。

## 2. 当前数据基础

截至 2026-10-14，S4 可用或计划使用的数据包括：

| 数据 | 当前状态 |
|---|---:|
| ICLR 2024-2026 主会论文 | 38,890 篇 |
| 原始官方领域标签 | 27 个 |
| 跨年度 canonical key | 23 个 |
| `core.paper_area` assignment | 38,890 条 |
| 有官方领域的论文 | 38,890 篇 |
| 当前多官方领域论文 | 0 篇 |
| `semantic.taxonomy_node` | 0 条 |
| `semantic.taxonomy_edge` | 0 条 |
| `semantic.paper_taxonomy_assignment` | 0 条 |
| `semantic.embedding` | 0 条 |

官方标签按年份分别覆盖 20、21 和 21 个原始类别。目前已经记录四组跨年度名称归一关系，
但每篇论文只有一个 `is_primary=true` 的官方标签，因此现有显式标签无法直接表示交叉领域。

S4 的内容表示主要依赖 S3 的 `paper_understanding_v1` Profile。S3 尚未冻结，因此当前可以
开展 S4 方法评测和 schema 设计，但不能提前冻结生产 taxonomy。

## 3. 三级领域的语义边界

现有计划中的“显式标签、Level 1、Level 2、Level 3”仍存在定义歧义。建议在 S4 Gate 前
明确以下语义：

| 层级 | 建议含义 | 示例 |
|---|---|---|
| 显式领域 | ICLR 官方提交标签，保留原始值、年份和 alias | Foundation Models、RL |
| Level 1 | 稳定大领域，优先由 canonical 官方领域锚定 | Generative Models、Learning Theory |
| Level 2 | 任务族或方法族 | LLM Agents、Offline RL、Diffusion Models |
| Level 3 | 具体问题、技术路线或证据形态 | Agent Memory、Diffusion Distillation |

Level 1 不宜完全由自由聚类产生，否则新增论文或重跑算法可能改变整个顶层目录。推荐把
23 个 canonical 官方领域作为 Level 1 的稳定锚点，主要从论文内容中学习 Level 2、
Level 3 和次级 Level 1 assignment。该建议仍需在 S4 方法评测后正式批准。

## 4. S4 面临的核心问题

### 4.1 单标签来源与多领域现实不一致

当前每篇论文只有一个官方领域，但实际论文可能同时属于多个任务、方法和应用方向。例如
“用于生物分子的生成模型”同时涉及生成模型和物理科学应用。S4 必须推断次级领域，同时
明确标记其模型派生来源，并单独保留官方标签。

### 4.2 跨年度标签漂移

2024-2026 的标签集合、名称和粒度并不完全一致。相同概念可能改名、合并或拆分。S4 需要
保留 `raw_label`、年份、`canonical_key` 和归一理由，不能覆盖历史标签。

### 4.3 类别规模严重不平衡

大领域包含数千篇论文，部分原始领域只有几十篇。直接执行全局聚类容易使大领域主导结果，
小领域则被合并或当作噪声。聚类和评价必须使用宏平均、分层采样、最小簇规模和离群处理。

### 4.4 S3 输入尚未冻结

S3 Profile 仍在生成，未覆盖全量论文，也尚未完成最终DeepSeek 代理抽样评价和质量 Gate。若 S4 直接在
未冻结输入上建立 taxonomy，后续加入剩余 Profile 可能改变向量分布、簇中心和层级边界。

### 4.5 表示字段尚未选择

可用表示包括 title/abstract、problem/gap、method、datasets、claims 和完整 Profile。
简单拼接全部字段会让长字段或常见实验术语主导向量；只使用标题摘要又可能丢失方法差异。
必须比较字段组合，记录输入模板和内容哈希。

### 4.6 Embedding 模型尚未确定

SPECTER2、SciNCL 和通用 embedding 对“论文相似”的定义不同。模型选择必须比较显式领域
检索、方法相似性、跨年迁移、细粒度邻居质量、吞吐、显存和存储成本，不能只比较速度。

### 4.7 聚类结果的科学语义核查

无监督簇可能受写作风格、年份、常用数据集、模型名称和篇幅影响，需要核查其与研究问题的对应。
每个候选簇都必须检查共同问题、方法、任务和证据形态，并提供代表论文与反例。

### 4.8 层级和边界稳定性

改变随机种子、样本、年份或阈值后，Level 2/3 可能发生大幅变化。不稳定 taxonomy 无法作为
长期 Reviewer 路由依据。S4 必须测量跨种子、bootstrap 和跨年度稳定性，并设置停止细分条件。

### 4.9 LLM 命名风险

LLM 可以根据代表论文生成簇名和定义，但可能放大少数样本特征或生成不存在的领域概念。
命名输入必须包含代表论文、共同特征、边界样本和反例，最终名称与定义需要DeepSeek 强模型审核。

### 4.10 缺少细粒度金标准

官方标签只能提供粗粒度评测信号，不能直接证明 Level 2/3 正确。S4 需要结合DeepSeek 代理抽样评价、
邻居相关性、簇内一致性、簇间可分性、跨年迁移和稳定性进行评价。

### 4.11 跨领域关系定义不足

共同出现、方法迁移、应用关系、共享任务和普通语义相似分别使用对应的边类型。当前
`semantic.taxonomy_edge` 只能保存 parent-child，缺少关系类型、分数和证据。正式实现前需要
扩展 schema 或新增 versioned cross-domain relation 表，不能把所有关系伪装成层级边。

### 4.12 测试集泄漏风险

held-out test 论文不能用于选择 embedding、聚类算法、簇数量、阈值、命名或合并边界。
测试集只能在 taxonomy 冻结后执行 assignment 和最终评价。

## 5. 具体工作内容

### 5.1 冻结输入和数据划分

- 固定 S3 Profile 版本、内容哈希和质量条件；
- 固定年度 train/dev/calibration/test manifest；
- 论文的所有版本、Review 和派生对象继承同一 split；
- 排除 acceptance、decision 和 Reviewer 身份等不应影响领域定义的字段；
- 单独记录 Markdown 缺失或 metadata-only 论文。

### 5.2 完成显式标签规范化

- 审核现有 27 个 raw label 到 23 个 canonical key 的映射；
- 保存标签适用年份、原始名称、canonical 名称和合并理由；
- 明确 canonical 官方领域是否直接作为 Level 1；
- 不使用新 taxonomy 覆盖历史官方标签。

### 5.3 建立表示方法评测

至少比较以下输入表示：

- title + abstract；
- title + abstract + research problem + prior gap；
- method overview + components + mechanism chain；
- 去除 Review Risk 等推断字段后的完整 S3 Profile；
- 不同字段的加权或分向量组合。

至少比较 SPECTER2、SciNCL 和一个通用 embedding 基线。评测输出应包含质量、吞吐、显存、
向量维度、索引大小和跨年度表现。

### 5.4 构建 Level 1

- 以 canonical 官方领域作为锚点候选；
- 训练集拟合论文到 Level 1 的内容表示；
- 在 calibration 上确定次级领域阈值和 `unknown` 条件；
- 一篇论文允许多个 Level 1 assignment；
- 官方标签与模型 assignment 分开保存。

### 5.5 构建 Level 2 和 Level 3

- 在每个稳定 Level 1 内比较层级聚类、HDBSCAN 和受约束聚类；
- 设置最小簇规模、最大簇规模、离群规则和停止细分条件；
- Level 2 优先表达任务族或方法族；
- Level 3 表达具体问题、路线或证据形态；
- 小领域可保留 `other/unknown`，不能为追求覆盖率强制分簇。

### 5.6 节点命名与DeepSeek 强模型审核

每个 taxonomy node 至少保存：

- 名称和正式定义；
- 纳入标准和排除标准；
- 代表论文和边界论文；
- 共同问题、方法、任务和关键词；
- 父节点、相邻节点和容易混淆的节点；
- 生成模型、Prompt 版本、审核状态和修改记录。

### 5.7 生成论文多标签 Assignment

- 为每篇论文保存多个 taxonomy node assignment；
- 保存 score、source、taxonomy version、embedding model 和输入哈希；
- score 低于阈值时保留 `unknown`；
- 子节点 assignment 必须与父节点保持一致；
- 对边界论文和跨领域论文允许多个高置信度节点。

### 5.8 建立跨领域关系

跨领域关系应至少区分：

- `parent_of`：层级父子关系；
- `overlaps_with`：研究范围重叠；
- `method_used_in`：方法被用于另一任务或领域；
- `application_of`：应用领域使用某类基础方法；
- `shares_evidence_pattern_with`：共享数据集、评价或证据结构。

每条非层级关系应保存支持论文数量、代表论文、年份范围、分数和生成方法。

### 5.9 版本化、冻结和更新

- 首个生产版本命名为类似 `taxonomy_v1` 的固定版本；
- 节点、边、assignment 和 embedding 全部记录版本；
- 新年份或输入模型变化生成新版本，不覆盖旧 taxonomy；
- 保存旧节点到新节点的 merge/split/rename 映射；
- 冻结后 held-out test 只运行 assignment，不重新拟合。

## 6. 验收指标

S4 至少需要通过以下 Gate：

| 维度 | 最低要求 |
|---|---|
| 粗粒度质量 | 报告 Level 1 官方标签的 macro 指标和检索指标 |
| 细粒度质量 | DeepSeek 代理抽样评价 Level 2/3 的簇内一致性和簇间可分性 |
| 稳定性 | 报告跨种子、bootstrap 和跨年度稳定性 |
| 覆盖 | 报告各层 assignment 覆盖率、`unknown` 和离群比例 |
| 多标签 | DeepSeek 代理抽样评价 secondary assignment precision |
| 层级一致性 | 子节点 assignment 必须有兼容父节点 |
| 边质量 | 跨领域关系具有类型、分数和可追溯证据 |
| 校准 | score 与DeepSeek 代理判定通过率或分桶质量相符，不能直接当概率 |
| 防泄漏 | test 不参与模型、阈值、命名和边界选择 |
| 可复现 | 固定输入、模型、参数、随机种子和版本后可重复生成 |

## 7. 计划产物

S4 完成后应产生：

1. versioned taxonomy nodes；
2. versioned hierarchy edges；
3. typed cross-domain relations；
4. paper multi-label assignments 和置信分数；
5. paper embeddings 与输入哈希；
6. 显式标签 alias 和跨年度映射；
7. embedding/聚类对比报告；
8. 稳定性、覆盖率、DeepSeek 代理抽样评价和 held-out test 报告；
9. Reviewer Twin 可直接消费的领域路由接口。

## 8. 完成条件和当前关键路径

S4 只有同时满足以下条件才算完成：

- S3 输入版本已经冻结并通过质量 Gate；
- embedding 和聚类方案经过固定样本评测；
- Level 1/2/3 定义和边界经过DeepSeek 强模型审核；
- nodes、edges、relations、assignments 和 embeddings 已写入正式数据库；
- train/dev/calibration/test 使用符合冻结规则；
- 稳定性、覆盖率、多标签和跨领域边通过验收；
- taxonomy 版本可重复生成，且不会覆盖历史版本。

当前关键路径为：

```text
完成并冻结 S3
-> S4 embedding/字段组合小样本评测
-> 固定三级定义和关系 schema
-> train 构建 / dev 选型 / calibration 标定 taxonomy
-> DeepSeek 强模型审核名称与边界
-> 冻结 taxonomy_v1
-> held-out test assignment 评测
```
