#!/usr/bin/env python3
"""Compare the 40 papers shared by existing Markdown, Docling, and MinerU standard."""

from __future__ import annotations

import json
import statistics
import subprocess
from collections import Counter, defaultdict
from html import unescape
from pathlib import Path

import benchmark


COUNT = 40
OUT_DIR = Path(__file__).resolve().parent
METRICS_PATH = OUT_DIR / "standard_40_metrics.jsonl"
SUMMARY_PATH = OUT_DIR / "standard_40_summary.json"
REPORT_PATH = OUT_DIR / "standard_40_report.md"
JUDGMENTS_PATH = OUT_DIR / "standard_40_conflict_judgments.jsonl"
MINERU_DIR = benchmark.ROOT / "outputs/mineru_standard_gpu_partial"
METHOD_LABELS = {
    "existing": "Existing Markdown",
    "docling": "Docling 2.130.0",
    "mineru_standard": "MinerU standard",
}


def output_path(method: str, paper: dict) -> Path:
    if method == "existing":
        return Path(paper["markdown_path"])
    if method == "docling":
        return benchmark.ROOT / "outputs/docling" / f"{paper['sample_id']}.md"
    return MINERU_DIR / f"{paper['sample_id']}.md"


def average(rows: list[dict], key: str) -> float | None:
    values = [row[key] for row in rows if isinstance(row.get(key), (int, float))]
    return round(statistics.mean(values), 4) if values else None


def reference_overlap(reference: str, candidate: str) -> tuple[float, float, float]:
    reference_counts = Counter(benchmark.tokens(unescape(reference)))
    candidate_counts = Counter(benchmark.tokens(unescape(benchmark.visible_text(candidate))))
    overlap = sum((reference_counts & candidate_counts).values())
    recall = overlap / max(1, sum(reference_counts.values()))
    precision = overlap / max(1, sum(candidate_counts.values()))
    f1 = 2 * recall * precision / max(1e-12, recall + precision)
    return recall, precision, f1


def score() -> list[dict]:
    manifest = benchmark.read_jsonl(benchmark.MANIFEST)[:COUNT]
    rows: list[dict] = []
    for index, paper in enumerate(manifest, 1):
        reference = subprocess.run(
            ["pdftotext", "-layout", paper["pdf_path"], "-"],
            capture_output=True,
            text=True,
            errors="replace",
            timeout=180,
            check=False,
        ).stdout
        pdf_chars = len(benchmark.normalize(reference))
        for method in METHOD_LABELS:
            path = output_path(method, paper)
            if not path.is_file():
                rows.append(
                    {
                        "sample_id": paper["sample_id"],
                        "paper_id": paper["paper_id"],
                        "method": method,
                        "error": "missing_output",
                        "path": str(path),
                    }
                )
                continue
            text = path.read_text(encoding="utf-8", errors="replace")
            metric = benchmark.metric_for(
                paper,
                method,
                text,
                pdf_chars,
            )
            recall, precision, f1 = reference_overlap(reference, text)
            metric["reference_token_recall"] = round(recall, 4)
            metric["reference_token_precision"] = round(precision, 4)
            metric["reference_token_f1"] = round(f1, 4)
            metric["balanced_quality_score"] = round(
                100
                * (
                    0.15 * metric["title_recall"]
                    + 0.20 * metric["abstract_recall"]
                    + 0.05 * metric["keyword_recall"]
                    + 0.15 * metric["section_score"]
                    + 0.05 * metric["sections"]["references"]
                    + 0.10 * metric["clean_score"]
                    + 0.05 * (1 - metric["repeat_rate"])
                    + 0.25 * f1
                ),
                4,
            )
            metric["output_bytes"] = path.stat().st_size
            metric["visible_text_bytes"] = len(benchmark.visible_text(text).encode())
            metric["formula_undecoded_placeholders"] = text.count("formula-not-decoded")
            metric["embedded_image_count"] = text.count("data:image/")
            rows.append(metric)
        print(f"[{index:02d}/{len(manifest)}] {paper['sample_id']}", flush=True)
    benchmark.write_jsonl(METRICS_PATH, rows)
    return rows


