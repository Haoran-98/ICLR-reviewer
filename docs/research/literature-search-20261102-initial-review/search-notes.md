# 检索与来源记录

- 访问日期：2026-11-02；模式：quick，聚焦初始审稿生成与证据定位、质量评测。
- 公开检索词：scientific peer review generation；review generation scientific papers；peer review large language models。
- Semantic Scholar `graph/v1/paper/search`，query=scientific peer review generation、year=2024-2026、limit=15：返回 429，未用于结论。
- OpenAlex `/works`，search=review generation scientific papers、2024-01-01 至 2026-11-02、per-page=15；search=peer review large language models、2025 年起、per-page=25；title.search=reviewer、2024 年起、per-page=30。宽检索包含文献综述、审稿人致谢等误匹配，未用作最终方法证据。
- 网页通用检索遇到重定向页，未用作最终证据。
- 关键发现来源为 ACL Anthology 的四个主会目录：2025.acl-long、2025.emnlp-main、2026.acl-long、2026.emnlp-main。
- 从目录读取完整标题，再核对对应页面的 citation_title、citation_conference_title、citation_publication_date、DOI 和摘要；六篇核心记录见 `sources.json`，其中保留页面 SHA-256。
- 进一步下载 ReviewGrounder、PaperAudit-Bench、TreeReview 的官方 PDF，用 pdftotext 阅读相关部分；PDF SHA-256 亦保存在 `sources.json`。
- TreeReview 成本数值来自全文表 5：MARG 2,314,052、MARG-BASE 1,007,608、TreeReview 458,968 token/篇。80.2% 与 54.4% 分别以这两个基线作为成本比较分母。
- ReviewGrounder 全文 §4 和实验设置区分通用 meta-rubrics 与人类 Review 派生的 paper-specific 评测量表；不能把后者作为待审论文的生成输入。
- PaperAudit 的可检索正文和官方摘要足以核对机制与受控合成错误属性；PDF 个别图形文字存在提取乱码，未使用乱码图中文字作证据。
- 过滤了文献综述生成、推荐系统商品评论、代码审查、非相关期刊条目；最终核心列表均为 ACL/EMNLP 主会正式页面。
- 检索范围为与初始审稿设计相关的定向候选文献，数据库、检索式和时间记录如下。
- 未使用目标论文的私人正文、审稿意见或未公开实验结果作为网络检索词；未调用付费生成模型。
