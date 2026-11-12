# S4：全量三分之一的实体候选与核心内容提取

> 完成补记：2026-11-02 已封存，12,964 篇、51,856 条向量，`SEALED.json` 与定位/向量审计存在。下文保留启动和恢复时的记录；最新范围、质量边界及部署见 [当前进度](../../STATUS.md)。

2026-10-30 冻结全量 38,890 篇，取三分之一向上取整 **12,964 篇**。按年份 × 统一一级领域分层，
每层按约三分之一分配名额，总数用最大余数法对齐。各层名额足够容纳此前 500 篇，因此全部保留这些种子，再固定随机种子补足。
这是保留既有种子的分层样本，并非全部论文具有相同纳入概率的简单随机样本。

| 年份 | 篇数 |
|---|---:|
| 2024 | 2,468 |
| 2025 | 3,890 |
| 2026 | 6,606 |
| 合计 | 12,964 |

复用 500 篇提取，预计新增 12,464 篇 API 调用；如结构校验失败可能有修复请求。
复用记录携带原文件哈希，原 500 篇完整封存包一并复制到本轮证据目录。
旧向量引用不沿用；按新样本顺序重新生成四套向量，避免行号错配。

流程和提示词沿用 500 篇实验：gpt-6-luna / medium，API 并发上限 **3**；
作者原始领域和关键词单独保存，仅标题和摘要输入 LLM。保留全部实体候选、原文位置及无效标记，
核心内容为研究问题／方法／研究对象，字段保留原文证据。

摘要与核心内容各保存 BGE-M3、Qwen3-Embedding-0.6B 一份向量，共 **51,856 条 1024 维向量**。
GPU 优先使用 4060 Ti，float32、原生 pooling、不加 query instruction；完整输入逐条检查长度，防止静默截断。
未新增候选词条 embedding 视图。原文定位有效率不代表语义准确率或检索收益。

- [实时报告及阶段 ETA](/data_big/iclr-s4/experiments/entity_core_third_gpt6luna_medium_dual_v1/REPORT.md)
- [进度页](/data_big/iclr-s4/experiments/entity_core_third_gpt6luna_medium_dual_v1/PROGRESS.md)
- [每 15 秒打印的简明进度日志](/data_big/iclr-s4/experiments/entity_core_third_gpt6luna_medium_dual_v1/runtime/progress.log)
- [API 请求、重试与运行日志](/data_big/iclr-s4/experiments/entity_core_third_gpt6luna_medium_dual_v1/runtime/run.log)
- [抽样清单与各层名额](/data_big/iclr-s4/experiments/entity_core_third_gpt6luna_medium_dual_v1/sample.json)
- [执行协议](/data_big/iclr-s4/experiments/entity_core_third_gpt6luna_medium_dual_v1/PROTOCOL.md)
- [提示词](/data_big/iclr-s4/experiments/entity_core_third_gpt6luna_medium_dual_v1/PROMPT.md)
- [文献依据](/data_big/iclr-s4/experiments/entity_core_third_gpt6luna_medium_dual_v1/LITERATURE.md)

后台服务：`iclr-s4-entity-core-third.service`。提取逐篇落盘，编码按 8 篇一批保存检查点，
失败采用有上限的重试；认证或模型端点拒绝时停止继续提交。
提取完成后自动执行双模型编码、证据校验和归档。脚本与依赖版本保存在本轮 `runtime/`。

2026-11-01 重启后从 6,851 个论文检查点恢复，原进度和 28 条失败记录已保存至 `evidence/resumes/`。
服务已安装为持久用户服务并启用自动启动；系统已启用 user linger，因此重启后也可恢复。
存在 `SEALED.json` 完成标记时跳过启动。服务文件副本保存在 `runtime/iclr-s4-entity-core-third.service`。

```bash
tail -f /data_big/iclr-s4/experiments/entity_core_third_gpt6luna_medium_dual_v1/runtime/progress.log
```

按上一轮速度初估提取约需 2–3 天，实时 ETA 以本轮实际请求耗时更新，仅覆盖当前阶段。
