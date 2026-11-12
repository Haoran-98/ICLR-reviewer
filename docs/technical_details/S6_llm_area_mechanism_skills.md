# S6：基础与前沿模型（含 LLM）的单领域版本

入口：[llm_area_review_skills.py](../../scripts/llm_area_review_skills.py)。
产物：`/data_big/iclr-review/experiments/modular_skill_llm_area_mechanisms_v1`。

用户已将全量工作收缩到大领域 `foundation_or_frontier_models_including_llms`。
它包含已完成 S4 论文 1,319 篇，占 12,964 篇的 10.17%。其中 1,286 篇满足当前配对标准，
含 4,350 份合格初审，拆成 1,318 个抽取任务。原始范围的 33 篇未满足配对条件，排除原因保留。

全量服务保持暂停，原有 1,199 个成功任务不改动。本轮从全量运行的冻结输入中筛选该领域，
不重新查询或扩展来源。既有该领域的成功缓存如存在则按原哈希复用；没有导入全库规则库。
抽取、候选检索、局部整理和导出都只包含本领域；准备与审计会检查范围和 Review 单元分区。

使用相同的 `gpt-6-luna`、`medium`，以及相同科研提炼提示词与来源门槛。
2026-11-06 按用户指令将 API 并发上限从 3 调至 4；先等待在途请求保存，再以四个 worker
和四个 semaphore 许可恢复。历史三并发请求与已完成结果保持不变，配置和代码变更另有迁移记录。
同日随后按用户指令改回 3 并发，仅补跑 173 个耗尽两次预算的网络失败任务；
每项最多再增加两次尝试，1,145 个成功结果复用。原始尝试不修改，补跑额度单独记录并冻结。
至少两篇独立配对稿件才能标记 source_supported；general 层仍需跨领域来源，不能因为本轮
只做一个领域就降低门槛。领域内抽取的 general 候选会保留原状态。

复用全量 runner 的稀疏检索、持久化局部更新、限流分类和 20 秒心跳。执行顺序为抽取、
候选汇集、串行共享库整理、模块导出和执行审计；存在抽取失败时先保留失败，不进入不完整的整理。
SIGINT/SIGTERM 处理为停止提交并等待当前请求保存，之后记录 paused。真实配置／认证拒绝仍停止。

```bash
python3 scripts/test_llm_area_review_skills.py
python3 scripts/llm_area_review_skills.py prepare
python3 scripts/llm_area_review_skills.py run
python3 scripts/llm_area_review_skills.py report
```

本机系统 Python 字节码缓存曾损坏，后台服务采用任务专用 `-X pycache_prefix=.../runtime/pycache`，
避免修改系统文件。运行状态见 `PROGRESS.md`，范围检查见 `SCOPE_AUDIT.json`。
来源提炼使用已记录覆盖的定向正文证据，实际审稿要求完整主文；科学质量通过后续独立评测验证。

2026-11-06 用户追加启用 DeepSeek 弱模型，最多 50 并发，同时保留 OpenAI 最多 3 并发。
新入口 `scripts/parallel_llm_area_review_skills.py` 复用已完成的 1,318 个抽取任务、
19,168 个候选和已提交的 SQLite 规则库，不重新抽取，也不引入其他领域。
先让旧串行服务保存当前请求并暂停，再记录数据库备份、代码与配置哈希后切换服务。

并行只用于生成局部规则变更提案：每个在途批次领取互不重复的 focus 候选，沿用原来的
机制分组、全局检索、最多八项操作和来源支持门槛。单一协调器在提交时检查目标规则
及候选访问次数；提案依赖的目标已经改变时，原始提案保留并重新排队，不消耗候选访问次数。
有效操作按当前全局计数分配唯一规则 ID，并用同一 SQLite 事务提交规则、候选、日志与任务标记。
已完成而未提交的请求可从任务及原始结果继续，避免重新调用模型。

OpenAI 沿用 `gpt-6-luna / medium`；DeepSeek 从 auth 读取 `deepseek-v4-flash`，
沿用该项目 DeepSeek 弱模型的 `thinking=disabled`，没有将其标为 medium。
官方通道返回的模型别名 `deepseek-flash` 在探测后显式记录；探测遇到的解码控制 token
只允许在 JSON 字符串外去除，引用与科学文字不改动，原响应完整保留。
两通道的请求、用量和推理设置分别记账。格式不合格的科学操作隔离，未形成可靠规则的候选
继续保留 deferred/unresolved，最多两次有效候选访问；网络请求每任务最多两次。
认证／余额／模型拒绝停用对应通道并保留原因，另一个通道继续处理队列。

进度统计已按完成候选数计算 ETA，避免把每次最多八条的 API 批次数当作候选数。
最终审计分别检查 OpenAI 的历史授权并发区间和 DeepSeek 的 50 并发上限。
离线检查：`python3 scripts/test_parallel_llm_area_review_skills.py`。

