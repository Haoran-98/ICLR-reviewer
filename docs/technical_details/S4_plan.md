# S4 v4.5：4060 Ti 实测双路关键词与 LLM 对照

## 当前执行（2026-10-23，覆盖下方环境未就绪记录）

最新通道调整：用户要求后续不再使用DeepSeek，统一改用auth的OpenAI弱模型（`gpt-6-luna`，并发4）。已完成的DeepSeek数据保留为历史对照。末段HTTP402余额不足的679项仲裁中，678项由OpenAI有效补齐，1项达到累计6次上限记为unknown；现有标签只从缓存重新整理。新任务默认OpenAI，原始论文树不变。

使用物理GPU 0的RTX 4060 Ti 16GB，在独立`runtime-dkta`环境完成同一200篇标题摘要上的Qwen3.5-9B NF4完整注意力抽取与KP20k One2Many BART推理，另生成RRF组合。两个新增方法均已各产出200份真实关键词。DeepSeek同输入的关键词+自由三级路径也已完成200篇。

已核对并导入ACM CCS 2012两个公开镜像，记录官方端点403和文件hash；三层投影为14/88/2,199节点、135个多父节点和2,352条路径。此批固定未扩充的体系，BGE-M3索引后统一对齐四种关键词来源；命中L3后恢复完整多父祖先路径，不改原始LLM论文树。Qwen路线是Attention-Seeker思路适配，不冒称原论文复现。

对比流程：200篇本地抽取 → 复用已完成的同输入DeepSeek基线 → 同一ACM DAG路径嵌入与模糊区仲裁 → 50篇按年份分层、OpenAI弱模型匿名评价 → 文档覆盖/关键词一致性/路径支持/语义层级/速度显存比较。增加DeepSeek关键词经过同一ACM对齐的控制，避免把体系局限误当成抽取差异；旧六板块三模型只作附加观察。评估不做人工抽查。全部数据为开发集，未作生产冻结。

目录：`/data_big/iclr-s4/experiments/dkta4060_200_v1`。完成状态与详细结果读取`alignment_status.json`、`judge_status.json`及`comparison.md/json`。执行方法、固定版本、来源、命令和评价口径见[S4_DKTA.md](S4_DKTA.md)。实现与对比入口为`scripts/s4_dkta.py`及`scripts/s4_dkta_compare.py`。

实测已完成：两路各200篇、RRF 200篇、统一对齐800份、匿名评价50/50篇，完整多父闭包通过。关键词F1@10为BART 0.1508、RRF 0.1312、Qwen 0.0156；已有同输入LLM为0.1317。当前ACM路径内容支持率为22.1%–28.4%，已有LLM自由路径84.4%。结论与置信区间见[200篇实测报告](../../benchmarks/s4_taxonomy/dkta4060_200_report.md)：保留BART关键词基线，不将本批未扩充ACM组合直接扩为生产三级体系。

API立即执行，读取auth并发；当前只调用OpenAI弱模型gpt-6-luna，并发4；历史前段为deepseek-v4-flash，并发50。初次+最多5次重试跨重启累计，日志北京时间；Kimi完全不进入当前数据、评判和请求。原始树及历史文件保留不动。

---

# 历史：S4 v4.4 原始论文树与新增 DKTA 双路对照

## 新增方法（2026-10-21）

保留已完成的200篇原始三模型标签树，继续排除Kimi。在独立实验目录新增两个关键词方法：Qwen3.5-9B完整注意力抽取（Attention-Seeker思路适配）与关键词微调BART One2Many；另设两路RRF融合的DKTA组合对照。输入为同一论文的标题+摘要，不修改既有树、不做旧标签合并或修复。

目标体系允许节点有多个父节点，采用三层DAG；每条L3全路径单独嵌入，模糊区由DeepSeek仲裁，命中后保留全部祖先路径；共享祖先的关键词权重去重。闭包优先于Top-N上限，超限显式报告。ACM CCS衍生体系须单独导入并记录三层投影，不伪造现成ACM数据。

完整方案、环境条件、命令、评分语义和未执行部分见 [S4_DKTA.md](S4_DKTA.md)。实现为`scripts/s4_dkta.py`。当前4.51.3运行环境不支持本地Qwen3.5架构的HF注意力读取，GGUF服务不能替代注意力接口；BART关键词checkpoint与正式体系文件尚未提供。当前执行就绪检查与算法测试，真实模型抽取须在这些条件满足后启动。

