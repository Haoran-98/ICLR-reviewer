# 本地部署与运行

版本：2026-11-12。三个主题页使用 Vite、同源 Node 代理与 Python 审稿任务服务。演示包支持“论文地图 → 历史 Skill → 案例回放 → 自填接口审稿”。下载入口、文件大小与完整 SHA-256 见 [演示资产](DEMO_ASSETS.md)。

## 1. 安装

环境：Linux、Python 3.11+、Node 20.19+ 或 22.12+、npm、Git。预留约 3 GiB 空间用于源码、依赖、下载与解压。

Ubuntu/Debian：

```bash
sudo apt-get update
sudo apt-get install -y git python3 python3-venv poppler-utils libreoffice-writer
# Node 按官方安装方式准备符合版本要求的版本。
node --version
python3 --version

git clone --single-branch --branch main https://github.com/Haoran-98/ICLR-reviewer.git
cd ICLR-reviewer
./scripts/install_website.sh
```

安装命令依次建立 `.venv`、安装 `requirements-web.txt`、执行 `npm ci`、下载演示资产，并将分词器缓存准备在数据目录中。下载校验清单随源码固定在 `docs/demo-assets.json`；安装器验证分段和完整压缩包 SHA-256，拒绝绝对路径、目录穿越、软链接、硬链接和重复文件，再校验解压文件清单。原始研究目录保持原样。

再次执行会校验已安装资产；已有资产版本不一致时选择新数据目录。已有 `web/public/generated` 时保留它，并要求使用新克隆目录，避免覆盖当前可视化数据。

离线资产安装：先从[下载页](DEMO_ASSETS.md)下载所有 `.partNN` 分段，再执行：

```bash
./scripts/install_website.sh --assets-dir /path/to/downloads
```

