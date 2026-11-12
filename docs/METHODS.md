# 方法、论文来源与实现对应

更新：2026-11-12。本文说明各模块**实际如何工作**、**参考了什么**、**采用到什么程度**，并把当前方案与历史实验分开。状态见 [STATUS](STATUS.md)，工程运行见 [DEPLOYMENT](DEPLOYMENT.md)。

## 1. 论文与出处核验

本次对已有方法记录中的论文进行定向书目与出处核验。ACL Anthology、Crossref、arXiv 的返回摘要保存于 [reference-audit.json](research/release-20261112/reference-audit.json)，记录访问日期、URL、返回校验和或失败原因。

| 论文 | 正式出处/类型 | 本项目采用程度 |
|---|---|---|
| [Embedding Atlas: Low-Friction, Interactive Embedding Visualization](https://arxiv.org/abs/2505.06386) | arXiv:2505.06386，2025；本次按预印本引用 | **直接使用软件库**构建交互地图；输入向量与投影由项目生成 |
| [ggdist: Visualizations of Distributions and Uncertainty in the Grammar of Graphics](https://doi.org/10.1109/TVCG.2023.3327195) | IEEE TVCG，30(1):414–424，2024；DOI/在线记录为 2023 | **直接使用 R/ggdist** 生成静态分布图；交互 SVG 以相同论文级数据自行实现 |
| [HINTs: Sensemaking on Large Collections of Documents With Hypergraph Visualization and INTelligent Agents](https://doi.org/10.1109/TVCG.2024.3459961) | IEEE TVCG，31(9):5532–5546，2025；DOI 带 2024 | **交互叙事启发**：文档总览、关系探索与证据回查 |
| [TaxoAdapt: Aligning LLM-Based Multidimensional Taxonomy Construction to Evolving Research Corpora](https://aclanthology.org/2025.acl-long.1442/) | ACL 2025，主会长文 | **早期开发实验改写**：多维分类与语料适配 |
| [TopicGPT: A Prompt-based Topic Modeling Framework](https://aclanthology.org/2024.naacl-long.164/) | NAACL 2024，主会长文 | **早期主题方案参考/改写**；当前展示采用实体与核心内容提取 |
| [ReviewGrounder: Improving Review Substantiveness with Rubric-Guided, Tool-Integrated Agents](https://aclanthology.org/2026.acl-long.1477/) | ACL 2026，主会长文 | **采用 rubric、正文 grounding 和实质性意见约束思路**，用于单次组合审查 |
| [RbtAct: Rebuttal as Supervision for Actionable Review Feedback Generation](https://aclanthology.org/2026.findings-acl.1696/) | Findings of ACL 2026 | **历史交流诊断中的动作类别参考**，使用提示词分析 |
| [AutoManual](https://openreview.net/forum?id=Pwl9n4zlf5) | 既有研究记录标记为 NeurIPS 2024；本次 API 403，页面未返回可核验元数据 | **手册式原子经验构建的适配**；venue 核验待补充可访问记录 |
| [ACE](https://openreview.net/forum?id=eC4ygDs02R) | 既有研究记录标记为 ICLR 2026；本次 API 403，页面未返回可核验元数据 | **增量规则维护、反思与整理的适配**；来源链接和未复核状态保留 |
| [DeepReview: Improving LLM-based Paper Review with Human-like Deep Thinking Process](https://aclanthology.org/2025.acl-long.1420/) | ACL 2025，主会长文 | **后续比较候选** |
| [TreeReview: A Dynamic Tree of Questions Framework for Deep and Efficient LLM-based Scientific Peer Review](https://aclanthology.org/2025.emnlp-main.790/) | EMNLP 2025，主会论文 | **后续分层检查参考** |

表中分别标注期刊、主会、Findings 与预印本出处。AutoManual/ACE 的既有方法使用记录见 [100 篇原型](technical_details/S6_modular_review_skill100.md)；后续补充可访问的正式记录后再更新 venue 核验状态。

## 2. 数据底座：保留来源、版本与正文位置

实现：[database/iclr_database.py](../database/iclr_database.py)、[schema.sql](../database/schema.sql)、[迁移](../database/migrations/versions/)。

- `raw` 保存来源记录、原始 OpenReview Note/Edit 及工件血缘。
- `core` 归一化主会论文、论文版本、作者、领域、审稿、评分、讨论与决定。
- `semantic` 保存画像、正文轻量索引、内容对象、向量和预留分类结构。
- `twin` 保存审稿原型表结构，数据生产列入后续工作。
- `ops` 记录运行与任务状态。

论文文件通过 SHA-256 内容寻址，数据库保存对象路径和索引；原始语料不因导入而修改。正文索引读取已有 Markdown，记录标题、图表/公式等对象标识和字符位置。Review Edit 回填保存来源和检查点，避免把迁移包络或单个最终分数伪装成可重放的历史评分变化。

本层使用 Python、SQL、PostgreSQL/pgvector。网站导出读取现有 BGE-M3 工件向量，地图在浏览器加载导出的快照。

### 解析器开发比较

另有 [40 篇同稿解析报告](../benchmarks/parser_comparison/standard_40_report.md)：Existing Markdown、Docling 2.130.0 与 MinerU standard 均完成 40/40，比对标题/摘要召回、章节、重复和结构信号，并对 8 个刻意选择的公式/表格冲突页做视觉模型审计。Docling 另有单路 100 篇解析记录，三路共同可比样本为 40 篇。

融合建议为：Docling 提供紧凑骨架、MinerU 提供表格/公式候选、原文本支持回溯审计。全量替换与人工质量评测列入后续工作。比较中的文本一致性衡量来源自一致，视觉裁决范围为选取的 8 个困难页。

## 3. 论文理解：便宜路径优先，证据不足时升级

实现：[paper_understanding_pipeline.py](../scripts/paper_understanding_pipeline.py)。依据：[50 篇开发比较](../benchmarks/paper_understanding/50_paper_report.md)、[详细流水线说明](technical_details/S3_profile_pipeline.md)。

对同一 50 篇论文比较三种自建路径，抽取模型为 `gpt-5.6-luna`，匿名顺序盲评模型为 `gpt-5.6-sol`：

| 路径 | 综合均分 / 5 | 抽取 token / 篇 | 秒 / 篇 |
|---|---:|---:|---:|
| One-shot 结构化抽取 | 4.5067 | 18,013.6 | 60.466 |
| 分节、证据约束的层次抽取 | 4.5067 | 62,613.6 | 194.728 |
| DocETL-style 计划式抽取 | 4.0333 | 49,949.9 | 159.318 |

One-shot 与层次路径的配对均分差为 0，95% bootstrap 区间为 `[-0.1833, 0.1833]`；one-shot 抽取 token 约为层次路径的 28.8%。因此选择 one-shot 为默认，字段缺失、证据不足、冲突等情况升级为层次路径。DocETL-style 在本项目中实现“计划—分解—汇总”，表中评价对象为该实现。

生产画像输入是按章节路由、限长选取的证据包。保存研究问题、方法、实验与证据等结构化字段，记录原文引用和运行状态；支持恢复与幂等入库。当前入库 38,807 篇。

后续质量审计将建立人工金标准，核查引文对主张的支持关系，完善作者陈述与模型推断的字段分离、置信度校准及缺失证据统计。

## 4. 实体、核心内容与领域表示

当前方案：[entity_core_third](research/s4-entity-core-third/README.md)、[抽取器](../scripts/s4_entity_core_third.py)。

固定主会 38,890 篇题录后，按年份 × 统一领域分层，采用最大余数分配取 12,964 篇，并保留前期 500 篇种子。分年为 2,468 / 3,890 / 6,606；抽样设计为保留种子的分层研究样本。

每篇将标题摘要送入 `gpt-6-luna / medium`，提取科学实体候选和核心研究问题/方法/研究对象。作者原始领域与关键词单独保留，不输入提取模型。候选保留原始词形、实体类型和字符位置；无法逐字定位的候选也保留并标记。

封存结果共 517,223 条候选，514,312 条能定位、2,911 条无效保留；该数字统计字符定位结果。两种视图（摘要、核心内容）分别用 BGE-M3 和 Qwen3-Embedding-0.6B 编码，形成 51,856 条 1024 维归一化向量。输入长度逐项检查，保存模型、输入与输出文件哈希。

当前网站分别展示投稿领域、自动提取的实体标签与二维邻域。正式学科父子树冻结、实体语义准确性和检索收益评测列入后续计划。

### 历史分类比较的用途

早期还有 TaxoAdapt/TopicGPT 改写、多模型标签融合、200 篇 DKTA 以及 500 篇不同协议的分类实验，记录见 [分类实验](../benchmarks/s4_taxonomy/README.md)、[DKTA](technical_details/S4_DKTA.md)、[500 篇协议](research/s4-reproduce500/PROTOCOL.md)。这些历史方案按各自协议保存，当前网站使用封存的实体与核心内容结果。

DKTA 将本地 Qwen 注意力词与 BART One2Many 关键词分路生成，再以 RRF（常数 60）融合，用 BGE-M3 对齐 ACM 多父路径，并在模糊区进行 LLM 仲裁。Qwen 使用量化模型和选定全注意力层，与 Attention-Seeker 原设定存在差异。

200 篇开发实验中，作者关键词 F1@10 为 BART 0.1508、RRF 0.1312、Qwen 注意力 0.0156、同输入 LLM 0.1317。作者关键词不完整；LLM 路径支持率也属于开发代理指标。细粒度分类准确性及概率校准需补充人工金标准。

## 5. 可视化：从地图到证据

实现：[export_s4.py](../web/export_s4.py)、[前端](../web/main.js)、[render_reviews.R](../web/render_reviews.R)、[交互评分分布](../web/review-distributions.js)。

1. **语义地图：** 取核心内容的 BGE-M3 向量，经 PCA 压到 50 维，再用固定随机种子 42、perplexity 40、750 次迭代的 t-SNE 投影到二维；评分和决定不作为投影特征。Embedding Atlas 提供 WebGPU 交互，不支持时走原生 Canvas。
2. **领域边界：** 对二维邻域按投稿领域做归一化高斯核密度计算，用优势分区及 Marching Squares 等值线展示边界。边界表示二维投影的邻域结构。
3. **逐层阅读：** 全景显示领域，放大显示领域内代表主题，再放大显示可选论文卡片；标题/ID 搜索与筛选共用同一论文集合。
4. **实体弦图：** 明确同义词归并后，同篇同概念只计一次；弦宽为同时出现两个概念的独立论文数。该权重衡量共现关联。
5. **录用统计：** 录用数除以当前筛选集合全部投稿数；同时列出拒稿、直接拒稿、撤稿与未知。
6. **论文评分：** 每篇有效评分均值、样本标准差 `sqrt(sum((x−mean)^2)/(n−1))` 或极差；不同年份分别展示，每篇等权。交互图组合经验分布主体、至多 40 个分位点、中位数和中央 50%/90% 区间；小组直接显示原始观测。静态图实际调用 `ggdist::stat_slab`、`stat_dots`、`stat_pointinterval`。
7. **证据回查：** 领域、概念和高分歧论文可以回到具体论文、原始评分和正文片段；借鉴 HINTs 的集合探索叙事。

图中的中央区间表示当前样本的观测跨度；统计范围遵循保留种子的分层抽样设计。

## 6. 历史 Review—作者响应轨迹诊断

实现：[s5_fused20.py](../scripts/s5_fused20.py)。协议：[20 篇开发诊断](../benchmarks/s5_trajectory/README.md)。

选择 2024/2025 各 10 篇开发案例，各年分别 5 篇有后续审稿人反馈、5 篇没有。每篇两次依赖调用：前缀阶段仅使用时间边界前可见的审稿及作者消息，拆解 concern、动作、证据与候选响应；回放阶段查看实际后续讨论，判断 concern 的可观察状态变化。

参考 RbtAct 的作者动作分析，另借鉴既有记录中 DRPG 的证据约束响应规划，以及评分轨迹研究中的交流结构特征。后两项见 [原技术记录](technical_details/S5_review_rebuttal_trajectory.md)，属于预印本/研究参考，本次未重新核验其正式会议出处。项目采用提示词进行历史交流诊断。

40/40 阶段完成：91 个 concern 中 resolved 2、partial 4、unresolved 5、unknown 80；4 个后续新问题单独计。没有后续反馈的 10 篇，其 46 个 concern 全保留 unknown。缺少独立前后评分快照时，评分变化保留 unknown；模型拟写的回应不作为真实历史事件。

## 7. 从历史经验构建冻结 Skill

实现：[modular_review_skill.py](../scripts/modular_review_skill.py)、[恢复](../scripts/recover_llm_area_review_skills.py)、[冻结](../scripts/freeze_llm_area_library.py)。

从初始 Review 单元与相关正文配对，归纳原子观察；将具有相似适用范围和失效机制的观察转成条件规则，再按 general/domain/method/task/specialty 等层级和机制组织为可组合模块。

规则包含适用条件、需要检查的现象、潜在失效机制、问题成立条件、可消除该问题的证据及来源。受到 AutoManual 手册构建和 ACE 增量整理的启发，通过已有规则检索、反思/整理、去重、修订和弃用维护库。

`source_supported` 要求至少两篇独立配对来源；`candidate` 单独保存，默认不进入新稿组合。未能形成通用规则、单案例观察、重复、缺证据及未解决项均有明确去向。队列无遗留待处理项后，重新导出当前注册模块，检查每条有效规则恰好归属一个模块，固定内容、模型、来源、代码和文件哈希。

当前冻结 7,795 个模块、9,175 条有效规则，另有 84 条未解决/缺证据候选。冻结审计覆盖来源、版本与执行记录，规则科学质量按后续人工评测协议验收。

## 8. 按新稿组合与单次证据审稿

实现：[compose_manuscript_skills.py](../scripts/compose_manuscript_skills.py)、[review_composed_manuscript.py](../scripts/review_composed_manuscript.py)、[review_api.py](../web/review_api.py)。

**输入隔离：** 与历史画像的限长证据包不同，新稿保留完整可用文本和已有附录；按论文 ID、论坛 ID 及全文排除全部领域来源论文。数据库选稿只读取标题摘要与稿件，不把目标的人类 Review、评分或决定给模型。

**选择过程：** 第一次调用识别领域、方法、任务和对象并引用正文；字符 n-gram TF-IDF 从来源支持规则中召回最多 24 条；第二次调用逐条输出 applicable / not_applicable / insufficient_evidence。未进入短名单的规则记录为 not_assessed。

**预算：** 最多加载 10 条、4,000 个 `cl100k_base` 代理 token 的实际检查文本；模型请求实际序列化输入另有 64,000 代理 token 上限。超限先减候选，不静默裁切正文；正文自身超限则停止并保留状态。加载后按新稿证据逐条核查。

**生成与依据：** 第三次调用依据完整稿件和已加载检查项生成 Review，区分有证据缺陷、待核实问题与建议，绑定段落/引文。局部唯一空白规范化匹配可恢复原文位置，不匹配意见隔离保存。沿用 ReviewGrounder 的 rubric/grounding 思路，当前执行为单次组合审查。

**运行恢复：** Web 同源代理按需启动回环 Python 服务；每个任务目录由一个协调器串行执行。输入、配置、库版本、请求和响应身份都参与复用判断；失败响应及早期尝试保留，重启中断任务可重试。新审稿凭据来自页面用户输入，只在任务内存及子进程环境中使用，任务文件仅记录接口地址哈希。

当前真实 MLRA 案例为 3 条规则、1,605 代理 token，已完成 Review 与原文点击回查。工程链条已跑通，质量评测将采用独立人工判定与无 Skill 基线。

## 9. 论文图相关检查

冻结库已提取图例/坐标、误差条、流程图、训练曲线归因与可视化证据等条件规则。当前 Web 通过正文与可用图注执行检查，实际图像审查列入后续接入。规则 ID、来源及执行路径见 [论文图审查能力](FIGURE_REVIEW.md)。