---

# 已完成：S4 v4.3 原始三级标签树

## 当前指令（2026-10-21，覆盖下方 v4.2 历史方案）

当前交付为已有200篇论文的原始标签树：只采用 DeepSeek、GPT（openai）、Qwen 三路生成结果，Kimi 标签、证据、投票及替补角色均不进入本次导出。历史原文件保留用于溯源，不属于当前交付。

每篇论文独立一棵树，论文题目为第0层根节点，下接原始 L1 → L2 → L3。来源用节点属性标记，不增加来源层；同名节点仍分别保留，不做 lexical/semantic 合并、重新命名、父节点调整或重新生成。仅沿同篇、同模型、相邻层的原始 parent_id 建树；结构不合法的 candidate 直接报错，不猜测父节点。

主树包含生成阶段 status=candidate 的全部节点；原来已标记 pruned 的输出和 pruned_branches 另存于逐篇 JSON 的 generation_pruned，保留原始内容与原因。此步骤保留候选生成状态，语义与质量验收另行开展。

当前不启动旧 Crowd Layer 融合、同义合并、层级语义验证或修复流水线；旧失败批次不阻塞原始树展示。本轮指令仅要求导出，不启动新的训练或推理请求。

实现：`scripts/s4_export_paper_trees.py`。输出目录：`/data_big/iclr-s4/experiments/taxonomy_llm3_paper_trees_200_v1`；包含 `trees.md`（全部200篇树）、`index.md`、`papers/<paper_id>.json`（完整定义/证据/来源/原始排除记录）、`manifest.json`（数量与输入SHA256）。

已完成导出并逐篇核对原始字段、父子路径及来源文件SHA256：200棵论文树，L1共1,751条、L2共4,110条、L3共8,903条，合计14,764条候选标签出现次数（按出现计数）；696条生成时已标记pruned的节点另存，原始内容未改写。

```bash
/data_big/iclr-s4/runtime/bin/python scripts/s4_export_paper_trees.py
```

下方 v4.2 内容仅为历史执行记录，启动命令不再是当前工作入口。

---

# 历史方案：S4 v4.2

版本：v4.2，2026-10-17。当前分析版本：taxonomy_llm4_gpt_200_v1；历史来源：taxonomy_llm4_200_v1。
本版替代 v3.3 的官方锚点内聚类。200 篇均为开发数据，生产冻结仍依赖 S3。

## 0. 当前执行配置（覆盖下文历史四模型记录）

2026-10-17 用户明确：Kimi 前面已经完成的工作继续使用，只有后续未完成任务由 gpt-6-luna 接替。
保留 DeepSeek、Kimi、gpt-6-luna、Qwen 四路历史标签、原文证据、官方类别票及已完成的同义判断，不以 ICLR 标签锚定自由树。
继续调用的实际模型为 DeepSeek Flash、gpt-6-luna、本地 Qwen3.5-9B Q8_0；不再发送 Kimi 请求。
gpt-6-luna 已完成当前200篇的674个交叉评价请求，可复用填补 Kimi 未完成的相同任务，不重复调用。
填补记录保存 assigned_role=kimi、actual_provider=openai、actual_model=gpt-6-luna；不把新结果伪装成 Kimi 生成。
同一评价对象只计算一份 GPT 观测：原始 Kimi 票仍独立，GPT 填补票与原 GPT 票去重；学习时重复观测置 missing，结构审核按独立来源多数票且无 no 通过。
因此历史四个独立来源通常至少3票 yes；全由后续三个实际模型评价的对象至少2票 yes。弃权保持缺失，未生成不作负例。

新结果独立写入 `/data_big/iclr-s4/experiments/taxonomy_llm4_gpt_200_v1`。
原目录的 Qwen 交叉评价保持运行，结束后新分支自动接续；Kimi 独有候选也保留。
仅当名称、定义、层级和 facet 与旧评价对象一致时复用票；定义变化的少量候选重新评价，避免把旧定义的判断套给新定义。
保留四模型历史候选集合，复用判断只对应完全一致的标签定义。
请求缓存、jobs 和 attempts 共享原账本，累计初次+最多5次重试不重置；新节点、边、指标、模型及版本独立保存。

保留原六板块表示，增加两个直接编码原文的对照：

