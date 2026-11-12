# S4 v4：200 篇实验启动记录

观测时间：2026-10-16 16:28:56（北京时间）。版本：`taxonomy_llm4_200_v1`。
本报告记录启动时点的配置和运行状态。最新状态以外部产物目录中的运行日志为准。

## 当前状态

200 篇原始 metadata/Markdown 已冻结，全部标记为开发数据。六板块编码完成，
保存 1,685 个 chunk、六板块向量和缺失掩码。四模型均已通过实际推理验证。

| 模型 | auth 并发上限 | 已完成三级生成的 pilot 论文 |
|---|---:|---:|
| DeepSeek Flash | 50 | 10/10 |
| Kimi K2.6 | 1（auth 未配置时的默认值） | 3/10 |
| gpt-6-luna | 4 | 10/10 |
| 本地 Qwen3.5-9B Q8_0 | 1 | 10/10 |

Kimi 第 4 篇已开始。四路 pilot 都完成后才继续同批的余下 190 篇。
`s4-llm4-200.service` 和等待后续处理的 `s4-llm4-fusion.service` 均为 active。
本地 Qwen 使用独立服务 `s4-qwen35-9b-q8.service`。S3 PID 3510518 保持运行。

## 已处理的启动问题

- OpenAI 返回过 HTTP 429；保留原始诊断，新增 provider 级冷却并尊重 Retry-After。
- Qwen 偶尔把 L3 挂回 L1 或超过每父三候选；这些是语义失败，应剪枝并留证，
  不应重复原请求直到耗尽预算。已有 HTTP 200 响应经过本地重验，无新增请求。
- Kimi K2.6 默认思考导致首轮根节点生成耗时约 259 秒；按官方文档关闭思考，
  后续已有约 23–60 秒的成功生成。初期响应仍保存，不伪装成同一推理配置。

初次请求后最多 5 次重试，尝试数跨重启累计，不清空失败历史。
没有人工审核，也未把某个模型的判断当成独立 gold。

## 验证与清理

32 项测试全部通过，包括章节原文位置、缺失/弃权、父链、重试预算、特征自拷贝防护、
合成 DS 可靠性恢复、Crowd Layer 训练、四种 repair 消融及临时数据库落库幂等。

验证 200 份新 raw snapshot 后，按用户授权删除三个旧 smoke 根目录和两份旧报告，
删除旧实验版本及其 370 条 assignment、200 条 embedding。
原始论文、S3、模型和环境保留，官方领域 assignment 仍为 38,890 条。
旧实验输出未保留恢复副本；原200 ID与原始输入用于复现新版实验。

## 后续自动流程

完成四模型生成后，继续 canonical 对齐、同义/层级验证、四模型显式交叉投票、
DS/static/conditional Crowd Layer、5 folds × 5 seeds、四组 embedding 消融，
再修复、父链闭包、实验落库和报告。related-work 输入消融会对同批200篇重新生成。
细粒度 gold 待补充，后验按开发指标记录；概率校准、生产冻结与质量验收另行开展。

产物根目录：`/data_big/iclr-s4/experiments/taxonomy_llm4_200_v1`。
主要文件：`run.log`、`fusion.log`、`execution.json`、`postprocess_execution.json`、
`pilot_summary.json`（四路 pilot 完成后产生）、`attempts/` 和后续 `report.md`。

完整设计：[S4_plan.md](../../docs/technical_details/S4_plan.md)。
