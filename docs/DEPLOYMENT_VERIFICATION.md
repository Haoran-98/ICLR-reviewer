# 干净环境部署验证

日期：2026-11-12。资产版本：`demo-2026-11-12-v1`；资产提交：`08f0c4754c24e7cbc5cf217029ed2245af379548`。

## 环境与安装

Debian 12 容器，Node 22.23.5、Python 3.11.2、Vite 7.3.7。使用 `scripts/demo.Dockerfile`，通过公开下载地址获取三份包并逐层核验。容器挂载数为 0，内部不存在开发机研究目录或服务器模型认证文件。浏览器从宿主机访问容器的回环端口；模型连接由浏览器表单传入。

账号通过 `scripts/init_web_account.py --username portable-check` 初始化，密码临时生成，权限 0600。账户文件、接口地址、密钥与原始模型响应均不随验证记录发布。

## 已完成检查

| 环节 | 结果 |
|---|---|
| 资产安装 | 三份公开包下载、分段/整包 SHA-256、解压文件清单校验通过 |
| 来源可移植性 | 全部 1,286 篇来源身份与 1,851 条来源支持规则的两篇配对证据可读取 |
| 来源排除 | ID、forum、文件 SHA-256、精确全文摘要重叠均拒绝；本地 MLRA 目录取稿无需数据库 |
| 解压边界 | 目录穿越、绝对路径、软/硬链接、索引篡改均拒绝 |
| 地图 | 12,964 篇论文，Canvas 兼容模式完成加载 |
| Skill 库 | 7,795 个模块可浏览，本地匹配默认排除候选规则 |
| 历史回放 | 5 篇、8 条 concern，原文引文与来源跳转核验通过 |
| 单篇案例 | 完成态 MLRA 的 Review、3 条规则与正文依据可回放 |
| 登录 | 页面、静态数据和 API 均拒绝匿名或错误密码 |
| 文档上传 | DOC/DOCX/DOCS/PDF 实测提取；损坏与超限输入被拒绝 |
| 模拟兼容接口 | 浏览器上传 88,275 字符全文，自填连接后完成识别、组合、Review 与证据导航 |
| 失败恢复 | 模拟审稿阶段失败后刷新页面并重试成功；profile/applicability 各 1 次，review 2 次，成功组合阶段复用 |
| 预算与凭据 | 模拟任务加载 2 条规则、974 代理 token；逐条适用性、历史来源、引用偏移通过；页面刷新后连接字段为空 |
| 构建与回归 | 容器内 API 检查和前端构建通过；认证、上传、规则匹配、统计口径与相关 Python 检查通过 |

模拟接口返回确定性测试内容，用于检查传输、状态、重试及证据处理。它的评分和 concern 是合成数据。

## 真实模型运行

真实弱模型已通过浏览器填写接口并发起请求，提供者返回 HTTP 200。原始稿件包含 OCR 断词与数学符号；四次 profile 返回中出现引文改写或段落定位错误，均被严格核验拒绝，任务与失败响应保留。这验证了失败状态与重试入口，也记录了该模型处理本稿引用的实际问题。

随后使用同一接口配置的 **gpt-6.1-sol** 完成一次真实新审稿：

- 全文 88,275 字符，24 条候选均有适用性判断；加载 7 条规则、3,748 代理 token，在 10 条/4,000 token 预算内。
- 输出 3 条 concern，合计 6 组证据引文与全文字符偏移逐一核验通过。
- 真实模型调用完成 3 次，任务第 1 次执行完成；浏览器全程约 187 秒，页面错误为 0。
- 刷新页面后完成态及结果仍可读取，接口字段为空；运行文件未发现使用的接口地址或密钥。

可复查的脱敏计数与规则 ID 见 [portable-deployment.json](verification/portable-deployment.json)。弱模型失败记录与强模型完成结果分别报告。

## 复查命令

```bash
.venv/bin/python scripts/test_portable_assets.py
.venv/bin/python scripts/test_compose_manuscript_skills.py
.venv/bin/python web/test_review_api.py
node web/test_site_auth.mjs
npm --prefix web run build
```

浏览器回归使用 `ICLR_WEB_BASE_URL`、`ICLR_WEB_USERNAME`、`ICLR_WEB_PASSWORD` 与已安装 Chromium；在 `web` 目录执行 `npm run portable:smoke`、`npm run reviewers:smoke`、`npm run access:smoke`、`npm run review:smoke`。`portable:smoke` 需要被测服务与模拟接口可以通过同一回环网络通信，容器验证采用 host 网络。

真实调用单独设置 `ICLR_REVIEW_LIVE=1`，私下提供 `ICLR_REVIEW_TEST_BASE_URL`、`ICLR_REVIEW_TEST_API_KEY`、`ICLR_REVIEW_TEST_MODEL_ID`、`ICLR_REVIEW_TEST_PROTOCOL`；不把值写入命令示例或报告。`ICLR_REVIEW_RETRY` 可指定已有失败任务，使用原连接与模型继续验证。

部署验收覆盖工程闭环；审稿质量与规则增益仍按独立研究评测计划验收。
