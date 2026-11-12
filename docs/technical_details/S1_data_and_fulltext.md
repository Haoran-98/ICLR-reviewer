# S1 数据库与轻量全文索引

状态：`已完成`

## 输入与存储

- 原始源：`/data_big/iclr_reviews`，只读。
- PostgreSQL：`iclr_reviewer`，PostgreSQL 16 + pgvector。
- 内容寻址对象：`/data_big/iclr-reviewer-store/objects/<sha256-prefix>/...`。
- 数据状态和报告：`/data_big/iclr-reviewer-db/state`。
- 数据库快照：`/data_big/iclr-reviewer-db/snapshots/database_v1.dump.zst`。

## Schema 分层

| Schema | 职责 |
|---|---|
| `raw` | 不可变来源、artifact、OpenReview Note/Edit、排除记录 |
| `core` | paper、version、review、revision、score、discussion、decision、area |
| `semantic` | 轻量全文索引、profile、后续 taxonomy/embedding |
| `twin` | 后续 archetype、Reviewer/Author twin、outcome |
| `ops` | pipeline run、质量问题、能力报告和 snapshot |

迁移当前到 `0005_text_first_fulltext_index.py`。主要实现见
[`../../database/schema.sql`](../../database/schema.sql) 和
[`../../database/migrations/versions/`](../../database/migrations/versions/)。

## 可恢复执行链

`database/iclr_database.py` 提供：

```text
inventory -> object-store -> migrate -> ingest -> fulltext-index
          -> revision-audit/revision-backfill -> validate -> snapshot
```

`all` 会重复执行一次 ingest；业务表行数变化即判定幂等失败。

## Text-first 索引

输入是已有 Markdown，不调用 LLM、Docling、MinerU 或视觉模型，也不把全文复制到
PostgreSQL。

`semantic.paper_fulltext_index` 每篇论文一行，保存：

- source artifact、content hash、index version 和状态；
- char/token/page 计数和 headings；
- figure/table/equation/theorem/algorithm 计数；
- 理论、结果表、消融、方法图等 routing signals；
- `deep_parse_status`，默认 `not_requested`。

`semantic.paper_content_object` 保存编号对象的类型、label、caption、近似页码、字符区间、
出现次数、置信度和按需解析状态。

## 已验收结果

- `core.paper`：38,890。
- Markdown indexed：38,715。
- Markdown missing：175。
- 内容对象：621,166。
- 深度解析启动数：0。
- 全量重复运行：38,890 条 `unchanged`。
- 随机重算 300 篇：主索引零差异，无悬空对象或非法字符位置。

## Revision 辅助链

`revision-audit` 通过 OpenReview edits API 验证历史 revision 是否可重放；
`revision-backfill` 按 conference domain 分页，每页约 1,000 edits，本地过滤 Review，
并将 checkpoint 写入 `revision_backfill_checkpoint.json`。

认证 token 不进入仓库。后台任务不读取 TOTP secret，token 过期时停止并要求人工续期。

更多操作说明见 [`../../database/README.md`](../../database/README.md)。
