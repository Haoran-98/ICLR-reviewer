# TaxoAdapt：100 篇 GPT-6 Luna API 实验

2026-10-29 按用户要求暂停本地 GPU 实验，改用 `gpt-6-luna` Responses API，思考强度 `low`，最大并发 3。只运行 TaxoAdapt 及其一级标签、深度和广度评价。

从原 500 篇中固定抽取 100 篇，覆盖 23 个真实一级领域，每领域 4–5 篇；2024/2025/2026 年分别 33/33/34 篇。作者标签仅用于采样和评价，生成阶段只有标题、摘要及生成主题。

实验根目录：`/data_big/iclr-s4/experiments/taxoadapt100_gpt6luna_low_v1`。

- `PROGRESS.md`：每 15 秒及请求完成时更新，包含当前批次进度、阶段预计完成时间、实时/峰值并发和 token 用量。
- `progress.json`：机器可读进度与最终运行状态。
- `runtime/run.log`：逐请求开始、结束、耗时、用量、失败及方法阶段事件。
- `requests/`：脱敏请求、完整响应、逐次尝试和成功缓存。
- `REPORT.md`：完整流程结束后的一级标签准确率、深度和广度。
- `PROTOCOL.md`、`manifest.json`、`runtime/code_hashes.json`：实验设置、样本与源码溯源。

任务通过 `iclr-s4-taxoadapt100-luna.service` 持久运行，执行实验目录中的冻结代码；设置 `CUDA_VISIBLE_DEVICES` 为空。旧 Qwen 数据及请求缓存保留。

```bash
systemctl --user status iclr-s4-taxoadapt100-luna.service
tail -f /data_big/iclr-s4/experiments/taxoadapt100_gpt6luna_low_v1/runtime/run.log
```

API 密钥从现有认证文件读取，不写入实验产物。Responses JSON mode 配合 schema 提示及本地 Pydantic/jsonschema 验证；不发送不适用于该推理配置的 temperature 或 seed。真实响应必须确认 model=`gpt-6-luna`、reasoning.effort=`low`。
