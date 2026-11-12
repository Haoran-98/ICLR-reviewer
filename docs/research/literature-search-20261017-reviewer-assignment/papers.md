# 顶会论文—审稿人分配机制、项目差异与 Benchmark

核查日期：2026-10-17。范围：ACL/ARR、ICLR、ICML、NeurIPS，以及与本仓库 S4/S6/S8 的比较。以下明确标年，历史部署不自动代表 2026 年配置。NIPS 现名 NeurIPS。

## 主要判断

1. 顶会分配通常分为两步：估计论文—审稿人适配分数，再在利益冲突、负载、每篇审稿人数等约束下求全局分配。AC/SAC 随后检查和调整。
2. 本仓库当前 S4 是领域表示与 taxonomy 学习；S6/S8 的审稿孪生与组合路由仍为规划。它们可改进适配分数和专家组合，但尚不能视作已完成、已优于会议系统的全局分配器。
3. 有直接可用 benchmark：Gold Standard Reviewer Assignment 与 SciRepEval Paper–Reviewer Matching。FairFlow 的公开 MIDL 等实例可补充分配层评估，但下载前应逐文件检查实际数据与约束完整性。
4. 最值得先检验的问题是：细粒度、可追溯的领域表示，能否在相同输入和候选审稿人条件下，优于 TF-IDF、SPECTER2、SciNCL 与其组合的专家适配排序。

## 1. 顶会分配究竟在优化什么

### 1.1 分数层：这个人是否适合审这篇论文

输入一般包括投稿论文的标题、摘要、主题/关键词，候选审稿人的既往论文或自报专长，以及可选的 bidding。Bidding 表达审稿兴趣/意愿，与专业能力相关但不等同。

常见内容分数为：先计算投稿论文与审稿人历史论文的相似度，再按最大值、均值等方式聚合为该审稿人的适配分数。OpenReview Expertise 支持这些聚合方式，也支持 BM25、TF-IDF、SPECTER、MFR、SPECTER2、SciNCL 及组合。其当前 README 记载 SPECTER2+SciNCL 在 paper–paper 相似度层等权组合；这是工具能力，不能据此断言每个会议每年都采用该配置。[R5]

概念上可写成：

\[
s_{pr}=\alpha a_{pr}+\beta b_{pr}+\gamma t_{pr},
\]

其中 a 是历史论文内容适配，b 是 bid，t 是主题等附加信号。这个式子只是一般化表达，各会议的具体权重须有单独证据。

### 1.2 分配层：在整个会议中如何分人

设 x_pr 为是否把审稿人 r 分给论文 p，基本问题为：

\[
\max_x\sum_{p,r}s_{pr}x_{pr},\quad
\sum_r x_{pr}=k_p,\quad
L_r\leq\sum_p x_{pr}\leq U_r,\quad
x_{pr}=0\ \text{if COI},\quad x_{pr}\in\{0,1\}.
\]

每篇独立选 Top-k 可能把热门专家全部挤满，因此需要全局分配。基本二部图容量匹配可用最小费用流求解；加入复杂的组内组合约束后，可能需要整数规划等方法，不能把所有扩展都视作同样容易求解。

| 算法 | 核心目标与机制 | 与我们的关系 |
|---|---|---|
| 最大总分 / Min-Cost Flow | 在每篇需求、每人负载、COI 约束下最大化总适配分。OpenReview 中名为 MinMax 的分配器实现此类目标 | 可直接接收我们的新适配分；这里的 MinMax **不是**“最大化最差论文分数” |
| PeerReview4All | 改善最不利论文的审稿团队总适配；基于增量最大流，有理论公平性与统计准确性分析 | 是分配公平性基线；并未解决我们拟研究的可追溯 taxonomy 学习 |
| FairIR / FairFlow | 在总适配目标中加入每篇团队适配下限等局部公平要求；分别使用迭代舍入/流方法 | 是约束分配基线。FairFlow 的公平性保证不能直接等同于 FairIR 的理论保证 |
| Randomized Assignment | 优化边际分配概率 q_pr 的期望总适配，并限制 q_pr≤Q；再用保留边际与容量约束的采样生成离散分配 | 减少恶意 bid、串通、定向打压与身份猜测风险；作用与领域理解不同 |
| Perturbed Maximization（PM） | 优化 Σ s_pr f(q_pr)，如 f(q)=q−αq²，在质量与随机性之间折中；约束采样形成最终分配 | NeurIPS 2024 有明确真实部署证据；可以和我们的分数层组合 |