| 配置 | 论文 embedding 输入 | 编码方式 |
|---|---|---|
| E1 | keywords/title/abstract/introduction/conclusion/related_work | 各字段向量拼接后，在训练折拟合 PCA |
| TA | title + abstract | 按标题、摘要顺序拼接原文，编码后在训练折拟合 PCA |
| TAK | title + abstract + keywords | 按标题、摘要、关键词顺序拼接原文，编码后在训练折拟合 PCA |

TA/TAK 使用固定 BGE-M3 revision；字段名加原文、字段间双换行；510内容tokens分块，64 overlap，分块归一向量均值后再归一。
保存原文输入哈希、字段缺失、字段哈希、chunk范围和编码规格。缺失原文不补写。
新增对照只改变论文 embedding 和相应字段 mask；LLM 六板块证据、标签名称/定义向量、分折、种子、模型及损失设置保持一致，关键词辅助监督仍按相同设置。
各表示分别运行修复前/后：E0R0/E0R1、E1R0/E1R1、TAR0/TAR1、TAKR0/TAKR1；E0 为无论文 embedding 基线。
不重新生成已有200篇标签。等原 Qwen 评价结束后再释放其GPU进行新向量编码，随后恢复 Qwen 执行必要的对齐与层级验证。
继续运行保留历史来源的 DS/static/conditional Crowd Layer、5折×5种子、去单来源/迁移/关键词消融。
真实 related-work 输入消融另建立三个未变模型（DeepSeek/GPT/Qwen）的匹配全输入控制分支，再与这三个模型移除 related-work 后的结果比较；不将 Kimi→GPT 的模型变化误当作输入消融收益。
此前排除 Kimi 的 taxonomy_llm3_200_v1 分支已停止，文件保留但不作为当前主结果。

启动或恢复当前分支：

```bash
CUDA_DEVICE_ORDER=PCI_BUS_ID CUDA_VISIBLE_DEVICES=1 OMP_NUM_THREADS=4 \
 /data_big/iclr-s4/runtime/bin/python scripts/s4_crowd_fusion.py watch \
 --root /data_big/iclr-s4/experiments/taxonomy_llm4_gpt_200_v1 \
 --source-root /data_big/iclr-s4/experiments/taxonomy_llm4_200_v1 \
 --providers deepseek kimi openai qwen --replace-kimi-with-openai
```

## 1. 已确定的设计

