# 仓库整理与发布核查

日期：2026-11-12。本轮任务为选择上传内容、更新项目说明与同步 GitHub；未重跑论文提炼或付费审稿。

## 内容整理

- 保留数据库、论文理解、领域/实体实验、Skill 提炼/冻结/组合、审稿 Web 的源码、协议和测试。
- 重写中文项目首页，保留中文旧链接入口；新增方法、状态、部署及上传筛选清单。
- 更新历史路线图和技术索引，明确历史阶段状态与当前工程事实的区别。
- 从最新 Git 树移除旧自动活动快照、旧小样本生成结果和概念宣传图；磁盘原件保留，历史提交可查阅。
- 忽略会话、凭据、数据库/模型运行时、生成网站数据、课程作业、PPT 和原始请求响应。
- 停用现有服务器上本项目旧 weekly/monthly README 发布 cron；其他项目任务及版本回填任务保留。本地 crontab 备份在忽略的 `logs/` 中。
- 更新早期 automation 测试，删除对旧首页活动标记块的过时断言，固定“近期 Agent”测试夹具为当前日期，保留汇总、渲染及公开字段边界检查。

## 无模型调用的验证

| 检查 | 结果 |
|---|---|
| `node web/test_site_auth.mjs` | 通过：页面、静态资源、API 认证，缺配置拒绝启动 |
| `python3 web/test_manuscript_upload.py` | 通过：真实 DOC/DOCX/DOCS/PDF、Unicode、损坏/空/超限文件及转换超时 |
| `python3 web/test_review_api.py` | 通过：回环令牌、输入、持久化、队列、重试、路径边界和证据隔离 |
| `python3 scripts/test_manuscript_review_models.py` | 通过：三协议、模型身份、缓存身份及密钥隔离 |
| `python3 scripts/test_compose_manuscript_skills.py` | 通过：完整稿件、逐规则判断、来源排除、预算、引文核验与恢复 |
| `node web/review-distributions-check.mjs` | 通过：12,964 篇论文的 JS/R 统计一致，缺失/并列/单评分边界 |
| `npm --prefix web run reviewers:check` | 通过：词边界、标点、候选隔离、范围与空输入 |
| `npm --prefix web run build` | 通过：三个 HTML 入口；Atlas 渲染包仍有较大 chunk 提示 |
| `python3 automation/test_manage.py` | 通过：历史汇总工具、角色渲染与公开字段边界，3 项测试 |
| `node review-smoke.mjs`，在 `web/` | 通过：回放既有真实任务，模型选择传递、来源、精确证据、地图跳转及窄屏；`real_run=false` |
| `node reviewers-smoke.mjs`，在 `web/` | 通过：7,795 模块、5 个旧版回放、8 个 concern，候选默认排除，正文引文可回查 |
| `node access-upload-smoke.mjs`，在 `web/` | 通过：认证、四种文档上传、无效/超限拒绝、旧文本清空；模型调用 0 |

浏览器检查使用随机临时账号、隔离任务目录和现有已完成案例，未修改线上管理员配置，未点击真实审稿或重试入口。实际页面截图共 7 张，地图走 Canvas 兼容模式，浏览器页面错误为 0。

核心文档的 115 个相对链接已检查，目标均存在于待发布源码树或其目录中。暂存区敏感内容筛查未发现凭据字面量、会话、私钥、个人课程学号或符号链接；本地研究资产仍不进入 Git。此项是本次已选文件检查，不代表对全部历史 Git 提交做过秘密扫描。

数据库聚合只读，结果另存 [database-counts.json](database-counts.json)。论文元数据核验见 [reference-audit.json](reference-audit.json)：OpenReview API 对 AutoManual/ACE 返回 403，HTML 无可核验元数据，此限制在方法文档中保留。

本轮没有正式审稿质量评测、人工语义准确性评测或新的模型接口联调。完整部署仍需外部数据与冻结来源包，步骤和路径限制已记录在 [部署说明](../../DEPLOYMENT.md)。
