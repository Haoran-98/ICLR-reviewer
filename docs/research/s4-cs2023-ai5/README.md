# CS2023 AI Body of Knowledge：5 篇诊断试验

使用 [CS2023 官方最终报告](https://csed.acm.org/final-report/) 中的 AI 知识领域，模型为 `gpt-6-luna`，`reasoning.effort=medium`，并发上限为 3。

- [5 篇实际分类与原文证据](/data_big/iclr-s4/experiments/cs2023_ai5_gpt6luna_medium_v1/REPORT.md)
- [逐篇质量检查](/data_big/iclr-s4/experiments/cs2023_ai5_gpt6luna_medium_v1/QUALITY_REVIEW.md)
- [进度及用量](/data_big/iclr-s4/experiments/cs2023_ai5_gpt6luna_medium_v1/PROGRESS.md)
- [分类结果 JSON](/data_big/iclr-s4/experiments/cs2023_ai5_gpt6luna_medium_v1/results.json)
- [词表及来源](/data_big/iclr-s4/experiments/cs2023_ai5_gpt6luna_medium_v1/taxonomy.json)
- [执行脚本](/home/yhr/WorkSpace/Codex_Program/ICLR-reviewer/scripts/s4_cs2023_ai5.py)

内容证据仅为标题与摘要。原始作者领域先映射为候选知识单元，再依据论文内容细化；关键词在分类后独立附加。官方层次为 AI → 知识单元 → 编号主题 → 子条目；课程覆盖属性不增加主题层级。保留原文限定语，不生成词表外的主题。

AI-ML 等单元代码来自原文，斜杠后的数字和字母是本地根据原文编号生成的来源定位符。5 篇是先前发现问题的诊断案例，不能估计总体准确率；作者领域已经作为输入，也不报告独立一级准确率。

验证命令：`/data_big/iclr-s4/runtime-dkta/bin/python scripts/test_s4_cs2023_ai5.py`。该检查不调用 API。