OpenReview 当前源码 README 还列出 FairSequence 等求解器；较旧用户文档只展示部分选项。平台支持某算法，不构成某会议使用该算法的证明。[R6–R7, P1–P4]

## 2. 四个会议的已核实做法

| 会议与年份 | 已证实的信号与流程 | 算法证据与边界 |
|---|---|---|
| ACL 2023 | 按 Area–Contribution–Language 思路匹配；官方方案说明收集细分领域、贡献类型，同时考虑 quota、COI、seniority，尽量保证至少一名资深审稿人；AC/SAC 人工调整 | 明确属于多维匹配，不能描述为单纯关键词或单一 embedding。本文未核实其底层求解器及全部权重 |
| ACL Rolling Review | 官方 FAQ：依据领域、既往工作、涉及语言自动分配；尝试至少一位非学生，避免同机构两位审稿人；AC 检查。建议维护 Semantic Scholar/OpenReview 论文画像以改善匹配 | 证明画像与多维约束的重要性；不据此指定某个 SPECTER 版本或某个 solver |
| ICLR 2025 | 官方 AC Guide：按研究画像分配；AC 可推荐审稿人，否则按研究画像自动分配；有 reviewer negative bids 和 AC 调整；目标为每篇三份高质量 review | 本次读取的官方资料未披露具体 affinity 模型、权重及最终 solver；不能凭 OpenReview 默认值补全 |
| ICML 2025 | 官方 Reviewer Instructions：审稿人申报研究专长并 bid；bid 是分配的一部分；检查冲突并联系 AC 调整 | 本次读取的官方资料未披露具体模型组合及 solver，因此不能将某一种研究算法直接称为 ICML 2025 算法 |
| NeurIPS 2024 | 文本与历史论文计算 affinity，再结合 bid；采用 PM，随后人工调整 | 官方部署说明明确：Q=0.9、α=0.1，每人上限 6 篇，使用 Gurobi；相比确定性最大总分方案保留约 98% 的匹配目标值 |

ACL 2023 官方报告称，84.97% 的 review 对应审稿人声明感兴趣的贡献类型；对目标包含非英语语言的论文，63.58% 的 review 来自具备相关语言能力的审稿人。这些是该会议的描述统计，不能作为相对旧算法的因果提升，也不能直接转成我们的方法结果。[R1–R2]

NeurIPS 的 98% 是匹配目标函数值，**不是审稿正确率或审稿质量达到 98%**。其官方博文关于五档 bid 的列举顺序与数值顺序存在文字歧义，本文不抄写具体五档映射；所需可复现细节应以实际配置/代码核对。[R4]

## 3. 与本仓库算法的逐层比较

项目事实来源：`docs/technical_details/S4_plan.md`（v4.2）、`scripts/s4_crowd_fusion.py`、`docs/technical_details/S6_reviewer_author_twins.md`、`S7_offline_evaluation.md`、`S8_online_review_mvp.md`。

### 3.1 当前 S4 已有方法与实验实现

- 从 keywords、title、abstract、introduction、conclusion、related_work 六板块生成可定位证据；多来源独立生成 L1/L2/L3 标签。
- 保留历史四路候选，后续 Kimi 未完成任务由 GPT 接续；同一实际来源观测去重，不能再把后续票当作四个独立模型。
- 词形归一、定义/embedding 近邻提出同义候选，显式交叉投票与层级包含验证。
- 多数票、Dawid–Skene、静态 Crowd Layer、条件 Crowd Layer；官方粗类头与自由多标签头分离；missing/abstain 不记为负票。
- BGE-M3 六字段表示，以及标题摘要 TA、标题摘要关键词 TAK 对照；结构修复与 E0/E1、R0/R1 消融。
- 200 篇是开发数据；细层没有 gold，潜在后验不能作为校准正确率；生产冻结仍依赖 S3。

