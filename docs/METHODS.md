# 方法、论文来源与实现对应

更新：2026-11-12。本文说明各模块**实际如何工作**、**参考了什么**、**采用到什么程度**，并把当前方案与历史实验分开。状态见 [STATUS](STATUS.md)，工程运行见 [DEPLOYMENT](DEPLOYMENT.md)。

## 1. 论文与出处核验

本次针对已有方法记录中的论文做定向元数据核验，未进行新的全领域检索或模型调用。ACL Anthology、Crossref、arXiv 的返回摘要保存于 [reference-audit.json](research/release-20261112/reference-audit.json)，记录访问日期、URL、返回校验和或失败原因。

| 论文 | 正式出处/类型 | 本项目采用程度 |
|---|---|---|
| [Embedding Atlas: Low-Friction, Interactive Embedding Visualization](https://arxiv.org/abs/2505.06386) | arXiv:2505.06386，2025；本次按预印本引用 | **直接使用软件库**构建交互地图；输入向量与投影由项目生成 |
| [ggdist: Visualizations of Distributions and Uncertainty in the Grammar of Graphics](https://doi.org/10.1109/TVCG.2023.3327195) | IEEE TVCG，30(1):414–424，2024；DOI/在线记录为 2023 | **直接使用 R/ggdist** 生成静态分布图；交互 SVG 以相同论文级数据自行实现 |
| [HINTs: Sensemaking on Large Collections of Documents With Hypergraph Visualization and INTelligent Agents](https://doi.org/10.1109/TVCG.2024.3459961) | IEEE TVCG，31(9):5532–5546，2025；DOI 带 2024 | **交互叙事启发**：文档总览、关系探索与证据回查；没有复现其超图与智能体系统 |
| [TaxoAdapt: Aligning LLM-Based Multidimensional Taxonomy Construction to Evolving Research Corpora](https://aclanthology.org/2025.acl-long.1442/) | ACL 2025，主会长文 | **早期开发实验改写**：多维分类与语料适配；不是当前展示数据的完整父子分类 |
| [TopicGPT: A Prompt-based Topic Modeling Framework](https://aclanthology.org/2024.naacl-long.164/) | NAACL 2024，主会长文 | **早期主题方案参考/改写**；当前实体提取不宣称复现其端到端系统 |
| [ReviewGrounder: Improving Review Substantiveness with Rubric-Guided, Tool-Integrated Agents](https://aclanthology.org/2026.acl-long.1477/) | ACL 2026，主会长文 | **采用 rubric、正文 grounding 和实质性意见约束思路**；未接入原论文完整多 Agent 工具链 |
| [RbtAct: Rebuttal as Supervision for Actionable Review Feedback Generation](https://aclanthology.org/2026.findings-acl.1696/) | Findings of ACL 2026 | **历史交流诊断中的动作类别参考**；使用提示词分析，未按原文训练反馈生成模型 |
| [AutoManual](https://openreview.net/forum?id=Pwl9n4zlf5) | 既有研究记录标记为 NeurIPS 2024；本次 API 403，页面未返回可核验元数据 | **手册式原子经验构建的适配**；本次不将既有 venue 标记当作新核验结果 |
| [ACE](https://openreview.net/forum?id=eC4ygDs02R) | 既有研究记录标记为 ICLR 2026；本次 API 403，页面未返回可核验元数据 | **增量规则维护、反思与整理的适配**；来源链接和未复核状态保留 |
| [DeepReview: Improving LLM-based Paper Review with Human-like Deep Thinking Process](https://aclanthology.org/2025.acl-long.1420/) | ACL 2025，主会长文 | **后续比较候选**；未接入当前单次 Web 审稿 |
| [TreeReview: A Dynamic Tree of Questions Framework for Deep and Efficient LLM-based Scientific Peer Review](https://aclanthology.org/2025.emnlp-main.790/) | EMNLP 2025，主会论文 | **后续分层检查参考**；没有将其问题树实现为当前 Web 执行器 |

TVCG 是期刊，Findings 与 ACL 主会区分，arXiv 不记为顶会录用。元数据核验只确认书目信息，不代表原论文结论已在本项目重现。AutoManual/ACE 的既有方法使用记录见 [100 篇原型](technical_details/S6_modular_review_skill100.md)；后续补充可访问的正式记录后再更新 venue 核验状态。

## 2. 数据底座：保留来源、版本与正文位置

实现：[database/iclr_database.py](../database/iclr_database.py)、[schema.sql](../database/schema.sql)、[迁移](../database/migrations/versions/)。

- `raw` 保存来源记录、原始 OpenReview Note/Edit 及工件血缘。
- `core` 归一化主会论文、论文版本、作者、领域、审稿、评分、讨论与决定。
- `semantic` 保存画像、正文轻量索引、内容对象、向量和预留分类结构。
- `twin` 保存后续审稿原型结构；存在表不表示生产孪生数据已完成。
- `ops` 记录运行与任务状态。

论文文件通过 SHA-256 内容寻址，数据库保存对象路径和索引；原始语料不因导入而修改。正文索引优先读取已有 Markdown，记录标题、图表/公式等对象标识和字符位置；不为全语料预先执行视觉深解析。Review Edit 回填保存来源和检查点，避免把迁移包络或单个最终分数伪装成可重放的历史评分变化。

本层使用普通 Python、SQL、PostgreSQL/pgvector。实际网站导出使用现有 BGE-M3 工件向量，不意味着地图在线查询 pgvector 或使用向量数据库自动构建分类树。

### 解析器开发比较

另有 [40 篇同稿解析报告](../benchmarks/parser_comparison/standard_40_report.md)：Existing Markdown、Docling 2.130.0 与 MinerU standard 均完成 40/40，比对标题/摘要召回、章节、重复和结构信号，并对 8 个刻意选择的公式/表格冲突页做视觉模型审计。Docling 的全 100 篇解析有运行记录，MinerU 三路可比结果为 40 篇 partial，不能写成三路全 100 篇均验收。

该实验提示可用 Docling 作紧凑骨架、MinerU 作表格/公式候选、原文本作回溯审计，但此为融合建议，尚未据此全量替换当前数据库正文。原 Markdown 相对 `pdftotext` 的一致性 1.0 是来源自一致，非独立准确率；8 个困难页裁决也不能外推成整体胜率。解析工具没有在本文另配未经核验的顶会出处。

## 3. 论文理解：便宜路径优先，证据不足时升级

实现：[paper_understanding_pipeline.py](../scripts/paper_understanding_pipeline.py)。依据：[50 篇开发比较](../benchmarks/paper_understanding/50_paper_report.md)、[详细流水线说明](technical_details/S3_profile_pipeline.md)。

对同一 50 篇论文比较三种自建路径，抽取模型为 `gpt-5.6-luna`，匿名顺序盲评模型为 `gpt-5.6-sol`：

| 路径 | 综合均分 / 5 | 抽取 token / 篇 | 秒 / 篇 |
|---|---:|---:|---:|
| One-shot 结构化抽取 | 4.5067 | 18,013.6 | 60.466 |
| 分节、证据约束的层次抽取 | 4.5067 | 62,613.6 | 194.728 |
| DocETL-style 计划式抽取 | 4.0333 | 49,949.9 | 159.318 |

One-shot 与层次路径的配对均分差为 0，95% bootstrap 区间为 `[-0.1833, 0.1833]`；one-shot 抽取 token 约为层次路径的 28.8%。因此选择 one-shot 为默认，字段缺失、证据不足、冲突等情况升级为层次路径。这里的 DocETL-style 是项目对“计划—分解—汇总”的改写，未使用原 DocETL 系统，不能据此评价原方法优劣。

生产画像输入是按章节路由、限长选取的证据包，**不是完整原稿无裁剪深读**。保存研究问题、方法、实验与证据等结构化字段，记录原文引用和运行状态；支持恢复与幂等入库。当前入库 38,807 篇。

模型评分尚无人工金标准校准；引文逐字命中只能确认出处存在，不能证明支持关系。作者陈述与模型推断的全字段分离、置信度校准和缺失证据分母仍需改进。

## 4. 实体、核心内容与领域表示

当前方案：[entity_core_third](research/s4-entity-core-third/README.md)、[抽取器](../scripts/s4_entity_core_third.py)。

固定主会 38,890 篇题录后，按年份 × 统一领域分层，采用最大余数分配取 12,964 篇，并保留前期 500 篇种子。分年为 2,468 / 3,890 / 6,606；这是保留种子的分层研究样本，不是等纳入概率的简单随机样本。

每篇将标题摘要送入 `gpt-6-luna / medium`，提取科学实体候选和核心研究问题/方法/研究对象。作者原始领域与关键词单独保留，不输入提取模型。候选保留原始词形、实体类型和字符位置；无法逐字定位的候选也保留并标记。

封存结果共 517,223 条候选，514,312 条能定位、2,911 条无效保留；这只说明定位检查。两种视图（摘要、核心内容）分别用 BGE-M3 和 Qwen3-Embedding-0.6B 编码，形成 51,856 条 1024 维归一化向量。输入长度逐项检查，保存模型、输入与输出文件哈希。

**当前网站没有完整冻结的学科父子树。** 投稿领域与自动提取的实体标签分别展示，二维局部区域也不作为正式分类节点。原始位置有效率不代表语义准确率或检索收益。

### 历史分类比较的用途

早期还有 TaxoAdapt/TopicGPT 改写、多模型标签融合、200 篇 DKTA 以及 500 篇不同协议的分类实验，记录见 [分类实验](../benchmarks/s4_taxonomy/README.md)、[DKTA](technical_details/S4_DKTA.md)、[500 篇协议](research/s4-reproduce500/PROTOCOL.md)。它们用于方案研究，不与当前封存实体结果混成一个已验收生产算法。

DKTA 将本地 Qwen 注意力词与 BART One2Many 关键词分路生成，再以 RRF（常数 60）融合，用 BGE-M3 对齐 ACM 多父路径，并在模糊区进行 LLM 仲裁。Qwen 使用量化模型和选定全注意力层，与 Attention-Seeker 原设定存在差异。

200 篇开发实验中，作者关键词 F1@10 为 BART 0.1508、RRF 0.1312、Qwen 注意力 0.0156、同输入 LLM 0.1317。作者关键词不完整；LLM 路径支持率也属于开发代理指标。没有人工细粒度分类金标准，不能报告真实 hierarchical F1、校准概率或宣称 RRF 必然改善效果。

## 5. 可视化：从地图到证据

实现：[export_s4.py](../web/export_s4.py)、[前端](../web/main.js)、[render_reviews.R](../web/render_reviews.R)、[交互评分分布](../web/review-distributions.js)。

1. **语义地图：** 取核心内容的 BGE-M3 向量，经 PCA 压到 50 维，再用固定随机种子 42、perplexity 40、750 次迭代的 t-SNE 投影到二维；评分和决定不作为投影特征。Embedding Atlas 提供 WebGPU 交互，不支持时走原生 Canvas。
2. **领域边界：** 对二维邻域按投稿领域做归一化高斯核密度计算，用优势分区及 Marching Squares 等值线展示边界。显示的是投影邻域结构，不是统计显著分界。
3. **逐层阅读：** 全景显示领域，放大显示领域内代表主题，再放大显示可选论文卡片；标题/ID 搜索与筛选共用同一论文集合。
4. **实体弦图：** 明确同义词归并后，同篇同概念只计一次；弦宽为同时出现两个概念的独立论文数。共现不能解释为因果关系。
5. **录用统计：** 录用数除以当前筛选集合全部投稿数；同时列出拒稿、直接拒稿、撤稿与未知。
6. **论文评分：** 每篇有效评分均值、样本标准差 `sqrt(sum((x−mean)^2)/(n−1))` 或极差；不同年份分别展示，每篇等权。交互图组合经验分布主体、至多 40 个分位点、中位数和中央 50%/90% 区间；小组直接显示原始观测。静态图实际调用 `ggdist::stat_slab`、`stat_dots`、`stat_pointinterval`。
7. **证据回查：** 领域、概念和高分歧论文可以回到具体论文、原始评分和正文片段；借鉴 HINTs 的集合探索叙事，没有复现其超图或多 Agent。

图中的中央区间表示观测跨度，不是参数置信区间；样本有种子保留机制，不据此推断会议总体的因果规律或录用概率。

## 6. 历史 Review—作者响应轨迹诊断

实现：[s5_fused20.py](../scripts/s5_fused20.py)。协议：[20 篇开发诊断](../benchmarks/s5_trajectory/README.md)。

选择 2024/2025 各 10 篇开发案例，各年分别 5 篇有后续审稿人反馈、5 篇没有。每篇两次依赖调用：前缀阶段仅使用时间边界前可见的审稿及作者消息，拆解 concern、动作、证据与候选响应；回放阶段查看实际后续讨论，判断 concern 的可观察状态变化。

参考 RbtAct 的作者动作分析，另借鉴既有记录中 DRPG 的证据约束响应规划，以及评分轨迹研究中的交流结构特征。后两项见 [原技术记录](technical_details/S5_review_rebuttal_trajectory.md)，属于预印本/研究参考，本次未重新核验其正式会议出处。项目采用提示词诊断，没有训练原论文模型或估计因果效果。

40/40 阶段完成：91 个 concern 中 resolved 2、partial 4、unresolved 5、unknown 80；4 个后续新问题单独计。没有后续反馈的 10 篇，其 46 个 concern 全保留 unknown。缺少独立前后评分快照时，评分变化保留 unknown；模型拟写的回应不作为真实历史事件。

## 7. 从历史经验构建冻结 Skill

实现：[modular_review_skill.py](../scripts/modular_review_skill.py)、[恢复](../scripts/recover_llm_area_review_skills.py)、[冻结](../scripts/freeze_llm_area_library.py)。

从初始 Review 单元与相关正文配对，归纳原子观察；将具有相似适用范围和失效机制的观察转成条件规则，再按 general/domain/method/task/specialty 等层级和机制组织为可组合模块。

规则包含适用条件、需要检查的现象、潜在失效机制、问题成立条件、可消除该问题的证据及来源。受到 AutoManual 手册构建和 ACE 增量整理的启发，通过已有规则检索、反思/整理、去重、修订和弃用维护库；没有复现其原始任务环境、训练或完整代理架构。

`source_supported` 要求至少两篇独立配对来源；`candidate` 单独保存，默认不进入新稿组合。未能形成通用规则、单案例观察、重复、缺证据及未解决项均有明确去向。队列无遗留待处理项后，重新导出当前注册模块，检查每条有效规则恰好归属一个模块，固定内容、模型、来源、代码和文件哈希。

当前冻结 7,795 个模块、9,175 条有效规则，另有 84 条未解决/缺证据候选。该状态证明来源和执行可追踪，不证明规则科学正确。

## 8. 按新稿组合与单次证据审稿

实现：[compose_manuscript_skills.py](../scripts/compose_manuscript_skills.py)、[review_composed_manuscript.py](../scripts/review_composed_manuscript.py)、[review_api.py](../web/review_api.py)。

**输入隔离：** 与历史画像的限长证据包不同，新稿保留完整可用文本和已有附录；按论文 ID、论坛 ID 及全文排除全部领域来源论文。数据库选稿只读取标题摘要与稿件，不把目标的人类 Review、评分或决定给模型。

**选择过程：** 第一次调用识别领域、方法、任务和对象并引用正文；字符 n-gram TF-IDF 从来源支持规则中召回最多 24 条；第二次调用逐条输出 applicable / not_applicable / insufficient_evidence。未进入短名单的规则保留 not_assessed，不能假装已被判不适用。

**预算：** 最多加载 10 条、4,000 个 `cl100k_base` 代理 token 的实际检查文本；模型请求实际序列化输入另有 64,000 代理 token 上限。超限先减候选，不静默裁切正文；正文自身超限则停止并保留状态。加载规则只表示应该核查，不表示新稿已违反规则。

**生成与依据：** 第三次调用依据完整稿件和已加载检查项生成 Review，区分有证据缺陷、待核实问题与建议，绑定段落/引文。局部唯一空白规范化匹配可恢复原文位置，不匹配意见隔离保存。沿用 ReviewGrounder 的 rubric/grounding 思路，当前执行为单次组合审查，不调度多审稿人和 AC。

**运行恢复：** Web 同源代理按需启动回环 Python 服务；每个任务目录由一个协调器串行执行。输入、配置、库版本、请求和响应身份都参与复用判断；失败响应及早期尝试保留，重启中断任务可重试。模型凭据由后端读取。

当前真实 MLRA 案例为 3 条规则、1,605 代理 token，已完成 Review 与原文点击回查。它证明流程能运行；是否改善审稿质量仍需要独立人工评测及无 Skill 基线。
