# 本地部署与运行

适用版本：2026-11-12。现有系统为 Vite 多页面前端 + 同源审稿代理 + 本机 Python 任务服务；研究数据和模型调用都在服务器端。已有开发机可直接启停；新机器需要先准备外部资产。

## 1. 选择运行范围

| 范围 | 必需内容 | 可做什么 |
|---|---|---|
| 源码检查 | Python、Node、依赖 | 阅读方法，运行与数据无关的单元检查；不能自动展示全部研究结果 |
| 历史数据展示 | 登录配置 + `web/public/generated/` 完整快照 | 论文探索、Skill 库、本地词面预览、静态历史回放；不需要调用模型 |
| 已有单篇任务回放 | 上述内容 + 持久化任务目录与服务端依赖 | 恢复 Review 详情与原文定位；只读回放不付费 |
| 新上传稿件实时审稿 | 完整规则发布包及其来源依赖 + 已配置模型 + Python 环境 | 按完整新稿组合 Skill 并审稿 |
| 从数据库选稿、重建网站快照 | PostgreSQL/对象存储 + 封存实体向量 + 冻结库及历史试验 | 导出当前研究数据，按论文 ID 取完整稿件并审稿 |

GitHub 不携带数据库、完整稿件、冻结规则原件、模型响应或 522 MiB 网站快照。`raw/` 中的标题摘要不能替代它们。当前没有一键下载完整公开演示资产的安装器；完整数据分发与跨机路径迁移是后续事项。

## 2. 安装源码依赖

推荐 Linux、Python 3.11+（开发机 3.12）、Node 20.19+ 或 22.12+（开发机 24.20）。

```bash
git clone https://github.com/Haoran-98/ICLR-reviewer.git
cd ICLR-reviewer
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements-web.txt
npm --prefix web ci
```

`requirements-web.txt` 只安装网站导出和远程模型审稿需要的依赖，不安装本地大模型。GPU 实体编码实验另见 `requirements-s4.txt` 和 `requirements-s4-dkta.txt`；不要为展示页面默认安装全部实验运行时。

Word/PDF 提取需要系统工具。Ubuntu/Debian 可安装：

```bash
sudo apt-get update
sudo apt-get install -y poppler-utils libreoffice-writer
```

DOCX 使用 Python 标准库解压 XML；DOC 调用 LibreOffice，PDF 调用 `pdftotext`。DOCS 是兼容文件扩展名，内容须实际为 DOCX 或 DOC。纯文本可在浏览器读取。原文件上限 15 MiB，提取文本上限 1,500,000 UTF-8 字节；扫描件先做 OCR，提取后检查公式和图表信息。

## 3. 初始化自己的管理员账号

站点使用服务器端 HTTP Basic 验证，保护页面、静态数据和审稿 API。现有服务器的管理员名为 `root`；新部署自行设密码。配置缺失时服务拒绝启动。

在仓库根目录、交互终端执行以下命令。密码不会回显，也不会作为命令行参数保存：

```bash
python3 - <<'PY'
from pathlib import Path
import getpass, hashlib, json, os, secrets
path = Path.home() / '.config/iclr-reviewer/web-auth.json'
if path.exists():
    raise SystemExit('配置已存在；如需修改，请先备份后再明确替换。')
password = getpass.getpass('设置管理员密码: ')
if not password or password != getpass.getpass('再次输入: '):
    raise SystemExit('密码为空或两次不一致')
salt = secrets.token_hex(16)
record = dict(username='root', salt=salt, password_hash=hashlib.scrypt(
    password.encode(), salt=salt.encode(), n=16384, r=8, p=1,
    dklen=64, maxmem=64*1024*1024).hex())
path.parent.mkdir(parents=True, exist_ok=True)
fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
with os.fdopen(fd, 'w') as stream:
    json.dump(record, stream)
print('管理员配置已保存；密码不会写入项目文件。')
PY
```

字段是 `username`、字符串 `salt`、64 字节 scrypt 结果的十六进制 `password_hash`，与 Node `scryptSync(password, salt, 64)` 一致。可通过 `ICLR_WEB_AUTH_FILE` 指向其他配置文件；权限保持 0600。局域网使用下文 HTTPS 入口。

