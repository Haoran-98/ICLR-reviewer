#!/usr/bin/env python3
"""Validate and normalize smoke-test LLM results before database ingestion."""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

from python_filter import classify_resolution, classify_score_action


LIMITS = {
    "research_tags": 12,
    "positive_factors": 5,
    "negative_factors": 8,
    "response_outcomes": 8,
    "counterfactuals": 3,
}


def normalize_effectiveness(value) -> str:
    text = str(value or "").lower()
    if any(
        term in text
        for term in (
            "no reaction",
            "not explicitly",
            "unknown",
            "not reported",
            "not assessable",
            "unavailable",
            "unclear",
            "no response",
        )
    ):
        return "unknown"
    if any(term in text for term in ("low-partial", "partial", "moderate", "medium", "limited")):
        return "partial_success"
    if any(
        term in text
        for term in (
            "ineffective",
            "insufficient",
            "unconvinced",
            "did not resolve",
            "unresolved",
            "concerns remained",
            "concerns remain",
            "negative",
            "low;",
        )
    ):
        return "no_effect"
    if any(
        term in text
        for term in (
            "effective",
            "high",
            "strong",
            "substantial",
            "addressed",
            "resolved",
            "positive",
            "sufficiently",
            "satisfactorily",
            "score increase",
            "score update",
        )
    ):
        return "strong_success"
    return "unknown"


def normalize_score_action(value) -> str:
    text = str(value or "").lower()
    if any(
        term in text
        for term in ("intent to raise", "will raise", "promised", "inclined_to_raise", "willing_to_raise")
    ):
        return "promised_increase"
    if "overall maintained" in text:
        return "maintained"
    if re.search(r"\b(increased|raised|upped)\b", text):
        return "increased"
    if any(term in text for term in ("adjusted evaluation positively", "adjusted_score", "improved_score", "updated_score")):
        return "increased"
    if any(term in text for term in ("maintained", "kept", "unchanged")):
        return "maintained"
    if any(term in text for term in ("decreased", "lowered")):
        return "decreased"
    return "unknown"