L1/L2/L3 均从内容自由归纳，ICLR 官方目录不约束命名或结构。官方标签和作者关键词是观测事实，不能被推断覆盖。官方标签仅用于独立监督头。
历史四路生成器为 DeepSeek Flash、Kimi、gpt-6-luna、本地 Qwen3.5-9B Q8_0；当前保留 Kimi 成果，仅后续任务换为 GPT，按第0章执行。生成器之间互不可见输出，不使用强模型单独仲裁，不做人工抽查。
下列 Kimi 切换、Batch 和四模型数量为历史执行记录，其后续调用已被第0章覆盖。
Kimi 起初使用 K2.6；2026-10-16 按用户修改的 auth 切换到 Coding 接口的 kimi-for-coding，reasoning_effort=low。
保留已完成的134篇旧模型结果，剩余66篇用新配置；唯一未完成论文的旧两级输出另存历史后重做。
2026-10-16 21:46，Coding 接口达到5小时用量上限（HTTP 403 / access_terminated_error），累计完成136篇，剩余64篇。
按用户要求切回 Moonshot 接口 kimi-k2.6；21:54 实际请求验证通过，按 auth 并发续跑未完成部分。
保留全部已完成结果和部分层级，逐层记录来源；不清空旧请求的重试次数或失败记录。
21:59 用户暂停时完成139篇，剩余61篇；随后按用户要求改为 Moonshot Batch API 续跑。
Batch 官方文档支持 kimi-k2.6，推理费用较实时 API 低40%；每批 completion_window=24h，实际完成时间受平台调度影响。
按层依赖分轮：每篇仅提交下一缺失层级，独立官方类别投票可并行入批；上一层回收并校验后才构造下一层。
复用实时 job_id、缓存、证据校验和累计6次尝试预算。批内 custom_id 对齐结果，不依赖返回顺序；成功项幂等落盘，仅失败项在剩余预算内重提。
提交前持久化 input_file_id；创建响应丢失时先查询批次列表核对，禁止盲目重复创建。批次和逐条错误记录保留。
批次由远端调度，auth 的 Kimi_concurrency 不决定远端并行数；本地一次只维护一个活动批次，每30秒查询状态。
本地停止轮询不会取消已提交的远端批次；暂停时还须调用远端取消接口并保留可回收的已完成结果。
实现：scripts/s4_kimi_batch.py；文档依据：https://platform.kimi.com/docs/guide/use-batch-api（2026-10-16 核对）。
上下文缓存：K2.6 使用平台自动前缀缓存，Batch 缓存命中输入价为 ¥0.66/百万tokens，未命中为 ¥3.90/百万tokens；输出仍为 ¥16.20/百万tokens。
后续未提交请求将同篇论文不变的 evidence 放在 user JSON 前部，instruction/level/parents 等变化内容置后，保持原字段、证据和任务语义。
记录 request_layout=evidence_prefix_v1 和实际 request_hash；逻辑 job_id 不变，既有缓存与重试预算不重置。历史及已提交批次不重发，报告披露输入顺序调整。
回收时保留原始 usage，并在各批次 cache_usage 中汇总输入、输出、缓存读取、缓存写入和报告覆盖数；缺失用量字段不冒充零命中。
K2.6 不支持新 Cache Write/TTL 配置，不添加 prompt_cache_options 或 cache_control；缓存命中取决于平台调度与前缀复用，不承诺所有重复文本均命中。
依据：https://platform.kimi.com/docs/guide/context-caching 与 https://platform.kimi.com/docs/pricing/batch（2026-10-16 核对）。
2026-10-17 解析修复：首批122条实际于10月16日22:30:51完成，平台逐条 status_code 均为0（与文档200示例不同）。
解析器 batch_response_v2 仅在无请求错误、body 无 API error 且具有 completion choices 时兼容0，并继续严格检查 finish_reason、JSON、字段和原文证据；真实401/403等错误不放行。
先归档原始批次判断及逐条 attempt，再从本地已下载响应重校验，不重新请求、不增加尝试次数。保留原始 status_code=0，记录经过校验的解释，避免伪造HTTP200。
其中120条内容可用；2条生成的 pruned_branches 内出现无键名字符串（非法JSON），在剩余预算内重试。
后续 K2.6 请求启用 response_format={"type":"json_object"} 约束合法JSON，业务字段和证据仍单独校验；请求hash和参数留档，既有 job_id 与预算不变。
参考：https://platform.kimi.com/docs/guide/use-json-mode-feature-of-kimi-api 与 https://platform.kimi.com/docs/guide/response_format（2026-10-17核对）。
2026-10-17 补齐：Qwen 的3条独立类别票均重复了末尾 privacy，仅在压缩相邻重复token后精确匹配允许类别时归一，并保留原字符串和归一规则；从已保存HTTP200响应回收，不新增请求。
OpenAI 论文3374的旧任务6次均为网关429，用户明确批准新增一轮修复；新 job 记录 repair_round 和 previous_job_id，旧6次尝试保留，新轮仍最多初次+5次重试。
四路200篇于2026-10-17 12:17:46全部补齐。接下来运行标签向量、同义对齐、显式交叉票、父子包含验证、DS/Crowd Layer及消融、四种修复分支和实验报告。
Kimi 在同义对齐、交叉票、层级验证及 related-work 消融中继续走 Batch；结果按 job_id 回填并共享原预算，无实时推理回退。分析批次状态见 analysis_batch_progress.json 和 batch/analysis_active.json。
分析启动后获得18,741个原始候选、18,235个词形归一候选，标签向量已生成，筛出1,287组同义候选对；这些数量分别统计候选词与同义候选对。
对齐中发现模型会抄错长ID：仅接收与输入ID精确匹配的票，未知ID票保留在 rejected_votes；缺失ID补为明确标记的程序弃权，绝不猜测对应标签或当作负票。有效ID重复、非法票值、全部ID无效、截断或非法JSON仍拒绝。
生成和分析投票的输出上限统一为12,288 tokens，解决32项投票在4,096上限下截断；逻辑job_id与累计尝试预算不变，已耗尽任务仅允许本地重校验旧完整响应。
因此当前 Kimi 通道包含两种模型配置，报告须披露，不能称为全200篇均由同一个固定 Kimi 模型生成。

每篇每模型先生成 3 个 L1，为每个 L1 生成 3 个 L2，再为每个 L2 生成 3 个 L3。
每模型最多 39 节点，每篇最多 156 节点，200 篇最多 31,200 个原始候选。
每层合批请求，生成最多 2,400 次调用；粗分类、交叉投票和关系验证调用另计。
允许证据不足时剪枝，保留原始候选、证据和拒绝原因，不强制凑满分支。

