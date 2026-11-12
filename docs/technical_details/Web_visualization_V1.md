# Web 可视化 V1：数据契约与接入验证

- 执行日期：2026-11-05
- 状态：`已完成，V1 验收通过`
- 关联：[六步实施计划](Web_visualization_plan.md)
- 实现入口：[web/](../../web/README.md)
- 机器可读证据：[validation.json](../research/web-visualization-v1/validation.json)

## 1. 服务入口与技术栈

仓库清点未发现现有 Web API、前端 `package.json`、前端源码或部署配置。`automation/public/` 是自动化生成的数据产物目录，不是 Web 应用。

本阶段新增 `web/` 作为独立的最小 Web 工程：

| 层 | 已采用实现 | 作用 |
|---|---|---|
| 页面 | Vite 7.3.7 + 原生 JavaScript | 承载自己的页面与静态资源 |
| 地图 | Embedding Atlas 0.26.0 原生 `EmbeddingView` | TypedArray 坐标、真实点击与多选回调 |
| 数据提取 | Python + 现有 psycopg | PostgreSQL 一致性只读事务导出 |
| 评分图 | R 4.4.3、ggdist 3.3.3、ggplot2 4.0.3、svglite 2.2.2 | 服务端生成 SVG |
| 浏览器验证 | Playwright 1.61.1 | 实际操作页面并检查 GPU 读回 |

V1 通过 `/generated/sample.json` 和 `/generated/reviews.svg` 接入静态样本；这两项是已实现资源入口。正式业务查询 API、动态筛选、超图渲染和生产部署尚未实现。本阶段不引入 Web 框架或修改业务数据库。

## 2. 数据清点与版本策略

提取时间为 `2026-11-05T09:39:16.489456+00:00`，事务快照为 `83381:83381:`。实际导出采用 `REPEATABLE READ READ ONLY`，数据集版本为 `v1-sample-520a224749858932`。

| 年份 | 论文 | 审稿（每条取一个版本） | 有 rating | 有 confidence | 实际 rating 取值 |
|---|---:|---:|---:|---:|---|
| 2024 | 7,404 | 28,028 | 28,028 | 28,028 | 1、3、5、6、8、10 |
| 2025 | 11,672 | 46,748 | 46,748 | 46,748 | 1、3、5、6、8、10 |
| 2026 | 19,814 | 90,034 | 74,540 | 75,859 | 2、4、6、8、10 |
| 合计 | 38,890 | 164,810 | 149,316 | 150,635 | 默认分年展示 |

- 现有 38,890 篇论文均有题目、摘要、关键词和显式主题；共有 27 个显式主题。
- 共 164,821 条审稿版本；先按 `review_id` 去重后，有评分的审稿是 149,316 条，而不是包含历史版本的 149,327 条。
- 共 431,990 条讨论事件、38,890 条决定；当前论文均有决定记录。
- `semantic.embedding` 与 `semantic.paper_taxonomy_assignment` 仍为空。V1 不生成语义向量。
- 原始 edit envelope 有 120,183 条，其中 22,568 条含 `note.content`；当前规范化审稿表只有 4 条审稿具有多个版本。原始 edit 数量不等于已核验、可直接用于分析的完整轨迹数量。

固定版本规则：

1. 论文文本取 `version_no DESC, paper_version_id DESC` 的首条；当前论文文本均仅有 `version_no=1`。这是当前观测文本，不宣称为最初投稿版本。
2. 审稿取 `revision_no DESC, review_revision_id DESC` 的首条，每条 `review_id` 只计一次。当前首选版本均为非历史 edit 的观测快照。`revision_no` 是系统版本序号，不直接当作作者提交时间。
3. 决定取 `created_at DESC NULLS LAST, decision_id DESC` 的首条。
4. `latest_observed` 表示最新已采集版本，不承诺等于初审或官方最终截止时刻。按时间截断与初审/最终配对属于后续轨迹验证。
5. rating 保留原始数值与原始标签，不跨年线性归一化或直接混合比较。confidence 是审稿人自报置信程度，不是统计置信区间。

