# 初始审稿意见生成：近期顶会工作与项目映射

检索日期：2026-11-02。范围：ACL、EMNLP 2025–2026 主会论文的小范围检索。
目标：从“论文生成初始 Review”出发，支持弱模型、单次调用和可定位证据；不执行新模型实验。
以下发表信息均由 ACL Anthology 官方页面核对；阅读深度与元数据见 `sources.json`。

| 工作 | 发表 | 已覆盖的能力 | 对当前项目的借鉴 |
|---|---|---|---|
| [ReviewGrounder: Improving Review Substantiveness with Rubric-Guided, Tool-Integrated Agents](https://aclanthology.org/2026.acl-long.1477/) | ACL 2026 main | ReviewBench；初稿、文献检索、方法分析、实验分析、汇总；以 rubric 和上下文证据改善审稿实质性 | 用简短审稿标准约束意见；重要批评必须给出论文依据。完整多 Agent 流程与当前预算不符 |
| [PaperAudit-Bench: Benchmarking Error Detection in Research Papers for Critical Automated Peer Review](https://aclanthology.org/2026.emnlp-main.474/) | EMNLP 2026 main | 220 篇 AI/ML 论文、八类受控合成错误；从结构化错误检测证据生成 Review | 在同一次调用中先检查主张—方法—实验的一致性，再形成主要缺点；合成错误检出率按其受控数据协议解释 |
| [ReGround: Grounding Reviewer Comments in Multimodal Evidence](https://aclanthology.org/2026.emnlp-main.54/) | EMNLP 2026 main | 审稿评论到原始匿名稿的多模态证据检索数据 | 设计 concern—证据位置接口；正文、表格、图像按类型定位。rebuttal 用于构造标注，初始审稿输入保留时间隔离 |
| [DeepReview: Improving LLM-based Paper Review with Human-like Deep Thinking Process](https://aclanthology.org/2025.acl-long.1420/) | ACL 2025 main | 结构化分析、文献检索、证据论证；DeepReview-13K 与训练后的 DeepReviewer-14B | 与已有结构化 profile 最接近；训练与提示词路径按各自实验配置比较 |
| [TreeReview: A Dynamic Tree of Questions Framework for Deep and Efficient LLM-based Scientific Peer Review](https://aclanthology.org/2025.emnlp-main.790/) | EMNLP 2025 main | 自顶向下问题分解、自底向上答案汇总、动态追问、按问题检索 | 借鉴问题驱动取证；表 5 仍约 458,968 token/篇，不直接复刻整棵问题树 |
| [The Good, the Bad and the Constructive: Automatically Measuring Peer Review’s Utility for Authors](https://aclanthology.org/2025.emnlp-main.1476/) | EMNLP 2025 main | RevUtil 数据与评论效用评测；四方面为 Actionability、Grounding & Specificity、Verifiability、Helpfulness | 用于日后判断意见是否具体、有依据、可核查、可行动，而不只判断语言像不像审稿 |

## 与已有信息结合

已有 [50 篇论文理解实验](../../../benchmarks/paper_understanding/50_paper_report.md) 中，
one-shot 与分层方案的模型评审综合均值均为 4.5067；抽取 token/篇分别为 18,013.6 与 62,613.6。
这支持以 one-shot 作为成本默认路线，但实验任务是结构化理解，不直接证明初始审稿生成的质量。

建议在本项目中组合以下机制：

1. 普通程序从已有 profile、领域标签和正文索引组装证据包，保留核心主张、假设、实验设定与关键结果。
2. 同一次弱模型调用内，按简短 rubric 检查主张—证据对应关系，选择最重要的 3–5 个 concern 后生成初始 Review。
3. 每条 concern 保存问题、章节/表格/公式位置、短证据、对结论的影响和需要澄清的事项；输入覆盖不足时标注未核查。
4. 程序核验位置、引用与结构，批评的科学正确性由独立评测判定。

历史人类 Review 可用于训练集内构造领域检查项或离线评测，不输入待审论文自己的真实 Review、录用结果和作者回复。
ReviewGrounder 的全文也区分通用 meta-rubrics 与从人类 Review 构造的 paper-specific 评测 rubrics；后者不提供给生成器。

输出目标：summary、strengths、主要 weaknesses、questions、rating 与 confidence；评分需与已陈述的关键问题一致。
当前可沿用每篇一次、弱模型、中等思考、单并发及约 2,000 output token 的工程预算。
这一预算下的审稿质量通过本项目独立评测确定。

## 研究定位

证据支撑的自动审稿已经有直接先例。可进一步检验的问题是：固定较小预算下，
复用已有论文理解与领域信息，能否减少无依据批评，同时保留对关键缺陷的覆盖。
当前不据此声明方法新颖性；后续应区分引用匹配、证据真正支持批评、批评的重要性与可行动性。

本轮优先读法：ReviewGrounder 的 rubric/grounding 接口 → PaperAudit 的错误证据表示 → RevUtil 的意见质量定义。
TreeReview 用于理解动态取证的价值与绝对成本；DeepReview 用于对齐已有 profile；ReGround 用于证据定位。

## 补充筛选

- [ReviewRL](https://aclanthology.org/2025.emnlp-main.857/)：EMNLP 2025 main，文献增强上下文、SFT 与 RL；保留为后续训练路线。
- [Mind the Blind Spots](https://aclanthology.org/2025.emnlp-main.1805/)：EMNLP 2025 main，关注评价对象和评价维度的覆盖；适合作为后续评测补充。
- [BadScientist](https://aclanthology.org/2026.acl-long.1134/)：ACL 2026 main，研究不可靠论文对 LLM 审稿器的欺骗，提示“发现严重问题却仍给接收分”的一致性风险。
- [Can AI Be a Good Peer Reviewer?](https://aclanthology.org/2026.acl-long.1504/)：ACL 2026 main，综述，可用于继续扩展引用范围。

## 检索核验状态

已完成公开关键词检索、官方出版状态核验、候选去重、六篇核心工作分型与项目映射。
ReviewGrounder、PaperAudit-Bench、TreeReview 阅读了全文相关方法及实验部分；其余核心工作核对官方摘要与元数据。
未进行穷尽检索、全部全文复现审计或数值质量评分；本记录服务于当前方向选择，不作完整新颖性结论。
