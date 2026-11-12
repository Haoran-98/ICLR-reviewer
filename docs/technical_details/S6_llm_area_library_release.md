# LLM 领域 Skill 库冻结版 llm-area-v1

> 当前进度补记（2026-11-12）：本文保留原实验/发布当时的协议与统计；其后已完成独立单篇 Web 审稿与任务恢复。当前汇总见 [STATUS](../STATUS.md)，新任务模型配置和部署见 [DEPLOYMENT](../DEPLOYMENT.md)。文末尚未集成 Web 的描述属于历史时点。

状态：2026-11-07 构建完成；执行、恢复、来源范围、模块与文件完整性审计通过。

本页对应演示路线的第 1 项“领域 Skill 库收尾”。沿用仓库现有编号，
它属于 S6 的领域审稿规则库，不更改 S5 Review/Rebuttal 轨迹阶段的验收状态。

发布入口：[freeze_llm_area_library.py](../../scripts/freeze_llm_area_library.py)。
依赖的历史运行与恢复协议见 [单领域提炼记录](S6_llm_area_mechanism_skills.md)。
发布操作只做本地审计与文件导出，不调用模型，不重跑成功抽取，不修改原版或恢复版产物。

## 固定范围与候选去向

范围为 `foundation_or_frontier_models_including_llms`：1,319 篇领域论文中，
1,286 篇满足配对条件；1,318 个抽取任务全部完成，失败为 0。
6,538 条恢复目标完成有界处理，原来源与历史记录保留。

| 项目 | 数量 |
|---|---:|
| 全部候选 | 19,168 |
| incorporated | 18,420 |
| duplicate | 246 |
| case_only | 369 |
| not_generalizable | 49 |
| unresolved | 81 |
| needs_evidence | 3 |
| pending / deferred | 0 / 0 |
| source_supported 规则 | 1,851 |
| candidate 规则 | 7,324 |
| deprecated 规则（仅历史保留） | 154 |

规则修订号为 **7408**，规则库内容哈希为
`4443886e65e1ff18b73be38bb040cc917680eddd59457c3e603189f1e4b502d0`。
发布版本名为 **llm-area-v1**。81 条 unresolved 和 3 条 needs_evidence
携带原候选、原因、来源和访问历史单独保存在 `unresolved.json`，原队列仍完整保存。

## 导出与审计

恢复版历史目录中有 380 个不再列于当前注册表的旧模块目录。
发布器从冻结规则在新目录重新导出，只发布 7,795 个有效模块：
1,636 个 source_supported 模块与 6,159 个 candidate 模块。
另有 131 个旧导出名称因截断而含连续连字符，发布包规范这些名称并保存旧路径映射，
规则内容与稳定 ID 保持一致。9,175 条有效规则各出现一次，
模块的 `rules.json`、`SKILL.md` 与注册表逐条一致。
默认组合入口为 source_supported；candidate 独立保存，后续选择器必须显式启用。

发布前重新运行原有执行、来源范围和恢复审计，核查来源稿件与 S4 哈希、
Review 单元分区、正文引文字符位置、候选覆盖、独立论文支持门槛、
模型请求、授权并发区间和有界恢复历史。审计写入临时副本，不改写旧审计文件。

发布包固定以下内容：

- `RELEASE.json`：版本、规则修订号、内容哈希、通道配置与全部包内文件 SHA-256。
- `FROZEN.json`：发布清单哈希与冻结状态。
- `registry.json`、`skills/`、`rule_library.json`：模块入口与完整规则状态。
- `EXPORT_REPAIRS.json`：模块名称规范及原路径映射。
- `candidates.json`、`queue.json`、`unresolved.json`：候选、完整去向及未解决项。
- `AUDIT.json`：本次执行、恢复和模块审计。
- `PROVENANCE.json`：恢复版与原版来源、请求、响应、变更记录、稿件原文和 S4 输出的文件哈希。
- `protocol/`：本次使用的科学协议与相关代码副本。

来源与模型原始记录继续保存在原运行目录，发布包通过路径和哈希引用；
迁移时须同时保留这两个来源目录及其中引用的稿件和 S4 文件。
包内哈希和来源哈希均可重新核验。
历史模型设置分开保留：OpenAI `gpt-6-luna / medium`，
DeepSeek `deepseek-v4-flash / thinking=disabled`（恢复期间暂停），
本地 `qwen-flash-iq3 / thinking=disabled`。
恢复结束时授权并发为 OpenAI 4、本地 3，实际请求和历史并发区间见审计及来源记录。

## 使用与验证

在仓库根目录执行，变量由调用者指定，不将模型认证信息放入发布包：

```bash
python3 scripts/test_freeze_llm_area_library.py
python3 scripts/test_recover_llm_area_review_skills.py
python3 scripts/freeze_llm_area_library.py build \
  --source "$RECOVERY_DIR" --release "$RELEASE_DIR" --version llm-area-v1
python3 scripts/freeze_llm_area_library.py verify --release "$RELEASE_DIR"
```

`build` 拒绝覆盖已有发布目录；只有全部检查通过才原子移入最终目录。
`verify` 检查包内文件清单、模块与规则对应关系以及保留来源文件的哈希。
回归检查覆盖旧模块残留、科学文字改动、来源改动、外部稿件改动、
发布文件改动、额外文件拒绝及模块名称规范。

本次两个回归检查均通过。系统 `skill-creator` 标准校验器检查全部 7,795 个发布模块，
失败为 0；发布器核验 15,609 个包内文件、62,938 条来源文件哈希及 2,572 个外部
稿件／S4 文件引用。`RELEASE.json` 的 SHA-256 为
`a30ecb33dc8a047582fa8b3a4bc661be08651e096a50cafb5ec6de8811544ae3`，
由 `FROZEN.json` 固定。未新增模型请求。

此处完成的是可追溯规则库冻结。科学正确性与审稿质量提升由后续新稿验收判断。
后续按方法、任务和技术对象限预算组合规则，并逐条保存适用性及加载理由；
新稿验收须排除所有参与本轮提炼的来源论文，完整提供主文，按 concern 补查附录和图表。
组合审查、新稿验收、Web Review 闭环和演示回放尚未由本次冻结完成。

后续第 2 项实现及真实运行见 [按新稿组合领域 Skill](S6_manuscript_skill_composition.md)。