随后按用户提供的本地接口增加第三通道：用户在本机填写的 OpenAI 兼容地址（公开文档不记录具体地址），
模型 `qwen-flash-iq3`，用户选择 1 并发；OpenAI 3、DeepSeek 50 保留，总 API 上限 54。
`/v1/models` 确认模型已加载且 `n_ctx=262144`，真实 JSON 探测请求成功。
本地客户端使用占位 key `local`，关闭模板 thinking，沿用相同输入/输出预算与候选规则校验，
不因为接口有 262,144 上下文就扩大现有提炼任务或重新抽取。
本地原始记录独立写入 `requests_local/curate/`，和其他通道共用互斥候选领取及单一提交器。
模型、用量、并发与最终执行审计分别记账；服务恢复时直接复用各通道已完成但尚未提交的结果。

切换时发现 DeepSeek 返回 JSON `null` 导致旧版进度统计退出，已修复：非对象响应按传输失败
做有界重试，原始 `null` 仍保留；统计将空响应记为无返回用量，不能让心跳退出。
读取响应同时设置总时限，防止服务端持续发送空白保活而绕过单次 socket 读取超时。
本地读取总时限为 900 秒，服务停止时允许在途请求保存；不丢弃已有来源、规则或历史尝试。

随后用户要求暂停 DeepSeek：其 provider 配置保留历史授权并发 50，另写 `paused=true`，
使当前可用并发变为 0；OpenAI 3 和本地 Qwen 1 继续运行，当前总上限为 4。
调度器不领取暂停通道的候选，HTTP 边界也禁止该通道发起新请求。已在途结果保存后入账，
历史响应、模型来源及规则不删除。暂停通道遗留的未提交任务释放候选领取权，其他通道可继续处理；
若以后恢复时相同候选已被处理，旧任务标为 superseded，避免重复访问或覆盖新规则。
进度分别报告当前可用并发与历史授权上限；历史 DeepSeek 的 50 并发审计保持有效。

随后按用户指令将本地 Qwen 提高到 3 并发。Strata 后端配置 `parallel=3`，
重启后 `/props` 实测 `total_slots=3`，三个 `/slots` 的 `n_ctx` 均为 262144；
共享同一模型权重。整理客户端同步设为 3，OpenAI 保持 3，DeepSeek 保持暂停，
当前总上限为 6。切换前在途请求已保存，并备份第 2896 批规则检查点和历史记录哈希；
保留原用量统计基线、来源门槛与候选池，迁移记录见
`runtime/migrations/local_concurrency3_20261106T095656Z/MIGRATION.json`。

2026-11-07 按用户指令启动未解决候选恢复，入口
`scripts/recover_llm_area_review_skills.py`，独立产物目录
`/data_big/iclr-review/experiments/modular_skill_llm_area_recovery_v1`。
仅处理原版 6,161 条 unresolved 和 377 条 needs_evidence；原版冻结产物不改动。
沿用 OpenAI gpt-6-luna / medium / 3 并发和本地 Qwen / 3 并发，DeepSeek 保持暂停。
从五类原因各取 20 条组成 100 条流程诊断，通过预算、引用和来源审计并恢复有效规则覆盖后，
自动继续其他目标。两模型分担不同候选，第二次有效访问切换通道以恢复整理。

恢复程序复用冻结的生成、校验、事务提交和导出器，每批最多两条同机制 focus，
仅检索同机制规则及邻居，并提供此前操作的具体校验错误。补充证据来自原稿全篇检索的
精确片段，保留原文哈希、偏移与初审片段；不将当前稿件视为与历史审稿时间对齐，
不修改候选 paired_source 或放宽多来源支持门槛。原 history 保留，每条恢复目标的原状态、
原访问次数另记 recovery_epoch，本轮最多新增两次有效访问；非目标不重新访问。
本轮请求和用量独立记账；所有提案仍经过原有来源及机制校验，未解决条目允许保留。
检查命令：`python3 scripts/test_recover_llm_area_review_skills.py`。

同日随后按用户指令将恢复任务 OpenAI 上限提高为 4，本地保持 3，DeepSeek 保持暂停。
OpenAI 优先处理自己的待领取候选；没有可领取的自有任务时，空闲槽位可接手尚未开始的
本地首轮候选。共享领取表排除在途请求，不重复处理已完成候选；第二轮依据实际执行通道
切换模型，保留原分配通道及新的实际执行通道。此调度仅用于恢复入口，冻结的并行入口不改动。
切换前保存当前在途请求、数据库、请求记录哈希及恢复代码，追加 OpenAI 历史并发授权区间；
恢复入口直接复用原 HTTP 客户端、校验与事务提交器，统一提交规则变更。
离线测试覆盖实际协调器 4+3 同时执行、接手优先级、领取互斥、第二轮通道切换和最终审计。

## 2026-11-07：恢复完成与发布冻结

6,538 条目标已完成恢复，19,168 条候选中没有 pending/deferred。
现有 1,851 条 source_supported、7,324 条 candidate 与 154 条历史 deprecated 规则。
81 条 unresolved 和 3 条 needs_evidence 独立保留。规则修订号 7408。
发布器在独立目录重新导出有效模块，排除历史目录遗留的 380 个旧模块目录，
重新核验执行、来源、恢复与模块一致性，并固定 `llm-area-v1` 清单。
发布内容、复核命令与后续验收边界见 [领域库冻结记录](S6_llm_area_library_release.md)。