这些属于**语义表示、弱监督标签融合与层级结构学习**。DS/Crowd Layer 中的“标注者”是模型来源，不是会议中的人类审稿人；模型可靠性不能直接当作人类审稿可靠性。

### 3.2 S6/S8 计划增加的行为与组合层

项目计划根据领域与审稿关注点构建匿名行为 archetype，选择 2 位细分领域 Twin、1 位同级大领域不同细分方向 Twin，再保留通用方法/实验/写作/伦理角色。其目标包含缺点覆盖、评审相关性、评分校准及 rebuttal 行为，而会议分配通常先解决有限真人池中的专家与工作量分配。

| 维度 | 顶会已有方法 | 本项目当前/计划差异 | 还需证明的内容 |
|---|---|---|---|
| 专长表示 | 历史论文语义表示、自报领域、bid；ACL 已考虑贡献/语言 | S4 自动归纳多层领域与原文证据，并处理跨领域关联 | 比单一 embedding 更能识别真实审稿能力，尤其是相近方向难例 |
| 可靠性 | COI、负载、资格和人工检查；研究算法关注公平/随机性 | S4 学习不同标签生成模型的混淆/条件可靠性 | 自动标签融合是否提升最终排序；模型错误相关性是否削弱收益 |
| 团队互补 | 已有跨领域、多维兴趣与资历约束 | S6 计划细分专家＋邻近专家＋通用角色，并引入历史行为偏好 | 固定 2:1 是否优于简单 Top-3、随机邻近专家、按需求自适应组合 |
| 分配规模 | 全会议、有限真人、每人多个任务 | S8 主要服务单稿 Agent 路由，Agent 可复用但仍有 token/时延成本 | 若声称替代会议分配，须补充全局容量、COI、资格与随机性约束 |
| 效果验证 | 适配分、bid 满足、负载、公平、随机性等 | S7 还计划审稿缺点覆盖、证据正确性、评分/rebuttal 校准 | 路由更好是否真正带来更有效的 review，而非只是更高相似度 |

**可以主张的待验证差异：**自动构建细粒度、证据可追溯的专长表示，并将其用于互补审稿角色路由。

**现有证据尚不足的主张：**“首次多维匹配”“首次专家互补”“比顶会分配算法更准确”“多模型投票已证明能替代人类专家”。ACL 2023 的设计已覆盖部分多维与跨领域动机；团队选择、覆盖优化等相邻文献尚需进一步检索。

对真人分配的合理接法是：给投稿论文与候选审稿人的**历史发表论文**用同一套表示建立画像，计算适配，再接相同分配器。公开匿名 Reviewer alias 只在单篇内有效，本项目也明确禁止跨论文关联；因此不能靠现有匿名 review 直接恢复某位真实审稿人的长期画像。

## 4. 可以使用的 Benchmark

### A. 首选：Gold Standard Reviewer Assignment

- 论文：*A Gold Standard Dataset for the Reviewer Assignment Problem*，Stelmakh 等，TMLR 2025；预印本首次发布于 2023，2025 修订。[P5]
- 规模：58 位研究者、477 个专家自评，评分范围 1–5；同时提供研究者发表论文画像与候选论文资料。
- 数据/代码：<https://github.com/niharshah/goldstandard-reviewer-paper-match>。
- 直接任务：对同一审稿人的两篇候选论文，正确排列其自评审稿能力；官方代码提供加权排序损失、easy/hard triples 等评价。
- 官方复现流程：10 组 `d_20_x` 画像数据，使用标题摘要评分，接作者的 `evaluation_script.py`；全文条件另有 `d_full_*` 子集，不能混用测试集合与输入条件。
- 适用性：最直接检验 S4 产生的表示是否改进适配分，尤其 hard triples。
- 限制：自评能力不是盲评审稿质量；数据较小、评分稀疏，不是完整会议规模的 COI/容量实例，也没有 Agent 团队互补标签。

该论文 2025 修订摘要报告：标题摘要条件下 SPECTER2 表现最好；全文 TF-IDF 可达到相近精度；直接使用的通用 LLM 落后于专门方法。这提示我们必须同时比较强科学 embedding 与便宜全文稀疏基线，不能把“用了 LLM”当成效果保证。摘要不支持断言任何 LLM 或本项目方法一定失败。

