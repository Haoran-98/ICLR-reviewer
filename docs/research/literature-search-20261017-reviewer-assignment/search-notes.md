# 检索与核查记录

日期：2026-10-17。模式：standard。目的：会议分配机制、与仓库 S4/S6/S8 的差异定位、公开 benchmark 发现。

## 查询及路径

使用公开关键词：reviewer assignment、reviewer matching benchmark、ACL reviewer matching、ICLR/ICML reviewer instructions、NeurIPS randomized assignment、PeerReview4All。没有向外发送项目私有文本或实验结果。

Google 返回跳转页；DuckDuckGo 返回人机挑战；Bing 对多词查询返回与首词相关但与完整问题无关的结果，故不将其结果作为证据。Crossref `/works?query.title=PeerReview4All&rows=2` 返回空 items；不据此推断论文不存在。

转而读取官方 conference guides、ACL/NeurIPS 博文、OpenReview 用户文档、论文 arXiv/ACL Anthology 页面、作者/工具仓库 README。部分代理请求出现 SSL EOF/timeout；在无需凭据的官方站点使用直接连接后取得正文。GitHub 网页/raw 连接不稳定，改用官方 GitHub REST `GET /repos/{owner}/{repo}/readme`，检查 HTTP 状态后解码 `content`。仓库定位包括：

- openreview/openreview-expertise
- openreview/openreview-matcher
- niharshah/goldstandard-reviewer-paper-match
- allenai/scirepeval
- iesl/fair-matching
- niharshah/PeerReview4All

NeurIPS 官方站 WordPress endpoint：`https://blog.neurips.cc/wp-json/wp/v2/posts?search=assignment&per_page=100`，筛出 2024-12-12 官方部署报告，再读取公开文章。ACL 2023 `/blog/` 目录定位 `/blog/reviewer-assignment/` 与 `/blog/review-report/`。没有将猜测后返回 404 的 URL 当作支持来源。

arXiv 精确 ID：1806.06237、1905.11924、2006.16437、2310.05995、2303.16750、2211.13308。ACL Anthology 精确 ID：2020.acl-main.207、2022.emnlp-main.802。

## 证据分级

- 真实部署已确认：ACL 2023 多维匹配、ARR FAQ 中的自动+人工流程、ICLR 2025 AC 画像与负 bid 流程、ICML 2025 bid/专长流程、NeurIPS 2024 PM。
- 工具能力已确认：OpenReview Expertise 的模型与聚合；Matcher 的 MinMax/FairFlow/FairIR/Randomized/FairSequence/PM。
- 未确认：ICLR/ICML 指定年份的最终 solver、模型 revision、分数权重；2026 年四会完整配置。工具默认值不能填补这些缺口。
- 数据集可用性：Gold Standard 作者仓库提供数据与脚本；SciRepEval README 明确提供 matching/reviewer configs 和 P@5/P@10。未批量下载数据，也未跑 benchmark。
- FairFlow 仓库已确认存在 data/config 目录及 MIDL 运行说明；没有逐文件审计全部实例的负载/COI/文本字段。
- NeurIPS 官方博文 bid 列表与数值排列有歧义，因此报告只使用“affinity+bid”的已确认机制，不采用其可疑逐档数值顺序。

## 本地事实与范围

读取 S4 v4.2 与 crowd fusion 实现、S6/S7/S8 状态及总体计划。当前 S4 的 200 篇全部为开发数据；S6/S8 尚未实现，不能把计划性行为孪生与固定 2:1 组合当作经过验证的完整分配算法。

没有调用模型进行新的标签生成、改变当前实验、修改既有计划、运行 GPU 任务或下载大体积 benchmark。新增内容仅为本检索目录。

## 质量与去重

优先主来源，排除低质量/政策排除来源，不引用 MDPI。论文按标题/标识去重；Gold Standard 标记为 TMLR 2025，SciRepEval 标记为 EMNLP 2023，避免把 arXiv 首发年份当最终发表年份。

papers.csv 的分数为基于摘要、开源实现和部署/数据文档的初筛：insight 反映问题与机制清晰性；completeness 反映可检查的理论/代码/数据覆盖；numeric_evidence 只表示可见数值证据充分性，未做全文统计或重现审计。pure benchmark 的 numeric_evidence 按要求记 N/A benchmark。

## 未解决与后续接口

更强创新性结论仍需检索 team formation、expertise coverage、complementarity/diversity、LLM reviewer routing 等相邻方法。当前报告足以否定“多维匹配本身是新点”，不足以裁定完整项目创新性。

可向实验设计模块交接：Gold Standard 官方协议＋SciRepEval matching＋相同 score/solver 交叉对照。本文只给比较框架，不报告未执行的实验或收益。
