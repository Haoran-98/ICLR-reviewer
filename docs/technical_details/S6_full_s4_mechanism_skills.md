# S6：全量 S4 文献的机制级审稿 Skill 提炼

入口：[full_s4_review_skills.py](../../scripts/full_s4_review_skills.py)。
协议：[modular-review-grounder-full](../../skills/modular-review-grounder-full/SKILL.md)。
默认产物：`/data_big/iclr-review/experiments/modular_skill_full_s4_mechanisms_v3`。

使用已封存的 `entity_core_third_gpt6luna_medium_dual_v1` 全部 12,964 篇 S4 结果，
逐篇核查资格，不再只取五个领域的 100 篇。模型保持 `gpt-6-luna`，思考强度 `medium`，
请求并发最多 3。无训练、无对照实验、无新增试审或 rebuttal 处理。

## 提炼目标

每条可复用检查保留：审查对象、适用条件、潜在失效机制、影响、检查步骤、疑虑成立条件、
消除证据与例外。具体规则只能由本轮真实 Review 与稿件配对证据产生，不预置单篇试审的
二次密度、连续时间、测量网格等具体议题。

协议提供一般审查视角，例如主张适用边界、不同阶段间的保证传递、定义与推导、实验设计、
鲁棒性、比较归因及可实施性；不要求每篇都触发这些视角。对相同主题但技术对象或失效
机制不同的检查，保留独立条目。材料不可得、澄清请求与已经有证据的问题分别处理。
承认一个限制不等于解决问题；证明指向未输入附录不等于论文缺少证明。

## 来源与覆盖

只使用可核实为 reviewer、且早于首次已知作者回复的最早已观测 Review 版本。
排除 AC、meta-review、决策记录、时间不满足条件或无可提炼意见的记录，原因逐条记录。
当前稿件与历史 Review 版本未确认对齐，配对仅表示可追溯来源，不表示历史指控成立。

原始 Review 字段完整保存。weaknesses、questions、ethics concerns 连续切为带字符位置
的文本单元并分批；所有单元必须有原子项、无 concern 或未解决去向。保留上下文用于解释
条件性追问。主文来源证据沿用审稿定向片段检索，记录实际供给范围；没有命中证据保留
unknown。后续真正审稿仍须完整保留主文，并逐篇核验正文与附录边界。

同稿多 Review 或多请求不增加独立论文计数。至少两篇配对稿件才能标为 source_supported，
通用层还需跨领域来源；单来源有用条目保留 candidate。具体条款的科学正确性未自动验证。
本轮包含此前试审稿件时，这些稿件成为开发来源，不能继续作为新库未见样本。

## 全量运行

```bash
python3 scripts/test_full_s4_review_skills.py
python3 scripts/full_s4_review_skills.py prepare
python3 scripts/full_s4_review_skills.py run
python3 scripts/full_s4_review_skills.py report
```

全量运行按抽取、收集候选、局部整理、模块导出、执行审计依次进行。
抽取最多 3 并发；整理串行维护共享规则。每个请求最多两次 HTTP 尝试，仅网络异常、429、
5xx 可自动重试；完整但格式失败的响应尽量本地保留有效条目，未解释部分明确记为 unresolved。
失败原始响应保持不变，不调用额外修复模型。

全局 TF-IDF 使用稀疏矩阵，按需查询近邻，不构建候选数平方大小的相似度矩阵。
整理为每个候选记录去向，最多访问两次。SQLite 原子保存变更规则、候选队列与日志索引，
恢复后复用原请求结果，不重跑已成功推理。非重试故障保留失败记录，不用后台无限重启重试。
有抽取失败或候选仍 pending/deferred 时不能冻结成完成库。

五级模块为 general/domain/method/task/specialty，并按审查机制组织。
source_supported 与 candidate 分目录导出，registry 保留状态及规则来源。
每次新增、细化、合并、拆分和停用保存前后内容；禁止跨失效机制混并来增加支持数。

## 检查与结果边界

离线检查覆盖：完整 Review 字符分区、无静默丢失、有效科学字段原样恢复、稀疏跨批检索、
跨机制错误合并拒绝，以及增量持久化。完成时再核查来源哈希、引用字符位置、队列去向、
独立配对来源计数、实际模型／思考强度、请求完整性、并发和用量。

实时状态在 `PROGRESS.md`，总体状态在 `REPORT.md`、`summary.json`；
资格台账为 `eligibility.json`，Review 排除记录为 `review_exclusions.json`，
抽取失败为 `extraction_failures.json`。`AUDIT.json` 通过后才写 `FROZEN.json`。
规则数量、来源支持数或执行审计通过均不表示审稿质量已经提升。

## 2026-11-05 传输恢复修复

网关曾以 HTTP 200 返回 `status=failed`、`gateway_concurrency_limit`，省略 reasoning 字段。
旧传输代码先检查模型／思考配置，错误触发全局停止。现在先分类失败响应，限流和网络异常
按有上限的传输重试处理；只对完成响应严格验证模型和思考强度。实际配置不一致或认证拒绝
仍会停止。科研提示词、输入、模型、medium 和最多 3 并发不变。

此前 20 个网络／网关失败任务进入一次有上限的断点补跑；已耗尽两次尝试的 17 项最多增加
两次，另 3 项只使用原两次预算中的剩余一次。原始失败记录不修改，额外额度冻结在
`retry_allowances.json`，代码和 manifest 迁移留在 `runtime/migrations/20261105_transport_liveness`。
历史无用量返回的尝试，其费用仍未知。已成功任务不重新推理。

进度每 20 秒刷新心跳、累计成功数、失败待处理数和运行状态；进程异常退出后记录 failed
及原因。服务使用任务专用 Python 字节码缓存，以绕过本机损坏的系统缓存；不修改系统文件。