立即执行，无凌晨限制。各 provider 并发从 /home/yhr/auth 读取，大小写不敏感；缺省 1，本地 Qwen 固定 1。
S4 v4 新增日志及本地状态时间统一使用 Asia/Shanghai（北京时间），ISO 8601 明确带 +08:00；历史 UTC 记录保留原始偏移。
每 job 初次请求加最多 5 次重试，跨重启累计。401/403 等永久错误停止，网络、408/409/429/5xx 和解析错误按预算退避。
API key 不进入日志。acceptance、decision、Review、Reviewer 身份不进入输入，不干扰 S3。
Kimi 优先读取 Kimi_model（兼容旧 Kimi_weak_model），Kimi_think_strength 映射为 reasoning_effort。
模型、地址及思考强度进入请求来源记录，新的配置不命中旧请求缓存；key 不进入缓存标识。
Kimi 当前用 Batch 传输，保留 K2.6 instant/thinking disabled 参数；不设置文档禁止修改的 temperature/top_p 等参数，不自动回退到实时付费推理。

## 2. 六板块、证据与资源

沿用旧 smoke 的 200 个 paper ID，冻结 metadata、Markdown、章节索引和 hash。
旧 test 已消费，全部标 dev；未来正式评价另封存论文。所有版本与派生对象继承 paper group。

六板块分别为 keywords、title、abstract、introduction、conclusion、related_work。
前三项取原始 metadata，后三项从原始 Markdown 和章节索引抽取。
兼容 I NTRODUCTION 等排版分隔，只归一标题匹配，保留原文字符位置；缺失保留 mask，不生成替代。
S3 Profile 不作为原文引文。

固定本地 BGE-M3 revision 5617a9f61b028005a4858fdac845db406aefb181。
六板块各自编码；512 tokens 分块、64 overlap，保存 chunk 向量和归一均值后的六板块向量。
模型拟合时才对训练折表示降维，不预先混成不透明的单一全文向量。
物理 GPU 1 为 V100；固定 CUDA_DEVICE_ORDER=PCI_BUS_ID、CUDA_VISIBLE_DEVICES=1。
Embedding 在子进程中完成并释放显存后启动 Qwen。复用现有 Q8_0 GGUF、parallel=1、32k context，监听 127.0.0.1。

| 层级 | 语义 | 主要依据 |
|---|---|---|
| L1 | 广义领域 | title/abstract/keywords，intro/conclusion 的目标 |
| L2 | 父领域内任务族或方法族 | 父路径、问题、本文贡献 |
| L3 | 具体问题或技术路线 | 完整父路径和本文具体机制证据 |

related work 只提供语境和边界，不能单独证明本文贡献。
长章节选择开头和末尾的可定位片段，保存选择规则与完整原文。
卡片含名称、定义、facet、纳入/排除、父路径、模型/prompt/hash、状态。
模型返回 span_id，程序回填原文 quote 与字符区间，避免模型改写引文。
quote 存在不自动证明语义支持。未知引用、相关研究独证等保留为 pruned。

参考 TaxoAdapt 的 title/abstract 与父路径上下文、TopicGPT 的生成—去重—证据指派。
这是项目适配，相似度阈值按本项目开发集选择并记录。

## 3. 对齐与双头融合

先词形归一/精确去重，再用定义及支持论文 embedding 近邻提出同义对。
四模型独立 yes/no/abstain 验证，保存原始 candidate→canonical mapping。
跨模型未生成某标签是 missing，不能当 no；收集显式交叉标注，每批最多 32 候选。
公共标签对齐用于全部消融，因此 E0 不声称整个流程从未使用 embedding。

自由生成之后，单独展示 23 个类别选项而隐藏真实答案，收集四路粗分类票。
官方 23 类头使用原始官方标签监督；自由层级头学习多标签潜真值，两头不把官方目录复制进自由树。
作者关键词作为自报正向监督，未列关键词保持未标注；关键词重合度作为代理一致性指标。

基线：多数票、经典 Dawid–Skene EM、静态 Crowd Layer、条件 Crowd Layer。
静态模型学习模型特异混淆矩阵，条件模型按内容/任务调节可靠性（本项目扩展）。
粗类可靠性向细类迁移需要消融验证。预测某模型 noisy label 时不能直接把它自己的输出作特征。
默认 hidden=32、dropout=.2、AdamW lr=1e-3、weight decay=1e-2、最多 200 epochs、内部验证 patience=15。
损失包括官方 CE、关键词辅助、masked crowd likelihood、层级一致性、全局可靠性收缩。
保存混淆、条件 gate、后验；细类后验不冒充校准正确率。