依赖仍需从 Python/npm 源安装，或由使用者准备自己的依赖镜像。也可分开运行各步骤：

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements-web.txt
npm --prefix web ci
.venv/bin/python scripts/install_demo_assets.py
```

## 2. 初始化账号与启动

```bash
.venv/bin/python scripts/init_web_account.py --username root
./scripts/run_website.sh
```

命令两次提示输入密码，输入不回显。配置以权限 0600 写到 `~/.config/iclr-reviewer/web-auth.json`，包含用户名、随机 salt 与 scrypt 密码哈希。已有配置时初始化命令退出；修改前自行备份并移走旧配置。

访问 **http://127.0.0.1:5174/**，输入自行设置的账号密码。三个主题页、静态资产与 API 共同受登录保护。前台终端按 Ctrl+C 停止服务；下次启动保留任务，运行中的任务标记为可重试。`ICLR_WEB_PORT` 可修改本机端口。

## 3. 走通演示

1. **论文探索 `/`：** 地图载入 12,964 篇论文；查看领域/主题筛选、录用率、评分分布与弦图。
2. **领域 Skill 库 `/reviewers.html`：** 浏览规则与来源，回放 5 篇历史试审。
3. **单篇审稿 `/review.html`：** 加载 MLRA 案例，查看已完成的规则组合、Review 和 concern 证据。导入案例保持只读。
4. **新审稿：** 选择随包 MLRA（ID 33089），或上传未参与规则提炼的完整领域内稿件。在页面输入自己的 Base URL、API Key、准确模型 ID，选择 Chat Completions 或 Responses，点击开始审稿。

运行界面展示领域/方法/任务/对象识别、逐条适用性与加载理由、历史来源、Review、修改优先级及原文定位。默认加载来源支持规则，最多 10 条、4,000 代理 token；完整输入超出 64,000 代理 token 的阶段预算时保留稿件并提示。

**地址和密钥仅供当前任务使用，不写入浏览器存储或任务文件。** 新任务使用页面提供的设置，不读取服务器默认模型认证文件。任务只记录模型、协议和接口地址哈希。服务重启或任务失败后重新填写原接口、模型和协议即可重试；更换模型时创建新任务。重试要求规则和代码版本保持一致；升级版本后创建新任务。

其他地图论文的题录与证据片段已包含在快照中；完整稿件由使用者上传，或从自己的数据库提供。重新生成语料、嵌入、规则与网站快照需要相应研究输入。运行演示与上传审稿使用公开包即可。

## 4. 路径配置

所有部署路径由环境变量读取，默认位于仓库 `.local-data`。安装和启动使用同一组变量：

```bash
export ICLR_DATA_DIR="$HOME/.local/share/iclr-reviewer"
./scripts/install_website.sh
.venv/bin/python scripts/init_web_account.py --username root
./scripts/run_website.sh
```

| 变量 | 默认值 | 用途 |
|---|---|---|
| `ICLR_DATA_DIR` | `<repo>/.local-data` | 便携数据根目录 |
| `ICLR_RELEASE_DIR` | `$ICLR_DATA_DIR/release` | 冻结规则及相对来源目录 |
| `ICLR_CASES_DIR` | `$ICLR_DATA_DIR/cases` | 只读案例、完整示例稿件与本地目录 |
| `ICLR_REVIEW_RUNS` | `$ICLR_DATA_DIR/runs` | 新任务与失败重试状态 |
| `ICLR_REVIEW_SEED` | `$ICLR_CASES_DIR/example` | 可选旧版组合种子目录 |
| `ICLR_PYTHON` | `<repo>/.venv/bin/python` | Node 启动任务使用的解释器 |
| `ICLR_WEB_AUTH_FILE` | `~/.config/iclr-reviewer/web-auth.json` | 服务器登录配置 |
| `ICLR_WEB_PORT` | `5174` | 本机启动端口 |
| `TIKTOKEN_CACHE_DIR` | `$ICLR_DATA_DIR/tokenizer-cache` | 安装时准备、运行时复用的分词器缓存 |
| `ICLR_ENTITY_ROOT` | `$ICLR_DATA_DIR/entity` | 可选封存实体/向量，用于重建快照 |
| `ICLR_PILOT_DIR` | `$ICLR_DATA_DIR/pilot` | 可选原始五篇试审，用于重新导出旧案例 |
| `ICLR_STORAGE_ROOT` | `$ICLR_DATA_DIR/research` | 历史研究脚本的大容量存储根；保留其下相对布局 |
| `ICLR_DATABASE_HOME` | `$ICLR_DATA_DIR/database` | 可选数据库运行目录 |
| `ICLR_REVIEWS_ROOT` | `$ICLR_DATA_DIR/iclr_reviews` | 自备原始论文/审稿语料 |
| `ICLR_OBJECT_STORE` | `$ICLR_DATA_DIR/objects` | 自备内容寻址全文 |
| `ICLR_DATABASE_STATE` | `$ICLR_DATABASE_HOME/state` | 数据导入/版本回填状态 |
| `ICLR_OPENREVIEW_TOKEN_FILE` | `$ICLR_REVIEWS_ROOT/fulltext/openreview.token` | 可选 OpenReview 会话文件 |
| `ICLR_DATABASE_URL` | 本机 55432、库 `iclr_reviewer`、当前系统用户 | 自备 PostgreSQL 连接 |

网站快照安装到 `$ICLR_DATA_DIR/website/generated`，由安装器链接到 `web/public/generated`。规则包内 `source_root` 使用相对路径；运行时基于规则目录解析。`source_identities.json` 覆盖所有 1,286 篇提炼来源，按 ID、forum、文件 SHA-256 与精确全文摘要排除重叠输入；加载时校验其冻结哈希。

历史研究脚本继续支持各自 `--root`、`--source`、`--auth` 等参数。其认证文件可由 `ICLR_AUTH_FILE` 指定。可选本地推理脚本通过 `ICLR_LLAMA_SERVER`、`ICLR_LLAMA_TOOLCHAIN`、`ICLR_QWEN_WEIGHTS`、`ICLR_LLAMA_PROJECT`、`ICLR_RESEARCH_PYTHON` 配置自备环境；网站远程审稿不依赖这些组件。

## 5. 文档提取、局域网与数据库

DOCX 使用标准库读取 XML；DOC 使用 LibreOffice；PDF 使用 `pdftotext`。DOCS 扩展名兼容实际 DOCX/DOC 内容。原文件上限 15 MiB，提取文本上限 1,500,000 UTF-8 字节。扫描件先 OCR；上传后检查公式和图表。图片视觉审查能力见 [FIGURE_REVIEW.md](FIGURE_REVIEW.md)。

局域网访问：

```bash
.venv/bin/python web/setup_lan.py --ip <SERVER_IP>
npm --prefix web run build
npm --prefix web run lan
```

5173 跳转到 HTTPS 8443；客户端信任本机生成的 CA。证书保存在忽略目录。单独执行 build 时也须已初始化账号；设置上述路径变量后，preview 同样提供审稿代理。已有用户服务的 `scripts/start_website.sh` 与 `scripts/stop_website.sh` 仅控制该服务，环境可用 `systemctl --user cat iclr-web-lan.service` 查看。

自备完整数据库与对象存储的安装、导入及版本回填见 [database/README.md](../database/README.md)。重建实体快照与领域库页面：

```bash
.venv/bin/python web/export_s4.py --root "$ICLR_ENTITY_ROOT"
.venv/bin/python web/export_reviewers.py --release "$ICLR_RELEASE_DIR" --pilot "$ICLR_PILOT_DIR"
```

重建 R 静态图使用 `web/r-environment.yml` 与 `web/render_reviews.R`。已发布快照包含评分图，直接展示无需安装 R。

## 6. Docker 与验证

```bash
docker build -f scripts/demo.Dockerfile -t iclr-reviewer-demo .
docker run --rm -it -p 127.0.0.1:5174:5174 iclr-reviewer-demo bash
# 容器内初始化自己的账号：
.venv/bin/python scripts/init_web_account.py --username root
# 容器需监听映射端口：
ICLR_PYTHON=/app/.venv/bin/python npm --prefix web run dev -- --host 0.0.0.0 --port 5174 --strictPort
```

示例容器删除后其中新任务及账号随之删除；持久部署使用卷保存 `ICLR_REVIEW_RUNS` 与 `ICLR_WEB_AUTH_FILE`。原生部署命令默认保存本机文件。验证使用独立目录与容器，无开发机资产挂载，详细记录见 [DEPLOYMENT_VERIFICATION.md](DEPLOYMENT_VERIFICATION.md)。

安装后可执行：

```bash
.venv/bin/python scripts/test_portable_assets.py
.venv/bin/python scripts/test_compose_manuscript_skills.py
.venv/bin/python web/test_review_api.py
node web/test_site_auth.mjs
npm --prefix web run build
```

## 7. 常见问题

| 现象 | 处理 |
|---|---|
| venv 无法建立 | 安装与 Python 版本匹配的 `python3-venv` |
| 地图/Skill 文件缺失 | 重新运行资产安装器；安装与启动使用相同 `ICLR_DATA_DIR` |
| 已有 generated 目录 | 保留现有数据，使用新克隆目录安装演示包 |
| 下载失败或哈希不匹配 | 重试下载，或使用下载页分段与 `--assets-dir`；安装器不会使用未通过校验的包 |
| 登录配置缺失 | 执行账号初始化；自定义位置同时设置 `ICLR_WEB_AUTH_FILE` |
| 地图选稿无全文 | 使用随包 MLRA，上传完整新稿，或配置自己的数据库 |
| 来源重叠 | 稿件参与过规则提炼，改用独立稿件；历史规则仍可浏览 |
| 提取失败 | 检查文件实际格式、转换工具、加密与扫描内容 |
| 模型调用失败 | 核对自填接口、模型、密钥及协议；失败状态保留后重试 |
| 旧任务配置不一致 | 填回原接口与模型，或新建任务 |
| API 启动失败 | 检查解释器和依赖；同一个任务目录只运行一个协调器 |
