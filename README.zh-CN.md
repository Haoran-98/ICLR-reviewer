# ICLR Reviewer

[English](README.md)

ICLR Reviewer 将 ICLR 公开论文、审稿意见、作者回复和最终决定整理成可复现的数据与多 Agent 审稿基础设施，用于研究 ICLR 的评分逻辑、审稿趋势、rebuttal 成败、录用因素，以及构建基于证据的审稿人和投稿人模拟。

即使目标是其他会议，项目也统一使用 ICLR 视角审视研究：创新性、技术可靠性、实验与证据、清晰度、可复现性、伦理风险和领域匹配。目标不是模仿可识别的真实个人，而是从公开历史证据中构建可审计的审稿行为模型，并保留不确定性与反事实假设。

## 仓库内容

- ICLR 2024-2026 主会论文的题目、摘要和主题目录
- 用于确定性过滤、提取、批处理、校验和审稿画像生成的 Python 脚本
- 通用审稿 Agent 分组及其协作规则
- Agent、Education 和交叉领域论文清单
- 已验证的 1% 端到端分析样本

仓库不包含论文 PDF、Workshop 记录、认证信息、API 请求/响应日志或本机路径。

## 分组审稿 Agent

公开配置位于 [`agents/reviewer_groups.json`](agents/reviewer_groups.json)：

- 核心审稿组：正向论证、严格批判、方法可靠性、实验与证据、创新定位、写作、伦理与复现
- 扩展审稿组：领域应用、消融证据、复现和非专家可理解性
- 决策与审计组：AC / Meta-Reviewer 和独立 Citation Auditor

通用面板始终运行，并可增加最多三个匹配的领域专科角色。AC 必须基于稿件证据解决冲突，不能用平均分掩盖致命问题；引用审计独立于 AC。

## 题目与摘要目录

[`raw/`](raw/) 按年份和主会主题展示论文，并为每年提供轻量 JSONL gzip 索引。字段仅包含主题、题目、摘要、关键词、OpenReview ID 和页面链接，不包含 review、rebuttal、decision、作者或 PDF。

当前共收录 38,890 篇主会论文：

- 2024：7,404 篇
- 2025：11,672 篇
- 2026：19,814 篇

[`raw/manifest.json`](raw/manifest.json) 记录论文数、主题数、索引体积和 SHA-256。

## 时间协议

- 2024：训练
- 2025：校准
- 2026：完全留出测试

使用者可以为自己的实验定义其他划分，但项目的历史审稿孪生协议不会把 2026 证据加入画像生成提示词。

## 已提取领域与冒烟测试

- Agent：1,745 篇，其中 1,594 篇为核心相关
- Education：52 篇，其中 45 篇为核心相关
- Agent + Education：7 篇，其中 6 篇为 core/core
- 1% 主会冒烟测试：389 篇，使用 3,428,182 tokens，Python 确定性过滤减少 13.61% payload

相关文件位于 [`twin_smoke/output/priority_agent_education/`](twin_smoke/output/priority_agent_education/) 和 [`smoke_report.md`](twin_smoke/output/smoke_report.md)。公开清单均移除了本机 `source_path`。

## 安装

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

运行本地提取流程：

```bash
export ICLR_REVIEWS_ROOT=/path/to/iclr_reviews
python twin_smoke/extract_priority_topics.py
python twin_smoke/prepare_priority_luna.py --batch-tokens 90000
```

API 运行器通过 `ICLR_AUTH_FILE` 读取兼容 OpenAI 的配置。不要提交认证文件、请求 payload 或模型原始响应。

## 研究边界

- 排除 Workshop 和 PDF 文件。
- reviewer silence 或语义不明确统一标记为 `unknown`。
- rebuttal 分析同时覆盖提分和未提分，并区分观察证据、因果假设与反事实条件。
- 匿名 reviewer ID 不用于推断真实身份。
- 历史模式只支持带不确定性的估计，不保证评分或录用结果。
