# 作者领域引导的 ACM CCS 分类：5 篇试跑

模型为 `gpt-6-luna`，`reasoning.effort=medium`（用户要求的 mid），API 并发上限为 3。

- [结果与逐篇证据](/data_big/iclr-s4/experiments/acm5_gpt6luna_medium_v1/REPORT.md)
- [实时进度与本阶段预计完成时间](/data_big/iclr-s4/experiments/acm5_gpt6luna_medium_v1/PROGRESS.md)
- [原始输入及作者标签](/data_big/iclr-s4/experiments/acm5_gpt6luna_medium_v1/inputs.json)
- [分类结果及完整性校验](/data_big/iclr-s4/experiments/acm5_gpt6luna_medium_v1/results.json)
- [词表来源、概念与父子边](/data_big/iclr-s4/experiments/acm5_gpt6luna_medium_v1/taxonomy.json)
- [执行脚本](/home/yhr/WorkSpace/Codex_Program/ICLR-reviewer/scripts/s4_acm5_api.py)

内容依据为标题与摘要。作者原始一级领域先映射为 ACM 锚点，再沿官方父子关系细化；作者关键词不发送给分类模型，在分类后独立附加，原始领域也原样保留。分类只保存词表内概念，保留完整官方路径，不强行限制为三级。

这是固定词表分类的诊断试验，不是原版 TaxoAdapt 的开放分类树构建。5 篇来自上一轮诊断案例，覆盖 2024—2026 年；不据此估计总体准确率。作者一级领域已作为输入，不能再用于报告独立一级分类准确率。

ACM 官网下载返回 HTTP 403，因此冻结两个字节一致的公开 XML 镜像，并记录来源与 SHA-256。排除专有名词分支。此操作验证了镜像一致性，未验证其与 ACM 官网当前下载内容的实时一致性。
