# S4 DKTA：Qwen 注意力抽取、BART 生成与多父体系对齐

版本：v2，2026-10-23。实现：`scripts/s4_dkta.py`；对比与报告：`scripts/s4_dkta_compare.py`；算法验证：`benchmarks/s4_taxonomy/test_dkta.py`。

当前真实实验目录：`/data_big/iclr-s4/experiments/dkta4060_200_v1`。RTX 4060 Ti 16GB已完成Qwen注意力、BART One2Many各200篇真实抽取，另完成标题摘要同输入的DeepSeek基线200篇。ACM公开镜像已导入并生成BGE-M3索引；全量对齐已产出800份assignment，8,556个不同论文/词项中1项累计请求耗尽记为unknown，其余均有确定处理结果。50/50篇匿名评价及比较报告已完成，`judge_status.json`无失败。完整算法/传输回归67项，65通过、2个数据库测试跳过；这些测试不是语义质量结果。

最终结果：BART作者关键词F1@10为0.1508，优于RRF的0.1312和Qwen注意力的0.0156；同输入已有LLM为0.1317。三级路径内容支持率分别为BART→ACM 28.4%、RRF→ACM 26.2%、Qwen→ACM 22.1%，已有LLM自由路径84.4%。这些是开发集的代理评价，当前未扩充ACM对齐不宜直接替代自由LLM细标签。完整区间、样例和解释见[实测报告](../../benchmarks/s4_taxonomy/dkta4060_200_report.md)。

**2026-10-23用户最新配置：后续不调用DeepSeek，改为auth的`OpenAI_weak_model_id`（当前`gpt-6-luna`），并发读取`OpenAI_concurrency`（当前4）。** 历史DeepSeek已完成输出保留为对照。仲裁末段679项遇HTTP402 `Insufficient Balance`，补齐只调用OpenAI，保留原失败记录；跨两通道累计最多6次请求。新`matched-llm`与`align`默认OpenAI，已有实验用`--cache-only`整理混合来源结果，不再向原通道发请求。

新建隔离环境`/data_big/iclr-s4/runtime-dkta`，旧环境保留。使用Transformers 5.20.2、PyTorch 2.6.0+cu124、bitsandbytes 0.50.2、Accelerate 1.15.0、Sentence Transformers 5.7.0；依赖版本见`requirements-s4-dkta.txt`。物理GPU 0为4060 Ti，GPU 1为GTX 980，本轮不使用后者。设置`CUDA_DEVICE_ORDER=PCI_BUS_ID CUDA_VISIBLE_DEVICES=0`。

本方法作为已有三模型原始论文树之外的新对照，不修改或合并原树。当前开发集仍为200篇，不使用Kimi。新方法输入只含标题和摘要，原六板块生成结果作为不同输入条件的历史基线，不能把它们的差异单独归因于抽取算法。

## 1. 两个新增方法与组合对照

| 方法ID | 关键词来源 | 后续对齐 |
|---|---|---|
| qwen_attention | 当前Qwen3.5-9B的完整自注意力，present-only | 同一版本DAG和路径索引 |
| bart_one2many | 科学关键词微调BART，一次生成多关键词，含absent | 同上 |
| dkta_rrf | 上述两路RRF融合 | 同上 |
| llm_deepseek_aligned | DeepSeek基于相同标题摘要抽词 | 同上，控制体系因素 |
| llm_deepseek | 同一次DeepSeek请求直接生成最多5条三级路径 | 自由标签，不经过ACM |

RRF常数60，Top-M默认20；每路同一规范化词最多计一次。仅规范化大小写和空白来匹配关键词，不借此合并体系节点。两路原始排序、BART beam/序列分数、present/absent属性及融合排名分别保存。

**Qwen是Attention-Seeker思路的适配版，当前不宣称已复现原论文。** 候选为标题/摘要中的1–5 gram，禁止跨句或跨标题/摘要边界；过滤停用词边界。完整注意力按head平均、query求和，再按因果可见query数量校正，跨所选层平均；短语按覆盖token分数均值排序。该打分及候选策略必须与原论文逐项核对后才能宣称复现。

