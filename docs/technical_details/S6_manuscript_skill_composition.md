# 按新稿组合领域 Skill

> 当前进度补记（2026-11-12）：本文保留原实验/发布当时的协议与统计；其后已完成独立单篇 Web 审稿与任务恢复。当前汇总见 [STATUS](../STATUS.md)，新任务模型配置和部署见 [DEPLOYMENT](../DEPLOYMENT.md)。文末尚未集成 Web 的描述属于历史时点。

入口：[compose_manuscript_skills.py](../../scripts/compose_manuscript_skills.py)。
固定规则输入：[llm-area-v1](S6_llm_area_library_release.md)。
本实现对应演示路线第 2 项，产物是带适用性依据与历史来源的检查项组合。
状态：2026-11-07 实现完成，OpenAI 弱模型真实运行及本地检查通过。

## 输入、模型与步骤

使用项目配置的 OpenAI 弱模型 `gpt-6-luna / medium`，单并发。
复用原有 Responses 请求通道、请求哈希缓存、模型与思考配置验证和原始响应记录。
每阶段至多两次传输尝试；完整返回中的格式或证据错误不触发额外修复模型。
适用性阶段逐条保留有效判断，将无效、缺失或重复判断隔离为 `insufficient_evidence`；
原始失败记录保持不变，恢复结果另存 `recovered_result.json`，不猜测引文或修改科学解释。

支持数据库论文 ID，或本地 Markdown 稿件及可选标题、论坛 ID。
数据库读取仅包括题目、摘要、论坛 ID 和稿件文件，不读取目标人类 Review、评分或决定。
按 ID、论坛 ID 和完整文本核对目标与所有领域库来源输入的隔离；来源资格名单中未产出
候选规则的论文同样排除。已有运行核验输入、配置、代码、协议和规则版本后复用缓存。

1. 完整保留可用稿件文件，包括其中已有的附录文本，并连续分段，记录原文字符区间。
2. 第一次模型调用识别领域、方法、任务和技术对象，每个判断引用原文。
3. 按四类信息对规则做字符 TF-IDF 检索。默认只检索 source_supported，最多提交 24 条。
4. 第二次模型调用逐条判断方法、任务和技术对象是否兼容，给出适用性、理由、优先级和证据。
5. 本地按来源状态、模型优先级和检索次序选取适用规则，执行条数及规则文本 token 双预算。
6. 为加载规则附加模块路径、规则版本、原文引文位置，以及历史候选和两篇独立配对来源的展示片段。

默认上限为 10 条、4,000 个 `cl100k_base` 代理 token；计数对象是实际供下一步审稿使用的
`checks.json` 规则文本，历史来源及加载解释为展示元数据，分别保存在 `composition.json`。
每次模型请求的实际序列化输入另有 64,000 个代理 token 上限。
超限时减少规则候选，不裁剪稿件；完整稿件本身超限时停止并保留输入。

`--include-candidates` 显式允许候选规则，占短名单最多四分之一；最终加载仍优先来源支持规则。
不强制凑齐 general/domain/method/task/specialty 五层，也不强制加载满预算。
当前单领域库没有满足跨领域门槛的 source_supported general 规则。

## 适用性与输出约定

每条进入模型短名单的规则恰有一次判断：`applicable`、`not_applicable` 或
`insufficient_evidence`。适用规则必须有至少一个匹配轴和可核验引文，不能带
`unknown` 或 `not_match`；证据不足必须列出缺少的信息。
规则适用仅表示应执行该条件检查，不表示新稿已违反规则。

加载结果进一步区分 `loaded`、`rule_count_budget`、`rule_token_budget` 及不适用／证据不足。
未进入短名单的规则保留检索分数与 `not_assessed`，不伪装成已判断不适用。
原文引文核验原始子串，或唯一的空白归一化匹配；保存原始模型响应和恢复后的精确字符区间。