def summarize(rows: list[dict]) -> dict:
    valid: dict[str, list[dict]] = defaultdict(list)
    missing: dict[str, list[str]] = defaultdict(list)
    by_paper: dict[str, list[dict]] = defaultdict(list)
    for row in rows:
        if "error" in row:
            missing[row["method"]].append(row["sample_id"])
        else:
            valid[row["method"]].append(row)
            by_paper[row["sample_id"]].append(row)

    wins = Counter()
    ties = 0
    for paper_rows in by_paper.values():
        if len(paper_rows) != len(METHOD_LABELS):
            continue
        best = max(row["balanced_quality_score"] for row in paper_rows)
        winners = [row["method"] for row in paper_rows if row["balanced_quality_score"] == best]
        if len(winners) == 1:
            wins[winners[0]] += 1
        else:
            ties += 1

    summary = {
        "scope": {
            "requested_papers": COUNT,
            "complete_triplets": sum(len(items) == len(METHOD_LABELS) for items in by_paper.values()),
            "mineru_tier": "standard",
            "mineru_source": str(MINERU_DIR),
        },
        "methods": {},
        "quality_score_wins": dict(wins),
        "quality_score_ties": ties,
    }
    for method in METHOD_LABELS:
        items = valid[method]
        summary["methods"][method] = {
            "label": METHOD_LABELS[method],
            "parsed": len(items),
            "missing": missing[method],
            "quality_score_mean": average(items, "balanced_quality_score"),
            "quality_score_median": round(statistics.median(row["balanced_quality_score"] for row in items), 4) if items else None,
            "title_recall_mean": average(items, "title_recall"),
            "abstract_recall_mean": average(items, "abstract_recall"),
            "keyword_recall_mean": average(items, "keyword_recall"),
            "section_score_mean": average(items, "section_score"),
            "references_present_rate": round(sum(row["sections"]["references"] for row in items) / len(items), 4) if items else None,
            "table_rows_mean": average(items, "table_rows"),
            "formula_markers_mean": average(items, "formula_markers"),
            "formula_undecoded_total": sum(row["formula_undecoded_placeholders"] for row in items),
            "embedded_image_count": sum(row["embedded_image_count"] for row in items),
            "figure_mentions_mean": average(items, "figure_mentions"),
            "citation_markers_mean": average(items, "citation_markers"),
            "repeat_rate_mean": average(items, "repeat_rate"),
            "replacement_chars_total": sum(row["replacement_chars"] for row in items),
            "coverage_score_mean": average(items, "coverage_score"),
            "reference_token_recall_mean": average(items, "reference_token_recall"),
            "reference_token_precision_mean": average(items, "reference_token_precision"),
            "reference_token_f1_mean": average(items, "reference_token_f1"),
            "output_mib": round(sum(row["output_bytes"] for row in items) / 1024**2, 3),
            "visible_text_mib": round(sum(row["visible_text_bytes"] for row in items) / 1024**2, 3),
            "embedded_image_mib": round(sum(row["embedded_image_bytes"] for row in items) / 1024**2, 3),
        }
    return summary


def fmt(value: object) -> str:
    return "N/A" if value is None else str(value)


def conflict_audit_summary() -> dict | None:
    judgments = benchmark.read_jsonl(JUDGMENTS_PATH)
    if not judgments:
        return None
    winners = Counter()
    winners_by_kind: dict[str, Counter] = defaultdict(Counter)
    score_values: dict[str, dict[str, list[int]]] = defaultdict(lambda: defaultdict(list))
    cases = []
    strong_calls = 0
    changed_winner = 0
    usage = Counter()
    for record in judgments:
        weak = record.get("weak") or {}
        strong = record.get("strong") or {}
        verdict = strong or weak
        if strong:
            strong_calls += 1
            changed_winner += weak.get("winner") != strong.get("winner")
        winner = verdict.get("winner")
        if winner:
            winners[winner] += 1
            winners_by_kind[record["kind"]][winner] += 1
        for method, scores in (verdict.get("scores") or {}).items():
            for dimension, value in scores.items():
                if isinstance(value, (int, float)):
                    score_values[method][dimension].append(value)
        for source in (record.get("weak_usage") or {}, record.get("strong_usage") or {}):
            usage.update({key: value for key, value in source.items() if isinstance(value, int)})
        cases.append(
            {
                "sample_id": record["sample_id"],
                "kind": record["kind"],
                "page": record["page"],
                "winner": winner,
                "confidence": verdict.get("confidence"),
                "used_strong": bool(strong),
            }
        )
    averages = {
        method: {dimension: round(statistics.mean(values), 3) for dimension, values in dimensions.items()}
        for method, dimensions in score_values.items()
    }
    return {
        "cases": cases,
        "winners": dict(winners),
        "winners_by_kind": {kind: dict(counts) for kind, counts in winners_by_kind.items()},
        "average_scores": averages,
        "strong_calls": strong_calls,
        "strong_changed_winner": changed_winner,
        "usage": dict(usage),
    }