## 4. 准备研究资产

### 路径与依赖

当前开发机的数据资产使用以下路径，部署时按本机布局调整：

| 资产 | 默认位置/配置 |
|---|---|
| 原始论文、审稿及正文语料 | `/data_big/iclr_reviews`；导入脚本支持 `ICLR_REVIEWS_ROOT` |
| 内容寻址对象存储 | `/data_big/iclr-reviewer-store/objects`；`ICLR_OBJECT_STORE` |
| 数据库运行与状态 | `/data_big/iclr-reviewer-db`；建库脚本支持 `ICLR_DATABASE_HOME` |
| 数据库连接 | `ICLR_DATABASE_URL`，例如 `postgresql://用户名@127.0.0.1:55432/iclr_reviewer` |
| 封存实体/向量队列 | `/data_big/iclr-s4/experiments/entity_core_third_gpt6luna_medium_dual_v1` |
| 冻结领域规则 | `/data_big/iclr-review/releases/llm-area-v1` |
| 冻结库来源原型与恢复包 | 由 `PROVENANCE.json` 与规则库 `source_root` 引用；必须一并保留 |
| Skill 库页旧案例 | `/data_big/iclr-review/experiments/modular_skill100_automanual_ace_v1` |
| MLRA 已有组合 | `/data_big/iclr-review/experiments/manuscript_composition_mlra_v1` |
| Web 实时任务目录 | `/data_big/iclr-review/experiments/web_review_runs`；`ICLR_REVIEW_RUNS` 可覆盖 |
| 网站导出快照 | `web/public/generated/` |

目前 Web 的规则发布路径与已有组合种子仍有开发机默认常量，未提供统一 `ICLR_RELEASE_DIR` 配置。要完整移机，先按同样布局恢复资产；或逐项调整 `scripts/compose_manuscript_skills.py` 的 `RELEASE`、`web/review_api.py` 的 `SEED` 等常量，并保持冻结包及来源校验一致。数据库内保存的对象绝对路径也需同步迁移。CLI 导出/组合支持显式 `--root`、`--release` 等参数；仅设置 `ICLR_REVIEW_RUNS` 不会迁移冻结库和来源。

### 方式 A：恢复已有快照

从自己的备份或经授权的资产包恢复完整 `web/public/generated/`，包括 `sample.json`、`topics.json`、`domains.json`、论文/主题分块、评分 CSV/SVG、地图标签以及 `reviewers/` 索引/规则/回放分片。不要只复制首页 JSON。快照中的论文/审稿内容与访问权限须一起管理。

如需单篇任务回放，把整个任务目录恢复至 `ICLR_REVIEW_RUNS`，保留 `job.json` 与各次 attempt 下的组合、稿件、审稿和证据文件。只读回放不会重新审稿；不要改写任务模型身份或伪造成功状态。

### 方式 B：从自己的数据重建

数据库建库详情见 [database/README](../database/README.md)。项目自带无 root 的 PostgreSQL 16.10/pgvector 0.8.0 源码安装脚本，需要 `curl`、编译工具和对应构建依赖；它仅监听本机回环，适合当前单机研究部署。

```bash
# 路径示例，调用者根据磁盘布局调整：
export ICLR_DATABASE_HOME="$HOME/.local/share/iclr-reviewer-db"
export ICLR_REVIEWS_ROOT=/path/to/iclr_reviews
export ICLR_OBJECT_STORE=/path/to/iclr-objects
export ICLR_DATABASE_STATE=/path/to/iclr-state
bash database/bootstrap_postgres.sh
export ICLR_DATABASE_URL="postgresql://$USER@127.0.0.1:55432/iclr_reviewer"
python3 database/iclr_database.py all
```

源语料布局须符合已有导入器约定，只有题录时不会自动下载全文或构建全部研究产物。已有数据库备份可用 `pg_restore` 恢复；这不恢复对象存储和规则来源，需另行还原。历史 Edit 在线回填需要 OpenReview 认证，见数据库说明；不会因启动网站而自动执行。

准备好封存实体队列、向量、冻结库及其旧案例后，重新导出网站数据：

