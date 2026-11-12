# 科学实体候选与三字段核心内容：5 篇试验

使用 gpt-6-luna，reasoning.effort=medium，API 并发上限为 3。

实验产物位于 `/data_big/iclr-s4/experiments/entity_core5_gpt6luna_medium_v1/`：

- `REPORT.md`：逐篇原始标签、三个核心字段、实际 embedding 文本及全部候选。
- `QUALITY_REVIEW.md`：语义检查、泛化候选与已知局限。
- `PROMPT.md`、`LITERATURE.md`：完整提示词与经过核实的顶会研究依据。
- `results.json`：实体原文位置、类型、角色、核心内容及向量行号。
- `embeddings/abstract.npz`、`embeddings/core.npz`：两套各 5 条 1024 维向量。
- `progress.json`、`runtime/run.log`、`requests/`：进度、用量与完整请求响应。

标题与摘要用于科学术语和核心内容提取；作者领域、关键词独立保存，不发送给 LLM。所有模型候选均保留，包含背景和泛指记录。核心内容仅由研究问题、方法、研究对象三个字段构成。摘要原文与核心文本分别使用现有固定版本 BGE-M3 在 CPU 上编码。

提示词改编自 SciERC、SciREX 的科学实体设计，以及 GoLLIE、UniversalNER 的指南和指令抽取思路。

执行脚本：`scripts/s4_entity_core5.py`。无 API 调用的检查：使用 S4 Python 环境执行 `scripts/test_s4_entity_core5.py`。

## 决策与证据封存

[决策留痕](DECISIONS.md) 记录用户确认的方案、文献依据、实际结果与适用范围。

- [审计记录](/data_big/iclr-s4/experiments/entity_core5_gpt6luna_medium_v1/AUDIT_TRAIL.md)
- [逐项核验结果](/data_big/iclr-s4/experiments/entity_core5_gpt6luna_medium_v1/AUDIT_CHECKS.json)
- [文件哈希清单](/data_big/iclr-s4/experiments/entity_core5_gpt6luna_medium_v1/AUDIT_MANIFEST.json)
- [封存包](/data_big/iclr-s4/archives/entity_core5_gpt6luna_medium_v1-20261029T183205+0800.tar.gz)
- [封存包 SHA-256](/data_big/iclr-s4/archives/entity_core5_gpt6luna_medium_v1-20261029T183205+0800.tar.gz.sha256)

2026-10-29 封存 66 个文件，约 2.1 MB。包含原始输入来源、文献 PDF／正式会议记录、提示词、执行代码、API 请求响应、全部候选、核心字段、两套向量、质量检查及逐文件哈希。大型模型资产保存固定版本引用和逐文件哈希。
