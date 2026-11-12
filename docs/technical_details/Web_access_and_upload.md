# 网站登录与文档上传

2026-11-09。保留论文探索、独立审稿页和 Skill 库的布局与审稿流程，增加统一登录验证和 Word/PDF 文本提取。

## 接入方式

现有 Vite dev / preview 服务使用服务器端 HTTP Basic 验证，生产入口沿用 HTTPS。浏览器输入账号后即可访问全部页面及同源 API，静态 JSON 和图片同样经过验证。HTTP 5173 入口继续跳转 HTTPS 8443。使用浏览器自带登录框，沿用单管理员账号，避免引入独立账户数据库和会话服务。

`web/site-auth.js` 必须位于审稿代理和静态服务之前。凭据错误返回 401；缺少或损坏的登录配置阻止服务启动。配置文件默认 `~/.config/iclr-reviewer/web-auth.json`，可用 `ICLR_WEB_AUTH_FILE` 指定其他服务器路径。文件包含 `username`、随机十六进制字符串 `salt`、`password_hash` 三个字段。校验值为 Node `scryptSync(password, salt, 64)` 的十六进制输出；文件权限设为 0600。盐按字符串传入，不进行十六进制解码。源码和客户端资源不保存实际密码。

## 文件提取

两个上传入口共用 `web/manuscript-upload.js`。TXT / Markdown / LaTeX 继续在浏览器本地读取；Word / PDF 使用同源 POST `/api/review/extract`，发送文件名和 Base64 内容。该接口同时经过网站登录、同源检查和本机代理令牌验证。

`web/manuscript_upload.py` 接收最多 15 MiB 原文件；输出文本最多 1,500,000 UTF-8 字节。DOCX 读取 ZIP 内 `word/document.xml` 的段落、制表和换行，单个正文 XML 限制 10 MiB；DOCS 接受 DOCX 或 DOC 内容。DOC 使用独立临时目录和 LibreOffice 配置转换；PDF 使用 `pdftotext -layout`。两个转换工具已安装在现有服务器，执行超时 60 秒。转换后临时目录清理，不使用模型，不创建审稿任务。

提取结果先展示在文本框内，用户检查或修改后再点击“开始审稿”。上传失败清空旧文本并展示具体原因，避免误审上一份文件。空文件、错误格式、损坏或加密文档、超限和转换超时均返回错误。无可提取文本的扫描件提示先做 OCR；图表、图中文字及复杂公式需要核对提取结果。已有完整文本和新稿的最低长度校验继续生效。

## 验证

- `node web/test_site_auth.mjs`：页面、静态数据与 API 验证，错误密码、客户端隔离、缺少配置时拒绝启动。
- `python3 web/test_manuscript_upload.py`：真实 DOC / DOCX / DOCS / PDF 转换，中文、损坏、空文件、文件与展开后 XML 限制、转换超时。
- `python3 web/test_review_api.py`：上传路由、后端令牌、提取不排队调用模型，以及原有任务持久化和重试。
- `npm run build`：现有三个主题页构建成功。
- `npm run access:smoke`：实际 HTTPS 实例的未登录与错误密码拒绝、四种格式上传、失败后的旧文本清理、Skill 页 Word 上传和 12,964 篇地图数据。凭据由 `ICLR_WEB_USERNAME` / `ICLR_WEB_PASSWORD` 环境变量提供。
- `npm run review:smoke`：已有真实案例回放、四个模型选项、来源追溯、正文证据、地图选稿和移动布局。

上述检查均已通过；浏览器测试没有触发真实模型调用。服务通过 `systemctl --user restart iclr-web-lan.service` 更新。
