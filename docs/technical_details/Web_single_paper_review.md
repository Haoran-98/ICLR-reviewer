# 独立单篇审稿页面

状态：2026-11-08 实现并接入现有 Web。按用户要求跳过多稿验收，将第四步做成独立主题页。

## 页面边界

- `/`：既有论文探索与可视化。原图表、算法、数据、筛选和布局保留，仅新增顶部主题导航与详情审稿链接。
- `/review.html`：单篇审稿。已有论文选择、Markdown/TXT 上传、模型识别与 Skill 组合、运行状态、Review、证据和重试。
- `/reviewers.html`：既有领域 Skill 库、本地匹配预览与历史案例回放，增加相同主题导航。

审稿页内部用“领域与 Skill”“Review 与优先级”“论文依据”组织结果，不将地图嵌入审稿页。
地图以 `/review.html?paper=<id>` 传递论文；历史来源以 `/?paper=<id>` 复用原有详情和可视化。
`?run=<id>` 恢复历史任务，刷新或离开页面不丢失服务端记录。

## 实现

前端为 [review.html](../../web/review.html)、[review.js](../../web/review.js) 和独立样式；
[site-nav.js](../../web/site-nav.js) 仅负责三页导航，不改动既有可视化组件。
Vite 多页面构建新增 review 入口。dev 和 HTTPS preview 通过
[review-api-plugin.js](../../web/review-api-plugin.js) 同源代理，按第一次 API 请求才启动
[review_api.py](../../web/review_api.py) 本机服务。原地图浏览不启动模型服务。

API 提供元信息、任务列表、创建任务、任务结果、重试和已有 MLRA 组合。
变更请求校验浏览器来源；Python 仅绑定回环地址并校验代理随机令牌。
限制请求与稿件大小、验证 ID 与任务路径，使用无 shell 的固定子进程入口。
所有稿件、来源与模型文字通过 textContent 显示。

每个任务目录保存原始输入、job 状态和多个 attempt 子目录。
服务协调锁保证同一任务存储只有一个服务，队列串行执行。
每次重试保留旧 attempt，复用成功的组合或已成功请求；服务重启将未完成任务标为 interrupted。
新任务可选择 OpenAI 6.1 sol 或 DeepSeek v4-pro；选择同时用于领域识别、Skill 组合和最终审稿。Qwen 与 Claude 按用户要求先展示待配置选项。历史 `gpt-6-luna / medium` 记录保持原模型标签，密钥只在服务端读取。

流程复用 [按稿组合入口](../../scripts/compose_manuscript_skills.py)，随后调用
[review_composed_manuscript.py](../../scripts/review_composed_manuscript.py) 读取完整稿件及实际加载的规则。
目标人类 Review、评分和决定不加入模型请求。完整文本超预算时停止，不静默截断。
concern 分为有证据支持的缺陷、待核实问题和修改建议，带 P1–P3、影响、行动与消除证据。
原文引文核验使用已有精确子串或唯一空白恢复规则，保存字符位置。

完整响应中个别条目引文无效时，该条目隔离保存，其余有效条目原样保留；
不猜测或重写科学文字，不将无效 concern 当作已核实缺陷。
界面提供单独待核验条目的相关原文，原始响应、评分和有效意见保留。
重试时可复用已保存响应进行这种本地核验，不追加推理调用。

## 真实运行与验证

浏览器从单篇页面启动论文 33089 *Multi-Head Low-Rank Attention*。
复用上一阶段真实组合（3 条规则，1,605 个规则代理 token），新增一次弱模型 Review 调用：
输入 32,491、输出 1,669，总计 34,160 个 provider token。
返回一条 P2 待核实问题，评分 6/10、置信度 2/5。
其中一条优点引用无法逐字匹配，被单独隔离；另外两条优点和一条 concern 的引文通过校验。
初次失败状态及原始响应保留，随后通过页面重试恢复，不增加模型调用。
真实任务 ID 为 `599c14be781f4eac98fa5093dd7eea43`，第二次执行完成。
这验证单篇运行和展示链路，不构成多稿质量评估或科学正确性裁决。

完成以下检查：

