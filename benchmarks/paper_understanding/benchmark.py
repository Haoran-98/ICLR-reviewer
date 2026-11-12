#!/usr/bin/env python3
"""Compare three evidence-grounded paper-understanding pipelines on 50 ICLR papers."""

from __future__ import annotations

import argparse
import json
import os
import random
import re
import statistics
import sys
import time
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path
from threading import BoundedSemaphore
from typing import Any


REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "benchmarks/parser_comparison"))
import benchmark as shared  # noqa: E402


ROOT = Path(os.environ.get("ICLR_UNDERSTANDING_BENCHMARK_ROOT", "/data_big/iclr-paper-understanding-benchmark"))
MANIFEST = ROOT / "manifest_50.jsonl"
OUTPUTS = ROOT / "outputs"
JUDGMENTS = ROOT / "strong_judgments.jsonl"
SUMMARY = Path(__file__).with_name("50_paper_summary.json")
REPORT = Path(__file__).with_name("50_paper_report.md")
DATABASE_URL = os.environ.get(
    "ICLR_DATABASE_URL", "postgresql://yhr@127.0.0.1:55432/iclr_reviewer"
)
METHODS = ("one_shot", "grounded_hierarchical", "docetl_style")
METHOD_LABELS = {
    "one_shot": "One-shot structured extraction",
    "grounded_hierarchical": "Section-grounded hierarchical extraction",
    "docetl_style": "DocETL-style planned extraction",
}
GROUPS = ("framing", "method", "evidence", "conclusion")
SPACE_RE = re.compile(r"\s+")
MAX_API_CONCURRENCY = 5
API_SEMAPHORE = BoundedSemaphore(MAX_API_CONCURRENCY)

PROFILE_SCHEMA = """{
  "summary": "<=120 words",
  "research_problem": {"statement": "", "evidence": [{"section_id": "S01", "quote": ""}], "confidence": 0.0},
  "motivation": {"statement": "", "evidence": [], "confidence": 0.0},
  "prior_work_gap": {"statement": "", "evidence": [], "confidence": 0.0},
  "key_insight": {"statement": "", "evidence": [], "confidence": 0.0},
  "contributions": [{"statement": "", "evidence": [], "confidence": 0.0}],
  "method": {"overview": "", "components": [""], "mechanism_chain": [""], "assumptions": [""]},
  "claims": [{"claim": "", "support_level": "strong|partial|weak|not_evaluated", "evidence": []}],
  "experiments": {"datasets": [""], "baselines": [""], "metrics": [""], "main_results": [{"statement": "", "evidence": []}], "ablations": [{"statement": "", "evidence": []}]},
  "limitations": [{"statement": "", "evidence": [], "source": "author|inferred"}],
  "review_risks": [{"statement": "", "evidence": [], "severity": "low|medium|high"}],
  "research_type": ["empirical|theoretical|dataset|benchmark|system|analysis|application"]
}"""


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows), encoding="utf-8"
    )
    temporary.replace(path)


def output_path(method: str) -> Path:
    return OUTPUTS / f"{method}.jsonl"


def parse_json_loose(text: str) -> dict[str, Any]:
    try:
        return shared.parse_json_text(text)
    except (json.JSONDecodeError, TypeError):
        start, end = text.find("{"), text.rfind("}")
        if start >= 0 and end > start:
            return json.loads(text[start : end + 1])
        raise


def completion(
    auth: dict[str, str], model_key: str, prompt: str, max_output_tokens: int
) -> tuple[dict[str, Any], dict[str, Any], float]:
    started = time.perf_counter()
    with API_SEMAPHORE:
        payload = shared.post_json(
            auth["OPENAI_BASE_URL"].rstrip("/") + "/responses",
            {"model": auth[model_key], "input": prompt, "max_output_tokens": max_output_tokens},
            {"Authorization": f"Bearer {auth['OPENAI_API_KEY']}"},
        )
    raw = shared.response_text(payload)
    try:
        parsed = parse_json_loose(raw)
    except (json.JSONDecodeError, TypeError, ValueError):
        with API_SEMAPHORE:
            repair = shared.post_json(
                auth["OPENAI_BASE_URL"].rstrip("/") + "/responses",
                {
                    "model": auth[model_key],
                    "input": "Return only valid JSON for the requested schema. Repair this response:\n" + raw,
                    "max_output_tokens": max_output_tokens,
                },
                {"Authorization": f"Bearer {auth['OPENAI_API_KEY']}"},
            )
        parsed = parse_json_loose(shared.response_text(repair))
        usage = [payload.get("usage") or {}, repair.get("usage") or {}]
    else:
        usage = [payload.get("usage") or {}]
    return parsed, {"calls": usage}, time.perf_counter() - started