## 4. 修复与评价

Embedding 只提出 merge/rename/reparent/prune/keep_separate；结合原文、交叉票、后验决定操作。
包含关系须验证，余弦相似不直接产生 parent_of。保留修复前后、反对票与证据。
修复后重新聚合表示与成员，重新指派，校验 DAG、版本一致、child⇒parent。
初始活跃节点筛选为至少 2 篇、2 模型支持、后验≥.9；作为开发筛选门槛，precision 通过人工 gold 另行评测。
稀疏或争议节点保留 candidate。

边类型：parent_of、overlaps_with、method_used_in、application_of、shares_evidence_pattern_with。
不得把全部相似性或 co-assignment 伪装成层级边。

| 消融 | 融合网络使用 embedding | embedding 后修复 |
|---|---|---|
| E0R0 | 否 | 否 |
| E1R0 | 是 | 否 |
| E0R1 | 否 | 是 |
| E1R1 | 是 | 是 |

另测 leave-one-model-out、移除粗到细可靠性迁移、移除关键词、移除 related-work。
related-work 消融必须重新生成对应输入，不能从已看过原文的输出中事后删除文本冒充。

200 篇按 paper group 做 5 folds×5 seeds；网络/降维/阈值只拟合训练折，报告稀有类支持数。
开放标签归纳可使用全部开发文本，明确 transductive 属性，不冒充 inductive 泛化。
官方头报告 OOF macro/micro-F1、ECE；细层无 gold，报告证据有效率、争议、熵、重复率、结构合法率、稳定性、修复变更。
不伪造细类 accuracy/precision/真实 ECE。合成不同准确率、相关错误、缺失标注检验可靠性恢复。
记录真实时延、tokens、峰值显存和 HTTP/解析/证据失败，不把模型自报信心当正确率。

测试涵盖章节缺失/字符位置、父路径、证据、abstention mask、跨重启预算、自拷贝防护、gold 隔离、合成可靠性、DAG、DB 幂等和四种消融。
conformal p-value 用于相容性判断，正确率与概率校准另行评价。

## 5. 执行、持久化与清理

入口 scripts/s4_llm_taxonomy.py。根目录 /data_big/iclr-s4/experiments/taxonomy_llm4_200_v1。
使用 --providers kimi 可单独恢复 Kimi，不重跑其他渠道或已完成的论文；部分渠道结束不产生全量 generation_complete 标记。
顺序：冻结原始输入→四路连通/六板块编码→同批 10 篇 pilot→余下 190 篇→对齐/交叉票→融合/消融→修复→实验落库与报告。
成功 job 按模型/prompt/input hash 缓存，重启不重复计费。execution.json、pilot_summary.json、attempts/ 和服务日志可审计。
最终节点/边/assignment/embedding 使用现有 semantic 表；中间候选、投票、模型、后验保存在版本目录。
当前只登记 experimental；S3 未冻结不得发布生产 taxonomy。

按用户授权清除旧实验结果：先验证新目录已保留原 200 ID 和完整 raw snapshot，
再删除精确的 3 个旧 smoke 根目录、2 份旧报告及 taxonomy_smoke_200_v1 数据库派生数据。
不清空整张 semantic 表，不删除 S3、原始论文、模型、环境；文件删除不提供自动恢复。
工程启动、生成完成、融合完成与质量验收分别报告。

## 6. 参考依据

- TaxoAdapt (ACL 2025): https://aclanthology.org/2025.acl-long.1442/
- TopicGPT (NAACL 2024): https://aclanthology.org/2024.naacl-long.164/
- Crowd Layer (AAAI 2018): https://arxiv.org/abs/1709.01779
- Dawid–Skene (1979): https://doi.org/10.2307/2346806
- CoNAL (AAAI 2021): https://doi.org/10.1609/aaai.v35i7.16730 （相关工作，非完整复现）

OpenAlex/CSO 后续作为外部对照；自由树构建与细粒度 gold 使用各自独立协议。

本地 Qwen 启动检查从 `auth` 的 `qwen_base_url` 或环境变量 `QWEN_BASE_URL` 读取兼容接口地址；本机启动命令绑定回环主机的 8080 端口，配置须指向该服务。
