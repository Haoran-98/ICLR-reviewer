# S4：500 篇科学实体候选、核心内容与双模型向量

实验目录：`/data_big/iclr-s4/experiments/entity_core500_gpt6luna_medium_dual_v1`。

- [提取及最终编码进度（含阶段 ETA）](/data_big/iclr-s4/experiments/entity_core500_gpt6luna_medium_dual_v1/PROGRESS.md)
- [并行进行的原始摘要向量进度](/data_big/iclr-s4/experiments/entity_core500_gpt6luna_medium_dual_v1/embedding-preparation.json)
- [运行日志](/data_big/iclr-s4/experiments/entity_core500_gpt6luna_medium_dual_v1/runtime/run.log)
- [每 15 秒打印的简明进度日志](/data_big/iclr-s4/experiments/entity_core500_gpt6luna_medium_dual_v1/runtime/progress.log)
- [实验协议](/data_big/iclr-s4/experiments/entity_core500_gpt6luna_medium_dual_v1/PROTOCOL.md)
- [提示词](/data_big/iclr-s4/experiments/entity_core500_gpt6luna_medium_dual_v1/PROMPT.md)
- [文献依据](/data_big/iclr-s4/experiments/entity_core500_gpt6luna_medium_dual_v1/LITERATURE.md)
- [完整报告（完成后）](/data_big/iclr-s4/experiments/entity_core500_gpt6luna_medium_dual_v1/REPORT.md)
- [双模型向量元数据](/data_big/iclr-s4/experiments/entity_core500_gpt6luna_medium_dual_v1/embeddings/metadata.json)
- [最终校验与归档结果（完成后）](/data_big/iclr-s4/experiments/entity_core500_gpt6luna_medium_dual_v1/runtime/finalize.log)

固定原有 500 篇：2024/2025/2026 年各 167/167/166 篇，23 个统一领域（27 个作者原始领域名称）。
提取使用 gpt-6-luna / medium，API 并发最多 3。输入相同且提示词未变的 5 篇已验证试跑结果复用，保留原请求证据。

每篇保存作者原始领域和关键词、标题摘要的科学实体候选及来源位置、研究问题／方法／研究对象及原文证据。
作者标签不输入 LLM。实体保留背景和泛化候选；原文定位无效的候选也保留并标记，不静默删除。

当前需要 embedding 的视图为原始摘要和三字段核心内容。每个视图都使用 BAAI/bge-m3 和 Qwen/Qwen3-Embedding-0.6B，
共 2,000 条 1024 维归一化向量。实体候选本身先保存文本及证据，未新增词条向量视图。

已完成的 1,000 条摘要向量保留 CPU 结果；后续两个模型的核心向量与新增视图优先使用 4060 Ti，以 float32 执行，各自使用原生 CLS / last-token pooling；输入完整文本，不添加检索 query instruction。
每条先检查 token 数，上限 8192，超限报错，防止静默截断。5 篇试验只复用提取结果，向量按本轮配置重新生成。
新增任何向量视图时，同一编码入口强制同时保存两个模型版本。

提取逐篇检查点，编码每 8 篇检查点，独立于对话在 systemd 用户服务中运行。原始摘要向量与提取并行；
提取完成后自动补齐核心内容向量、校验 500 篇与四套向量、封存证据及 SHA256 归档。

这些是模型提取结果。原文可定位比例不代表语义准确率；本轮未用人工金标准验证召回率或匹配收益。

## 服务与恢复

`iclr-s4-entity-core500-extract.service` 执行提取；`iclr-s4-entity-core500-abstract.service` 预计算摘要向量；
`iclr-s4-entity-core500-pipeline.service` 等待前两者结束，随后执行编码和归档。没有启动本地 LLM 服务；GPU 用于 embedding。

终端实时查看：

```bash
tail -f /data_big/iclr-s4/experiments/entity_core500_gpt6luna_medium_dual_v1/runtime/progress.log
```

最终阶段使用 `runtime/scripts-final/` 固定脚本；原始提取脚本在 `runtime/scripts/`。
断点恢复使用相同实验目录和相同脚本，不更换模型或提示词。
