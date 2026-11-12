# ICLR Reviewer 分阶段技术细节

本目录保存总体计划 S0-S10 的技术事实、数据血缘、实现状态、接口和验收门。
当前进度以 [STATUS](../STATUS.md) 为准，方法与论文出处见 [METHODS](../METHODS.md)，部署见 [DEPLOYMENT](../DEPLOYMENT.md)。
[总体计划](../ICLR_REVIEWER_MASTER_PLAN.md) 保留历史设计；各实验文档按其记录日期阅读。以下索引更新于 2026-11-12。

## 状态约定

- `已完成`：实现和阶段验收均已有证据。
- `进行中`：实现已经运行，但尚未完成全量验收。
- `规划中`：只有批准的设计和 Gate，没有可声称完成的实现。
- `阻塞`：实现已开始，但依赖外部状态或人工动作。

## 阶段目录

| 阶段 | 技术文档 | 当前状态 |
|---|---|---|
| S0 | [`S0_governance.md`](S0_governance.md) | 已完成 |
| S1 | [`S1_data_and_fulltext.md`](S1_data_and_fulltext.md) | 已完成 |
| S2 | [`S2_understanding_benchmark.md`](S2_understanding_benchmark.md) | 已完成 |
| S3 | [`S3_profile_pipeline.md`](S3_profile_pipeline.md) | 38,807 篇画像已入库，质量与余缺审计待完成 |
| S4 | [`完整计划`](S4_plan.md)；[`概要`](S4_taxonomy.md)；[`问题描述`](S4_problem_description.md) | 实体/核心/向量 12,964 篇已封存；正式层次分类未冻结 |
| S5 | [`S5_review_rebuttal_trajectory.md`](S5_review_rebuttal_trajectory.md) | 20 篇两阶段诊断完成；版本继续回填，质量/效果评测未完成 |
| S6 | [`S6_reviewer_author_twins.md`](S6_reviewer_author_twins.md)；[`领域库冻结`](S6_llm_area_library_release.md)；[`按新稿组合`](S6_manuscript_skill_composition.md) | LLM 领域库冻结、按稿组合及单篇真实 Review 完成；质量评测待完成 |
| S7 | [`S7_offline_evaluation.md`](S7_offline_evaluation.md) | 规划中 |
| S8 | [`S8_online_review_mvp.md`](S8_online_review_mvp.md) | 已实现单次组合审查 Web；多审稿人/AC 尚未实现 |
| S9 | [`S9_online_rebuttal_mvp.md`](S9_online_rebuttal_mvp.md) | 规划中 |
| S10 | [`S10_trend_and_release.md`](S10_trend_and_release.md) | 规划中 |

## Web 数据可视化专项

| 专项 | 技术文档 | 当前状态 |
|---|---|---|
| 历史论文数据探索 | [`六步计划`](Web_visualization_plan.md)；[`V1 验证记录`](Web_visualization_V1.md) | 实体队列地图、领域边界、弦图及论文级评分/分歧已接入 |
| 评分与分歧组合图 | [`ggdist 升级`](Web_ggdist_upgrade_2026-11-11.md) | R/交互统计一致性及浏览器验证通过 |
| 登录与文档上传 | [`访问控制与上传`](Web_access_and_upload.md) | 页面/静态/API 认证与 Word/PDF 提取已实现 |
| 用户自填审稿接口 | [`连接输入与隐私`](Web_user_api_configuration.md) | Base URL/Key/模型自行输入，地址密钥不持久化，重试重新输入 |
| 独立单篇审稿页 | [`接入与验证记录`](Web_single_paper_review.md) | 已接入现有 Web；单篇真实运行、重试恢复与 HTTPS 验证通过 |

## 更新规则

1. 已实现阶段必须引用真实代码、表、配置、运行报告或日志。
2. 规划阶段不得把候选模型、阈值或表结构写成已经实现。
3. 模型、prompt、输入、派生结果和 Gate 必须版本化。
4. 观察事实、作者声称、模型抽取和模型推断必须分开记录。
5. 阶段 Gate 通过后，同时更新本目录和总体计划。