```bash
export ICLR_ENTITY_ROOT=/path/to/entity_core_third_gpt6luna_medium_dual_v1
export ICLR_RELEASE_PATH=/path/to/llm-area-v1
export ICLR_PILOT_PATH=/path/to/modular_skill100_automanual_ace_v1
OPENBLAS_NUM_THREADS=4 OMP_NUM_THREADS=4 \
  python3 web/export_s4.py --root "$ICLR_ENTITY_ROOT"
python3 web/export_reviewers.py --release "$ICLR_RELEASE_PATH" --pilot "$ICLR_PILOT_PATH"
python3 web/validate_s4.py
python3 web/validate_topics.py
```

这三个 `ICLR_*_PATH/ROOT` 变量用于本段 shell 示例的 CLI 参数传递。Web 后端使用各自列明的配置项。导出器读取封存文件、来源哈希和数据库，不调用 LLM。首次生成投影会执行 PCA/t-SNE，可能较慢。重跑实体提取和规则提炼会调用模型，与导出是不同任务，不要为启动展示站默认重跑。

### R/ggdist 静态图

若已有快照含评分图，可直接使用。重建时安装 R 与 `ggdist`、`ggplot2`、`svglite`、`jsonlite`，或使用已有 conda/micromamba：

```bash
micromamba create -y -p ./logs/web_visualization/runtime/r -f web/r-environment.yml
./logs/web_visualization/runtime/r/bin/Rscript \
  web/render_reviews.R web/public/generated/reviews.csv web/public/generated/reviews.svg
```

如使用系统 R，将上面的路径换为 `Rscript`。R 和前端共用论文级统计口径；刷新后重新构建。

## 5. 在页面填写自己的审稿接口

打开 `/review.html`，填写以下内容：

| 字段 | 输入要求 |
|---|---|
| Base URL | 自己的 OpenAI 兼容 HTTP(S) 服务地址，包含 API 前缀，不含末尾调用路径 |
| API Key | 自己的有效密钥，密码框输入 |
| 模型 ID | 该接口实际支持的准确 ID，不预置模型 |
| 接口格式 | Chat Completions（默认）或 Responses |

程序根据选择追加 `/chat/completions` 或 `/responses`。Responses 当前使用 medium reasoning 与 JSON 输出；Chat Completions 使用标准 messages、JSON 输出及非流式返回。实际服务须支持所选格式。兼容服务可能将模型别名解析为版本 ID，运行记录保留返回的模型身份。

**网站不读取 `~/auth` 或服务器默认模型设置来执行新审稿。** 这些文件仍可由历史研究 CLI 使用，不能作为 Web 新任务的凭据来源。

接口地址与密钥只在当前页面内存、任务内存和对应子进程环境中使用，不写入 localStorage/sessionStorage、任务清单、配置文件、请求日志或 Git。任务文件只保存模型、协议和地址哈希；提供者响应中回显的地址/密钥会脱敏。地址不能带内嵌账号、查询参数或片段，避免意外把凭据放进 URL。

成功提交后页面清空密钥。失败任务或服务重启后的中断任务仍保留原输入与成功阶段，重试时重新填写原 Base URL、模型、协议和有效密钥；可以更换已失效的密钥。地址/模型/协议不一致时拒绝复用旧任务，应另建新任务。旧版预设接口任务保留只读回放，重新审稿使用新的自填接口任务。

仓库仅提供字段名称及测试占位值，不发布实际模型接口地址与 API Key。不要把自己的输入写入截图、文档、共享脚本或提交文件。

## 6. 启动网站

### 本机开发

```bash
source .venv/bin/activate
export ICLR_PYTHON="$PWD/.venv/bin/python"
export ICLR_REVIEW_RUNS="$HOME/.local/share/iclr-reviewer/web-review-runs"
npm --prefix web run dev -- --port 5174 --strictPort
```

访问 `http://127.0.0.1:5174/`；三个入口是 `/`、`/review.html`、`/reviewers.html`。浏览器会要求账号密码。浏览地图不调用模型；在审稿页确认并点击“开始审稿”才创建真实模型任务。单目录任务串行，停止时在途记录保留。