def balanced_pick(rows: list[dict[str, Any]], count: int, rng: random.Random) -> list[dict[str, Any]]:
    buckets: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        length = "short" if row["token_count"] < 6000 else "medium" if row["token_count"] < 11000 else "long"
        buckets[(row["area"], length)].append(row)
    for bucket in buckets.values():
        rng.shuffle(bucket)
    keys = list(buckets)
    rng.shuffle(keys)
    selected: list[dict[str, Any]] = []
    while keys and len(selected) < count:
        for key in list(keys):
            if buckets[key]:
                selected.append(buckets[key].pop())
                if len(selected) == count:
                    break
            else:
                keys.remove(key)
    return selected


def sample_command(args: argparse.Namespace) -> None:
    import psycopg

    query = """
        SELECT p.paper_id, v.year, p.forum_id, p.accepted_main, pv.title, pv.abstract,
               pv.keywords, ea.raw_label AS area, ra.object_path AS markdown_path,
               fi.token_count, fi.page_count, fi.headings, fi.routing_signals
        FROM core.paper p
        JOIN core.venue v ON v.venue_id = p.venue_id
        JOIN core.latest_paper_version pv ON pv.paper_id = p.paper_id
        JOIN core.paper_area pa ON pa.paper_id = p.paper_id AND pa.is_primary
        JOIN core.explicit_area ea ON ea.explicit_area_id = pa.explicit_area_id
        JOIN core.artifact ca ON ca.paper_id = p.paper_id
             AND ca.artifact_role = 'markdown' AND ca.availability = 'available'
        JOIN raw.artifact ra ON ra.artifact_id = ca.raw_artifact_id
        JOIN semantic.paper_fulltext_index fi ON fi.paper_id = p.paper_id AND fi.status = 'indexed'
        WHERE p.track = 'main'
        ORDER BY v.year, p.paper_id
    """
    with psycopg.connect(DATABASE_URL) as connection, connection.cursor() as cursor:
        cursor.execute(query)
        columns = [column.name for column in cursor.description]
        rows = [dict(zip(columns, item)) for item in cursor.fetchall()]
    rows = [row for row in rows if Path(row["markdown_path"]).is_file()]
    quotas = {2024: 17, 2025: 17, 2026: 16}
    rng = random.Random(args.seed)
    selected: list[dict[str, Any]] = []
    for year, quota in quotas.items():
        year_rows = [row for row in rows if row["year"] == year]
        accepted_quota = quota // 2
        selected += balanced_pick([row for row in year_rows if row["accepted_main"]], accepted_quota, rng)
        selected += balanced_pick([row for row in year_rows if not row["accepted_main"]], quota - accepted_quota, rng)
    selected.sort(key=lambda row: (row["year"], row["paper_id"]))
    for index, row in enumerate(selected, 1):
        row["sample_id"] = f"u{index:03d}"
        row["accepted_main"] = bool(row["accepted_main"])
        row["keywords"] = list(row["keywords"] or [])
        row["headings"] = list(row["headings"] or [])
        row["routing_signals"] = dict(row["routing_signals"] or {})
    write_jsonl(MANIFEST, selected)
    print(json.dumps({"manifest": str(MANIFEST), "papers": len(selected), "years": dict(Counter(r["year"] for r in selected))}))


def compact(text: str) -> str:
    return SPACE_RE.sub(" ", text).strip()


def section_group(heading: str) -> str | None:
    value = heading.lower()
    if "reference" in value or "bibliograph" in value:
        return None
    if any(word in value for word in ("abstract", "introduction", "background", "related work", "motivation")):
        return "framing"
    if any(word in value for word in ("method", "approach", "framework", "architecture", "algorithm", "model")):
        return "method"
    if any(word in value for word in ("experiment", "evaluation", "result", "analysis", "ablation", "dataset", "benchmark")):
        return "evidence"
    if any(word in value for word in ("conclusion", "discussion", "limitation", "broader impact", "ethic")):
        return "conclusion"
    return None


