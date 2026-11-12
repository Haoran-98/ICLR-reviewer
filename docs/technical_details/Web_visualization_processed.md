# 已处理论文全量可视化

更新：2026-11-06。此为历史扩容记录；用户随后限定当前页面为 S4 的 12,964 篇，见 [当前 S4 版本](Web_visualization_S4.md)。访问入口：<http://172.24.246.231:5173/>，继续自动跳转至原 HTTPS 服务。

## 数据范围

从 PostgreSQL 只读一致性快照中选取 `semantic.paper_profile.profile_version = paper_understanding_v1` 的全部论文，不再限制每年 12 篇。

| 年份 | 已有结构化结果的论文 | 最新已采集审稿 | 有效 rating |
|---|---:|---:|---:|
| 2024 | 7,402 | 28,020 | 28,020 |
| 2025 | 11,648 | 46,651 | 46,651 |
| 2026 | 19,757 | 89,767 | 74,316 |
| 总计 | 38,807 | 164,438 | 148,987 |

- 全库论文 38,890 篇，当前 83 篇没有该版本的结构化结果；处理日志记录为失败，本次未重新调用模型处理。
- 174 篇现有结构化结果带 `needs_review` 标记，仍纳入探索，并在选中详情提示待复核。已有结果不等同于整条 S3 流水线通过验收，`progress.json` 的全量 gate 仍为失败状态。
- 15,451 条审稿 rating 缺失，未记为零。有效评分全部来自数据库，无模拟数据。
- 论文文本取 `version_no DESC, paper_version_id DESC` 的最新已采集版本；每条审稿仅保留 `revision_no DESC, review_revision_id DESC` 的最新已采集版本。
- 当前数据版本：`processed-b6d264e6f6804127`。这是浏览快照，不随后台数据库自动刷新。

## 地图方法

为尽快将现有结果用于全量探索，采用已安装 sklearn 提供的本地词汇特征基线：

1. 输入标题、结构化总结、研究问题与方法概述；仅总结缺失时以摘要替代。输入不包含审稿、评分或录用决定。
2. 英文 stop words、word unigram/bigram、`min_df=2`、`max_features=40000`、`sublinear_tf=True` 的 TF-IDF。
3. `TruncatedSVD(n_components=64, random_state=42)`。
4. Barnes-Hut t-SNE：二维、perplexity 40、750 次迭代、PCA 初始化、learning rate auto、随机种子 42；sklearn 1.9.0。

投影版本：`tfidf-svd-tsne-6dc21e809467eff0`。输入哈希、参数、64 维向量及坐标缓存在被忽略的 `logs/web_visualization/projections/<input-hash>/`；未改变输入可复用缓存。所有年份使用同一空间，筛选不会重新计算坐标。

页面明确称为“文本地图”。该版本没有生成深度语义模型 embedding，也没有向 `semantic.embedding` 写入数据；`semantic_projection=false`。二维邻近用于词汇主题探索，簇间距离、坐标轴和簇大小不表示质量或影响。后续 V2 仍需正式向量模型和近邻质量检查。

## 全量页面

- 支持 WebGPU/shader-f16 时使用 Embedding Atlas；缺少支持时使用原生 Canvas 2D，无须修改 Windows 浏览器的 GPU 配置。
- 两种渲染均加载全部 38,807 个点，支持缩放、拖动、点选与 Shift 多选。
- 提供标题/ID 搜索、年份和决定状态筛选、清空搜索、重置缩放。筛选结果覆盖地图全部匹配论文，下方列表明确只列前 20 篇，提供键盘选择入口。
- 初始 JSON 约 12.14 MB，只含地图元数据。摘要、结构化总结/问题/方法、各条 rating/confidence 按 200 篇一组，选择后加载对应文件并缓存。异步结果通过选择序号防止过期详情覆盖新选择。
- 原始记录链接指向 OpenReview；模型生成内容明确标注，待复核结果单独提示。
- 显式主题超边单独导出 `hyperedges.json`（27 条），未在初始地图加载，也未新增超图页面。

## 全量评分图

继续由 R/ggdist 生成 SVG。将全部有效 rating 按年、按整数分值绘制离散直方分布（`stat_slab(density="histogram")`），不再为 14 万多条评分各绘制一个 SVG 点，产物约 13 KB。

图内按年归一化高度，只比较同一年内各评分的相对频率。年份标签、原始分值、每年有效数量和总缺失数量均保留。不同年份的可选评分不同，不做连续核平滑或推断区间。评分图仍是整个已处理队列的静态分布，不随地图筛选或选中论文更新。

## 刷新与验证

仓库根目录：

```bash
PYTHONPYCACHEPREFIX=/tmp/iclr-map-pycache OPENBLAS_NUM_THREADS=4 OMP_NUM_THREADS=4 python3 -u web/export_v1.py
logs/web_visualization/runtime/r/bin/Rscript web/render_reviews.R web/public/generated/reviews.csv web/public/generated/reviews.svg
npm --prefix web run build
```

`PYTHONPYCACHEPREFIX` 用于避开本机系统 Python 的一处损坏字节码缓存，不改变系统文件。`--per-year 12` 可显式生成按年小样本用于开发；默认导出所有已处理论文。网页数据与评分图应同时生成后再构建。`iclr-web-lan.service` 从 `web/dist/` 提供静态内容。

验证包含：数据库论文 ID 集合完全匹配；所有详情文件完整；审稿 ID 唯一；CSV 与独立 SQL 的逐年数量/有效评分一致；坐标有限；真实浏览器像素读回、点选多选、按需详情、筛选与空结果、列表定位、手机布局。

机器可读结果见 `docs/research/web-visualization-processed/`。两条真实浏览器路径均已通过：Canvas 首屏 571 ms、选点与详情 189 ms、筛选 88 ms；Atlas 首屏 714 ms、选点与详情 47 ms、筛选 66 ms。初始详情请求为 0；抽查 300 个点的真实像素，Canvas 命中 286、Atlas 命中 298（密集点存在像素取整和重叠，不将抽查作为逐点无重叠证明）。两种模式均通过搜索空结果、搜索后列表定位、年份/决定筛选和手机宽度检查，无浏览器页面错误。

扩容验证还修复了 Atlas 密集地图的默认提示框拦截附近点点击的问题：使用不接收鼠标事件的自定义提示框，真实点击与 Shift 多选验证覆盖该问题。性能测量环境为服务器本机 Chromium，通过同一 LAN 入口访问。

## 与固定计划的关系

本次完成已处理队列扩容，提前交付 V2 的词汇投影基线、V3 的全量浏览与 V4 的全量静态评分图。V2 正式语义模型、V3 框选和语义检索、V4 动态联动统计、V5 超图、V6 三视图联动继续按原计划迭代。
