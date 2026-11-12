# Gold Standard Reviewer Assignment：2023 与 2025 版本、运行与评价

核查日期：2026-10-17。材料：arXiv v1/v2 完整 PDF、作者仓库历史与当前数据/代码、实验 notebook；实际重跑公开预测的评价。

## 1. 版本结论

比较对象：

- [2023-03-23 arXiv v1](https://arxiv.org/abs/2303.16750v1)，PDF 22 页。
- [2025-05-30 arXiv v2](https://arxiv.org/abs/2303.16750v2)，PDF 26 页；作者仓库将该工作标注为 TMLR 2025。

2025 版沿用同一批专家自评数据，主要扩充模型、聚合方式和评价分析，并未发布规模更大的新标注集。

| 项目 | 2023 v1 | 2025 v2 |
|---|---|---|
| 专家人数 | 58 | 58 |
| 专家—论文自评数 | 477 | 477 |
| 不同被评论文数 | 463 | 463 |
| 专家历史发表记录 | Semantic Scholar，2022-05-01 抓取 | 沿用同一快照，不因论文 2025 修订而变成 2025 画像 |
| 主实验输入 | 投稿与历史论文的标题、摘要；每人最多 20 篇近期发表论文 | 基本相同 |
| 原有方法 | Trivial、TPMS、ELMo、SPECTER、SPECTER+MFR、ACL | 保留这些方法，并补充新比较 |
| 新方法 | 无 | SPECTER2；o1-mini、Claude Sonnet 3.5、Gemini 2 Flash |
| 画像相似度 pooling | 未系统比较 SPECTER2 pooling | 比较 mean、75th percentile、max |
| 主指标 | 差值加权的归一化错序损失 | 主指标语义相同，函数改名并支持 top-k 扩展 |
| easy/hard 分层 | 已有 | 保留并扩展模型结果 |
| 附加指标 | 无对应附录 | 新增 WKTD@k、MRR@k、NDCG@k、Precision@k，报告 k=1/3/5/7 |
| 标题摘要条件的最低主损失 | SPECTER+MFR，0.24 | SPECTER2 max pooling，0.22 |
| LLM 分析 | 无 | 直接把专家历史论文与候选论文交给 LLM 打适配分 |

数据一致性不仅来自论文数字：2023 仓库提交 `aac90f2df5e2` 与当前提交 `00296730e3eb` 的 `data/evaluations.csv` Git blob SHA 均为 `7311b3236659dba030eda0cd6b333b710d6b1d5e`，文件内容完全相同。2025-04-14 提交增加模型预测、LLM notebook 和新指标；2026-09 的后续提交主要增加许可与引用元数据。

注意：旧模型的部分数值/区间在新版有小变化，例如 ELMo 主损失由 0.34 变为 0.35；不能把旧表和新表视为逐项完全一致，也不能将这种变化归因于新标注数据。

## 2. 数据实际是什么

研究者回忆自己过去一年读过的约 5–10 篇论文，对“我是否具备审这篇论文的能力”自评。评分范围 1–5，允许 0.25 间隔：1 表示不具备审稿资格，5 表示具备评价全部方面的背景。被评论文不能是研究者自己的作品。

每位参与者评价自己的候选小集合，共形成 477 个配对。一篇论文可能由多名参与者评价，因此不同论文数为 463。根据评分文件实际计数，每人集合内所有无序论文对共 1,841 对（包含真值相同的配对）。

文件分为：

- `data/evaluations.csv`：专家自评，虽然后缀为 csv，实际使用 TAB 分隔。
- `data/participants/`：专家 Semantic Scholar 画像。
- `data/papers/`：投稿候选与历史论文元数据。
- `data/txts/`：部分可公开获取论文的解析全文。
- `evaluation_datasets/`：作者已整理的模型输入。
- `predictions/`：作者公开的各模型预测，可直接复算评价。

其主要任务是：**固定一位专家，在该专家评过的论文集合内，预测哪些论文更适合其审阅。**它没有完整专家×论文矩阵，不直接执行全会议 COI/容量约束分配，也没有多级分类或数字孪生行为 gold。

## 3. 一次实验怎样运行

### 3.1 构造专家画像

从专家历史发表论文中选最多 20 篇近期论文；不足 20 篇则全部使用。按发表年份排序，同年论文随机打破并列。作者重复生成 10 组 `d_20_1` 到 `d_20_10`，平均结果以减小画像采样波动。

这 10 组是相同 benchmark 的画像重复采样。主比较中模型使用现有预训练实现/默认参数，未在 477 个自评上统一训练一个监督模型。

### 3.2 算每个专家—候选论文的适配分

科学 embedding 方法先编码候选论文和专家历史论文，再算相似度。若专家有 n 篇历史论文，得到 n 个 paper–paper 分数，再聚合：

\[
s_{max}(r,p)=\max_{j\leq n}\operatorname{sim}(p,h_{rj}),
\qquad
s_{mean}(r,p)=\frac{1}{n}\sum_j\operatorname{sim}(p,h_{rj}).
\]

75th percentile pooling 取这些分数的第 75 百分位。max 强调“至少有一篇很相关的历史作品”；mean 也会受到无关历史方向的影响。它们没有普遍优劣保证，论文在该数据上发现 SPECTER2 max 的总体损失最低。

LLM 分支把专家最多 20 篇历史论文的标题摘要及一篇候选论文的标题摘要放入 prompt，要求输出 0–100 整数匹配分及解释。评价时仍使用其分数排序，不以解释质量作为该实验指标。

### 3.3 输出预测文件并评价

预测格式概念上为：

```json
{
  "reviewer_id": {
    "paper_id_A": 0.82,
    "paper_id_B": 0.47
  }
}
```

数字范围由方法决定，官方主指标只依赖每位专家内部的分数顺序。文件需要覆盖全部应评配对；缺失值不能随意填零。

新方法输出十份 `ours_d_20_1_ta.json` … `ours_d_20_10_ta.json` 后，在官方仓库内运行：

```bash
python3 evaluation_script.py \
  --dataset ./data/evaluations.csv \
  --prediction_dir ./predictions \
  --algo ours
```

这条命令只评价已有预测，不会替我们生成 taxonomy、建立画像、加载 embedding 或训练模型。前面的适配打分需由方法自己完成。

只想检查作者基线时，使用仓库已有预测：

```bash
python3 evaluation_script.py \
  --dataset ./data/evaluations.csv \
  --prediction_dir ./predictions \
  --algo spector2_max
```

`spector2_max` 是作者实际使用的文件名前缀拼写，需与文件一致。

## 4. 主指标怎么计算

令 e_ri 为专家 r 对论文 i 的自评能力，s_ri 为算法适配分。对同一专家评过的任意两篇 i、j：

- 预测顺序正确：损失 0。
- 顺序颠倒：损失 |e_ri−e_rj|。
- 算法预测并列，但真实评分不同：损失为差值的一半。
- 真实评分相同：权重为 0，不产生损失或归一化权重。

将所有专家的加权损失相加，再除以所有真实差值之和：

\[
L=\frac{\sum_r\sum_{i<j}|e_{ri}-e_{rj}|\big[\mathbf 1((s_{ri}-s_{rj})(e_{ri}-e_{rj})<0)+\tfrac12\mathbf 1(s_{ri}=s_{rj})\big]}{\sum_r\sum_{i<j}|e_{ri}-e_{rj}|}.
\]

L 在 0–1 之间，越低越好；完美排序为 0，完全反序为 1，无区分度的常数预测为 0.5。计算使用下式定义的自评分差加权错序损失。

例：某专家对 A/B/C 的真值为 5/4/1，配对权重为 1/4/3，分母为 8。只交换 A/B 时损失为 1/8；只交换 B/C 时为 3/8。把明显不适合的论文排到高能力论文前，会受到更重处罚。

主损失 0.22 按上述加权错序定义解释。

## 5. easy/hard 与新增指标

### 5.1 easy/hard accuracy

- easy：同一专家的两篇论文，一个自评≥4、另一个≤2。完整数据共有 261 个这样的三元组。
- hard：同一专家的两篇论文都≥4，且评分不相等。完整数据共有 417 个这样的三元组，例如 4.25 与 4.75。
- accuracy 是严格预测顺序正确的比例；官方代码中预测并列不计正确。easy/hard 分别按给定阈值选取子集，其余配对不进入这两个指标。

这两个分层 2023 年就已经存在，2025 年扩展了模型比较。

### 5.2 2025 新增附录指标

WKTD@k 关注 top-k 相关配对的加权错序；NDCG@k 衡量推荐顺序对应的专家能力；Precision@k 衡量预测与自评 top-k 的重合；MRR@k 的作者实现是“真实 top-k 论文在预测列表中的倒数排名的平均”。复现时使用上述作者定义。

核查发现一个应明确记录的差异：附录 C 的 WKTD@k 用自评 top-k（R_k）确定参与配对，而当前 `compute_kendall_tau(..., k=k)` 用预测 top-k 过滤配对。`k=None` 的主指标不受此问题影响。若比较附录结果，应声明使用作者代码定义或论文公式定义，不能混用并都称为严格复现。

## 6. 置信区间与子集

官方脚本对 10 组画像的损失取平均。95% CI 通过 1,000 次 reviewer-level bootstrap：以专家为单位有放回抽样，保留每位专家内部的论文集合，重新评价。论文也比较相对于 TPMS 的配对损失差及区间。

衍生三元组共享同一专家，不能把它们当作互相独立的几百个样本随意抽样。当前主脚本未固定 NumPy 随机种子，因此重跑 CI 边界可能略变；正式实验应记录种子，并给方法使用相同 bootstrap 样本。

输入子集必须区分：

- 标题摘要主代码/README 使用全部 58 位专家、463 篇目标论文、477 个标签。
- 全文相关实验使用 57 位专家与 457 篇可得全文的目标论文，并重新构造可得全文的历史画像；画像长度 1–20 的不同条件各重复 5 次。
- v2 第 6 节开头关于“本节先移除 6 篇和 1 人”的措辞与其 notebook 主比较代码并不一致。当前官方 evaluator、notebook 的 TA 配置及本次复算均按全体数据执行。报告时应写清实际采用的 manifest/子集，不只引用 PDF 中一个笼统句子。

这也解释了 TA 主表 TPMS=0.28，而全文控制表中的 TA=0.27，不能把不同子集数字直接拼成严格同条件提升。

## 7. 新版主表及本次实际复算

v2 表 3 的损失（TA 条件）：TPMS 0.28，SPECTER 0.27，SPECTER+MFR 0.24，SPECTER2 mean 0.25、75th percentile 0.24、max 0.22，o1-mini 0.25，Claude Sonnet 3.5 0.31，Gemini 2 Flash 0.38。模型间的显著差异按原文配对检验结果逐项解释。

本次下载作者十份 SPECTER2 max 预测文件，以当前官方脚本复算，结果：

| 项目 | 结果 |
|---|---:|
| 加权错序损失，10 组均值 | 0.2214761182 |
| Easy accuracy，10 组均值 | 0.8892720307 |
| Hard accuracy，10 组均值 | 0.6067146283 |
| 当前 evaluator 输出，四舍五入 | 0.22 |
| 本次未固定种子的 bootstrap 95% CI | [0.18, 0.27] |

论文表 3 的 SPECTER2 max CI 为 [0.18, 0.26]；本次使用相同算法但重新抽样，边界有小幅随机变化。点估计与表 3/5 的 0.22、0.89、0.61 一致。

同时把相同十份预测分别送入 2023 `compute_main_metric` 与当前 `compute_kendall_tau(k=None)`，每份损失之差小于 1e-12，确认主指标保持一致。

上述是**复算作者已公开预测的评价结果**，没有重新推理 SPECTER2，也没有执行本项目方法。机器可读记录见 `goldstandard_metric_verification.json`。

## 8. 对本项目的具体含义

近期比较以新版强基线和主指标为准：冻结 taxonomy/编码器，用相同 TA 输入和相同 d_20 画像构造我们的匹配分，测主损失、easy/hard accuracy 及成本。SPECTER2+SciNCL 可以作为额外的 OpenReview 强基线，但不应伪装成 v2 主论文表 3 已列的方法。

用户 L1 优先与层级分类质量需另外评价；benchmark 没有用户 L1 或 L2/L3 gold。数字孪生行为与团队互补也不能由该适配 benchmark 单独证明。若使用 477 个标签学习混合权重，需另外设置开发/留出协议，不能在全部数据上调完再称无调参复现。

## 可复查来源

- 论文 [v1 PDF](https://arxiv.org/pdf/2303.16750v1)、[v2 PDF](https://arxiv.org/pdf/2303.16750v2)。
- [2023 仓库快照](https://github.com/niharshah/goldstandard-reviewer-paper-match/tree/aac90f2df5e2)。
- [本次核查的当前快照](https://github.com/niharshah/goldstandard-reviewer-paper-match/tree/00296730e3eb)。
- [官方 evaluator](https://github.com/niharshah/goldstandard-reviewer-paper-match/blob/00296730e3eb/evaluation_script.py)。
- [官方 scoring](https://github.com/niharshah/goldstandard-reviewer-paper-match/blob/00296730e3eb/scripts/scoring.py)。
- [官方实验 notebook](https://github.com/niharshah/goldstandard-reviewer-paper-match/blob/00296730e3eb/notebooks/Experiments.ipynb)。