### 局域网 HTTPS

```bash
python3 web/setup_lan.py --ip 192.168.1.100
npm --prefix web run build
npm --prefix web run lan
```

将示例 IP 换为可达的本机地址。入口 `http://服务器IP:5173/` 跳转至 `https://服务器IP:8443/`；不要使用 `http://服务器IP:8443/`。客户端信任 `web/public/iclr-lan-ca.crt` 后访问；证书私钥保留在本机忽略目录。当前实现固定 5173/8443，需确保端口空闲且网络可达。preview 通过 Node 与 Python 同源代理提供服务。

### 当前开发机已有服务

只在已安装 `iclr-web-lan.service` 的现有用户环境执行：

```bash
./scripts/start_website.sh
./scripts/stop_website.sh
systemctl --user status iclr-web-lan.service
journalctl --user -u iclr-web-lan.service -n 50
```

当前开发机入口为 `http://172.24.246.231:5173/`，仅在可路由的网络中可达。这些脚本用于启停已有的用户级服务；新机器先按前文安装。修改网页后先构建，再重启服务；确保该单元的环境使用正确 Python 和资产路径。

## 7. 运行检查

### 不调用模型的检查

```bash
node web/test_site_auth.mjs
python3 web/test_manuscript_upload.py
python3 web/test_review_api.py
python3 scripts/test_manuscript_review_models.py
python3 scripts/test_compose_manuscript_skills.py
node web/review-distributions-check.mjs
npm --prefix web run reviewers:check
npm --prefix web run build
```

依赖数据快照的统计检查须在数据准备后执行；DOC/PDF 测试依赖系统转换工具。

### 浏览器检查

```bash
cd web
npx playwright install chromium
```

对既有实例，在当前进程安全设置 `ICLR_WEB_USERNAME`、`ICLR_WEB_PASSWORD` 和 `ICLR_WEB_BASE_URL` 后，执行 `npm run review:smoke` / `reviewers:smoke` / `access:smoke`。不要把真实密码写进仓库、共享脚本或 shell 示例。

无 WebGPU 时可设置 `ICLR_WEB_FORCE_COMPAT=1` 运行 `npm run smoke`；支持 GPU 的机器使用默认 Atlas。自签证书按 Web README 的 CA/公钥验证配置，或在本机启动隔离的开发检查环境。`PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH` 可指定已有 Chromium，默认使用 Playwright 安装版本。

`review:smoke` 默认检查已有结果，不调用模型；显式设置 `ICLR_REVIEW_LIVE=1` 并私下提供 `ICLR_REVIEW_TEST_BASE_URL`、`ICLR_REVIEW_TEST_API_KEY`、`ICLR_REVIEW_TEST_MODEL_ID` 才做一次真实付费审稿。`ICLR_REVIEW_RETRY=<任务ID>` 会实际重试对应任务，需理解已有缓存和失败原因。结果存入忽略的 `web/artifacts/`。

## 8. 常见问题

| 现象 | 检查 |
|---|---|
| 启动时找不到登录配置 | 先完成第 3 节；不能用删除认证插件绕过配置 |
| 地图、Skill 索引 404 | 按第 4 节准备 `web/public/generated/` 数据快照 |
| 新任务找不到规则或来源 | 检查冻结库、`PROVENANCE.json` 依赖及开发机默认路径；仅复制规则 JSON 不够 |
| API 无法启动 | 检查 `ICLR_PYTHON`、Python 依赖、任务目录写权限、同目录是否已存在协调器 |
| DOC/PDF 提取失败 | 检查 LibreOffice/`pdftotext`、文件实际格式、加密/扫描件、15 MiB 限制 |
| 模型调用失败 | 检查页面自行输入的 Base URL、准确模型 ID、密钥，以及 Chat/Responses 格式 |
| 旧任务配置不匹配 | 恢复其原配置或新建任务，不能跨模型复用结果 |
| HTTPS 失败/空响应 | 区分 5173 HTTP 入口与 8443 HTTPS；检查 CA 信任、IP 与路由 |

数据库、对象存储、冻结库和原始稿件应分别备份；Git 只保存代码和公开说明，不能代替研究资产备份。
