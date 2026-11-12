# S6 领域审稿 Skill：无训练原型

状态：2026-11-02 已完成单领域、单篇新论文流程验证；审稿质量提升待评测。

## 方法

S4 标签负责路由；历史论文与初始 Review 配对提炼检查经验；新论文正文负责提供
当前判断的证据。借鉴 [ReviewGrounder（ACL 2026）](https://aclanthology.org/2026.acl-long.1477/)
的 rubric 与 grounding 思路，当前实现不包含其训练式 drafter 或多 agent 系统。
不从目标论文的人类 Review 构造生成用 rubric。

每条 skill 包含适用条件、检查内容、所需证据、严重性条件、暂不判断条件，以及
历史 Review 和对应论文段落 ID。至少两篇不同论文的配对来源才能形成可复用规则；
单篇经验另行保留；来源数量用于记录独立配对支持。

新稿按领域加载 skill，并在一次模型调用中检查证据、生成优点、concern、问题、
评分与置信度。concern 记录观察、影响、修改建议、正文证据及不确定性。
历史 concern 只触发检查，不能直接成为新论文的缺陷。匿名 reviewer alias 不跨论文关联。

## 本次运行

| 项目 | 实际设置或结果 |
|---|---|
| S4 路由 | `acm:3:#10010305`，Latent variable models；另要求标题/摘要支持 diffusion 范围 |
| 历史来源 | ICLR 2024：1833、2505、2584，均来自已有 dev 划分 |
| 新稿 | ICLR 2026：33830，Plug-and-Play Prompt Refinement via Latent Feedback for Diffusion Model Alignment，dev |
| skill | 5 条候选中 3 条满足双论文配对来源条件，另 2 条保留为单篇案例 |
| 检查项 | conditioning-design、comparison-and-reporting、data-and-generalization |
| 模型 | `gpt-6-luna`，medium，单并发 |
| 审稿输出 | 3 个 concern；13 个被引用的目标正文段落 |
| skill 长度 | 872 token，使用 cl100k 代理计数 |
| 已返回用量 | 输入 12,538 + 输出 2,678 = 15,216 token |
| 审稿阶段用量 | 输入 6,705 + 输出 1,536 = 8,241 token |

实际共 3 次 HTTP 尝试：首次 400，随后两次返回凝练与审稿输出。上表用量来自这两次
返回记录；400 未返回用量，不能据此确定其计费。凝练结果的来源条件筛选在本地完成，
采用提示词完成单领域初始审稿；对照评测作为后续任务。

## 实现与复用

通用流程见 [项目 Skill](../../skills/domain-review-grounder/SKILL.md)，入口为
[domain_review_skill.py](../../scripts/domain_review_skill.py)。数据与模型原始输出保存在
外部运行目录，默认是 `/data_big/iclr-review/experiments/domain_skill_smoke_v1`。

```bash
python3 scripts/domain_review_skill.py self-check
python3 scripts/domain_review_skill.py prepare --root "$RUN_DIR"
python3 scripts/domain_review_skill.py run --root "$RUN_DIR"
```

`RUN_DIR` 为调用者指定的产物目录。默认参数使用上表的开发集论文。匹配请求哈希的
已完成结果直接复用；失败默认停止，`--retry-failed` 才允许一次额外尝试。
文件锁保证同一运行目录单实例执行。

后续同领域新稿使用新目录、指定目标论文和既有 skill：

```bash
python3 scripts/domain_review_skill.py run \
  --root "$NEXT_RUN_DIR" --target-paper-id "$TARGET_PAPER_ID" \
  --skill-dir "$RUN_DIR/skills/diffusion-reviewer"
```

复用前核对历史 Review/正文片段、源论文哈希和 S4 标签哈希。凝练阶段不调用模型，
每篇新稿只需一次审稿调用。当前 runner 限定为上述 diffusion 范围，目标还必须具有
已有 dev 划分、正文、理解 profile 与相应 S4 导出标签；多领域注册与自动选源仍待实现。

## 验证范围

程序核对来源与目标隔离、年份顺序、输入哈希、引用段落的字符位置、输出 schema、
规则的独立配对来源及目标正文中的审稿证据；语义支持与科学正确性需独立评测。

历史 Review 取最早已观测版本；存在作者首次回复时间时要求它早于该时间，仅使用
回复时间元数据。历史正文使用当前快照，版本日期标为未核实。
目标的 Review、评分、decision 和作者回复内容不进入模型输入。

本次使用部分文本证据包，尚未核验图表或外部文献。三个 concern 均标记为
`needs_verification`，当前输出更适合作为待核验的初审草稿。下一步优先补全它们涉及的
结果表与实验段落，确认问题是否成立，再判断 skill 的审稿价值。
