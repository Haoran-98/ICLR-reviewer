# 发布内容筛选清单

整理日期：2026-11-12。先确定上传范围，再更新 README；本次整理不重跑模型提取。

## 保留上传

| 路径 | 内容及保留理由 |
|---|---|
| `web/` 源文件、锁文件和测试 | 论文探索、单篇审稿、领域 Skill 库三个主题页；数据导出、认证、文档提取、审稿服务和浏览器检查 |
| `database/`、`alembic.ini` | PostgreSQL/pgvector 建库、迁移、导入、版本回填和只读检索；不包含数据库实例 |
| `scripts/` | 论文理解、领域实体抽取、审稿经验提炼、冻结、按稿组合、单次审稿、恢复和测试 |
| `benchmarks/` | 已有实验协议、汇总和评测代码；开发集实验与后续正式评测明确区分 |
| `skills/`、`agents/` | 通用审稿角色设计，以及正文证据约束、模块化规则提炼的协议；不等同于 Web 已运行多审稿人编排 |
| `raw/` | 38,890 篇公开标题/摘要索引、分类题录和校验清单；保留旧版本的数据入口，不含完整论文及审稿历史 |
| `docs/technical_details/`、`docs/research/` | 可追溯的方法和实验记录。历史编号保留在研究文档中；当前状态以 `docs/STATUS.md` 为准 |
| `docs/images/screenshots/` | 本次实际网站截图；不使用生成式效果图替代运行截图 |
| README 与部署/方法/进度说明 | 最新项目入口、数据口径、论文来源、已完成及待完成工作 |
| `automation/`、`twin_smoke/` 源码和测试 | 历史小样本/定时汇总工具，保留为历史工具；不再用旧活动日志更新项目首页 |

## 仅保留本地，不上传

| 内容 | 原因与处理 |
|---|---|
| 实际模型 API 地址/密钥、`auth`、`.env*`、证书私钥、管理员配置 | 认证信息；部署说明仅给配置方法，不提供现网密码 |
| `.codex/`、`SESSION.md` | 私有会话及指向会话记录的符号链接 |
| `web/public/generated/` | 本地生成快照；脱敏版本以独立下载包发布，主分支保存清单与校验和 |
| `web/dist/`、`web/node_modules/`、`web/artifacts/` | 构建、依赖及浏览器测试运行产物 |
| `logs/`、`output/`、数据库状态及模型缓存 | 运行时、请求响应、PPT 与图片生成产物；保留本地，避免与可运行源码混杂 |
| `docs/reports/` | 课程作业、个人身份信息、汇报 PPT/DOCX 及重复素材；方法总结已由公开方法说明承接 |
| `twin_smoke/output/`、`automation/public/` | 旧小样本结果和自动活动快照，从最新 Git 树中移除，磁盘文件保留；旧提交仍可查阅 |
| `docs/images/promo/` | 早期概念宣传图，从最新 Git 树中移除；当前首页使用真实网站截图 |
| `/data_big/` 下数据库、完整稿件、冻结库、模型请求及审稿运行 | 原始研究资产保持外部存储；演示所需网站、规则来源与案例通过独立资产标签发布，参见 `DEMO_ASSETS.md` |

本地实验原件保留。约 75.7 MiB 的 `raw/` 为既有公开题录；演示资产使用独立分支与版本标签，源码主分支只保存安装器、下载清单与校验和。

## 整理后的文档入口

- `../README.md`：英文项目首页，串联“历史论文探索 → 经验规则 → 新稿审查 → 原文依据”。
- `../README.zh-CN.md`：完整中文项目说明，与英文首页同步维护。
- `METHODS.md`：分模块方法、论文出处、采用程度和证据边界。
- `STATUS.md`：本次只读核查数据、完成进度和后续验收条件。
- `DEPLOYMENT.md`：依赖、外部数据、账号配置、模型配置、本地与局域网运行。
- `ICLR_REVIEWER_MASTER_PLAN.md` 和旧阶段说明：保留历史设计，并添加当前状态入口，避免把历史计划误读为现状。

## 发布检查

审稿接口由使用者在页面自行填写，公开内容不提供实际模型 API 地址与密钥。

上传前检查 Git 暂存区：确认无账号、私有会话、论文全文、原始模型响应或课程身份资料；检查截图、相对链接、前端构建和现有无付费调用的验证。最终文件数与体积记录在发布核查报告中。

## 可移植资产发布

`docs/demo-assets.json` 固定三份演示包的分段与完整 SHA-256；`scripts/install_demo_assets.py` 下载、安全解压并逐文件核验。`scripts/deployment_paths.py` 统一配置路径。`scripts/install_website.sh`、`scripts/init_web_account.py`、`scripts/run_website.sh` 提供安装到启动命令。下载入口见 [DEMO_ASSETS.md](DEMO_ASSETS.md)，实测见 [DEPLOYMENT_VERIFICATION.md](DEPLOYMENT_VERIFICATION.md)。
