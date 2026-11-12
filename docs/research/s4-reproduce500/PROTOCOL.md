# 500 篇论文的本地 Qwen 主题提取复现实验

实验根目录：`/data_big/iclr-s4/experiments/repro500_qwen38_27b_q3_medium_64k_v2`。采样 seed=20261026。2026-10-27 按用户要求更新模型；采样及评价协议延续 v1。原实验和代码快照保留在 repro500_qwen_v1，旧 LLM 输出不复用于新实验。

本实验是四种算法在同一数据、同一本地模型下的受控适配，不能视为作者原模型配置或原 benchmark 的完整复刻。原论文分别见 [TaxoAdapt](https://aclanthology.org/2025.acl-long.1442/)、[Context](https://aclanthology.org/2025.emnlp-main.788/)、[LiSA](https://aclanthology.org/2025.acl-long.902/)、[LLM-ITL](https://aclanthology.org/2025.acl-long.70/)。

## 数据与泄漏控制

- 固定 500 篇，2024/2025/2026 年分别 167/167/166 篇；覆盖 23 个跨年 canonical 一级领域，年份内按领域轮转均衡抽样。
- 排除旧 200 篇实验的所有 paper_id，按归一化标题去重。不同年份可用领域选项并不完全相同。
- `inputs.json` 只有 paper_id、title、abstract。作者 primary area 及年份保存在独立 `evaluation/gold.json`。
- 生成和聚类不读取每篇真实领域；扁平方法已知类别数量 K=23，遵循 LiSA 论文主实验使用真实类别数量的设置。实验提供 K=23 的类别数量先验。
- 无标签主题发现可以使用全部 500 篇；因此是 transductive 实验。准确率的统计范围为该均衡样本。
- 作者提交的一级领域是比较目标，不能充当二三级主题、层级边或审稿人适配程度的标准答案。

## 统一模型和推理

- RTX 4060 Ti 16GB；只使用物理 GPU 0，不使用 GTX 980。
- 本地 Qwen3.8-27B UD-Q3_K_XL GGUF；K、V 均为 q8_0；每槽上下文 65536；开启 thinking，reasoning_effort=medium；temperature=0；结构化输出、逐请求缓存、失败日志、累计最多六次尝试；若输出因长度中止，在当前槽容量内增加输出预算重试，保留实际请求。
- BAAI/bge-m3 固定本地 snapshot；增量 embedding 使用 CPU，适应 27B 服务约 15.1 GB 的显存占用。标题摘要保留全文，embedding 使用 510 内容 token 分块、64 token 重叠、归一化均值聚合。
- 当前采用单模型、4 槽、4 请求并发，启用 unified KV。共享池总容量 65536，每请求上限 65536；多个请求不能各自同时占满 64K。客户端通过渲染模板并精确计数输入，预留输入 + 最大生成预算 + 32 token 余量；总预留不得超过共享池，长请求自动排队。
- 上下文长度、并发及显存结论以实测为准。长提示不静默截断；聚合命名提示使用预先声明的代表论文预算。

## 四种适配

| 方法 | 保留的核心 | 本实验设置及偏离 |
|---|---|---|
| TaxoAdapt | 直接调用官方 DAG、贡献维度分类、节点多标签分类、宽度/深度扩展代码和提示 | 五维；初始深度 1；密度阈值 40；最大深度 3（仓库默认 2）；原双模型统一替换 Qwen；处理官方空返回值不一致 |
| Context | 动态方面生成、逐篇多方面摘要、每方面聚类、精确最大权重方面簇选择、递归命名 | 依论文使用 GMM，而非公开代码硬编码的 KMeans；每方面 4 簇，每父节点最多 4 个孩子，深度上限 3；tied covariance，reg=0.01；小于 16 篇不再分裂；方面生成使用 24 篇多样代表、命名 12 篇；每方面摘要最多 35 词 |
| LiSA | 候选主题与描述、双空间 KMeans、无标签 Hungarian 对齐、近邻 LLM 修正、双 TPN 及论文公式 5–11 的协同损失 | 官方仓库仅 README，按论文公式实现；K=23；256–256–K；Adagrad 1e-3；30 epochs；batch 125；tau=1.5、alpha=0.8；修正近邻 5、训练近邻 15；修正后的主题向量使用主题簇均值；输出网络列用不含 gold 的匹配对齐主题名 |
| LLM-ITL | 官方 NVDM 网络结构、主题词 LLM 修订、word-intrusion 置信度、可微 EMD 损失回传训练 | K=23；CountVectorizer 至多 5000 词，min_df=3、max_df=.7；250 epochs，前 200 warmup、后 50 refinement；每五轮刷新 LLM 反馈，每 minibatch 都回传 OT；权重 200；BGE 替代 GloVe；将官方 uniform 噪声改为 Gaussian，将可能为负的 transport mass 改为 softmax |

LLM-ITL 的低频反馈刷新是本地资源适配，刷新频率按本地配置记录。保留每次训练损失及非零 OT 梯度证据。LiSA 和 LLM-ITL 的主题结构原生扁平，深度按 1 记录。

## 评价

1. **语义 L1 accuracy / macro-F1**：共享 Qwen 评估器只读取生成主题名称、描述及祖先路径，从该年份真实可用的一级领域选项中选一项。看不到原论文标题摘要或每篇真实标签。扁平方法使用原生 top1 主题；层级方法使用所有最末已分配主题。该项受评估映射器能力影响。
2. **五折校准 L1 accuracy / macro-F1**：先冻结全部无标签主题与表示；每折只用训练 400 篇的作者一级标签建立主题→领域条件概率表，评价另 100 篇。多维主题先按维度等权，再按维度内最末主题等权；扁平方法使用完整主题分布。未覆盖样本采用训练集多数类，同时单报 coverage。不得全 500 篇拟合再评价同 500 篇。
3. NMI、ARI 使用 hard top1 主题；未覆盖为共同 missing 类。报告各年份、各一级领域切片及按领域分层的 bootstrap 95% 准确率区间。
4. **深度**：人工根节点和五维容器不计语义层；DAG 节点按最长根路径计深度，重复节点仅计一次，检测环。
5. **广度**：逐层唯一主题节点数、最大层宽、平均非叶语义节点分支数；另报含根的平均分支数、总/有论文支持节点数、叶节点数。人为上限与实际结果同时保留，不能凭更深更宽认定更优。
6. JSON 缓存、源代码下载 hash、样本 hash、逐篇预测、训练损失及请求用量全部保留。代码结构/泄漏检查不能替代真实实验结果。

## 运行

```bash
bash scripts/s4_qwen38_27b_64k.sh # 单独终端启动服务
/data_big/iclr-s4/runtime-dkta/bin/python scripts/s4_reproduce500.py run --device cpu --concurrency 4
/data_big/iclr-s4/runtime-dkta/bin/python scripts/s4_reproduce500.py evaluate --concurrency 4
/data_big/iclr-s4/runtime-dkta/bin/python scripts/test_s4_reproduce500.py
```

实际采用的推理槽和上下文配置、重试及异常见实验根目录 runtime 和 requests。结果表在真实实验完成后写入 `REPORT.md`。

客户端与服务端均显式设置 enable_thinking=true 和 reasoning_effort=medium。客户端取消禁用思考的提示，初次 max_tokens 为方法原输出预算加 8192（包含思考和最终 JSON），长度中止时在 64K 容量内扩大预算重试。请求超时为 3600 秒。运行前核验权重路径与每槽上下文，防止误用旧服务。

实际验证：runtime/model_switch_verification.json 记录真实论文请求，medium 思考内容非空、finish_reason=stop、JSON/schema 校验通过；服务器报告单槽 65536。该记录验证单请求传输，500 篇比较结果另行记录。

当前持久运行服务：`iclr-s4-qwen38-medium-64k.service`；四方法及最终评价任务：`iclr-s4-repro500-qwen38.service`。使用 `systemctl --user status` 查看状态；逐请求缓存与日志保存在新实验根目录。实际任务从 runtime 代码快照执行，使用 CPU 计算增量向量。

## 2026-10-27 并发实测与调整

固定 4 篇已记录单并发请求，以相同消息、JSON schema、temperature、seed、medium 思考设置重放。单并发参照为之前同 4 请求实测记录之和；2、4 并发分别重放一次，属于小样本工程测试。

| 并发 | 4 请求耗时 | 生成 token/s（包含思考） | 相对单并发的 token 吞吐 | 分类结果一致 | GPU 总显存 MiB |
|---|---:|---:|---:|---:|---:|
| 1 | 161.5 秒 | 17.98 | 1.00 | 参照 | 约 15100 |
| 2 | 86.1 秒 | 29.44 | 1.64 | 4/4 | 15295 |
| 4 | 50.8 秒 | 49.19 | 2.74 | 4/4 | 15599 |

选择 4 并发。由于批处理数值差异会改变思考长度，4 请求墙钟加速 3.18 倍与 token 吞吐加速 2.74 倍分别报告，不把小样本加速等同于全流程固定加速。此前已完成请求继续复用，模型及语义提示未改变；精确准入统计新增两个本地模板/分词请求。代码、原始响应和显存快照见 runtime/concurrency_benchmark。

## 2026-10-29 故障恢复补充

10 月 28 日 optimization 节点的深层聚类请求在思考区出现重复 +1 序列；两次长度中止后四次 3600 秒超时，随后触发官方错误诊断变量未初始化异常。成功缓存保留；恢复时按原输入、顺序和固定种子重放，已有成功请求直接复用。

仅在请求长度中止或 ReadTimeout 后，重试设置 reasoning_budget_tokens=8192，保持 enable_thinking=true、medium 思考强度与原 JSON schema；实际重试参数逐次保存。每次调用最多六次新尝试，历史失败尝试继续保留并递增编号。此规则统一适用于四种方法；此前成功响应不重算。

TaxoAdapt 官方 expansion.py 保持原文件，在 runtime 生成本地副本，初始化 cluster_topics/cluster_outputs，修复失败诊断使用未赋值变量的问题。另加入批次开始事件，并以 workflow_status.json 持久保存实际退出状态，避免将已中断的任务显示为进行中。故障前代码及本次代码 hash 保存在 runtime。

本地模型服务器地址通过 `S4_REPRO_QWEN_URL` 环境变量提供，值为服务 origin，调用方另行拼接 `/props` 等路径。
