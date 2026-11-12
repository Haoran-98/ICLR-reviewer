#!/usr/bin/env python3
"""Find the fastest stable paper-level concurrency using real pending papers."""

from __future__ import annotations

import argparse
import json
import statistics
import time
from collections import deque
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from pathlib import Path
from typing import Any

import psycopg

import paper_understanding_pipeline as pipeline


REPORT = pipeline.LOG_DIR / "concurrency_benchmark.json"


def balanced_pending(papers: list[dict[str, Any]], existing: set[int]) -> list[dict[str, Any]]:
    buckets = [deque(), deque(), deque()]
    for paper in papers:
        if paper["paper_id"] in existing:
            continue
        tokens = int(paper.get("token_count") or 0)
        buckets[0 if tokens < 6000 else 1 if tokens < 11000 else 2].append(paper)
    ordered: list[dict[str, Any]] = []
    while any(buckets):
        for bucket in buckets:
            if bucket:
                ordered.append(bucket.popleft())
    return ordered


def percentile(values: list[float], percentile_value: int) -> float:
    return statistics.quantiles(values, n=100, method="inclusive")[percentile_value - 1]


def run_level(
    connection: psycopg.Connection[Any],
    auth: dict[str, str],
    papers: list[dict[str, Any]],
    workers: int,
    fuzzy_threshold: float,
    escalation_threshold: float,
) -> dict[str, Any]:
    started = time.perf_counter()
    results: list[dict[str, Any]] = []
    failures: list[dict[str, Any]] = []
    iterator = iter(papers)
    with ThreadPoolExecutor(max_workers=workers) as executor:
        active: dict[Any, dict[str, Any]] = {}
        for _ in range(workers):
            try:
                paper = next(iterator)
            except StopIteration:
                break
            active[executor.submit(pipeline.process_paper, auth, paper, fuzzy_threshold, escalation_threshold)] = paper
        while active:
            done, _ = wait(active, return_when=FIRST_COMPLETED)
            for future in done:
                paper = active.pop(future)
                try:
                    result = future.result()
                    pipeline.atomic_json(pipeline.checkpoint_path(paper["paper_id"]), pipeline.sanitize_value(result))
                    result["outcome"] = pipeline.upsert_profile(connection, result)
                    pipeline.checkpoint_path(paper["paper_id"]).unlink(missing_ok=True)
                    results.append(result)
                except Exception as error:
                    connection.rollback()
                    failures.append({"paper_id": paper["paper_id"], "error": f"{type(error).__name__}: {error}"})
                try:
                    next_paper = next(iterator)
                except StopIteration:
                    continue
                active[executor.submit(pipeline.process_paper, auth, next_paper, fuzzy_threshold, escalation_threshold)] = next_paper

    wall_seconds = time.perf_counter() - started
    latencies = [float(item["elapsed_seconds"]) for item in results]
    tokens = sum(int(item["tokens"]) for item in results)
    return {
        "workers": workers,
        "papers": len(papers),
        "succeeded": len(results),
        "failed": len(failures),
        "failure_rate": len(failures) / len(papers),
        "wall_seconds": round(wall_seconds, 3),
        "papers_per_hour": round(len(results) / wall_seconds * 3600, 2),
        "tokens_per_second": round(tokens / wall_seconds, 2),
        "median_seconds": round(statistics.median(latencies), 3) if latencies else None,
        "p95_seconds": round(percentile(latencies, 95), 3) if len(latencies) >= 2 else (latencies[0] if latencies else None),
        "max_seconds": round(max(latencies), 3) if latencies else None,
        "over_300_seconds": sum(value > 300 for value in latencies),
        "escalated": sum(bool(item["escalated"]) for item in results),
        "tokens": tokens,
        "failures": failures,
        "paper_ids": [item["paper_id"] for item in results],
    }


def choose_workers(levels: list[dict[str, Any]]) -> int:
    stable = [
        item for item in levels
        if item["failed"] == 0 and item["p95_seconds"] is not None and item["p95_seconds"] <= 900
    ]
    if not stable:
        return min(item["workers"] for item in levels)
    best_rate = max(item["papers_per_hour"] for item in stable)
    near_best = [item for item in stable if item["papers_per_hour"] >= best_rate * 0.95]
    return max(item["workers"] for item in near_best)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--auth", type=Path, default=Path.home() / "auth")
    parser.add_argument("--database-url", default=pipeline.DATABASE_URL)
    parser.add_argument("--levels", default="3,4,5")
    parser.add_argument("--waves", type=int, default=2)
    parser.add_argument("--report", type=Path, default=REPORT)
    parser.add_argument("--fuzzy-threshold", type=float, default=0.70)
    parser.add_argument("--escalation-evidence-threshold", type=float, default=0.60)
    args = parser.parse_args()
    levels = [int(value) for value in args.levels.split(",")]
    if not levels or min(levels) < 1 or max(levels) > pipeline.MAX_WORKERS or args.waves < 1:
        raise SystemExit(f"levels must be between 1 and {pipeline.MAX_WORKERS}; waves must be positive")

    auth = pipeline.understanding.shared.load_auth(args.auth)
    pipeline.understanding.validate_auth(auth)
    if pipeline.current_pid():
        raise SystemExit("stop the full pipeline before benchmarking")

    report: dict[str, Any] = {"started_at": pipeline.utc_now(), "waves": args.waves, "levels": []}
    with psycopg.connect(args.database_url) as connection:
        manifest = pipeline.load_or_create_manifest(connection, 1701)
        existing = set(pipeline.existing_profiles(connection))
        pending = iter(balanced_pending(manifest, existing))
        for workers in levels:
            papers = []
            for _ in range(workers * args.waves):
                try:
                    papers.append(next(pending))
                except StopIteration:
                    break
            if not papers:
                break
            print(f"testing workers={workers} papers={len(papers)}", flush=True)
            result = run_level(
                connection, auth, papers, workers, args.fuzzy_threshold, args.escalation_evidence_threshold
            )
            report["levels"].append(result)
            report["recommended_workers"] = choose_workers(report["levels"])
            pipeline.atomic_json(args.report, report)
            print(json.dumps(result, ensure_ascii=False), flush=True)

    report["finished_at"] = pipeline.utc_now()
    report["recommended_workers"] = choose_workers(report["levels"])
    pipeline.atomic_json(args.report, report)
    print(json.dumps({"report": str(args.report), "recommended_workers": report["recommended_workers"]}, indent=2))


if __name__ == "__main__":
    main()