def normalize_grade(value) -> str:
    text = str(value or "").lower()
    if text in {"a", "b", "c", "d"}:
        return text.upper()
    if any(term in text for term in ("speculative", "future", "not applicable")):
        return "D"
    if any(term in text for term in ("low", "weak", "limited", "claim", "concern", "requested", "observational", "qualitative")):
        return "C"
    if any(term in text for term in ("high", "strong", "direct", "controlled", "large_scale", "large empirical", "multi_dataset")):
        return "A"
    if any(term in text for term in ("moderate", "medium", "empirical", "theor", "evidence", "experiment", "ablation", "benchmark", "supported", "correction", "argument")):
        return "B"
    return "D"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--input-dir",
        type=Path,
        default=Path(__file__).resolve().parent / "output" / "llm",
    )
    parser.add_argument(
        "--manifest",
        type=Path,
        default=Path(__file__).resolve().parent / "output" / "sample_manifest.jsonl",
    )
    parser.add_argument("--prefix", default="")
    parser.add_argument("--local-records", type=Path)
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path(__file__).resolve().parent / "output",
    )
    args = parser.parse_args()

    base = args.output_dir
    base.mkdir(parents=True, exist_ok=True)
    manifest = [
        json.loads(line)
        for line in args.manifest.read_text(encoding="utf-8").splitlines()
    ]
    expected = {row["openreview_id"] for row in manifest}
    local_by_id = {}
    if args.local_records:
        local_payload = json.loads(args.local_records.read_text(encoding="utf-8"))
        local_by_id = {item["openreview_id"]: item for item in local_payload.get("papers", [])}
    items = []
    for path in sorted(args.input_dir.glob("batch_*_result.json")):
        items.extend(json.loads(path.read_text(encoding="utf-8"))["papers"])

    model_returned = [item.get("openreview_id") for item in items]
    python_only = {
        paper_id for paper_id, record in local_by_id.items() if record.get("python_only")
    }
    errors = []
    if len(model_returned) != len(set(model_returned)):
        errors.append("duplicate_openreview_id")
    if set(model_returned) != expected - python_only:
        errors.append("openreview_id_mismatch")
    for paper_id in sorted(python_only):
        items.append(
            {
                "openreview_id": paper_id,
                "research_tags": [],
                "positive_factors": [],
                "negative_factors": [],
                "response_outcomes": [],
                "counterfactuals": [],
                "python_only": True,
            }
        )
    returned = [item.get("openreview_id") for item in items]
    if set(returned) != expected:
        errors.append("final_openreview_id_mismatch")

    truncations = {key: 0 for key in LIMITS}
    normalized = []
    for item in items:
        clean = dict(item)
        for key, limit in LIMITS.items():
            values = list(clean.get(key) or [])
            if len(values) > limit:
                truncations[key] += 1
            clean[key] = values[:limit]
        outcomes = []
        for outcome in clean["response_outcomes"]:
            value = dict(outcome)
            value["effectiveness_raw"] = value.get("effectiveness")
            value["score_action_raw"] = value.get("score_action")
            value["effectiveness"] = normalize_effectiveness(value.get("effectiveness"))
            value["score_action"] = normalize_score_action(value.get("score_action"))
            outcomes.append(value)
        clean["response_outcomes"] = outcomes
        local_record = local_by_id.get(clean.get("openreview_id"), {})
        existing = {
            (
                str(outcome.get("reviewer_id") or "").removeprefix("Reviewer_"),
                outcome.get("score_action"),
            ): outcome
            for outcome in clean["response_outcomes"]
        }
        for event in local_record.get("local_events") or []:
            reviewer_id = str(event.get("reviewer_id") or "").removeprefix("Reviewer_")
            evidence = event.get("evidence_excerpt") or ""
            score_action = classify_score_action(evidence)
            resolution = classify_resolution(evidence)
            effectiveness = {
                "resolved": "strong_success",
                "partial": "partial_success",
                "unresolved": "no_effect",
            }.get(resolution, "unknown")
            key = (reviewer_id, score_action)
            if key in existing:
                existing[key]["effectiveness"] = effectiveness
                existing[key]["local_reconciled"] = True
                existing[key]["source_message_id"] = event.get("source_message_id")
                existing[key]["evidence_excerpt"] = evidence
                continue
            outcome = {
                "reviewer_id": event.get("reviewer_id"),
                "effectiveness": effectiveness,
                "score_action": score_action,
                "confidence": 0.95,
                "source": "python_filter",
                "source_message_id": event.get("source_message_id"),
                "evidence_excerpt": evidence,
            }
            clean["response_outcomes"].append(outcome)
            existing[key] = outcome
        clean["python_facts"] = local_record.get("python_facts") or {}
        counterfactuals = []
        for counterfactual in clean["counterfactuals"]:
            value = dict(counterfactual)
            value["evidence_grade_raw"] = value.get("evidence_grade")
            value["evidence_grade"] = normalize_grade(value.get("evidence_grade"))
            counterfactuals.append(value)
        clean["counterfactuals"] = counterfactuals
        normalized.append(clean)

    payload = {"papers": normalized}
    (base / f"{args.prefix}normalized_results.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    qa = {
        "expected_papers": len(expected),
        "returned_papers": len(items),
        "model_returned_papers": len(model_returned),
        "python_only_papers": len(python_only),
        "unique_ids": len(set(returned)),
        "errors": errors,
        "truncation_violations": truncations,
        "normalized_effectiveness": {
            key: sum(
                outcome["effectiveness"] == key
                for item in normalized
                for outcome in item["response_outcomes"]
            )
            for key in ("strong_success", "partial_success", "no_effect", "unknown")
        },
        "normalized_score_action": {
            key: sum(
                outcome["score_action"] == key
                for item in normalized
                for outcome in item["response_outcomes"]
            )
            for key in ("increased", "promised_increase", "maintained", "decreased", "unknown")
        },
        "python_events_merged": sum(
            outcome.get("source") == "python_filter"
            for item in normalized
            for outcome in item["response_outcomes"]
        ),
        "python_events_reconciled": sum(
            bool(outcome.get("local_reconciled"))
            for item in normalized
            for outcome in item["response_outcomes"]
        ),
    }
    (base / f"{args.prefix}qa_report.json").write_text(
        json.dumps(qa, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps(qa, ensure_ascii=False, indent=2))
    if errors:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