- `python3 web/test_review_api.py`：代理令牌、输入验证、任务持久化、重试、路径边界和有效条目保留／无效条目隔离。
- `npm run review:smoke`：独立页面、真实运行或已有案例、历史来源、新稿引文、上传输入、刷新恢复、地图带入和窄屏。
- `npm run reviewers:smoke`：原专家库的 7,795 个模块与 5 个历史回放完整通过。
- 原 `npm run smoke` 的 Canvas 兼容模式：12,964 篇地图、筛选、缩放、边界、弦图和证据交互通过。
- `npm run build`：三个 HTML 入口构建通过。

已重启既有局域网 preview 服务并验证实际 HTTPS 入口。
发布实例的浏览器检查通过，包括历史任务恢复、证据定位、上传输入和地图跳转。
来源校验同时支持 HTTP/1.1 Host 和 HTTP/2 authority；实际同源无效输入返回 400，跨站提交返回 403。
发布复核仅回放已有结果，不追加模型调用。

报告及截图位于被忽略的 `web/artifacts/`，真实任务保存在 experiments 的 `web_review_runs/`。
重现方式与现有局域网入口见 [Web README](../../web/README.md)。

## 审稿模型配置（2026-11-08）

`/api/review/meta` 返回模型白名单、实际 model ID 和配置状态。POST `/runs` 的 `model`
取 `openai-sol`（默认）、`deepseek-pro`、`qwen-local` 或 `claude-opus`；未知值和待配置模型返回 400。
前端选择保存在本浏览器，下次新建任务沿用；任务详情按记录中的实际模型展示。

服务端从 `ICLR_AUTH_FILE`（默认 `~/auth`）读取 export 赋值，再由同名环境变量覆盖。
认证文件只解析，不通过 shell 执行。当前配置：

| 选项 | model ID | 接口 | 状态 |
|---|---|---|---|
| OpenAI 6.1 sol | `gpt-6.1-sol` | Responses，medium | 已完成最小真实 JSON 调用 |
| DeepSeek v4-pro | `deepseek-v4-pro` | Chat Completions，thinking disabled | 已完成最小真实 JSON 调用 |
| 本地 Qwen3.8-next flash | 待确定 | 待确定 | 前端展示，禁止调用 |
| Claude Opus5.5 | 待确定 | 待确定 | 前端展示，禁止调用 |

OpenAI 使用 `OPENAI_BASE_URL`、`OPENAI_API_KEY`、`OPENAI_STRONG_MODEL_ID`；
DeepSeek 使用既有 `DeepSeek_base_url`、`DeepSeek_api_key`、`DeepSeek_strong_model`。
后续可通过 `QWEN_LOCAL_BASE_URL`、`QWEN_LOCAL_MODEL_ID`、可选 `QWEN_LOCAL_API_KEY`，
以及 `ANTHROPIC_BASE_URL`、`ANTHROPIC_MODEL_ID`、`ANTHROPIC_API_KEY` 配置另外两项。
配置 URL 是含 API 前缀的 base URL；程序追加 `/responses`、`/chat/completions` 或 `/messages`。
默认 Claude 协议为原生 Messages；兼容接口可设 `ICLR_REVIEW_ANTHROPIC_PROTOCOL=chat`。
各通道支持 `ICLR_REVIEW_<OPENAI|DEEPSEEK|QWEN_LOCAL|ANTHROPIC>_<BASE_URL|MODEL_ID|API_KEY|PROTOCOL>` 覆盖。

新任务记录模型与接口快照，缓存摘要包含请求、接口、模型和 transport 代码版本。
切换模型须新建任务；配置变化时旧任务停止并保留记录，不能跨模型冒用结果。
新任务不复用弱模型 MLRA 组合；已有组合案例和历史任务继续独立回放。
每个阶段至多两次 HTTP 尝试，仅连接失败、429 和 5xx 自动重试。
原始供应商响应与规范化响应都保存在服务器，继续逐字校验引文和隔离无效条目。

补充验证：`python3 scripts/test_manuscript_review_models.py`、
`python3 web/test_review_api.py`、`python3 scripts/test_compose_manuscript_skills.py`。
浏览器 smoke 同时检查四个模型选项、待配置禁用状态、选中模型提交、历史案例和证据。
真实接口探针保存在被 Git 忽略的 `logs/web_visualization/model-probes/`；仅做最小调用，未新增完整论文审稿。
接口格式参考 [OpenAI official documentation](https://developers.openai.com/api/docs/guides/structured-outputs)。
本机网关的 model ID 以其 `/models` 和真实响应为准。
