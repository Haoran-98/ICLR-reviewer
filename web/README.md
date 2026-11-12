# ICLR Web：论文探索与单篇审稿

> 新环境先阅读 [完整部署说明](../docs/DEPLOYMENT.md)：Git 不包含生成数据、冻结库及其来源资产；也须先初始化自己的管理员配置。当前工程进度见 [STATUS](../docs/STATUS.md)。

站点分为三个独立主题页：**论文探索** `/`、**单篇审稿** `/review.html`、**领域 Skill 库** `/reviewers.html`。地图保留原有图表、布局和筛选，只增加主题导航及论文详情中的“进入单篇审稿”链接。

[单篇审稿](http://172.24.246.231:5173/review.html)支持地图选稿、搜索论文、上传 Word（DOC / DOCX / DOCS）、PDF、Markdown/TXT/LaTeX 完整稿件，展示领域识别、Skill 加载理由与历史来源、Review 与修改优先级，并可逐条定位原文。API 地址和密钥由使用者在页面自行填写；点击“开始审稿”才提交真实任务。已有 MLRA 案例可直接查看并继续审稿。运行记录和失败响应持久保存，重试复用成功阶段。完整说明见 [单篇审稿接入记录](../docs/technical_details/Web_single_paper_review.md)。

## 登录与文档上传（2026-11-09）

访问网站时，浏览器会要求输入管理员用户名和密码。三个主题页、静态论文数据和审稿 API 均经过服务器验证；管理员账号为 `root`。密码校验配置保存在服务器 `~/.config/iclr-reviewer/web-auth.json`（权限 0600），不进入源码、构建产物或浏览器。新环境须先配置此文件；缺失时服务会拒绝启动。具体配置与验证见 [访问控制与上传说明](../docs/technical_details/Web_access_and_upload.md)。

单篇审稿页和 Skill 匹配页均支持上述上传格式：文件最多 15 MB，提取后的文本最多 1.5 MB。DOCX/DOCS 使用本机解析，DOC 使用 LibreOffice，PDF 使用 `pdftotext`；DOCS 兼容实际内容为 DOCX/DOC 的文件。提取结果显示在文本框内供检查，文件提取不触发模型调用。扫描版 PDF 或图片文档需先进行 OCR，图表需单独核对。纯文本文件仍在浏览器本地读取。

相关检查：`node web/test_site_auth.mjs`、`python3 web/test_manuscript_upload.py`、`python3 web/test_review_api.py`。浏览器测试通过环境变量 `ICLR_WEB_USERNAME`、`ICLR_WEB_PASSWORD` 提供凭据；在 `web/` 执行 `npm run access:smoke` 可验证已运行实例的登录和四种文档上传，需同时设置 `ICLR_WEB_BASE_URL`。测试不调用模型。

[领域 Skill 库](http://172.24.246.231:5173/reviewers.html)：浏览冻结的 7,795 个有效模块、输入文本预览匹配、回放 5 篇历史试审的 concern 与正文证据。范围与复现见 [工作台说明](../docs/technical_details/Web_review_workbench.md)。更新该数据使用 `python3 web/export_reviewers.py`，再执行 `npm run build`；该页匹配在浏览器本地运行，真实审稿使用独立的 `/review.html` 页面。

审稿 API 通过 Vite 的 dev / preview 同源中间件按需启动本机 Python 服务，不影响地图的初始加载。Python 环境沿用项目依赖，默认任务目录为 experiments 下的 `web_review_runs`；可用 `ICLR_REVIEW_RUNS` 设置独立存储目录。每个存储目录只有一个协调服务，任务串行执行。新审稿只使用页面填写的 OpenAI 兼容地址、密钥和模型 ID，不读取服务器认证文件；地址和密钥不写入浏览器存储或任务文件。服务停止后在途记录保留，下次启动标记为可重试。

新增检查：在仓库根目录执行 `python3 web/test_review_api.py`，在 `web/` 执行 `npm run review:smoke`。后者默认验证页面及已存在的真实案例，不触发模型；仅显式设置 `ICLR_REVIEW_LIVE=1` 才启动一次真实审稿。`ICLR_REVIEW_RETRY=<run-id>` 可验证失败任务的重试恢复。浏览器执行文件配置沿用下文现有验证方式。

当前收录 **12,964 篇论文、54,900 条审稿**。页面提供论文语义地图、实体主题/投稿领域筛选、样本内录用率、论文均分与篇内审稿分歧组合图、同论文实体共现弦图及原文证据。

## 评分与分歧组合图（2026-11-11）

原评分直方图已升级为论文级组合分布：同时展示均分与篇内样本标准差，可将分歧切换为极差。默认按年份比较录用与拒稿论文；也可选择全部决定或单组。每篇论文等权，均分需要至少一条有效评分，标准差（分母 n−1）和极差需要至少两条。当前可用均分12,738篇、分歧12,725篇。

上方交互SVG随领域、主题及弦带选择更新，组合阶梯分布主体、最多40个分位点、中位数及中央50%/90%区间；小于等于40篇的组显示逐篇观测。高分歧列表显示原始评分及评分数，并可定位论文和原文证据。下方全样本图实际调用R/ggdist的 `stat_slab`、`stat_dots`、`stat_pointinterval`，按年展示全部决定、录用、拒稿三组；全部决定与后两组存在成员重叠。

区间描述观测论文的差异，不是置信区间；不跨年混合量表，缺失评分不补零，分歧需结合审稿人数阅读。R输出SVG、PNG及论文级统计CSV，前端与R的均值、标准差、极差逐篇一致。设计与报告修改说明见 [ggdist迭代记录](../docs/technical_details/Web_ggdist_upgrade_2026-11-11.md)。

验证：`node web/review-distributions-check.mjs`；在 `web/` 运行 `node review-distributions-smoke.mjs` 检查真实浏览器筛选与论文回查。设置 `ICLR_GGDIST_FULL_SMOKE=1` 同时执行原地图、弦图和证据回查回归。浏览器检查采用临时登录配置，不修改网站管理员凭据，也不调用模型。

弦图使用 S4 核心实体多标签，先归并明确同义词，再对同篇同概念去重；弦宽表示同时含两个概念的独立论文数，原始词形与标签 ID 可展开查看。地图默认按投稿领域着色，并标注局部领域与代表主题，支持图例筛选和区域索引。已有结果不包含这批论文的完整学科父子指派，因此领域分组与实体标签分别标注。范围、数据口径与验证见 [S4 可视化记录](../docs/technical_details/Web_visualization_S4.md)。

## 本机启动

在仓库根目录生成数据与评分图：

```bash
PYTHONPYCACHEPREFIX=/tmp/iclr-map-pycache OPENBLAS_NUM_THREADS=4 OMP_NUM_THREADS=4 python3 web/export_s4.py
logs/web_visualization/runtime/r/bin/Rscript web/render_reviews.R web/public/generated/reviews.csv web/public/generated/reviews.svg
```

启动页面：

```bash
cd web
npm ci
npm run dev -- --port 5174 --strictPort
```

浏览器打开 <http://127.0.0.1:5174/>。点击地图中的点查看论文，Shift + 点击可多选。支持 WebGPU 和 `shader-f16` 的设备使用 Atlas；其他设备自动使用原生 Canvas 兼容地图，同样支持点选、多选和论文详情。S4 分析区的交互评分图随领域、实体标签或弦带更新；底部 ggdist 图是整个 S4 队列的静态结果。5173 留给下面的局域网跳转入口。

## 新环境准备

- Python 使用现有环境的 `psycopg`、`numpy`、`scikit-learn`（本次 1.9.0），数据库连接由 `ICLR_DATABASE_URL` 提供；未设置时连接本机 `127.0.0.1:55432/iclr_reviewer`。导出事务为 `REPEATABLE READ READ ONLY`。
- Node 使用支持 Vite 7 的版本（20.19+ 或 22.12+），本机验证版本为 Node 24.20.0。npm 依赖通过 `package-lock.json` 固定。
- R 可以使用已有 R 4.4 环境，并安装 `ggdist`、`ggplot2`、`svglite`、`jsonlite`；也可以用 micromamba/conda 根据 [r-environment.yml](r-environment.yml) 创建独立环境。
- 本机已有任务专用 micromamba，运行时位于被 Git 忽略的 `logs/web_visualization/runtime/`。在新机器上安装 [micromamba](https://mamba.readthedocs.io/en/latest/installation/micromamba-installation.html) 后，可运行：

```bash
micromamba create -y -p ./logs/web_visualization/runtime/r -f web/r-environment.yml
```

生成的论文 JSON、CSV、SVG、截图和运行时均不进入 Git。刷新数据后重新运行 R 脚本和构建，使评分图与地图队列一致。默认导出封存 S4 的全部 12,964 篇；`export_v1.py` 是历史 S3 队列导出入口，当前页面使用 `export_s4.py`。

## 验证

构建与浏览器验证在 `web/` 下执行：

```bash
npm run build
npx playwright install chromium
npm run smoke
```

Linux 无头验证依赖可用的 Vulkan/WebGPU 适配器。当前机器通过 AMD RDNA 3 验证，具体运行命令为：

```bash
VK_ICD_FILENAMES=/usr/share/vulkan/icd.d/radeon_icd.json \
PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH="$HOME/.cache/ms-playwright/chromium_headless_shell-1234/chrome-headless-shell-linux64/chrome-headless-shell" \
npm run smoke
```

`PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH` 仅用于复用现有浏览器；安装匹配的 Playwright 浏览器后可以省略。`VK_ICD_FILENAMES` 应按目标机器驱动调整。

验证实际浏览器点击与多选事件、论文标识回查、全量地图数据及抽查真实绘图像素、SVG 加载及页面错误。结果保存为 `artifacts/v1-smoke.json`，GPU 原始读回保存在 `artifacts/v1-atlas-canvas.png`。Linux 无头 Vulkan 截图不包含 GPU surface，因此全页截图使用同一次真实 GPU 读回帧补入地图图层，记录中有 `screenshot_uses_gpu_readback` 标记。

构建产物在 `dist/`。`npm run dev` 只监听回环地址；局域网使用下面的 HTTPS 静态预览。当前审稿业务 API 由同源 Node 代理与回环 Python 服务提供；面向公网的生产部署需另行配置。

## 局域网 HTTPS 访问

推荐入口为 <http://172.24.246.231:5173/>，自动跳转到 <https://172.24.246.231:8443/>，保留路径与查询参数。服务仅发布 `dist/` 构建结果。准备与启动命令（在仓库根目录执行）：

```bash
python3 web/setup_lan.py --ip 172.24.246.231
cd web
npm run build
npm run lan
```

首次在其他设备访问时，将 [本地 CA 证书](https://172.24.246.231:8443/iclr-lan-ca.crt) 导入该设备或浏览器的受信任证书颁发机构，再重新打开页面。也可以从服务器复制 `web/public/iclr-lan-ca.crt`。只有公开 CA 证书需要传给客户端；私钥保存在服务器被 Git 忽略的 `logs/web_visualization/lan/` 中。

- Windows：将证书导入当前用户的“受信任的根证书颁发机构”，再重启浏览器。
- macOS：导入“钥匙串访问”，将该证书设为始终信任。
- Firefox：在证书管理的“证书颁发机构”中导入并信任此 CA 用于网站。
- iOS/iPadOS：安装证书描述文件后，在“设置 → 通用 → 关于本机 → 证书信任设置”中启用完全信任。

CA 固定复用；服务器 IP 改变后，用新 IP 重新运行 `setup_lan.py`，重新构建并重启服务，客户端无需重新导入同一 CA。Atlas 模式要求客户端支持 WebGPU 与 `shader-f16`，不具备这些能力时自动显示兼容地图。若其他设备无法建立连接，应检查它与服务器是否可路由、网络是否允许访问 TCP 5173 和 8443。

`http://服务器IP:8443/` 会将普通 HTTP 发给 TLS 端口，可能得到 Chrome 的 `ERR_EMPTY_RESPONSE`；证书导入不能修复这种协议不匹配。使用上面的 5173 入口即可。2026-11-06 已由局域网 Windows Chrome 用户确认该入口可打开页面。服务日志记录跳转、HTTPS 请求状态及 TLS 错误码，可用 `journalctl --user -u iclr-web-lan.service` 排查。

当前运行实例由用户级 systemd 服务 `iclr-web-lan` 托管，便于终端关闭后继续访问：

在当前服务器以 `yhr` 用户运行以下脚本（无需 `sudo`；在仓库根目录执行）：

```bash
./scripts/start_website.sh  # 启动，重复运行不会启动第二份服务
./scripts/stop_website.sh   # 关闭网站及 HTTP 跳转入口
```

脚本使用已有的构建产物、证书与登录配置；修改网页源码后，先执行 `npm --prefix web run build`。状态、重启与日志可使用 systemd 命令：

```bash
systemctl --user status iclr-web-lan.service
systemctl --user start iclr-web-lan.service
systemctl --user restart iclr-web-lan.service
systemctl --user stop iclr-web-lan.service
```

手动启动时使用 `npm run lan`；不要与已运行的服务同时占用 8443。该验证服务不设置开机自启。

现有浏览器验证也支持 HTTPS 实例。在 `web/` 下设置 `ICLR_WEB_BASE_URL` 指向实例，`NODE_EXTRA_CA_CERTS` 指向本地 CA，`ICLR_WEB_TLS_CERT` 指向服务器证书，再运行 `npm run smoke`。HTTP 客户端正常验证 CA；浏览器自动验证仅固定信任此服务器的公钥，不全局忽略证书错误。结果写入 `artifacts/lan-smoke.json`。

`ICLR_WEB_BASE_URL` 也可使用上述 HTTP 跳转入口，测试会继续验证跳转后的 HTTPS 页面。增加 `ICLR_WEB_FORCE_COMPAT=1` 可在自动验证中屏蔽 WebGPU，检查真实 Canvas 绘图、点击、多选和详情；结果写入 `artifacts/compat-smoke.json`。兼容地图当前展示 12,964 篇 S4 论文并支持缩放和平移；与 Atlas 共用领域/代表主题标注；不包含 Atlas 的密度估计。Atlas 包按需加载，兼容模式无需下载其完整渲染包。

当前数据核对命令：`PYTHONPYCACHEPREFIX=/tmp/iclr-map-pycache python3 web/validate_s4.py`（仓库根目录）。浏览器验证包含 S4 标签/弦带→录用和评分→地图→原文证据。

同义词规则与地图标注可单独刷新：`PYTHONPYCACHEPREFIX=/tmp/iclr-map-pycache OPENBLAS_NUM_THREADS=4 OMP_NUM_THREADS=4 python3 web/derive_topics.py`，随后运行 `python3 web/validate_topics.py` 和生产构建。完整导出已自动包含此步骤。地图的 30 个局部区域用于说明二维邻域内容，不代表正式学科父子分类。

弦图标签采用左右分列、换行避让和引导线；窄屏可在图内横向滚动。地图“领域过渡”默认启用，可选细/中/宽并随筛选更新；颜色混合表示邻域论文的投稿领域构成，切换年份着色后自动隐藏。独立渐变逻辑验证：`node web/visual-checks.mjs`；现有 `npm run smoke` 同时检查实际渐变像素和 16/24/32 节点的文字碰撞。

地图现支持数学计算的领域边界与逐级阅读：全景只显示原始投稿领域；2.2× 后显示带领域标记的 S4 主题；5× 后显示可点击的论文信息卡片。论文点随缩放连续增大。领域边界来自归一化高斯核密度的优势分区与 Marching Squares 等值线，填色和边界可独立开关。完整数据导出会生成领域内的 S4 局部主题，既有快照更新时重新执行 `derive_topics.py`、`validate_topics.py` 与构建即可。数学检查仍使用 `node web/visual-checks.mjs`。

### 审稿接口设置

在单篇审稿页自行输入 Base URL、API Key、模型 ID，选择 Chat Completions 或 Responses。所有字段初始为空，API Key 使用密码框；提交成功清空密钥。当前任务仅在内存和工作进程环境中使用配置，持久记录只保存接口哈希、模型和协议，错误及供应商回显脱敏。

重试需重新输入原接口和模型，可使用更新后的有效密钥。服务重启保留结果和输入，不保留凭据。旧版预设接口案例继续只读回放，新任务不再使用服务器预设模型或 `~/auth`。详情见 [接口输入与隐私说明](../docs/technical_details/Web_user_api_configuration.md)。