| 产物 | 用途 |
|---|---|
| `MANUSCRIPT.md`、`manuscript.json` | 完整稿件、连续分段及覆盖记录 |
| `profile.json` | 模型识别的方法、任务、对象及原文依据 |
| `retrieval.json` | 规则检索次序、分项分数、短名单及未评估状态 |
| `applicability.json` | 模型对短名单每条规则的适用性判断 |
| `checks.json` | 实际加载的有限规则文本，供后续审稿输入使用 |
| `composition.json` | 版本、预算、加载解释、目标证据和历史来源，供 Web 使用 |
| `COMPOSITION.md` | 可直接阅读的组合结果及全部短名单判断 |
| `AUDIT.json` | 输入隔离、证据定位、预算及产物哈希 |
| `requests/`、`progress.json` | 原始请求、响应、用量、执行状态和失败记录 |

历史来源取自冻结库的真实候选、初审单元和稿件片段，读取前复核来源文件哈希。
配对来源数量表示可追溯支持，不表示历史意见已经科学裁决；稿件与初审的版本日期未确认对齐。

## 运行与检查

在仓库根目录执行，`RUN_DIR` 和 `RELEASE_DIR` 由调用者设置：

```bash
python3 scripts/test_compose_manuscript_skills.py
python3 scripts/compose_manuscript_skills.py run \
  --root "$RUN_DIR" --release "$RELEASE_DIR" --paper-id 33089
```

本地稿件入口：

```bash
python3 scripts/compose_manuscript_skills.py run \
  --root "$RUN_DIR" --release "$RELEASE_DIR" \
  --manuscript "$PAPER_MARKDOWN" --title 'Manuscript title' \
  --max-rules 10 --rule-tokens 4000 --shortlist 24
```

`prepare` 命令只准备输入并核对范围，不调用模型。
同一目录相同请求复用成功结果；不同论文、规则版本、预算或代码须使用新目录或明确迁移。

离线检查覆盖原文引文、空白恢复、虚构证据拒绝、逐规则完整性、范围不确定性拒绝、
来源支持优先级、条数与 token 上限、完整文本保留、重复运行身份以及 ID／论坛／全文来源隔离。

## 真实运行记录

案例为 ICLR 2026 论文 33089，*Multi-Head Low-Rank Attention*，论坛 `vBJKZ19XGY`。
产物目录名为 `manuscript_composition_mlra_v1`，位于既有 experiments 目录。
该稿与库内全部 1,286 篇来源按 ID、论坛和全文隔离。模型输入完整保留 88,275 字符、
27,319 个文本代理 token，包括文件中已有的附录文本；未做图像核验。

两次真实请求均返回 `gpt-6-luna / medium`，共计输入 72,140、输出 3,745，
总计 75,885 个 provider 返回 token。没有额外修复推理调用。
模型评估 24 条来源支持规则，最终 3 条适用、20 条不适用、1 条证据不足；
其余 1,827 条规则保留未评估状态。实际加载 3 条、1,605 个规则文本代理 token：

| 规则 | 加载目的 |
|---|---|
| R6574 | 核验语言模型相对性能主张的基线覆盖与条件可比性 |
| R8311 | 核验推理效率主张与成本测量、比较对象是否对齐 |
| R1054 | 核验解码加速主张与延迟、吞吐量等直接测量是否对应 |

每条加载规则均保留精确目标引文、模块与版本，以及两篇独立历史论文的 Review／稿件配对展示。
一次适用性原始响应中，R4170 的“不适用”判断将引文中的参考文献省略，
逐字核验失败。该行连同错误隔离保存，加载决策改为“证据不足、待核实”；
其他 23 条有效判断原样保留。`runtime/migrations/applicability_quote_quarantine_v1/`
记录新增本地隔离逻辑时的代码、manifest 和请求哈希迁移，原响应不改写。

离线回归包含无效行隔离与有效行保留。真实案例还执行禁用 HTTP 的缓存重放，
验证无新增调用、原始尝试和组合内容不变、所选来源配对及目标引文位置正确；
结果保存在 `REPLAY_AUDIT.json`。模型适用性判断本身尚未经独立领域专家裁决。

本阶段不生成 concern 或评分，不更新冻结库。第 3 项仍需 3–5 篇未参与提炼的新稿完整审查，
验证 concern 的真实性、正文定位与修改优先级；第 4 项再接入 Web。
