# S4 显式记录与派生三级领域体系

状态：v4 四模型 200 篇开发实验；生产冻结依赖 S3。
完整规则与当前实施以 [S4_plan.md](S4_plan.md) 为准。
旧 [问题说明](S4_problem_description.md) 保留历史背景，不替代 v4 决策。

## 输入与结构

从原始论文抽取 keywords、title、abstract、introduction、conclusion、related_work，
分别编码为六板块向量与缺失掩码。证据引用回指原始 span 和字符位置。

DeepSeek Flash、Kimi、gpt-6-luna、Qwen3.5-9B Q8_0 独立自由生成，
每模型每篇最多 3 个 L1、9 个 L2、27 个 L3，允许有记录的剪枝。
三级目录不依赖 ICLR 官方标签；官方标签仅用于独立的 23 类监督头。
Kimi 由 K2.6 短暂切为 Coding 接口 kimi-for-coding、low 思考强度，遇5小时额度限制后切回 K2.6。
暂停时已完成139篇，剩余61篇按用户要求使用 Batch API 分层续跑（官方标示推理费用低40%，每批24h窗口）。
已完成结果、逐层模型来源及累计重试预算保留；模型混用记录见版本目录的 kimi_model_transition.json、kimi_k26_resume.json。

## 执行与评价

流程：原文冻结 → 六板块 embedding → 四模型独立生成 → 标签对齐/显式交叉投票
→ DS 与 Crowd Layer 双头融合 → embedding 关系修复 → 层级一致性 → 版本化实验落库。

不做人工抽查，不由单个强模型代替真值。用多模型可靠性、可定位证据、
结构合法性、争议与稳定性评价；细层后验不当校准概率。

当前版本 taxonomy_llm4_200_v1 的 200 篇均为 dev，旧 test 不再冒充未见测试数据。
正式评价另封存新论文，冻结后仅指派。四组 embedding 消融、leave-one-model-out、
移除可靠性迁移/关键词辅助和重新生成的 related-work 输入消融见完整计划。

全量 embedding 和本地 Qwen 分阶段占用 V100。API 即时执行，并发来自 auth，
初次请求后最多 5 次重试，成功结果按 hash 恢复。运行入口为
scripts/s4_llm_taxonomy.py 和 scripts/s4_crowd_fusion.py。

## 产物

版本化六板块向量、候选/拒绝记录、canonical mapping、投票、混淆矩阵、
潜真值后验、修复日志、nodes/typed edges/assignments 和开发报告。
官方 core.paper_area 保留观测事实；实验结果不发布到 frozen taxonomy 路由视图。
