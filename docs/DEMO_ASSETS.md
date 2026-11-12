# Portable demo assets / 可移植演示资产

Version: **demo-2026-11-12-v1**. [Download directory](https://github.com/Haoran-98/ICLR-reviewer/tree/demo-2026-11-12-v1) · [Machine-readable manifest](demo-assets.json) · [SHA256SUMS](https://raw.githubusercontent.com/Haoran-98/ICLR-reviewer/demo-2026-11-12-v1/SHA256SUMS)

| Package | Compressed bytes | Download parts, in order | Whole archive SHA-256 |
|---|---:|---|---|
| website | 71,053,120 | [1](https://raw.githubusercontent.com/Haoran-98/ICLR-reviewer/demo-2026-11-12-v1/website.tar.gz.part00) / [2](https://raw.githubusercontent.com/Haoran-98/ICLR-reviewer/demo-2026-11-12-v1/website.tar.gz.part01) | `e7eb87bf144dd88c6dd5372faeb52abf7bbd69aafa7fa0a3bcbccf84b9bd939b` |
| rules | 27,350,139 | [1](https://raw.githubusercontent.com/Haoran-98/ICLR-reviewer/demo-2026-11-12-v1/rules.tar.gz.part00) | `e182c515e74d0b26ae6a8ffc8926108f829f21f9deeb8f54609b36f747447e15` |
| cases | 89,858 | [1](https://raw.githubusercontent.com/Haoran-98/ICLR-reviewer/demo-2026-11-12-v1/cases.tar.gz.part00) | `8d87f5c85f2efac5574cb30c95772abb583ec9c05de9947389fa7a73c780c6db` |

The website archive has two parts. The installer downloads every part, verifies its checksum, concatenates parts in order, verifies the complete archive, rejects unsafe archive paths and links, and checks every extracted file against PACKAGE.json. The source repository pins the download manifest. Downloaded files live outside Git's source history.

```bash
.venv/bin/python scripts/install_demo_assets.py
# Offline installation after downloading all *.partNN files into a directory:
.venv/bin/python scripts/install_demo_assets.py --assets-dir /path/to/downloads
```

For manual verification, concatenate each package's parts in numeric order into `<package>.tar.gz`, then run `sha256sum -c SHA256SUMS` in the directory containing all parts and archives.

## Contents and provenance

- **website:** the 12,964-paper map, domain/topic/paper shards, score graphics, 7,795 displayed modules and five historical library replays. Generated coordinates and charts are ready for display; R, embeddings and PostgreSQL are needed only when rebuilding the snapshot.
- **rules:** 9,175 active rules, all module exports, candidate/queue status, paired historical review and manuscript passages, and identities of all 1,286 distillation-source manuscripts. The portable RELEASE/FROZEN manifests verify the derived package. UPSTREAM.json preserves the original frozen release hash, library identity and protocol hashes. Source exclusion compares paper ID, forum ID, manuscript SHA-256 and the exact full-text digest, including source papers that yielded no rule.
- **cases:** the completed MLRA composition and Review, exact target evidence, recovery record, plus its full manuscript as a runnable example. The original case retains its historical rule version/hash. It is read-only; a fresh review creates a separate job.

Original papers and public reviews remain attributable through paper IDs, titles and OpenReview links. Historical passages retain their passage IDs and character offsets. Projected source files have new SHA-256 values; PROVENANCE.json records those alongside upstream source-file hashes. Full source manuscript identities are preserved as hashes; runtime request envelopes, credentials, private model configuration and machine paths are excluded.

## 中文说明

三份资产包分别提供网站快照、规则与配对来源、完整历史案例。表格中的数字链接为按顺序排列的下载分段；网站包需要下载两段。安装器自动合并，逐层校验分段、完整压缩包及解压后的文件清单。离线安装使用 `--assets-dir`。

规则包保留规则、模块、候选状态和历史证据，并用全部 1,286 篇来源稿件的身份与全文摘要执行排除检查。`UPSTREAM.json` 保留原始冻结版本身份；`PROVENANCE.json` 分别记录原件与公开投影文件的哈希。案例保留原版本结果，供只读回放；重新审稿会建立新任务。

本次发布保留论文及公开审稿的题名、引文和 OpenReview 来源，移除了开发机路径、模型接口配置、密钥及请求响应信封。作者对原始论文与审稿的权利保持原样。