年度指南已核对：[2024](https://iclr.cc/Conferences/2024/ReviewerGuide)、[2025](https://iclr.cc/Conferences/2025/ReviewerGuide)、[2026](https://iclr.cc/Conferences/2026/ReviewerGuide)。这些页面说明审稿流程，但本次未取得完整年度数值选项标签；公开 invitation 请求返回 403。因此上表严格表述为数据库观测取值，不额外推断各分值的官方文字含义。这不影响分年原值分布，跨年阈值比较须在 V4 前补齐官方量表映射。

## 3. 字段字典

PostgreSQL bigint 标识在 JSON 中统一序列化为字符串，避免 JavaScript 精度问题。

| JSON 字段 | 类型/空值 | 来源与含义 |
|---|---|---|
| `papers[].paper_id` | string，非空 | `core.paper.paper_id`，三个视图的统一主键 |
| `forum_id` | string，非空 | OpenReview forum 标识 |
| `year` | integer | `core.venue.year` |
| `paper_version_id` | string/null | 按固定规则选出的 `core.paper_version` |
| `title`、`abstract` | string/null | 所选文本版本；空文本保留为缺失 |
| `keywords` | string[]/null | 原始关键词，不等于模型分类标签 |
| `content_hash` | string/null | 所选文本内容哈希 |
| `openreview_url` | string/null | 来源链接；页面按 `forum_id` 构造官方域名链接 |
| `decision_raw` | string/null | 所选 `core.decision.decision_category` |
| `decision` | enum | `accepted/rejected/desk_rejected/withdrawn/unknown` |
| `areas` | object[] | `core.paper_area → core.explicit_area` 的数组聚合 |
| `areas[].area_id` | string | 显式主题主键 |
| `areas[].label`、`canonical_key` | string | 原始名称与现有规范键 |
| `review_count` | integer | 当前版本口径下该论文的审稿数 |
| `rating_count` | integer | 其中有评分的审稿数 |
| `mean_rating` | number/null | 该论文有效 rating 的描述性平均值；无评分时 null |
| `x`、`y` | number | V1 测试网格坐标，不能用于语义解释 |
| `reviews[].paper_id` | string | 指向样本论文 |
| `review_id`、`review_revision_id` | string | 审稿主键与所选版本主键 |
| `revision_no` | integer | 所选版本序号 |
| `rating`、`confidence` | number/null | `core.review_score` 原值 |
| `soundness/contribution/presentation` | number/null | 同一版本的分项原值 |
| `historical_edit` | boolean | 所选原始内容是否含 `_openreview_edit` 标记 |
| `hyperedges[].edge_id` | string | V1 采用 `area:<area_id>` |
| `type`、`label`、`source` | string | 关系类型、标签、来源表 |
| `paper_ids` | string[] | 该超边在样本中的实际成员 |
| `meta.contract_version` | string | 当前为 `v1` |
| `data_version`、`content_sha256` | string | 样本论文、审稿与成员数据的内容标识 |
| `extracted_at`、`transaction_snapshot` | string | 同一只读事务的时间与快照 |
| `paper_version_policy/review_version_policy` | string | 本次提取的版本规则 |
| `projection_version`、`semantic_projection` | string、boolean | 当前为 `validation-grid-v1`、false |
| `taxonomy_version` | string/null | 当前为 null；未使用模型分类 |

决定映射：Poster/Spotlight/Oral → accepted；Reject → rejected；Desk Reject → desk_rejected；Withdraw → withdrawn；无记录或未识别值 → unknown。未录用布尔值不自动等于拒稿。

## 4. 共享筛选契约（已固定，后续实现）

```json
{
  "contract_version": "v1",
  "data_version": "v1-sample-520a224749858932",
  "projection_version": "validation-grid-v1",
  "taxonomy_version": null,
  "years": [2024, 2025, 2026],
  "area_ids": null,
  "decisions": null,
  "text_query": "",
  "score": {
    "field": "rating",
    "review_version": "latest_observed",
    "paper_aggregation": "mean_observed_rating",
    "min": null,
    "max": null,
    "include_missing": false
  },
  "selected_paper_ids": null
}
```

- `years/area_ids/decisions`：null 表示该字段不限制，空数组表示没有符合值；同一字段内取并集，不同字段间取交集。
- `selected_paper_ids`：null 表示没有额外选区约束；空数组表示明确的空选区。最终论文集合为基础筛选结果与非 null 选区的交集。
- 评分筛选作用于每篇论文的 `mean_observed_rating`；只有启用 min/max 时才按 `include_missing` 处理缺失，否则不排除无评分论文。统计面板随后对最终论文集合中的逐条有效审稿作图，两者单位分别标明。
- 改变基础筛选后同步收敛选区；悬停与临时高亮不改变最终集合。
- 响应须回传数据版本、有效筛选、论文数、有效审稿数、评分缺失数及截断状态；缓存键包含版本与统计参数。
- 地图、超图、审稿统计共用最终论文集合，不分别应用隐式过滤。超图加载上限仅影响展示范围，必须显式标记。
- 请求由后端校验字段、枚举、范围和 ID，SQL 使用参数绑定；浏览器不接收数据库连接配置。V1 仅使用受控导出样本。

## 5. 三个工具的接入结论

| 工具 | 来源与版本 | 接入结论 |
|---|---|---|
| Embedding Atlas | [官方仓库](https://github.com/apple/embedding-atlas)，npm 0.26.0，MIT | 通过原生组件嵌入；`querySelection` 返回真实 `paper_id`，`onSelection` 驱动详情。已验证点击和 Shift 多选 |
| ggdist | [官方项目](https://mjskay.github.io/ggdist/)，3.3.3，GPL-3.0-or-later | 作为独立 R 绘图进程输出 SVG；本阶段已实跑，未引入浏览器端 R 运行时 |
| HINTs | [官方仓库](https://github.com/SamLee-dedeboy/HINTs)，检查 main 分支文件快照 | 采用其文档/实体关系探索思路，V5 独立实现局部超图；当前不复制上游代码 |

HINTs 核验事实：

- README 明确关联论文 [HINTs, DOI:10.1109/TVCG.2024.3459961](https://doi.org/10.1109/TVCG.2024.3459961)。
- 前端是 Svelte 4 + D3 7 + Vite 4，后端是 Flask；不是独立 npm 可视化组件。
- `HyperMap.svelte` 接收 `article_graph`、`entity_graph`、Gosper 布局及多个颜色/状态对象；会派发 `article-label-clicked`、`entity-label-clicked` 等事件，具备选择联动的机制。
- 当前应用还依赖分层聚类、预处理数据及多条后端路由；服务启动时读取 OpenAI key。接入纯关系探索无需照搬这套应用与聊天功能。
- 本次根目录 `LICENSE`、`LICENSE.md`、`LICENSE.txt` 均返回 404，所查 package.json 未声明许可证。尚未确认完整授权范围、最近维护时间或固定发布版本；不能把可浏览源码直接视为明确的复用授权。
- 因而当前选择按论文方法独立实现，以自己的超边契约为输入；以后若确认许可证，再评估有价值的局部代码复用。查询文件的 SHA-256、来源 URL 与接口证据保存在验证记录中。

浏览器兼容性事实：Atlas 0.26.0 要求 WebGPU `shader-f16`。本机默认 SwiftShader 缺少该特性；指定 AMD Vulkan 后端后可用。2026-11-06 根据 Windows Chrome 的实际反馈增加了原生 SVG 兼容地图，缺少 WebGPU、无可用适配器或缺少 `shader-f16` 时自动启用。两种地图共享论文 ID、点选、多选与详情；兼容视图先覆盖 V1 小样本，完整 Atlas 交互与全量兼容性能仍属于后续阶段。

## 6. 验证内容与后续入口

- 真实样本：每年按 `md5(forum_id)` 排序取 12 篇，共 36 篇；关联 153 条去重后的审稿、16 条显式主题超边成员关系。
- ggdist：142 条有效 rating、11 条缺失，按年作离散点分布，无推断区间。
- 浏览器检查：真实点击和 Shift 多选产生实际 `paper_id`；详情题目与数据库样本匹配；SVG 成功加载；GPU 原始绘点和页面错误由 `smoke.mjs` 验证。
- 构建使用锁定依赖；Atlas 主包约 2.13 MB、gzip 约 725 KB，V6 再依据实测处理加载性能。
- 生成语义向量与全量投影仍为 V2；本阶段的网格与小样本不作为语义地图结果。

下一阶段从 V2 开始，复用本次统一标识、文本版本规则和元数据契约，先评估单一向量模型的小样本结果，再生成全量向量与共同二维投影。

V1 验收结果：数据标识和版本口径已固定；三个工具均有明确接入结论；真实点击、多选与 36 个 GPU 绘点通过；142 条有效评分成功绘制；重复导出内容哈希一致；生产构建通过；依赖检查没有已知漏洞。官方分值文字映射、HINTs 源码授权和浏览器覆盖范围作为有明确处理规则的后续项保留。

## 7. 2026-11-06：局域网 HTTPS 接入

按用户要求，新增 `npm run lan`，在 `0.0.0.0:8443` 提供构建后的静态页面；当前访问地址为 <https://172.24.246.231:8443/>。`iclr-web-lan.service` 用户级 transient 服务负责维持进程，不设置开机自启。

`setup_lan.py` 生成可复用的本地 CA 与包含局域网 IP SAN 的服务器证书。客户端需导入公开 CA 证书后访问；服务器私钥只保存在被 Git 忽略的运行目录，证书与启动步骤见 [Web 运行说明](../../web/README.md#局域网-https-访问)。

已验证：按该 CA 正常验证 TLS 链和 IP 后，主页、样本 JSON、评分 SVG 与公开 CA 下载均返回 200；服务监听 `0.0.0.0:8443`；浏览器通过该 HTTPS 地址运行时属于安全上下文，36 个真实论文点、点击、多选及 SVG 加载全部通过。浏览器自动验证使用明确的服务器公钥固定信任；没有修改操作系统的信任库，也没有代替其他设备完成证书导入。局域网 Windows 客户端随后已确认 HTTP 跳转入口可访问，见下文。

验证证据见 [lan-validation.json](../research/web-visualization-v1/lan-validation.json)，本地浏览器结果为 `web/artifacts/lan-smoke.json`。

同日局域网 Windows Chrome 报告 `ERR_EMPTY_RESPONSE`。服务器可复现向 HTTPS 8443 端口发送普通 HTTP 时关闭连接且不返回响应的行为，日志为 `ERR_SSL_HTTP_REQUEST`。新增普通 HTTP 5173 入口自动跳转 HTTPS，并增加握手与访问日志。用户已确认 <http://172.24.246.231:5173/> 能打开页面，推荐后续使用该入口。

随后该 Windows 客户端报告缺少 WebGPU/`shader-f16`。已加入自动兼容地图，并将 Atlas 改为按需加载。兼容性验证通过在浏览器初始化时屏蔽 WebGPU，实际检查 SVG 绘点、点击、多选、详情和 ggdist SVG；Atlas 分支仍通过同一局域网跳转入口验证。最新记录分别为 `web/artifacts/compat-smoke.json` 与 `web/artifacts/lan-smoke.json`。