当前Qwen3.5-9B为32层混合线性/完整注意力：只有零基3、7、11、15、19、23、27、31为full_attention。默认选择中间半区可用完整层，即零基11、15、19、23（第12/16/20/24层）；不能照搬LLaMA3的9–15层。支持显式`--layers`，线性注意力层不冒充常规注意力矩阵。

当前实际使用`/data_big/models/Qwen3.5-9B`的HF权重、eager完整注意力和NF4 4-bit量化、FP16计算。200篇峰值PyTorch allocated为7.95GiB，实际16GB显卡可执行；不是GGUF服务、prompt抽词或embedding替代。量化精度与历史Q8生成结果不同。默认输入上限1024tokens，本次200篇两路均未截断。四个本地权重分片及config/tokenizer的SHA256见`assets/qwen_local_provenance.json`。

BART必须提供已做关键词One2Many微调的checkpoint及训练/版本来源，普通base BART不能替代。分隔符默认`;`，须与checkpoint训练格式一致；beam=5，按整条序列分数再按短语位置排序，不把beam分数称作单个关键词的生成概率。输入截断也留档。

实际checkpoint：[`taln-ls2n/bart-base-kp20k`](https://huggingface.co/taln-ls2n/bart-base-kp20k)，固定revision `674e4b03753c70d23b0c5be504a81043dcb783a7`，Apache-2.0。模型卡标明KP20k训练集、ONE2MANY、present-absent次序、`;`分隔及`title<s>abstract`输入；代码严格使用该输入格式。本地目录`/data_big/iclr-s4/models/bart-base-kp20k`，beam=5、返回5条序列、early_stopping=true、max_new_tokens=192。此次使用公开微调权重推理，没有在200篇上重新训练。

## 2. 体系是三层有向无环图，而不是严格单父树

本次已导入ACM CCS 2012公开镜像。官方XML端点返回HTTP403；核对[`filpia/acm-computing_classification_system`](https://github.com/filpia/acm-computing_classification_system)与[`cli99/acm-ccs`](https://github.com/cli99/acm-ccs)两份镜像的同一Git blob `99a4e9be680153e3f51c536b15d948140aa2a690`后读取XML，来源、SHA256及403记录保留。不宣称已从官方端点重新核验最新版。

原始2,299个概念按“原始根 / 第一分支 / 更深后代”投影为三层：L1=14、L2=88、L3=2,199，共2,301个层级限定节点、135个多父节点、2,352条完整路径。中间被压缩的原路径保存在`assets/acm_projection.json`；同一概念跨层角色用level-qualified ID区分。版本`acm_ccs_2012_root_branch_descendant_v1`，本轮未做LLM扩充，现代ML术语覆盖缺口是本次对照的限制。现有LLM原始论文树不参与这个投影，也不被修改。

格式示例仅用于说明schema，不是正式ACM数据：

```json
{
  "version": "example-v1",
  "source": {"kind": "example_only"},
  "nodes": [
    {"id": "r1", "name": "领域甲", "description": "...", "level": 1, "parent_ids": []},
    {"id": "r2", "name": "领域乙", "description": "...", "level": 1, "parent_ids": []},
    {"id": "m", "name": "任务族", "description": "...", "level": 2, "parent_ids": ["r1", "r2"]},
    {"id": "l", "name": "具体路线", "description": "...", "level": 3, "parent_ids": ["m"]}
  ]
}
```

节点唯一ID；`parent_ids`允许多个父节点，但只能连接相邻层。校验缺失父节点、重复ID、空父链与不合法层级；相邻层约束保证无环。原始CCS若超过三层，应单独保留原概念ID、原始路径和三层投影理由；不能直接将原始任意深度称为L3。

每个L3的**每条**完整L1→L2→L3路径单独编码，文本为`L1 > L2 > L3 : 描述`。同一L3跨父路径共享节点ID，但路径ID不同；不通过复制节点隐藏多父关系。

## 3. 路径感知匹配与仲裁

沿用本地固定revision的BGE-M3，路径和关键词上下文使用同一模型、510内容token分块/64重叠/归一化均值，不新增未评测的embedding模型。present词使用所在句；absent词没有原文位置，使用标题+摘要上下文并标明类型。

1. 对路径向量计算余弦Top-5。
2. 最高相似度≥0.7：直接命中最佳路径对应的L3。
3. 0.5≤最高相似度<0.7：默认OpenAI弱模型仲裁。提供标题、摘要、关键词、Top-5路径及其父节点下子树；只能返回给定路径ID或空列表。本次历史前段为DeepSeek，来源逐项保留。
4. 相似度<0.5，或仲裁全部拒绝：进入未匹配词池。未执行仲裁的模糊项标记pending，不能冒充新词或确定命中。

阈值仅为开发初值，不代表0.7就是70%正确率。仲裁复用现有`request_job`、北京时间日志和持久化初次+最多5次重试，所有API调用按auth配置。本版统一批量GPU编码，同一论文同一词跨方法共享匹配/仲裁缓存；API线程并发读取auth（当前OpenAI=4，历史DeepSeek=50）。每个候选父节点的同级上下文最多12项，截断留标记。抽取全本地，但完整对齐仍需要模糊区API，不能称为零API成本。

## 4. 多父路径传播、权重与Top-N

命中L3后展开该节点全部有效祖先路径；不把多父节点只挂到最相近的一个父节点。每个关键词对同一节点最多贡献一次RRF权重，共同祖先不因多条路径重复加分。

节点支持分数为关键词权重之和；另报归一化支持比例，均不是已校准正确率。注意力原始分数只决定路A排名，不再与RRF权重相乘来重复加权。

默认L1 Top-3、每父节点L2 Top-2用于候选路径筛选，再选择全局L3 Top-5。最终对入选L3恢复全部父路径；完整父闭包优先于L1/L2上限。如因此超限，输出`topn_overflow`，不默默删除父节点。各路径共享L3支持分数，不把路径条数当独立标签票数。

## 5. 新词与体系迭代

未匹配词池按不同文档计频，同一篇被三个方法发现仍只算一篇；保存来源论文与最多五个上下文例句。仲裁pending项单独统计。

本次实现到候选池输出。离线“挂到现有节点/提议新节点”的评议、审核和新版本发布尚未执行；不修改已冻结索引。后续评议需保留建议父节点列表、证据与状态，通过审核后创建新体系版本并重建或增量更新索引。原始论文树导出不依赖这些步骤。

## 6. 命令与产物

```bash
export CUDA_DEVICE_ORDER=PCI_BUS_ID CUDA_VISIBLE_DEVICES=0 OMP_NUM_THREADS=4
DKTA_PY=/data_big/iclr-s4/runtime-dkta/bin/python
DKTA_ROOT=/data_big/iclr-s4/experiments/dkta4060_200_v1

# 两路独立运行，按需加载/释放模型；不要修改已完成路由的签名参数。
"$DKTA_PY" scripts/s4_dkta.py extract --root "$DKTA_ROOT" \
 --routes qwen_attention --four-bit --limit 200
"$DKTA_PY" scripts/s4_dkta.py extract --root "$DKTA_ROOT" \
 --routes bart_one2many --bart-model /data_big/iclr-s4/models/bart-base-kp20k \
 --bart-checkpoint-provenance 'taln-ls2n/bart-base-kp20k@674e4b03753c70d23b0c5be504a81043dcb783a7' --limit 200
"$DKTA_PY" scripts/s4_dkta_compare.py acm --root "$DKTA_ROOT"
"$DKTA_PY" scripts/s4_dkta.py index --root "$DKTA_ROOT" \
 --taxonomy "$DKTA_ROOT/assets/taxonomy_acm.json" --embedding-device cuda:0
# 本实验的DeepSeek基线已完成；仅补齐保存的402失败：
"$DKTA_PY" scripts/s4_dkta_compare.py recover-arbitration --root "$DKTA_ROOT"
# deepseek在此仅用于定位原缓存签名；cache-only禁止任何API请求或重新编码。
"$DKTA_PY" scripts/s4_dkta.py align --root "$DKTA_ROOT" --embedding-device cuda:0 \
 --methods qwen_attention bart_one2many dkta_rrf llm_deepseek --limit 200 \
 --arbitrator deepseek --cache-only
"$DKTA_PY" scripts/s4_dkta_compare.py judge --root "$DKTA_ROOT" --judge-papers 50
"$DKTA_PY" scripts/s4_dkta_compare.py report --root "$DKTA_ROOT"
```

上述命令用于当前历史缓存续接。新全OpenAI实验应使用新root，先`prepare`并复用固定输入/本地抽取，再执行默认OpenAI的`matched-llm --baseline-provider openai`；对齐传`--methods qwen_attention bart_one2many dkta_rrf llm_openai --arbitrator openai`。不要在当前root混用不同签名或把已有DeepSeek输出改名为GPT结果。

输出根目录：`/data_big/iclr-s4/experiments/dkta4060_200_v1`。包含冻结`inputs/`、两路`keywords/`、四配置`fused/`、`matched_llm/`、`taxonomy_index.json`、`path_vectors.npz`、四配置`assignments/`、共享`alignment_cache/`、`new_term_pool.json`、`quality/`、`comparison.md/json`及执行状态。API请求/响应、累计重试与token用量均可溯源。原有Kimi和三模型树不被改写。旧`dkta_200_v1`只准备过输入，本次真实实验使用新目录。

## 7. 对比协议与结果口径

先完成10篇运行验证，再执行同一200篇开发集。关键词指标使用作者自报关键词的大小写/词元精确匹配，P@10分母固定10，缺少十个预测时视为空位；参考不完备，因此是代理一致性而非真实领域准确率。报告逐篇宏平均、1,000次论文bootstrap的95%区间，以及相对BART的配对差值区间。

按年份轮转分层、seed=1701抽50篇，以auth中`gpt-6-luna`盲评匿名三级路径；每方法最多5个不同L3，每L3取一条代表父路径，其余多父边只做结构完整性校验。评判内容支持、语义父子包含、具体程度1–5，并为支持判断提供可精确回溯到标题摘要的原文引文。大小写、Unicode兼容字形、PDF断行/连字符及Markdown加粗差异，在原文唯一匹配后可恢复实际原文跨度，附模型原始引文、处理规则及字符区间；其他不在原文的引文仍拒绝。5份初始失败评价从保留响应本地重验恢复，没有增加模型请求，17条引文留有排版恢复记录。不猜测路径ID。无人工抽查；不能将模型判断称为人工金标准。API并发从auth取值（本轮OpenAI=4）。补齐仲裁和评判同用弱模型，存在同源偏好，结果需披露。

同输入主比较包括Qwen/BART/RRF对齐路径、已完成的DeepSeek自由路径及DeepSeek抽词后同体系对齐路径，不为对比重新调用DeepSeek。原六板块DeepSeek/OpenAI/Qwen只作附加历史参照，取其原始顺序前5条L3路径；输入、量化及分支数量不同，不能作同输入消融。历史OpenAI与评判器同源，单独声明偏差。仲裁能读取全文标题摘要，因此最终标签质量同时反映抽词、体系词表及仲裁，不是纯关键词算法准确率。

同时报告文档路径覆盖率、空输出计零的支持率、未匹配词比例、完整多父闭包、Top-N溢出、每篇抽取服务时间和峰值显存。抽取时间不含模型加载，不等于不同并发下的全流程吞吐。没有细粒度gold，不报告真实hierarchical F1或ECE；未冻结生产taxonomy。完整结果与样例见当前实验的`comparison.md`和项目内的对比报告。
