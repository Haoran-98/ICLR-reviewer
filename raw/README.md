# ICLR 主会题目与摘要目录

本目录按年份和主会主题展示 ICLR 2024-2026 论文的题目与摘要，Workshop 已排除。

| 年份 | 主题目录 | 机器可读索引 |
|---|---|---|
| 2024 | [按主题浏览](2024/README.md) | [`papers.jsonl.gz`](2024/papers.jsonl.gz) |
| 2025 | [按主题浏览](2025/README.md) | [`papers.jsonl.gz`](2025/papers.jsonl.gz) |
| 2026 | [按主题浏览](2026/README.md) | [`papers.jsonl.gz`](2026/papers.jsonl.gz) |

机器可读记录只包含：年份、主题、题目、摘要、关键词、OpenReview ID 和公开页面链接。不包含论文 PDF、作者、review、rebuttal 或 decision。

[`manifest.json`](manifest.json) 提供每年论文数、主题数、索引体积和 SHA-256。重新生成：

```bash
python twin_smoke/export_public_raw.py \
  --input /path/to/iclr_reviews \
  --output raw
```

数据来自公开 OpenReview 页面。本仓库没有为第三方文本重新授予许可；使用者应遵守 OpenReview 条款、原作者权利和适用的研究伦理要求。
