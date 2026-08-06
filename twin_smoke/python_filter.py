#!/usr/bin/env python3
"""Apply deterministic main-track filters before paid LLM processing."""

from __future__ import annotations

import argparse
import json
import math
import re
from pathlib import Path

from run_llm_smoke import OUTPUT_INSTRUCTIONS
from smoke_test import SYSTEM_PROMPT, compact_payload, token_count
from token_utils import get_encoder


SCORE_TERMS = re.compile(r"\b(score|rating|accept|reject|threshold)\b", re.I)
CONTENT_TERMS = re.compile(
    r"\b(concern|experiment|result|baseline|novel|method|theor|proof|analysis|"
    r"clarif|address|resolve|comparison|dataset|evaluation|ablation)\b",
    re.I,
)
REMINDER_TERMS = re.compile(
    r"last day|discussion period|please actively check|prompt responses are important|"
    r"thank you for your efforts and contribution to iclr",
    re.I,
)
AUTHOR_NUDGE = re.compile(
    r"kindly ask.*(update|adjust|raise).*score|consider adjusting the score|"
    r"looking forward to your response",
    re.I | re.S,
)


def normalize_space(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def clean_message(text: str, seen: set[str]) -> tuple[str, dict[str, int]]:
    stats = {
        "quoted_lines": 0,
        "table_lines": 0,
        "reference_blocks": 0,
        "duplicate_paragraphs": 0,
        "courtesy_paragraphs": 0,
        "truncated": 0,
    }
    lines = []
    for line in (text or "").splitlines():
        if line.lstrip().startswith(">"):
            stats["quoted_lines"] += 1
            continue
        lines.append(line)
    compacted_lines = []
    index = 0
    while index < len(lines):
        if (
            index + 1 < len(lines)
            and "|" in lines[index]
            and re.search(r"\|?\s*:?-{3,}:?\s*\|", lines[index + 1])
        ):
            header = normalize_space(lines[index])[:240]
            end = index + 2
            while end < len(lines) and "|" in lines[end]:
                end += 1
            stats["table_lines"] += end - index
            compacted_lines.append(f"[Markdown table omitted locally: {end - index - 2} data rows; header: {header}]")
            index = end
            continue
        compacted_lines.append(lines[index])
        index += 1
    paragraphs = re.split(r"\n\s*\n", "\n".join(compacted_lines))
    kept = []
    for paragraph in paragraphs:
        paragraph = paragraph.strip()
        if not paragraph:
            continue
        compact = normalize_space(paragraph)
        citation_lines = sum(
            bool(re.match(r"^\s*(?:\[\d+\]|\d+[\.\)])\s+", line))
            for line in paragraph.splitlines()
        )
        if len(compact) > 400 and (
            re.match(r"^(references|bibliography)\b", compact, re.I) or citation_lines >= 3
        ):
            stats["reference_blocks"] += 1
            kept.append(f"[Reference list omitted locally: {max(citation_lines, 1)} entries]")
            continue
        fingerprint = compact.lower()
        if fingerprint in seen:
            stats["duplicate_paragraphs"] += 1
            continue
        seen.add(fingerprint)
        courtesy = (
            len(compact) <= 160
            and not SCORE_TERMS.search(compact)
            and not CONTENT_TERMS.search(compact)
            and re.search(r"^(dear\b|thank you\b|thanks\b|best regards\b|sincerely\b|authors\.?$)", compact, re.I)
        )
        if courtesy:
            stats["courtesy_paragraphs"] += 1
            continue
        kept.append(paragraph)
    cleaned = "\n\n".join(kept)
    if len(cleaned) > 12000:
        cleaned = cleaned[:9000] + "\n\n[...locally truncated...]\n\n" + cleaned[-3000:]
        stats["truncated"] = 1
    return cleaned, stats


def classify_score_action(text: str) -> str:
    value = normalize_space(text).lower()
    if re.search(r"(cannot|can't|will not|won't|unable to) raise|cannot increase", value):
        return "maintained"
    if re.search(r"will raise.*(once|when)|intend to raise|plan to (raise|increase)", value):
        return "promised_increase"
    if re.search(r"\b(raised|increase[sd]?|upped|revised|adjusted) (my |the )?(score|rating)\b", value):
        return "increased"
    if re.search(
        r"\b(maintain|maintained|keep|kept) (my |the |our )?(score|rating)\b|"
        r"score remains|rating remains|stand by my scores?|maintain my original score|"
        r"score (?:is |was )?unchanged|not changed the score",
        value,
    ):
        return "maintained"
    if re.search(r"\b(lowered|decreased|reduce[sd]?) (my |the )?(score|rating)\b", value):
        return "decreased"
    return "unknown"


def classify_resolution(text: str) -> str:
    value = normalize_space(text).lower()
    partial = re.search(
        r"partially addressed|(?:some|most|part of) (?:of )?(?:my )?concerns?.*addressed|"
        r"addressed (?:some|most|part of) (?:of )?(?:my )?concerns?",
        value,
    )
    residual = re.search(
        r"\bbut\b|\bhowever\b|\bstill\b|remain|reservation|not fully|not convinced|"
        r"insufficient|only partial",
        value,
    )
    if partial and residual:
        return "partial"
    if re.search(
        r"haven't (?:been |be )?(?:fully )?addressed|hasn't (?:been )?(?:fully )?addressed|"
        r"have not (?:been )?(?:fully )?addressed|has not (?:been )?(?:fully )?addressed|"
        r"not fully addressed|insufficiently addressed|(?:major|core|most) concerns? remain|"
        r"concerns? (?:still )?remain|unresolved|not (?:very )?convinced",
        value,
    ):
        return "unresolved"
    if partial:
        return "partial"
    if re.search(
        r"all (?:of )?my concerns?.*(?:addressed|resolved)|"
        r"concerns?.*(?:fully|sufficiently|satisfactorily) (?:addressed|resolved)|"
        r"(?:fully|sufficiently|satisfactorily) (?:addressed|resolved).*concerns?|"
        r"no remaining concerns?|resolved my (?:issue|question)",
        value,
    ):
        return "resolved"
    return "unknown"


def filtered_payload(paper: dict) -> tuple[dict | None, dict]:
    if paper.get("track") != "main":
        return None, {"excluded_workshop": 1}

    payload = compact_payload(paper)
    seen = set()
    local_events = []
    ambiguous = []
    counters = {
        "excluded_workshop": 0,
        "dropped_reminders": 0,
        "dropped_author_nudges": 0,
        "locally_classified_comments": 0,
        "quoted_lines": 0,
        "table_lines": 0,
        "reference_blocks": 0,
        "duplicate_paragraphs": 0,
        "courtesy_paragraphs": 0,
        "truncated_messages": 0,
    }

    for message in payload["discussion"]:
        raw = message.get("comment") or ""
        cleaned, stats = clean_message(raw, seen)
        counters["quoted_lines"] += stats["quoted_lines"]
        counters["table_lines"] += stats["table_lines"]
        counters["reference_blocks"] += stats["reference_blocks"]
        counters["duplicate_paragraphs"] += stats["duplicate_paragraphs"]
        counters["courtesy_paragraphs"] += stats["courtesy_paragraphs"]
        counters["truncated_messages"] += stats["truncated"]
        if not cleaned:
            continue
        if message.get("kind") == "reviewer_comments" and REMINDER_TERMS.search(cleaned) and not SCORE_TERMS.search(cleaned):
            counters["dropped_reminders"] += 1
            continue
        if message.get("kind") == "rebuttals" and AUTHOR_NUDGE.search(cleaned) and not CONTENT_TERMS.search(cleaned):
            counters["dropped_author_nudges"] += 1
            continue

        score_action = classify_score_action(cleaned)
        resolution = classify_resolution(cleaned)
        if message.get("kind") == "reviewer_comments" and (
            score_action != "unknown" or resolution != "unknown"
        ):
            signature = message.get("signature") or ""
            local_events.append(
                {
                    "reviewer_id": signature.rsplit("/", 1)[-1] or None,
                    "score_action": score_action,
                    "concern_resolution": resolution,
                    "replyto": message.get("replyto"),
                    "source_message_id": message.get("id"),
                    "evidence_excerpt": normalize_space(cleaned)[:800],
                }
            )
            counters["locally_classified_comments"] += 1
            continue
        compact = {key: value for key, value in message.items() if key != "comment"}
        compact["comment"] = cleaned
        ambiguous.append(compact)

    payload["discussion"] = ambiguous
    payload["local_events"] = local_events
    payload["python_facts"] = {
        "review_count": len(paper.get("reviews") or []),
        "rebuttal_count": len(paper.get("rebuttals") or []),
        "reviewer_comment_count": len(paper.get("reviewer_comments") or []),
        "review_statistics": paper.get("review_statistics") or {},
    }
    has_semantic_evidence = bool(payload["reviews"] or payload["discussion"] or payload["local_events"])
    return (payload if has_semantic_evidence else None), counters


def pack_batches(papers: list[dict], encoder, max_tokens: int) -> list[list[dict]]:
    bins = []
    weighted = sorted(
        ((token_count(encoder, paper), paper) for paper in papers),
        reverse=True,
        key=lambda item: item[0],
    )
    for tokens, paper in weighted:
        placed = False
        for batch in bins:
            if batch["tokens"] + tokens <= max_tokens:
                batch["papers"].append(paper)
                batch["tokens"] += tokens
                placed = True
                break
        if not placed:
            bins.append({"tokens": tokens, "papers": [paper]})
    return [batch["papers"] for batch in bins]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--manifest",
        type=Path,
        default=Path(__file__).resolve().parent / "output" / "sample_manifest.jsonl",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path(__file__).resolve().parent / "output" / "main_filtered",
    )
    parser.add_argument("--batch-tokens", type=int, default=180000)
    args = parser.parse_args()

    encoder = get_encoder()
    rows = [json.loads(line) for line in args.manifest.read_text(encoding="utf-8").splitlines()]
    rows = [row for row in rows if row.get("track_group") == "main"]
    payloads = []
    local_records = []
    totals = {}
    before_tokens = 0
    python_only = 0
    for row in rows:
        with Path(row["path"]).open(encoding="utf-8") as handle:
            paper = json.load(handle)
        before_tokens += token_count(encoder, compact_payload(paper))
        payload, counters = filtered_payload(paper)
        for key, value in counters.items():
            totals[key] = totals.get(key, 0) + value
        if payload is None:
            python_only += 1
            local_records.append(
                {
                    "openreview_id": paper.get("openreview_id"),
                    "python_only": True,
                    "local_events": [],
                    "python_facts": {
                        "review_count": len(paper.get("reviews") or []),
                        "rebuttal_count": len(paper.get("rebuttals") or []),
                        "reviewer_comment_count": len(paper.get("reviewer_comments") or []),
                        "review_statistics": paper.get("review_statistics") or {},
                    },
                }
            )
        else:
            payloads.append(payload)
            local_records.append(
                {
                    "openreview_id": payload["paper"].get("openreview_id"),
                    "python_only": False,
                    "local_events": payload.get("local_events") or [],
                    "python_facts": payload.get("python_facts") or {},
                }
            )

    batches = pack_batches(payloads, encoder, args.batch_tokens)
    args.output.mkdir(parents=True, exist_ok=True)
    batch_dir = args.output / "batches"
    batch_dir.mkdir(exist_ok=True)
    prompt_tokens = 0
    for index, papers in enumerate(batches, start=1):
        prompt = {
            "system": SYSTEM_PROMPT,
            "task": {
                "research_profile": ["domains", "methods", "contribution_types", "evidence_tags"],
                "review_analysis": ["positive_factors", "negative_factors", "unresolved_concerns"],
                "response_events": ["reviewer_id", "effectiveness", "score_action", "confidence"],
                "counterfactuals": ["treatment", "outcome", "assumptions", "evidence_grade", "confidence"],
                "local_events_are_facts": True,
            },
            "output_instructions": OUTPUT_INSTRUCTIONS,
            "papers": papers,
        }
        prompt_tokens += token_count(encoder, prompt)
        (batch_dir / f"batch_{index:02d}_prompt.json").write_text(
            json.dumps(prompt, ensure_ascii=False, separators=(",", ":")), encoding="utf-8"
        )

    filtered_payload_tokens = sum(token_count(encoder, payload) for payload in payloads)
    report = {
        "scope": "ICLR main track only",
        "sample_papers": len(rows),
        "llm_papers": len(payloads),
        "python_only_papers": python_only,
        "before_payload_tokens": before_tokens,
        "after_payload_tokens": filtered_payload_tokens,
        "prepared_prompt_tokens": prompt_tokens,
        "payload_token_reduction": before_tokens - filtered_payload_tokens,
        "payload_reduction_percent": round((before_tokens - filtered_payload_tokens) / before_tokens * 100, 2),
        "batches": len(batches),
        "filter_counts": totals,
    }
    (args.output / "filter_report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    (args.output / "main_sample_manifest.jsonl").write_text(
        "\n".join(json.dumps(row, ensure_ascii=False) for row in rows) + "\n",
        encoding="utf-8",
    )
    (args.output / "local_records.json").write_text(
        json.dumps({"papers": local_records}, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