### B. 第二项：SciRepEval Paper–Reviewer Matching

- SciRepEval：EMNLP 2023，24 项科学文档表示任务；其中 Paper–Reviewer Matching 官方指标为 Precision@5、Precision@10。[P6]
- 项目：<https://github.com/allenai/scirepeval>。
- 元数据：<https://huggingface.co/datasets/allenai/scirepeval> 的 `paper_reviewer_matching`。
- 标签与候选审稿人：<https://huggingface.co/datasets/allenai/scirepeval_test> 的 `paper_reviewer_matching` 和 `reviewers`。
- 仓库说明该任务组合旧 NIPS reviewer 数据、UIUC reviewer 数据、IEEE ICIP 2016 retrospective 数据；不同来源标签的生成方式、候选池和分割必须分别核对。
- 适用性：公开统一评测接口下的专家检索，兼顾 ML、信息检索及视觉领域。
- 限制：P@k 的相关标签不自动等同于真实审稿能力；与 Gold Standard 的自评任务不可混报。当前未下载整套数据，未重新统计样本数和复现实验分数。

### C. 分配层：Fair Matching 的公开实例

- 论文：*Paper Matching with Local Fairness Constraints*，KDD 2019。[P2]
- 代码与部分复现实验数据：<https://github.com/iesl/fair-matching>，含 `data/`、`config/`；README 给出 MIDL 运行配置。
- 可比较：Min-Cost Flow、FairFlow/FairIR、PR4A、Randomized、PM。
- 指标：总适配、最差论文团队适配、低分位团队适配、低分配对比例、负载分布、COI/配额违规数、时间/内存；随机分配另看边际概率上限、熵、支持集和多个采样的方差。
- 限制：已有 affinity 矩阵通常只能测试“固定分数下谁分得更好”；缺少原始文本和专家标签时，不能检验我们的语义表示好坏。公开仓库只承诺包含部分数据，本次未逐文件验完整性。

### D. 项目已有 ICLR 数据适合下游评估

本仓库公开目录含 ICLR 2024–2026 题目摘要；本地完整流程另管理 review/rebuttal/decision。可用来研究领域泛化、review 内容、问题覆盖与年度漂移，但匿名匹配、未分配人的能力及完整 COI/bid 通常不可观测。

因此不能把真实 reviewer assignment 当唯一最优 gold，也不能把“未分给此人”当成负例，更不能用录用决定作为匹配准确率。PeerRead、OpenReview review 语料等同样需要先检查是否具备审稿人画像与独立专长标签，不能仅凭有 review 就称为分配 benchmark。

## 5. 最小而有解释力的比较方案

### 5.1 先测表示与适配分

候选基线：TF-IDF/BM25、BGE-M3、SPECTER2、SciNCL、SPECTER2+SciNCL、自报标签匹配、单模型 taxonomy、简单多数融合 taxonomy、完整 S4。完整 S4 在外部 benchmark 上先补充“候选审稿人历史论文→领域画像→配对分数”接口；目前尚无已冻结的接口与效果结果。

第一组所有方法只给相同标题摘要；第二组在可获得全文的**共同子集**给相同全文。S4 当前六字段/关键词条件单独报告，不能与只有 TA 的基线直接归因于算法。使用相同候选池、画像论文数和缺失处理，不能让一种方法额外获得目标自评、未来发表论文或待预测论文自身的 review。

报告 Gold 官方损失与 easy/hard accuracy、SciRepEval 官方 P@5/P@10，以及推理成本。小样本不确定性建议按 reviewer 分组 bootstrap，不能把同一人的多个 triples 当独立样本。若新增 fit/tune，按 reviewer/关联论文隔离；模型选型与校准不能使用最终测试标签。

### 5.2 再测全局分配

采用交叉对照，隔离分数和 solver 的贡献：

| 分数组件 | 分配器 |
|---|---|
| 强 embedding 基线 | Min-Cost Flow |
| 我们的适配分 | 同一个 Min-Cost Flow |
| 强 embedding 基线 | FairFlow 或 PM |
| 我们的适配分 | 同一个 FairFlow 或 PM |

