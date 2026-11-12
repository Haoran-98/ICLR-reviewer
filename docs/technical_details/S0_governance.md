# S0 总体治理与边界

状态：`已完成`

## 目标

固定项目目标、数据范围、执行顺序、成本原则、隐私边界和人工 Gate。

## 固定范围

- 只处理 ICLR 2024、2025、2026 主会，不处理 Workshop。
- 最终产物是 Reviewer Twin、Author Twin、离线评测、在线 Review/Rebuttal 和
  2027 趋势预测。
- 不推断匿名审稿人的现实身份，不跨论文关联短 Reviewer ID。
- 原始 `/data_big/iclr_reviews` 保持只读，派生结果进入独立对象存储和数据库。
- 普通 Python/SQL 能完成的工作不调用 LLM。
- 强模型不是默认批处理模型，只能由固定规则触发。
- 不对全部 PDF 预先执行公式、表格、图片和 OCR 深度解析。

## 数据隔离

- 计划中的年度内划分版本为 `annual_stratified_v1`。
- 每年分别使用 70% train、15% calibration、15% held-out test。
- 同一论文的所有版本、Review、Rebuttal 和 discussion 必须落入同一 split。
- test 不得参与 prompt、模型、阈值、taxonomy 边界或标签选择。
- 另保留 2024 -> 2025、2024-2025 -> 2026 的滚动时间评测。

## Gate 与人工权限

以下动作必须由用户批准：进入下一阶段、修改研究目标或 split、引入新的付费模型、
发布数据/Agent/评测、把用户定制 Agent 放入私人仓库。

## 回滚原则

- PostgreSQL schema 使用 Alembic，迁移必须可 downgrade。
- taxonomy、profile、twin、prompt 均须带版本，不能覆盖旧版本。
- 派生表可由 raw/core 和对象存储重新生成。
- 每个主要阶段完成后创建数据库 snapshot、行数和哈希报告。

权威路线见 [`../ICLR_REVIEWER_MASTER_PLAN.md`](../ICLR_REVIEWER_MASTER_PLAN.md)。
