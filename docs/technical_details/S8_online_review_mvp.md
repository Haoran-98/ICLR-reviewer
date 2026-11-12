# S8 在线 Review MVP

状态：`规划中，尚未实现`

## 计划流程

```text
用户上传 PDF/Markdown/LaTeX + 显式领域
-> TTL 临时存储
-> text-first 解析
-> S3 结构化理解
-> 显式/隐式领域分布
-> 2:1 细分/邻近领域 Twin + 通用 Reviewer
-> 各 Reviewer 独立审稿
-> concern 触发局部图/表/公式解析
-> AC 证据化汇总
-> ICLR Review、评分、置信度、理由和修改优先级
-> 到期清理临时数据
```

## 证据和隔离要求

- 用户文件不自动进入历史训练集；
- Reviewer 在初始评审前不共享结论；
- 每个重要 concern 回指论文位置；
- 视觉/OCR 只处理被 concern 指向的页或对象；
- 领域匹配失败时使用通用组并降低置信度。

## Gate

- 端到端可重复；
- 证据定位正确；
- 单篇成本与延迟满足预算；
- 临时文件和缓存可按 TTL 清理；
- 不因已有公共 review skill 而把数据库驱动的在线 MVP 视为已完成。