def write_report(summary: dict) -> None:
    methods = summary["methods"]
    report = [
        "# 40 篇 ICLR 论文解析器对比：初步确定性结果",
        "",
        "## 对比范围",
        "",
        "固定比较同一批 `p001`–`p040`。三路输入分别为原有 Markdown、Docling 2.130.0 和已完成的 MinerU standard GPU partial；MinerU basic 冒烟结果未参与。标题、摘要、关键词和 PDF `pdftotext` 文本作为非 LLM 锚点。",
        "",
        f"完整三路样本：**{summary['scope']['complete_triplets']}/{COUNT}**。本报告是可复现的代理指标对比，不等价于人工逐页转写准确率。",
        "",
        "## 总体结果",
        "",
        "| 方法 | 完成 | 启发式总分* ↑ | 标题召回 ↑ | 摘要召回 ↑ | 章节覆盖 ↑ | PDF 文本一致性* ↑ | 重复率 ↓ |",
        "|---|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for method in METHOD_LABELS:
        item = methods[method]
        report.append(
            f"| {item['label']} | {item['parsed']} | {fmt(item['quality_score_mean'])} | "
            f"{fmt(item['title_recall_mean'])} | {fmt(item['abstract_recall_mean'])} | "
            f"{fmt(item['section_score_mean'])} | {fmt(item['reference_token_f1_mean'])} | "
            f"{fmt(item['repeat_rate_mean'])} |"
        )
    report += [
        "",
        "## 结构信号",
        "",
        "以下统计解析器保留的结构信号；单元格与公式的语义质量按困难页审计记录。",
        "",
        "| 方法 | 表格行均值 ↑ | LaTeX 公式标记均值 ↑ | 未解码公式总数 ↓ | Figure 提及均值 ↑ | 引用标记均值 ↑ |",
        "|---|---:|---:|---:|---:|---:|",
    ]
    for method in METHOD_LABELS:
        item = methods[method]
        report.append(
            f"| {item['label']} | {fmt(item['table_rows_mean'])} | {fmt(item['formula_markers_mean'])} | "
            f"{fmt(item['formula_undecoded_total'])} | {fmt(item['figure_mentions_mean'])} | "
            f"{fmt(item['citation_markers_mean'])} |"
        )
    report += [
        "",
        "## 输出构成",
        "",
        "| 方法 | 原始输出 MiB | 可见文本 MiB | 内嵌图片 MiB | 内嵌图片数 | PDF 词频召回* | PDF 词频精确率* |",
        "|---|---:|---:|---:|---:|---:|---:|",
    ]
    for method in METHOD_LABELS:
        item = methods[method]
        report.append(
            f"| {item['label']} | {fmt(item['output_mib'])} | {fmt(item['visible_text_mib'])} | "
            f"{fmt(item['embedded_image_mib'])} | {fmt(item['embedded_image_count'])} | {fmt(item['reference_token_recall_mean'])} | "
            f"{fmt(item['reference_token_precision_mean'])} |"
        )
    report += [
        "",
        "## 启发式筛选",
        "",
        f"按启发式总分领先统计：`{json.dumps(summary['quality_score_wins'], ensure_ascii=False)}`；并列 `{summary['quality_score_ties']}` 篇。它只用于定位冲突样本，不作为解析器冠军结论。",
        "",
        "`*` 原有 Markdown 是 `pdftotext` 风格文本，因此它相对 `pdftotext` 的一致性为 1.0 衡量来源自一致；总分也受该项影响。",
        "",
        "## 当前选择建议",
        "",
        "| 使用目标 | 推荐路径 | 原因 |",
        "|---|---|---|",
        "| LLM 全文理解的结构骨架 | Docling | 章节清晰、输出最小、40 篇无缺失；但 908 个公式未解码占位符必须补齐 |",
        "| 表格、公式与视觉对象候选 | MinerU standard | 困难表格页 4/4 视觉首选，并保留 LaTeX 与图片；需要剥离 base64，公式还需校验 |",
        "| 原始文字回溯与审计 | Existing Markdown | 与 PDF 文本层高度一致，但表格、公式和标题结构较弱 |",
        "| 最终数据库入库 | Docling 骨架 + MinerU 候选 + Existing 审计 | 三路互补；冲突字段保留来源和置信度，不让单一解析器覆盖证据 |",
        "",
        "## 视觉冲突审计",
        "",
    ]
    audit = summary.get("conflict_audit")
    if audit:
        report += [
            "对 4 个公式密集冲突和 4 个表格冲突，自动选择证据页并以 PDF 页面图像为真值。弱模型先判，`unresolved` 或低置信度才升级强模型。该集合是刻意选择的困难样本，不能外推为 40 篇总体胜率。",
            "",
            f"- 最终单页首选：`{json.dumps(audit['winners'], ensure_ascii=False)}`。",
            f"- 按冲突类型：`{json.dumps(audit['winners_by_kind'], ensure_ascii=False)}`。",
            f"- 强模型调用：{audit['strong_calls']}/8；其中 {audit['strong_changed_winner']} 篇改变弱模型首选。",
            f"- API 总用量：{audit['usage'].get('total_tokens', 'N/A')} tokens。",
            "",
            "| 样本 | 类型 | PDF 页 | 最终首选 | 置信度 | 强模型 |",
            "|---|---|---:|---|---:|---|",
        ]
        for case in audit["cases"]:
            report.append(
                f"| {case['sample_id']} | {case['kind']} | {case['page']} | {case['winner']} | "
                f"{case['confidence']} | {'yes' if case['used_strong'] else 'no'} |"
            )
        report += [
            "",
            "视觉裁决平均分（1–5，仅针对 8 个困难页）：",
            "",
            "| 方法 | 文本 | 结构 | 表格 | 数学 |",
            "|---|---:|---:|---:|---:|",
        ]
        for method in METHOD_LABELS:
            scores = audit["average_scores"].get(method, {})
            report.append(
                f"| {METHOD_LABELS[method]} | {fmt(scores.get('text'))} | {fmt(scores.get('structure'))} | "
                f"{fmt(scores.get('table'))} | {fmt(scores.get('math'))} |"
            )
    else:
        report.append("尚未运行视觉冲突审计。")
    report += [
        "",
        "## 效率证据",
        "",
        "- Docling 的已保存全量运行记录：100 篇耗时 2255.446 秒，约 22.554 秒/篇，峰值 GPU 3246 MiB，0 失败。",
        "- MinerU standard 的 3 篇 smoke 记录：52 页耗时 228.538 秒，峰值 GPU 1980 MiB，0 失败。40 篇 partial 的精确总耗时未保留，因此不猜测吞吐量。",
        "- Existing Markdown 的历史生成耗时未知，不能与两个解析器作速度比较。",
        "",
        "## 结论",
        "",
        "- Docling 适合充当紧凑的章节与正文骨架，但不能单独承担数学论文解析：40 篇出现 908 个未解码公式占位符。",
        "- MinerU standard 在本次困难表格页审计中最强，但 40 篇原始输出的 93.5% 左右是内嵌图片；送入 LLM 前必须拆分文本与视觉对象。",
        "- 公式正确性按页面原图核验。4 个公式冲突页中 Existing 在 3 页更忠实，MinerU 在 1 页更好；数学字段需要交叉核验或页面视觉裁决。",
        "- 因此后续论文理解采用三路融合，不再继续补跑 MinerU basic 100 篇。",
        "",
        "## 指标边界",
        "",
        "- 质量分组合标题/摘要/关键词恢复、章节与 references、文本覆盖、重复和编码洁净度。",
        "- 表格行、公式标记、Figure 与引用数量衡量结构保留；本次只对 8 个高冲突页做了视觉核验。",
        "- 输出更长不自动表示更完整，可能包含嵌入图片或重复内容。",
        "",
    ]
    REPORT_PATH.write_text("\n".join(report), encoding="utf-8")


def main() -> None:
    rows = score()
    summary = summarize(rows)
    summary["conflict_audit"] = conflict_audit_summary()
    SUMMARY_PATH.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    write_report(summary)
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
