# S5 Review/Rebuttal 轨迹与因果证据

状态：`三源融合原型已实现；20 样例开发集诊断完成；完整 S5 Gate 待验收`

## 已有基础

- core review、review revision、score、discussion、decision 表已存在；
- 2024 和 2025 revision 回填完成；
- 2026 回填约 51%，当前因 OpenReview token 过期停止；
- 总体 revision backfill 约 78%。

上述完成度仅为数据获取进度；S5 原型与诊断进展见下文。

## 计划实体

- atomic concern；
- author response；
- reviewer response；
- resolution：resolved / partially_resolved / unresolved / unknown；
- score/confidence change；
- observable outcome；
- counterfactual hypothesis 和 confounders。

## 计划推断规则

只有目标 Reviewer 针对该 concern 明确接受解释，或 Review revision/后续回复明确改变判断，
才能记录对应解决状态。分数变化与回复的时间先后单独只能支持关联，不能证明 concern
已解决。最终录用、Reviewer 沉默或语言共现不能单独作为因果证据。

每个反事实必须分开保存：观察事实、因果假设、混杂因素、反事实条件、支持/反对证据和
置信度。

## 计划产物与 Gate

- 可重放的 conversation tree；
- concern-response-resolution ledger；
- positive/negative/unknown outcome；
- counterfactual evidence table；
- 每个结果回指 OpenReview Note/Edit/revision。

无回复必须保持 `unknown`。revision 不公开时只能使用可观察快照并降低置信度。

## 三源融合方法与 20 样例试跑

2026-11-01 启动、2026-11-02 完成开发集诊断（北京时间），阶段质量验收另行推进。执行说明与代码入口见
[`../../benchmarks/s5_trajectory/README.md`](../../benchmarks/s5_trajectory/README.md)。

- RbtAct：复用 review–rebuttal 对齐思路与 CRP/SRP/VCR/DWC/DRF 作者行动标签。
  行动标签记录回应方式；回应质量与作者所述修改分别核验。
- DRPG：执行 concern 拆解、证据检索、候选策略生成、可执行性筛选和回复草稿生成。
  Planner 同时读取 concern 历史，缺少实验时列出待完成行动。
- 改分轨迹研究：复用初始评分结构的分析思路，以及有来源链接的 44 项交流特征标签。
  本轮只进行可观察特征标注与未校准的方向判断，不拟合评分模型或策略因果效果。

每个 concern 分别记录作者行动、证据支持、审稿人明确判断及可观测性。
真实后续事件更新历史状态；模型生成草稿和模拟判断另存，不写入历史事实。

试跑使用配置中的 OpenAI 弱模型，`reasoning.effort=medium`，API 单并发。
20 篇独立论文均来自已有开发集：2024、2025 各 10 篇；每年各含 5 条有后续
目标审稿人反馈、5 条无反馈的线程。每例两个依赖调用：先处理时间截断前缀，
再回放真实后续记录并检索正文快照。正文快照的历史版本时间未核实，故只用于
事后支持核查和下一步规划，不进入前缀预测输入。

运行产物保存在仓库外，逐例保存源记录、输入哈希、请求/响应、引用字符位置、
concern 台账、候选策略与回复草稿。历史分数缺乏独立时间配对时保持 `unknown`。
本轮不训练模型、不运行对照实验，程序引用核验也不替代人工语义裁决。

### 本轮运行结果

- `gpt-6-luna`、中等思考，20/20 样例、40/40 阶段结果完成；请求起止记录核验并发峰值为 1。
- 初始 concern 共 91 个：resolved 2、partially_resolved 4、unresolved 5、unknown 80；后续新增 concern 4 个另存。
- 无后续目标审稿人回应的 10 个样例包含 46 个 concern，全部保持 unknown。
- 引用位置、输入哈希、来源角色、策略可执行性及阶段覆盖的程序核验通过；5 处不可执行策略暂缓。
- 发帖顺序与当前快照可用顺序分别保存，缺失父节点仅保留 ID；原始模型输出和约束处理记录均可追溯。
- 共 56 次请求尝试，其中 39 次直接通过，另有 1 个阶段从已保存响应约束恢复；2 次传输失败用量未知。
- 历史数值改分均为 unknown，缺少独立时间配对的前后快照；当前结果不提供改分预测准确率或策略因果效果。

报告位于 `/data_big/iclr-s5/experiments/fused20_gpt6luna_medium_v1/REPORT.md`；
同目录的 `verification.json`、`verify_run.py` 和逐例 `replay_timeline.json` 提供无需模型调用的复核与回放。