约束、候选边、随机种子/采样次数一致。若“总适配”直接使用方法自己预测的分数，分数尺度变化可制造虚假收益：应使用独立专家标签或固定外部评价矩阵，并同时披露各 solver 实际优化的输入分数。用同一 embedding 生成标签、再评价同一 embedding 优化的分配存在循环验证。

### 5.3 最后测 Agent 团队的实际作用

同等总 token/费用预算比较：通用组、相似度 Top-3 专家、2:1 领域组合、2:1＋行为互补。用独立审阅者/预先审定的证据问题集比较有效关键缺点覆盖、错误指控率、证据定位正确率、重复意见和修改可操作性。现有公开匹配 benchmark 不能单独验证这一层。

这是建议的评测接口与对照框架，尚未执行，所有收益均为待验证假设。

## 6. 文献与官方来源

### 部署/工具来源

- [R1] ACL 2023 matching design：<https://2023.aclweb.org/blog/reviewer-assignment/>。
- [R2] ACL 2023 peer-review report：<https://2023.aclweb.org/blog/review-report/>。
- [R3] ARR Reviewer Guidelines，FAQ “How are paper assignments determined?”：<https://aclrollingreview.org/reviewerguidelines>。
- [R4] NeurIPS 2024 官方部署报告：<https://blog.neurips.cc/2024/12/12/neurips-2024-experiment-on-improving-the-paper-reviewer-assignment/>。
- [R5] OpenReview Expertise：<https://github.com/openreview/openreview-expertise>。
- [R6] OpenReview Matcher：<https://github.com/openreview/openreview-matcher>。
- [R7] OpenReview matching configuration：<https://docs.openreview.net/how-to-guides/paper-matching-and-assignment/how-to-do-automatic-assignments/how-to-run-a-paper-matching>。
- [R8] ICLR 2025 AC Guide：<https://iclr.cc/Conferences/2025/ACGuide>。
- [R9] ICML 2025 Reviewer Instructions：<https://icml.cc/Conferences/2025/ReviewerInstructions>。

### 核心论文

| ID | 论文 | 年份/来源 | 类型 | 相关性 |
|---|---|---|---|---|
| P1 | [PeerReview4All: Fair and Accurate Reviewer Assignment in Peer Review](https://arxiv.org/abs/1806.06237) | JMLR 2021；预印本 2018 | theory/proof | 最不利论文公平性与增量最大流 |
| P2 | [Paper Matching with Local Fairness Constraints](https://arxiv.org/abs/1905.11924) | KDD 2019 | pure method | FairIR/FairFlow 与公开复现实例 |
| P3 | [Mitigating Manipulation in Peer Review via Randomized Reviewer Assignments](https://arxiv.org/abs/2006.16437) | NeurIPS 2020 | pure method | 概率上限、期望适配与约束采样 |
| P4 | [A One-Size-Fits-All Approach to Improving Randomness in Paper Assignment](https://arxiv.org/abs/2310.05995) | NeurIPS 2023 | pure method | PM，NeurIPS 2024 部署方法来源 |
| P5 | [A Gold Standard Dataset for the Reviewer Assignment Problem](https://arxiv.org/abs/2303.16750) | TMLR 2025；预印本 2023 | pure benchmark | 真实专家自评与官方评价脚本 |
| P6 | [SciRepEval: A Multi-Format Benchmark for Scientific Document Representations](https://arxiv.org/abs/2211.13308) | EMNLP 2023；预印本 2022 | method + benchmark | Reviewer matching 任务及 SPECTER2 |
| P7 | [SPECTER: Document-level Representation Learning using Citation-informed Transformers](https://aclanthology.org/2020.acl-main.207/) | ACL 2020 | method + benchmark | 引文监督科学文档表示与 SciDocs |
| P8 | [Neighborhood Contrastive Learning for Scientific Document Representations with Citation Embeddings](https://aclanthology.org/2022.emnlp-main.802/) | EMNLP 2022 | pure method | SciNCL 强语义基线 |

核查使用官方页面、论文摘要及公开代码 README；没有将元数据或摘要冒充全文深读，也没有运行任何方法的性能测试。搜索过程、证据缺口见 `search-notes.md`；候选文献的初步质量评分见 `papers.csv`，评分不代表接受概率或完整方法复现审计。
