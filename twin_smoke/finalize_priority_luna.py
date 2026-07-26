#!/usr/bin/env python3
"""Validate Luna relevance labels and write final Agent/Education manifests."""

from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path


def normalize(value: object) -> str:
    text = str(value or "").lower()
    if "core" in text or "central" in text:
        return "core"
    if "adjacent" in text or "direct" in text:
        return "adjacent"
    return "no"


def write_jsonl(path: Path, rows: list[dict]) -> None:
    path.write_text("".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows), encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser()
    base = Path(__file__).resolve().parent / "output" / "priority_agent_education"
    parser.add_argument("--input", type=Path, default=base / "papers.jsonl")
    parser.add_argument("--results", type=Path, default=base / "api_luna")
    parser.add_argument("--output", type=Path, default=base)
    args = parser.parse_args()

    source = {row["openreview_id"]: row for row in map(json.loads, args.input.read_text(encoding="utf-8").splitlines())}
    labels = []
    for path in sorted(args.results.glob("batch_*_result.json")):
        labels.extend(json.loads(path.read_text(encoding="utf-8"))["papers"])
    returned = [row.get("openreview_id") for row in labels]
    errors = []
    if len(returned) != len(set(returned)):
        errors.append("duplicate_openreview_id")
    if set(returned) != set(source):
        errors.append("openreview_id_mismatch")

    merged = []
    for label in labels:
        row = dict(source[label["openreview_id"]])
        row["luna_agent_relevance"] = normalize(label.get("agent_relevance"))
        row["luna_education_relevance"] = normalize(label.get("education_relevance"))
        row["luna_agent_tags"] = list(label.get("agent_tags") or [])[:6]
        row["luna_education_tags"] = list(label.get("education_tags") or [])[:6]
        row["luna_rationale"] = str(label.get("rationale") or "")[:400]
        merged.append(row)

    agent = [
        row for row in merged
        if row["agent_tier"] in {"core", "adjacent"}
        and row["luna_agent_relevance"] in {"core", "adjacent"}
    ]
    education = [
        row for row in merged
        if row["education_tier"] in {"core", "adjacent"}
        and row["luna_education_relevance"] in {"core", "adjacent"}
    ]
    intersection = [row for row in agent if row["luna_education_relevance"] in {"core", "adjacent"}]
    intersection = [row for row in intersection if row["education_tier"] in {"core", "adjacent"}]
    agent_core = [row for row in agent if row["luna_agent_relevance"] == "core"]
    education_core = [row for row in education if row["luna_education_relevance"] == "core"]
    intersection_core = [
        row for row in intersection
        if row["luna_agent_relevance"] == "core" and row["luna_education_relevance"] == "core"
    ]
    luna_only_agent = [
        row for row in merged
        if row["agent_tier"] not in {"core", "adjacent"}
        and row["luna_agent_relevance"] in {"core", "adjacent"}
    ]
    luna_only_education = [
        row for row in merged
        if row["education_tier"] not in {"core", "adjacent"}
        and row["luna_education_relevance"] in {"core", "adjacent"}
    ]
    rejected = [row for row in merged if row not in agent and row not in education]
    key = lambda row: (-row["year"], row["title"].lower())
    for rows in (
        merged, agent, agent_core, education, education_core, intersection,
        intersection_core, luna_only_agent, luna_only_education, rejected,
    ):
        rows.sort(key=key)

    args.output.mkdir(parents=True, exist_ok=True)
    write_jsonl(args.output / "luna_screened_papers.jsonl", merged)
    write_jsonl(args.output / "luna_agent_papers.jsonl", agent)
    write_jsonl(args.output / "luna_agent_core_papers.jsonl", agent_core)
    write_jsonl(args.output / "luna_education_papers.jsonl", education)
    write_jsonl(args.output / "luna_education_core_papers.jsonl", education_core)
    write_jsonl(args.output / "luna_agent_education_papers.jsonl", intersection)
    write_jsonl(args.output / "luna_agent_education_core_papers.jsonl", intersection_core)
    write_jsonl(args.output / "luna_only_agent_candidates.jsonl", luna_only_agent)
    write_jsonl(args.output / "luna_only_education_candidates.jsonl", luna_only_education)
    write_jsonl(args.output / "luna_rejected_candidates.jsonl", rejected)
    api_summary_path = args.results / "summary.json"
    api_runs = json.loads(api_summary_path.read_text(encoding="utf-8")).get("runs", []) if api_summary_path.exists() else []
    usage = {
        "input_tokens": sum((run.get("usage") or {}).get("input_tokens", 0) for run in api_runs),
        "cached_tokens": sum(((run.get("usage") or {}).get("input_tokens_details") or {}).get("cached_tokens", 0) for run in api_runs),
        "output_tokens": sum((run.get("usage") or {}).get("output_tokens", 0) for run in api_runs),
        "reasoning_tokens": sum(((run.get("usage") or {}).get("output_tokens_details") or {}).get("reasoning_tokens", 0) for run in api_runs),
        "total_tokens": sum((run.get("usage") or {}).get("total_tokens", 0) for run in api_runs),
    }
    summary = {
        "expected": len(source),
        "returned": len(labels),
        "unique_ids": len(set(returned)),
        "errors": errors,
        "agent_papers": len(agent),
        "agent_core_papers": len(agent_core),
        "education_papers": len(education),
        "education_core_papers": len(education_core),
        "intersection": len(intersection),
        "intersection_core": len(intersection_core),
        "luna_only_agent_candidates": len(luna_only_agent),
        "luna_only_education_candidates": len(luna_only_education),
        "rejected": len(rejected),
        "agent_relevance": Counter(row["luna_agent_relevance"] for row in merged),
        "education_relevance": Counter(row["luna_education_relevance"] for row in merged),
        "by_year": {
            str(year): {
                "agent": sum(row["year"] == year for row in agent),
                "education": sum(row["year"] == year for row in education),
                "intersection": sum(row["year"] == year for row in intersection),
            }
            for year in (2024, 2025, 2026)
        },
        "accepted_main": {
            "agent": sum(row["accepted_main"] for row in agent),
            "education": sum(row["accepted_main"] for row in education),
            "intersection": sum(row["accepted_main"] for row in intersection),
        },
        "usage": usage,
    }
    (args.output / "luna_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    lines = [
        "# Luna-Confirmed Agent and Education Papers",
        "",
        "Scope: ICLR 2024-2026 main track only. Inclusion requires both deterministic evidence and Luna semantic confirmation.",
        "",
        f"- Agent: {len(agent)}",
        f"- Agent core: {len(agent_core)}",
        f"- Education: {len(education)}",
        f"- Education core: {len(education_core)}",
        f"- Agent + Education: {len(intersection)}",
        f"- Agent + Education core/core: {len(intersection_core)}",
        "",
        "## Agent + Education",
        "",
        "| Title | Year | Accepted | Agent | Education | URL |",
        "| --- | ---: | --- | --- | --- | --- |",
    ]
    for row in intersection:
        lines.append(
            f"| {row['title'].replace('|', '\\|')} | {row['year']} | "
            f"{'Yes' if row['accepted_main'] else 'No'} | {row['luna_agent_relevance']} | "
            f"{row['luna_education_relevance']} | [OpenReview]({row['openreview_url']}) |"
        )
    lines.extend(
        [
            "",
            "## Education",
            "",
            "| Title | Year | Accepted | Relevance | URL |",
            "| --- | ---: | --- | --- | --- |",
        ]
    )
    for row in education:
        lines.append(
            f"| {row['title'].replace('|', '\\|')} | {row['year']} | "
            f"{'Yes' if row['accepted_main'] else 'No'} | {row['luna_education_relevance']} | "
            f"[OpenReview]({row['openreview_url']}) |"
        )
    (args.output / "luna_papers.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    if errors:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