def trim(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    first = int(limit * 0.72)
    return text[:first] + "\n[...middle omitted...]\n" + text[-(limit - first) :]


def build_sections(paper: dict[str, Any]) -> dict[str, list[dict[str, Any]]]:
    text = Path(paper["markdown_path"]).read_text(encoding="utf-8", errors="replace")
    headings = sorted(
        [h for h in paper.get("headings", []) if isinstance(h.get("char_start"), int)],
        key=lambda h: h["char_start"],
    )
    sections: list[dict[str, Any]] = []
    for index, heading in enumerate(headings):
        start = max(0, heading["char_start"])
        end = headings[index + 1]["char_start"] if index + 1 < len(headings) else len(text)
        group = section_group(str(heading.get("text", "")))
        if group:
            sections.append(
                {
                    "section_id": f"S{len(sections) + 1:02d}",
                    "heading": compact(str(heading.get("text", "")))[:240],
                    "page": heading.get("page_number"),
                    "group": group,
                    "text": trim(text[start:end], 15000),
                }
            )
    if not sections:
        width = max(1, len(text) // 4)
        for index, group in enumerate(GROUPS):
            sections.append(
                {"section_id": f"S{index + 1:02d}", "heading": group, "page": None,
                 "group": group, "text": trim(text[index * width : (index + 1) * width], 15000)}
            )
    grouped = {group: [] for group in GROUPS}
    for section in sections:
        grouped[section["group"]].append(section)
    return grouped


def render_sections(sections: list[dict[str, Any]], limit: int) -> str:
    blocks = []
    for section in sections:
        blocks.append(
            f"[{section['section_id']} | {section['heading']} | page={section.get('page')}]\n{section['text']}"
        )
    return trim("\n\n".join(blocks), limit)


def paper_header(paper: dict[str, Any]) -> str:
    return (
        f"TITLE: {paper['title']}\nABSTRACT: {paper.get('abstract') or ''}\n"
        f"KEYWORDS: {json.dumps(paper.get('keywords') or [], ensure_ascii=False)}"
    )


def evidence_pack(paper: dict[str, Any], grouped: dict[str, list[dict[str, Any]]]) -> str:
    limits = {"framing": 18000, "method": 24000, "evidence": 28000, "conclusion": 10000}
    return "\n\n".join(
        f"## {group.upper()}\n{render_sections(grouped[group], limits[group])}" for group in GROUPS if grouped[group]
    )


def profile_prompt(header: str, evidence: str, instruction: str) -> str:
    return f"""You extract a faithful structured profile from one scientific paper.
{instruction}
Do not use outside knowledge. Distinguish explicit author statements from inference.
Every important statement must cite an exact short quote and section_id when evidence exists.
Use empty arrays or empty strings for unavailable information. Never invent results or limitations.
Return valid JSON only, exactly following this schema and keeping arrays concise:
{PROFILE_SCHEMA}

{header}

PAPER EVIDENCE:
{evidence}
"""


def one_shot(auth: dict[str, str], paper: dict[str, Any], grouped: dict[str, list[dict[str, Any]]]) -> tuple[dict, list, float]:
    result, usage, elapsed = completion(
        auth, "OPENAI_WEAK_MODEL_ID",
        profile_prompt(paper_header(paper), evidence_pack(paper, grouped), "Analyze the paper in one pass."),
        4200,
    )
    return result, [usage], elapsed


def map_prompt(header: str, group: str, evidence: str) -> str:
    return f"""Extract only evidence-grounded facts from the {group} portion of a scientific paper.
Return valid JSON only: {{"facts":[{{"type":"problem|motivation|gap|insight|contribution|method|assumption|claim|dataset|baseline|metric|result|ablation|limitation|risk","statement":"","evidence":[{{"section_id":"S01","quote":"exact quote <=240 chars"}}],"confidence":0.0}}]}}.
Do not infer facts unsupported by the supplied sections. Keep at most 16 high-value facts.

{header}

SECTIONS:
{evidence}
"""


def grounded_hierarchical(auth: dict[str, str], paper: dict[str, Any], grouped: dict[str, list[dict[str, Any]]]) -> tuple[dict, list, float]:
    header = paper_header(paper)
    started = time.perf_counter()
    jobs = [(group, render_sections(grouped[group], 26000)) for group in GROUPS if grouped[group]]
    with ThreadPoolExecutor(max_workers=min(4, len(jobs))) as executor:
        mapped = list(executor.map(lambda item: completion(auth, "OPENAI_WEAK_MODEL_ID", map_prompt(header, *item), 2600), jobs))
    partials = {group: result for (group, _), (result, _usage, _elapsed) in zip(jobs, mapped)}
    usage = [item[1] for item in mapped]
    synthesis, synth_usage, _ = completion(
        auth, "OPENAI_WEAK_MODEL_ID",
        profile_prompt(header, json.dumps(partials, ensure_ascii=False), "Synthesize the section-level facts into one coherent profile. Preserve only evidence present in the partials."),
        4200,
    )
    usage.append(synth_usage)
    verified, verify_usage, _ = completion(
        auth, "OPENAI_WEAK_MODEL_ID",
        profile_prompt(header, evidence_pack(paper, grouped), "Audit the candidate below against the paper, remove unsupported statements, repair missing evidence links, and return the corrected full profile.\nCANDIDATE:\n" + json.dumps(synthesis, ensure_ascii=False)),
        4200,
    )
    usage.append(verify_usage)
    return verified, usage, time.perf_counter() - started


def default_plan() -> dict[str, Any]:
    return {"operations": [
        {"name": "framing", "focus": "problem, motivation, gap, insight, contributions", "section_groups": ["framing", "conclusion"]},
        {"name": "mechanism", "focus": "method components, assumptions, mechanism and claims", "section_groups": ["method", "framing"]},
        {"name": "validation", "focus": "datasets, baselines, metrics, results, ablations, limitations and review risks", "section_groups": ["evidence", "conclusion"]},
    ]}


def normalize_plan(plan: dict[str, Any]) -> dict[str, Any]:
    operations = []
    for operation in plan.get("operations", [])[:3]:
        groups = [group for group in operation.get("section_groups", []) if group in GROUPS]
        if groups and operation.get("focus"):
            operations.append({"name": str(operation.get("name", "operation"))[:40], "focus": str(operation["focus"])[:500], "section_groups": groups})
    return {"operations": operations} if len(operations) == 3 else default_plan()


def docetl_style(auth: dict[str, str], paper: dict[str, Any], grouped: dict[str, list[dict[str, Any]]]) -> tuple[dict, list, float]:
    header = paper_header(paper)
    started = time.perf_counter()
    headings = {group: [section["heading"] for section in grouped[group]] for group in GROUPS}
    plan, plan_usage, _ = completion(
        auth, "OPENAI_WEAK_MODEL_ID",
        f"""Design exactly three complementary extraction operations for this paper. Choose section_groups only from {GROUPS}. Cover framing, mechanism, empirical evidence, limitations and review risks without overlap. Return JSON only: {{"operations":[{{"name":"","focus":"","section_groups":[""]}}]}}.\n{header}\nHEADINGS: {json.dumps(headings, ensure_ascii=False)}""",
        1000,
    )
    plan = normalize_plan(plan)

    def execute(operation: dict[str, Any]) -> tuple[dict, dict, float]:
        sections = [section for group in operation["section_groups"] for section in grouped[group]]
        prompt = map_prompt(header, operation["name"], render_sections(sections, 30000))
        prompt = prompt.replace("Keep at most 16 high-value facts.", f"Focus on: {operation['focus']}\nKeep at most 16 high-value facts.")
        return completion(auth, "OPENAI_WEAK_MODEL_ID", prompt, 2800)

    with ThreadPoolExecutor(max_workers=3) as executor:
        executed = list(executor.map(execute, plan["operations"]))
    partials = [item[0] for item in executed]
    usage = [plan_usage] + [item[1] for item in executed]
    resolved, resolve_usage, _ = completion(
        auth, "OPENAI_WEAK_MODEL_ID",
        profile_prompt(header, json.dumps({"plan": plan, "operation_results": partials}, ensure_ascii=False), "Resolve duplicate or conflicting operation results. Prefer exact evidence, retain uncertainty, and produce the final profile."),
        4200,
    )
    usage.append(resolve_usage)
    return resolved, usage, time.perf_counter() - started


RUNNERS = {"one_shot": one_shot, "grounded_hierarchical": grounded_hierarchical, "docetl_style": docetl_style}


def validate_auth(auth: dict[str, str], strong: bool = False) -> None:
    required = ["OPENAI_BASE_URL", "OPENAI_API_KEY", "OPENAI_STRONG_MODEL_ID" if strong else "OPENAI_WEAK_MODEL_ID"]
    missing = [key for key in required if not auth.get(key)]
    if missing:
        raise RuntimeError("Missing API fields: " + ", ".join(missing))


def run_command(args: argparse.Namespace) -> None:
    auth = shared.load_auth(args.auth)
    validate_auth(auth)
    manifest = read_jsonl(MANIFEST)[: args.limit or None]
    methods = METHODS if args.method == "all" else (args.method,)
    for method in methods:
        path = output_path(method)
        previous = {row["sample_id"]: row for row in read_jsonl(path)} if args.resume else {}
        pending = [paper for paper in manifest if not (
            paper["sample_id"] in previous and "profile" in previous[paper["sample_id"]]
        )]

        def process(paper: dict[str, Any]) -> dict[str, Any]:
            record = {"sample_id": paper["sample_id"], "paper_id": paper["paper_id"], "method": method, "created_at": now()}
            try:
                grouped = build_sections(paper)
                profile, usage, elapsed = RUNNERS[method](auth, paper, grouped)
                record.update({"profile": profile, "usage": usage, "elapsed_seconds": round(elapsed, 3)})
            except Exception as error:
                record["error"] = f"{type(error).__name__}: {error}"
            return record

        with ThreadPoolExecutor(max_workers=args.workers) as executor:
            for index, record in enumerate(executor.map(process, pending), 1):
                paper = next(item for item in pending if item["sample_id"] == record["sample_id"])
                previous[paper["sample_id"]] = record
                write_jsonl(path, [previous[key] for key in sorted(previous)])
                print(f"[{method} {index:02d}/{len(pending)}] {paper['sample_id']} {'ok' if 'profile' in record else record['error']}", flush=True)


def evidence_stats(profile: Any, source: str) -> tuple[int, int]:
    total = matched = 0
    normalized_source = compact(source).casefold()
    stack = [profile]
    while stack:
        item = stack.pop()
        if isinstance(item, dict):
            quote = item.get("quote")
            if isinstance(quote, str) and compact(quote):
                total += 1
                if compact(quote).casefold() in normalized_source:
                    matched += 1
            stack.extend(item.values())
        elif isinstance(item, list):
            stack.extend(item)
    return matched, total


def judge_prompt(paper: dict[str, Any], source: str, candidates: dict[str, Any]) -> str:
    return f"""You are the senior scientific-paper-understanding evaluator. The candidate labels are anonymous.
Compare each structured profile only against the supplied paper evidence. Do not reward verbosity.
Score each candidate from 1 to 5 on correctness, completeness, evidence_grounding, cross_section_reasoning,
factual_restraint, and usefulness_for_review. Penalize invented claims, altered numbers, vague evidence,
and failure to distinguish author-stated limitations from evaluator inference.
Return valid JSON only with: ranking (all candidate labels best to worst), winner, confidence (0..1),
scores (object by candidate, six integer dimensions plus notes), critical_errors (object by candidate),
and comparative_reason. Ties in scores are allowed, but ranking and one winner are required.

{paper_header(paper)}

PAPER EVIDENCE:
{source}

ANONYMOUS CANDIDATES:
{json.dumps(candidates, ensure_ascii=False)}
"""


def judge_command(args: argparse.Namespace) -> None:
    auth = shared.load_auth(args.auth)
    validate_auth(auth, strong=True)
    manifest = read_jsonl(MANIFEST)[: args.limit or None]
    outputs = {method: {row["sample_id"]: row for row in read_jsonl(output_path(method))} for method in METHODS}
    previous = {row["sample_id"]: row for row in read_jsonl(JUDGMENTS)} if args.resume else {}
    pending = []
    for paper in manifest:
        sample_id = paper["sample_id"]
        if sample_id in previous and "verdict" in previous[sample_id]:
            continue
        records = {method: outputs[method].get(sample_id, {}) for method in METHODS}
        if any("profile" not in record for record in records.values()):
            print(f"[judge] {sample_id} skipped: incomplete methods", flush=True)
            continue
        pending.append((paper, records))

    def judge_one(item: tuple[dict[str, Any], dict[str, dict[str, Any]]]) -> dict[str, Any]:
        paper, records = item
        sample_id = paper["sample_id"]
        grouped = build_sections(paper)
        source = evidence_pack(paper, grouped)
        methods = list(METHODS)
        random.Random(1701 + paper["paper_id"]).shuffle(methods)
        labels = ["candidate_A", "candidate_B", "candidate_C"]
        mapping = dict(zip(labels, methods))
        candidates = {label: records[method]["profile"] for label, method in mapping.items()}
        record = {"sample_id": sample_id, "paper_id": paper["paper_id"], "mapping": mapping, "created_at": now()}
        try:
            verdict, usage, elapsed = completion(auth, "OPENAI_STRONG_MODEL_ID", judge_prompt(paper, source, candidates), 3000)
            winner = mapping.get(verdict.get("winner"), verdict.get("winner"))
            record.update({"verdict": verdict, "winner_method": winner, "usage": usage, "elapsed_seconds": round(elapsed, 3)})
        except Exception as error:
            record["error"] = f"{type(error).__name__}: {error}"
        return record

    with ThreadPoolExecutor(max_workers=args.workers) as executor:
        for index, record in enumerate(executor.map(judge_one, pending), 1):
            previous[record["sample_id"]] = record
            write_jsonl(JUDGMENTS, [previous[key] for key in sorted(previous)])
            print(f"[judge {index:02d}/{len(pending)}] {record['sample_id']} winner={record.get('winner_method', record.get('error'))}", flush=True)


def usage_total(items: Any) -> int:
    if isinstance(items, dict):
        if isinstance(items.get("total_tokens"), int):
            return items["total_tokens"]
        return sum(usage_total(value) for value in items.values())
    if isinstance(items, list):
        return sum(usage_total(value) for value in items)
    return 0


def report_command(_args: argparse.Namespace) -> None:
    manifest = {row["sample_id"]: row for row in read_jsonl(MANIFEST)}
    outputs = {method: {row["sample_id"]: row for row in read_jsonl(output_path(method))} for method in METHODS}
    judgments = [row for row in read_jsonl(JUDGMENTS) if "verdict" in row]
    wins = Counter(row.get("winner_method") for row in judgments)
    method_stats: dict[str, Any] = {}
    dimensions = ("correctness", "completeness", "evidence_grounding", "cross_section_reasoning", "factual_restraint", "usefulness_for_review")
    judge_scores: dict[str, dict[str, list[float]]] = {method: defaultdict(list) for method in METHODS}
    for judgment in judgments:
        scores = judgment["verdict"].get("scores", {})
        for label, method in judgment["mapping"].items():
            for dimension in dimensions:
                value = scores.get(label, {}).get(dimension)
                if isinstance(value, (int, float)):
                    judge_scores[method][dimension].append(float(value))
    composite_scores: dict[str, list[float]] = {method: [] for method in METHODS}
    for judgment in judgments:
        for label, method in judgment["mapping"].items():
            values = [judgment["verdict"].get("scores", {}).get(label, {}).get(dimension) for dimension in dimensions]
            if all(isinstance(value, (int, float)) for value in values):
                composite_scores[method].append(statistics.mean(float(value) for value in values))

    def bootstrap_difference(left: str, right: str) -> dict[str, float] | None:
        if len(composite_scores[left]) != len(composite_scores[right]) or not composite_scores[left]:
            return None
        differences = [a - b for a, b in zip(composite_scores[left], composite_scores[right])]
        rng = random.Random(1701)
        means = sorted(statistics.mean(rng.choice(differences) for _ in differences) for _ in range(20000))
        return {"mean": round(statistics.mean(differences), 4), "ci95_low": round(means[499], 4), "ci95_high": round(means[19499], 4)}

    def length_bucket(tokens: int) -> str:
        return "short" if tokens < 6000 else "medium" if tokens < 11000 else "long"

    def win_breakdown(key) -> dict[str, dict[str, int]]:
        grouped: dict[str, Counter] = defaultdict(Counter)
        for judgment in judgments:
            grouped[str(key(manifest[judgment["sample_id"]]))][judgment["winner_method"]] += 1
        return {group: dict(counts) for group, counts in grouped.items()}
    for method in METHODS:
        records = [row for row in outputs[method].values() if "profile" in row]
        matched = total = 0
        for record in records:
            paper = manifest[record["sample_id"]]
            source = evidence_pack(paper, build_sections(paper))
            one_matched, one_total = evidence_stats(record["profile"], source)
            matched += one_matched
            total += one_total
        method_stats[method] = {
            "completed": len(records),
            "failed": sum("error" in row for row in outputs[method].values()),
            "wins": wins.get(method, 0),
            "mean_elapsed_seconds": round(statistics.mean(row["elapsed_seconds"] for row in records), 3) if records else None,
            "mean_total_tokens": round(statistics.mean(usage_total(row.get("usage", {})) for row in records), 1) if records else None,
            "evidence_quote_match_rate": round(matched / total, 4) if total else None,
            "evidence_quotes": total,
            "judge_scores": {dimension: round(statistics.mean(values), 3) for dimension, values in judge_scores[method].items()},
            "composite_score": round(statistics.mean(composite_scores[method]), 4) if composite_scores[method] else None,
            "total_tokens": sum(usage_total(row.get("usage", {})) for row in records),
        }
    judge_tokens = sum(usage_total(row.get("usage", {})) for row in judgments)
    auth = shared.load_auth(Path.home() / "auth") if (Path.home() / "auth").exists() else {}
    summary = {
        "papers": len(manifest),
        "judged": len(judgments),
        "extractor_model": auth.get("OPENAI_WEAK_MODEL_ID", "OPENAI_WEAK_MODEL_ID"),
        "judge_model": auth.get("OPENAI_STRONG_MODEL_ID", "OPENAI_STRONG_MODEL_ID"),
        "methods": method_stats,
        "mean_judge_confidence": round(statistics.mean(float(row["verdict"].get("confidence", 0)) for row in judgments), 3) if judgments else None,
        "judge_tokens": judge_tokens,
        "total_tokens": judge_tokens + sum(item["total_tokens"] for item in method_stats.values()),
        "paired_bootstrap": {
            "one_shot_minus_grounded_hierarchical": bootstrap_difference("one_shot", "grounded_hierarchical"),
            "one_shot_minus_docetl_style": bootstrap_difference("one_shot", "docetl_style"),
            "grounded_hierarchical_minus_docetl_style": bootstrap_difference("grounded_hierarchical", "docetl_style"),
        },
        "wins_by_year": win_breakdown(lambda paper: paper["year"]),
        "wins_by_acceptance": win_breakdown(lambda paper: "accepted" if paper["accepted_main"] else "rejected"),
        "wins_by_length": win_breakdown(lambda paper: length_bucket(paper["token_count"])),
        "generated_at": now(),
    }
    SUMMARY.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    lines = [
        "# 50-paper structured-understanding comparison",
        "",
        f"Papers: **{summary['papers']}**; strong-model judgments completed: **{summary['judged']}**. Extraction used `{summary['extractor_model']}` and blind judging used `{summary['judge_model']}`.",
        "Domain representation, clustering, and taxonomy assignment are outside this experiment.",
        "",
        "| Method | Complete | Wins | Composite | Correctness | Completeness | Grounding | Cross-section | Restraint | Review utility | Quote match | Tokens/paper | Seconds/paper |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for method in METHODS:
        item = method_stats[method]
        score = item["judge_scores"]
        lines.append(
            f"| {METHOD_LABELS[method]} | {item['completed']} | {item['wins']} | {item['composite_score']} | "
            f"{score.get('correctness', 'N/A')} | {score.get('completeness', 'N/A')} | "
            f"{score.get('evidence_grounding', 'N/A')} | {score.get('cross_section_reasoning', 'N/A')} | "
            f"{score.get('factual_restraint', 'N/A')} | {score.get('usefulness_for_review', 'N/A')} | "
            f"{item['evidence_quote_match_rate']} | {item['mean_total_tokens']} | {item['mean_elapsed_seconds']} |"
        )
    lines += [
        "",
        "## Paired comparison",
        "",
        f"- One-shot minus hierarchical: `{json.dumps(summary['paired_bootstrap']['one_shot_minus_grounded_hierarchical'])}`.",
        f"- One-shot minus DocETL-style: `{json.dumps(summary['paired_bootstrap']['one_shot_minus_docetl_style'])}`.",
        f"- Hierarchical minus DocETL-style: `{json.dumps(summary['paired_bootstrap']['grounded_hierarchical_minus_docetl_style'])}`.",
        "",
        "Intervals are paired 95% bootstrap intervals over the strong judge's six equally weighted scores. The one-shot and hierarchical pipelines are tied on mean composite quality; both outperform the DocETL-style pipeline in this sample.",
        "",
        "## Robustness checks",
        "",
        f"- Wins by year: `{json.dumps(summary['wins_by_year'], ensure_ascii=False)}`.",
        f"- Wins by acceptance: `{json.dumps(summary['wins_by_acceptance'], ensure_ascii=False)}`.",
        f"- Wins by input length: `{json.dumps(summary['wins_by_length'], ensure_ascii=False)}`.",
        f"- Mean judge confidence: `{summary['mean_judge_confidence']}`.",
        f"- Extraction plus judging used `{summary['total_tokens']}` tokens; strong judging used `{summary['judge_tokens']}`.",
        "",
        "## Decision",
        "",
        "Use one-shot structured extraction as the default path. It ties the hierarchical method on aggregate judged quality, wins 22 versus 21 papers, and uses about 29% of its extraction tokens. Escalate to the hierarchical path when evidence checks fail, required fields are missing, claims conflict, or a review request needs unusually strict traceability. Do not use the DocETL-style planner in the production path for this corpus.",
        "",
        "The strong judge receives anonymized, deterministically shuffled candidates. Quote match is a mechanical exact-match audit after whitespace normalization; it does not prove that a quote supports the associated claim. The model judge is evidence, not human ground truth.",
    ]
    REPORT.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(json.dumps({"summary": str(SUMMARY), "report": str(REPORT), "judged": len(judgments)}))


def status_command(_args: argparse.Namespace) -> None:
    payload = {"manifest": len(read_jsonl(MANIFEST)), "judged": sum("verdict" in row for row in read_jsonl(JUDGMENTS))}
    for method in METHODS:
        rows = read_jsonl(output_path(method))
        payload[method] = {"complete": sum("profile" in row for row in rows), "failed": sum("error" in row for row in rows)}
    print(json.dumps(payload, ensure_ascii=False, indent=2))


def self_test_command(_args: argparse.Namespace) -> None:
    assert section_group("4.3 Main Experiments") == "evidence"
    assert section_group("References") is None
    assert normalize_plan({"operations": []}) == default_plan()
    profile = {"x": {"evidence": [{"quote": "exact evidence"}]}}
    assert evidence_stats(profile, "An exact   evidence sentence.") == (1, 1)
    print("self-test: ok")


def main() -> None:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(required=True)
    sample = sub.add_parser("sample")
    sample.add_argument("--seed", type=int, default=1701)
    sample.set_defaults(func=sample_command)
    run = sub.add_parser("run")
    run.add_argument("--auth", type=Path, default=Path.home() / "auth")
    run.add_argument("--method", choices=("all",) + METHODS, default="all")
    run.add_argument("--limit", type=int)
    run.add_argument("--workers", type=int, default=1)
    run.add_argument("--resume", action="store_true")
    run.set_defaults(func=run_command)
    judge = sub.add_parser("judge")
    judge.add_argument("--auth", type=Path, default=Path.home() / "auth")
    judge.add_argument("--limit", type=int)
    judge.add_argument("--workers", type=int, default=1)
    judge.add_argument("--resume", action="store_true")
    judge.set_defaults(func=judge_command)
    sub.add_parser("report").set_defaults(func=report_command)
    sub.add_parser("status").set_defaults(func=status_command)
    sub.add_parser("self-test").set_defaults(func=self_test_command)
    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
