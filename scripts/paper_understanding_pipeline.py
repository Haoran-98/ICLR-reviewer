#!/usr/bin/env python3
"""Staged, resumable paper-profile extraction for the ICLR corpus."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import random
import re
import signal
import subprocess
import sys
import time
import unicodedata
from collections import defaultdict, deque
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from datetime import datetime, timezone
from difflib import SequenceMatcher
from pathlib import Path

try:
    from .deployment_paths import storage_path
except ImportError:
    from deployment_paths import storage_path
from typing import Any, Iterable

import psycopg
from psycopg.types.json import Jsonb


REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
from benchmarks.paper_understanding import benchmark as understanding  # noqa: E402


DATABASE_URL = os.environ.get(
    "ICLR_DATABASE_URL", "host=127.0.0.1 port=55432 dbname=iclr_reviewer"
)
PROFILE_VERSION = "paper_understanding_v1"
PIPELINE_NAME = "paper_understanding"
LOG_DIR = REPO / "logs/paper_understanding"
LOG_FILE = LOG_DIR / "pipeline.log"
STATE_FILE = LOG_DIR / "progress.json"
RESULTS_FILE = LOG_DIR / "results.jsonl"
MANIFEST_FILE = LOG_DIR / "manifest.jsonl"
PID_FILE = LOG_DIR / "pipeline.pid"
CHECKPOINT_DIR = LOG_DIR / "checkpoints"
POLICY_FILE = REPO / "benchmarks/paper_understanding/selected_pipeline.json"
SPACE_RE = re.compile(r"\s+")
WORD_RE = re.compile(r"[a-z0-9]+")
STAGES = (("stage_0_1", 39), ("stage_1", 389), ("stage_full", None))
REQUIRED_ROOT = {
    "summary": str,
    "research_problem": dict,
    "motivation": dict,
    "prior_work_gap": dict,
    "key_insight": dict,
    "contributions": list,
    "method": dict,
    "claims": list,
    "experiments": dict,
    "limitations": list,
    "review_risks": list,
    "research_type": list,
}
STOP_REQUESTED = False
MAX_WORKERS = 5


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def atomic_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


def append_jsonl(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as stream:
        stream.write(json.dumps(value, ensure_ascii=False) + "\n")
        stream.flush()
        os.fsync(stream.fileno())


def read_json(path: Path, default: Any) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return default


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    try:
        return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]
    except OSError:
        return []


def sanitize_value(value: Any) -> Any:
    """PostgreSQL text/JSONB cannot represent U+0000."""
    if isinstance(value, str):
        return value.replace("\x00", "\ufffd")
    if isinstance(value, list):
        return [sanitize_value(item) for item in value]
    if isinstance(value, dict):
        return {sanitize_value(key): sanitize_value(item) for key, item in value.items()}
    return value


def checkpoint_path(paper_id: int) -> Path:
    return CHECKPOINT_DIR / f"{paper_id}.json"


def format_duration(seconds: float | None) -> str:
    if seconds is None or seconds < 0:
        return "--:--:--"
    seconds = int(seconds)
    return f"{seconds // 3600:02d}:{seconds % 3600 // 60:02d}:{seconds % 60:02d}"


def progress_line(state: dict[str, Any]) -> str:
    completed, target = state.get("completed", 0), max(1, state.get("target", 1))
    ratio = min(1.0, completed / target)
    filled = round(ratio * 20)
    elapsed = max(0.001, time.time() - state.get("started_epoch", time.time()))
    eta = elapsed / completed * (target - completed) if completed else None
    evidence = state.get("evidence_rate")
    evidence_text = "N/A" if evidence is None else f"{evidence:.1%}"
    return (
        f"[{state.get('stage', 'idle')}] [{'#' * filled}{'-' * (20 - filled)}] "
        f"{completed}/{target} {ratio:.1%} inserted={state.get('inserted', 0)} "
        f"updated={state.get('updated', 0)} skipped={state.get('skipped', 0)} "
        f"escalated={state.get('escalated', 0)} failed={state.get('failed', 0)} "
        f"evidence={evidence_text} tokens={state.get('tokens', 0)} ETA={format_duration(eta)}"
    )


def save_state(state: dict[str, Any], emit: bool = True) -> None:
    state["updated_at"] = utc_now()
    state["progress_bar"] = progress_line(state)
    atomic_json(STATE_FILE, state)
    if emit:
        print(state["progress_bar"], flush=True)


def normalize_with_map(text: str) -> tuple[str, list[int]]:
    output: list[str] = []
    positions: list[int] = []
    pending_space = False
    for index, character in enumerate(text):
        expanded = unicodedata.normalize("NFKC", character).casefold()
        for item in expanded:
            if item.isspace():
                pending_space = bool(output)
            else:
                if pending_space:
                    output.append(" ")
                    positions.append(index)
                    pending_space = False
                output.append(item)
                positions.append(index)
    return "".join(output).strip(), positions[: len("".join(output).strip())]


def normalized(text: str) -> str:
    return SPACE_RE.sub(" ", unicodedata.normalize("NFKC", text).casefold()).strip()


def text_candidates(text: str) -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []
    seen: set[str] = set()
    source_cursor = 0
    for raw_block in re.split(r"\n\s*\n", text):
        block = raw_block.strip()
        block_start = text.find(block, source_cursor) if block else source_cursor
        if block_start < 0:
            block_start = source_cursor
        source_cursor = block_start + len(block)
        pieces = [(block, block_start)]
        if len(block) > 1800:
            pieces = []
            local_cursor = 0
            for raw_piece in re.split(r"(?<=[.!?])\s+|\n", block):
                value = raw_piece.strip()
                local_start = block.find(value, local_cursor) if value else local_cursor
                if local_start < 0:
                    local_start = local_cursor
                local_cursor = local_start + len(value)
                pieces.append((value, block_start + local_start))
        for value, start in pieces:
            if not 20 <= len(value) <= 2200:
                continue
            norm, mapping = normalize_with_map(value)
            if not norm or norm in seen:
                continue
            seen.add(norm)
            candidates.append(
                {
                    "norm": norm,
                    "mapping": [start + position for position in mapping],
                    "words": set(WORD_RE.findall(norm)),
                }
            )
    return candidates


def locate_quote(
    quote: str, source: str, source_norm: str, source_map: list[int], candidates: list[dict[str, Any]], threshold: float
) -> dict[str, Any]:
    quote_norm = normalized(quote)
    if not quote_norm:
        return {"located": False, "method": "empty", "score": 0.0}
    exact = source_norm.find(quote_norm)
    if exact >= 0:
        start = source_map[exact]
        end = source_map[min(len(source_map) - 1, exact + len(quote_norm) - 1)] + 1
        return {"located": True, "method": "exact", "score": 1.0, "char_start": start, "char_end": end, "matched_text": source[start:end]}

    quote_words = set(WORD_RE.findall(quote_norm))
    shortlist = sorted(
        candidates,
        key=lambda item: len(quote_words & item["words"]) / max(1, len(quote_words)),
        reverse=True,
    )[:8]
    best: tuple[float, dict[str, Any] | None, SequenceMatcher | None] = (0.0, None, None)
    for candidate in shortlist:
        matcher = SequenceMatcher(None, quote_norm, candidate["norm"], autojunk=True)
        coverage = sum(block.size for block in matcher.get_matching_blocks()) / max(1, len(quote_norm))
        word_recall = len(quote_words & candidate["words"]) / max(1, len(quote_words))
        score = 0.65 * coverage + 0.35 * word_recall
        if score > best[0]:
            best = (score, candidate, matcher)
    score, candidate, matcher = best
    if candidate is None or matcher is None or score < threshold:
        return {"located": False, "method": "unresolved", "score": round(score, 4)}
    blocks = [block for block in matcher.get_matching_blocks() if block.size]
    if not blocks:
        return {"located": False, "method": "unresolved", "score": round(score, 4)}
    left = min(block.b for block in blocks)
    right = max(block.b + block.size for block in blocks) - 1
    mapping = candidate["mapping"]
    start, end = mapping[left], mapping[min(right, len(mapping) - 1)] + 1
    return {
        "located": True,
        "method": "fuzzy",
        "score": round(score, 4),
        "char_start": start,
        "char_end": end,
        "matched_text": source[start:end],
    }


def key_items(profile: dict[str, Any]) -> Iterable[tuple[str, dict[str, Any]]]:
    for name in ("research_problem", "motivation", "prior_work_gap", "key_insight"):
        item = profile.get(name)
        if isinstance(item, dict) and item.get("statement"):
            yield name, item
    for name in ("contributions", "claims"):
        for index, item in enumerate(profile.get(name, [])):
            if isinstance(item, dict):
                yield f"{name}[{index}]", item
    experiments = profile.get("experiments", {})
    if isinstance(experiments, dict):
        for name in ("main_results", "ablations"):
            for index, item in enumerate(experiments.get(name, [])):
                if isinstance(item, dict):
                    yield f"experiments.{name}[{index}]", item


def localize_key_evidence(profile: dict[str, Any], source: str, threshold: float) -> dict[str, Any]:
    source_norm, source_map = normalize_with_map(source)
    candidates = text_candidates(source)
    locations: list[dict[str, Any]] = []
    located_items = total_items = 0
    uncited_items: list[str] = []
    for path, item in key_items(profile):
        evidence = item.get("evidence", []) if isinstance(item.get("evidence"), list) else []
        evidence = [citation for citation in evidence if isinstance(citation, dict) and isinstance(citation.get("quote"), str) and citation["quote"].strip()]
        if not evidence:
            uncited_items.append(path)
            continue
        total_items += 1
        item_located = False
        for index, citation in enumerate(evidence):
            result = locate_quote(citation["quote"], source, source_norm, source_map, candidates, threshold)
            result.update({"item_path": path, "evidence_index": index, "section_id": citation.get("section_id")})
            locations.append(result)
            item_located |= bool(result["located"])
        located_items += item_located
    return {
        "key_items_total": total_items,
        "key_items_located": located_items,
        "key_evidence_rate": located_items / total_items if total_items else 1.0,
        "uncited_key_items": uncited_items,
        "locations": locations,
    }


def normalize_research_types(profile: Any) -> Any:
    if not isinstance(profile, dict) or not isinstance(profile.get("research_type"), list):
        return profile
    aliases = {
        "experiment": "empirical", "experimental": "empirical", "experimental study": "empirical", "empirical study": "empirical",
        "theory": "theoretical", "theoretic": "theoretical",
        "datasets": "dataset", "data set": "dataset",
        "benchmarks": "benchmark", "evaluation": "benchmark",
        "systems": "system", "systematic": "system",
        "analytical": "analysis", "survey": "analysis",
        "applied": "application", "applications": "application",
    }
    allowed = {"empirical", "theoretical", "dataset", "benchmark", "system", "analysis", "application"}
    normalized_types = []
    for value in profile["research_type"]:
        if not isinstance(value, str):
            continue
        canonical = aliases.get(SPACE_RE.sub(" ", value.strip().casefold()), value.strip().casefold())
        if canonical in allowed and canonical not in normalized_types:
            normalized_types.append(canonical)
    profile["research_type"] = normalized_types
    return profile


def validate_profile(profile: Any) -> list[str]:
    if not isinstance(profile, dict):
        return ["profile is not an object"]
    errors = [f"{key} must be {expected.__name__}" for key, expected in REQUIRED_ROOT.items() if not isinstance(profile.get(key), expected)]
    if errors:
        return errors
    for name in ("research_problem", "motivation", "prior_work_gap", "key_insight"):
        item = profile[name]
        if not isinstance(item.get("statement"), str) or not isinstance(item.get("evidence"), list):
            errors.append(f"{name} has invalid statement/evidence")
    method = profile["method"]
    for key, expected in (("overview", str), ("components", list), ("mechanism_chain", list), ("assumptions", list)):
        if not isinstance(method.get(key), expected):
            errors.append(f"method.{key} must be {expected.__name__}")
    experiments = profile["experiments"]
    for key in ("datasets", "baselines", "metrics", "main_results", "ablations"):
        if not isinstance(experiments.get(key), list):
            errors.append(f"experiments.{key} must be list")
    allowed_types = {"empirical", "theoretical", "dataset", "benchmark", "system", "analysis", "application"}
    if any(item not in allowed_types for item in profile["research_type"]):
        errors.append("research_type contains an unsupported value")
    return errors


def required_content_missing(profile: dict[str, Any]) -> list[str]:
    missing = []
    for name in ("research_problem", "key_insight"):
        if not str(profile.get(name, {}).get("statement", "")).strip():
            missing.append(name)
    if not profile.get("contributions"):
        missing.append("contributions")
    if not str(profile.get("method", {}).get("overview", "")).strip():
        missing.append("method.overview")
    return missing


def mean_confidence(value: Any) -> float | None:
    values: list[float] = []
    stack = [value]
    while stack:
        item = stack.pop()
        if isinstance(item, dict):
            confidence = item.get("confidence")
            if isinstance(confidence, (int, float)) and 0 <= confidence <= 1:
                values.append(float(confidence))
            stack.extend(item.values())
        elif isinstance(item, list):
            stack.extend(item)
    return sum(values) / len(values) if values else None


def load_candidates(connection: psycopg.Connection[Any]) -> list[dict[str, Any]]:
    query = """
        SELECT p.paper_id, v.year, p.forum_id, p.accepted_main, pv.title, pv.abstract,
               pv.keywords, COALESCE(area.raw_label, 'unknown') AS area,
               artifact.core_artifact_id, artifact.markdown_path,
               COALESCE(fi.token_count, 0) AS token_count,
               COALESCE(fi.headings, '[]'::jsonb) AS headings,
               COALESCE(fi.routing_signals, '{}'::jsonb) AS routing_signals
        FROM core.paper p
        JOIN core.venue v ON v.venue_id = p.venue_id
        JOIN core.latest_paper_version pv ON pv.paper_id = p.paper_id
        LEFT JOIN LATERAL (
            SELECT ea.raw_label
            FROM core.paper_area pa JOIN core.explicit_area ea USING (explicit_area_id)
            WHERE pa.paper_id = p.paper_id
            ORDER BY pa.is_primary DESC, ea.explicit_area_id LIMIT 1
        ) area ON true
        LEFT JOIN LATERAL (
            SELECT ca.paper_artifact_id AS core_artifact_id, ra.object_path AS markdown_path
            FROM core.artifact ca JOIN raw.artifact ra ON ra.artifact_id = ca.raw_artifact_id
            WHERE ca.paper_id = p.paper_id AND ca.artifact_role = 'markdown' AND ca.availability = 'available'
            ORDER BY ca.paper_artifact_id LIMIT 1
        ) artifact ON true
        LEFT JOIN semantic.paper_fulltext_index fi ON fi.paper_id = p.paper_id AND fi.status = 'indexed'
        WHERE p.track = 'main'
        ORDER BY v.year, p.paper_id
    """
    with connection.cursor() as cursor:
        cursor.execute(query)
        columns = [column.name for column in cursor.description]
        rows = [dict(zip(columns, values)) for values in cursor.fetchall()]
    for row in rows:
        row["accepted_main"] = bool(row["accepted_main"])
        row["keywords"] = list(row["keywords"] or [])
        row["headings"] = list(row["headings"] or [])
        row["routing_signals"] = dict(row["routing_signals"] or {})
    return rows


def stratified_order(rows: list[dict[str, Any]], seed: int) -> list[dict[str, Any]]:
    eligible, missing = [], []
    for row in rows:
        path = row.get("markdown_path")
        (eligible if path else missing).append(row)
    buckets: dict[tuple[Any, ...], list[dict[str, Any]]] = defaultdict(list)
    for row in eligible:
        length = "short" if row["token_count"] < 6000 else "medium" if row["token_count"] < 11000 else "long"
        buckets[(row["year"], row["accepted_main"], row["area"], length)].append(row)
    rng = random.Random(seed)
    for bucket in buckets.values():
        rng.shuffle(bucket)
    group_orders: dict[tuple[int, bool], deque[dict[str, Any]]] = {}
    for group in ((year, accepted) for year in (2024, 2025, 2026) for accepted in (True, False)):
        keys = [key for key in buckets if key[:2] == group]
        rng.shuffle(keys)
        values: list[dict[str, Any]] = []
        while keys:
            for key in list(keys):
                if buckets[key]:
                    values.append(buckets[key].pop())
                else:
                    keys.remove(key)
        group_orders[group] = deque(values)
    ordered: list[dict[str, Any]] = []
    active = list(group_orders)
    while active:
        for group in list(active):
            if group_orders[group]:
                ordered.append(group_orders[group].popleft())
            else:
                active.remove(group)
    missing.sort(key=lambda row: (row["year"], row["paper_id"]))
    return ordered + missing


def load_or_create_manifest(connection: psycopg.Connection[Any], seed: int) -> list[dict[str, Any]]:
    manifest = read_jsonl(MANIFEST_FILE)
    if manifest:
        return manifest
    manifest = stratified_order(load_candidates(connection), seed)
    temporary = MANIFEST_FILE.with_suffix(".jsonl.tmp")
    temporary.parent.mkdir(parents=True, exist_ok=True)
    with temporary.open("w", encoding="utf-8") as stream:
        for row in manifest:
            stream.write(json.dumps(row, ensure_ascii=False) + "\n")
    temporary.replace(MANIFEST_FILE)
    return manifest


def source_for(paper: dict[str, Any]) -> tuple[str, str]:
    path = paper.get("markdown_path")
    if path and Path(path).is_file():
        return Path(path).read_text(encoding="utf-8", errors="replace"), "markdown"
    return f"# {paper['title']}\n\n## Abstract\n{paper.get('abstract') or ''}\n", "metadata_only"


def input_hash(paper: dict[str, Any], source: str) -> str:
    payload = json.dumps(
        {"paper_id": paper["paper_id"], "title": paper["title"], "abstract": paper.get("abstract"), "source": source, "version": PROFILE_VERSION},
        ensure_ascii=False,
        sort_keys=True,
    )
    return hashlib.sha256(payload.encode()).hexdigest()


def grouped_sections(paper: dict[str, Any], source: str, mode: str) -> dict[str, list[dict[str, Any]]]:
    if mode == "markdown":
        return understanding.build_sections(paper)
    return {
        "framing": [{"section_id": "S01", "heading": "Abstract", "page": None, "group": "framing", "text": source}],
        "method": [], "evidence": [], "conclusion": [],
    }


def process_paper(
    auth: dict[str, str], paper: dict[str, Any], fuzzy_threshold: float, escalation_threshold: float
) -> dict[str, Any]:
    started = time.perf_counter()
    raw_source, source_mode = source_for(paper)
    digest = input_hash(paper, raw_source)
    cached = read_json(checkpoint_path(paper["paper_id"]), None)
    if (
        isinstance(cached, dict)
        and cached.get("input_hash") == digest
        and cached.get("provenance", {}).get("fuzzy_threshold") == fuzzy_threshold
        and cached.get("provenance", {}).get("escalation_evidence_threshold") == escalation_threshold
        and not validate_profile(cached.get("profile"))
    ):
        return cached
    source = sanitize_value(raw_source)
    grouped = sanitize_value(grouped_sections(paper, raw_source, source_mode))
    attempts: list[dict[str, Any]] = []

    def extract(method: str) -> dict[str, Any]:
        runner = understanding.one_shot if method == "one_shot" else understanding.grounded_hierarchical
        profile, usage, elapsed = runner(auth, paper, grouped)
        profile = normalize_research_types(sanitize_value(profile))
        schema_errors = validate_profile(profile)
        evidence = localize_key_evidence(profile, source, fuzzy_threshold) if not schema_errors else {
            "key_items_total": 0, "key_items_located": 0, "key_evidence_rate": 0.0, "uncited_key_items": [], "locations": []
        }
        return {"method": method, "profile": profile, "usage": usage, "elapsed": elapsed, "schema_errors": schema_errors, "evidence": evidence}

    first = extract("one_shot")
    attempts.append(first)
    reasons = []
    if first["schema_errors"]:
        reasons.append("schema_invalid")
    elif required := required_content_missing(first["profile"]):
        reasons.append("required_core_field_missing:" + ",".join(required))
    if first["evidence"]["key_evidence_rate"] < escalation_threshold:
        reasons.append("key_evidence_insufficient")
    if any(path in {"research_problem", "key_insight"} or path.startswith("contributions[") for path in first["evidence"]["uncited_key_items"]):
        reasons.append("key_claim_has_no_evidence")
    selected = first
    if reasons:
        fallback = extract("grounded_hierarchical")
        attempts.append(fallback)
        valid = [item for item in attempts if not item["schema_errors"]]
        if valid:
            selected = max(valid, key=lambda item: item["evidence"]["key_evidence_rate"])
        else:
            selected = fallback

    schema_errors = selected["schema_errors"]
    if schema_errors:
        raise ValueError("schema validation failed after fallback: " + "; ".join(schema_errors[:8]))
    evidence = selected["evidence"]
    needs_review = evidence["key_evidence_rate"] < escalation_threshold or bool(required_content_missing(selected["profile"]))
    tokens = sum(understanding.usage_total(item["usage"]) for item in attempts)
    provenance = {
        "input_hash": digest,
        "policy_version": PROFILE_VERSION,
        "model": auth["OPENAI_WEAK_MODEL_ID"],
        "selected_method": selected["method"],
        "fallback_attempted": len(attempts) > 1,
        "escalation_reasons": reasons,
        "source_mode": source_mode,
        "source_artifact_id": paper.get("core_artifact_id"),
        "token_usage": tokens,
        "attempts": [{"method": item["method"], "tokens": understanding.usage_total(item["usage"]), "seconds": round(item["elapsed"], 3)} for item in attempts],
        "evidence_metrics": {
            **{key: evidence[key] for key in ("key_items_total", "key_items_located", "key_evidence_rate")},
            "uncited_key_items": len(evidence["uncited_key_items"]),
        },
        "evidence_locations": evidence["locations"],
        "needs_review": needs_review,
        "fuzzy_threshold": fuzzy_threshold,
        "escalation_evidence_threshold": escalation_threshold,
        "created_at": utc_now(),
    }
    return {
        "paper_id": paper["paper_id"], "profile": selected["profile"], "confidence": mean_confidence(selected["profile"]),
        "provenance": provenance, "input_hash": digest, "tokens": tokens, "escalated": len(attempts) > 1,
        "evidence_total": evidence["key_items_total"], "evidence_located": evidence["key_items_located"],
        "elapsed_seconds": round(time.perf_counter() - started, 3),
    }


def existing_profile(connection: psycopg.Connection[Any], paper_id: int) -> dict[str, Any] | None:
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT profile, confidence, provenance FROM semantic.paper_profile WHERE paper_id=%s AND profile_version=%s",
            (paper_id, PROFILE_VERSION),
        )
        row = cursor.fetchone()
    return {"profile": row[0], "confidence": row[1], "provenance": row[2]} if row else None


def existing_profiles(connection: psycopg.Connection[Any]) -> dict[int, dict[str, Any]]:
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT paper_id, profile, confidence, provenance FROM semantic.paper_profile WHERE profile_version=%s",
            (PROFILE_VERSION,),
        )
        return {
            row[0]: {"profile": row[1], "confidence": row[2], "provenance": row[3]}
            for row in cursor.fetchall()
        }


def upsert_profile(connection: psycopg.Connection[Any], result: dict[str, Any]) -> str:
    try:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO semantic.paper_profile (paper_id, profile_version, profile, confidence, provenance)
                VALUES (%s, %s, %s, %s, %s)
                ON CONFLICT (paper_id, profile_version) DO UPDATE
                SET profile=EXCLUDED.profile, confidence=EXCLUDED.confidence, provenance=EXCLUDED.provenance
                WHERE semantic.paper_profile.provenance->>'input_hash' IS DISTINCT FROM EXCLUDED.provenance->>'input_hash'
                RETURNING (xmax = 0) AS inserted
                """,
                (
                    result["paper_id"], PROFILE_VERSION, Jsonb(sanitize_value(result["profile"])),
                    result["confidence"], Jsonb(sanitize_value(result["provenance"])),
                ),
            )
            row = cursor.fetchone()
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    if row is None:
        return "skipped"
    return "inserted" if row[0] else "updated"


def state_add_profile(state: dict[str, Any], provenance: dict[str, Any], outcome: str) -> None:
    state[outcome] = state.get(outcome, 0) + 1
    state["completed"] += 1
    state["tokens"] += int(provenance.get("token_usage", 0))
    state["escalated"] += bool(provenance.get("fallback_attempted"))
    metrics = provenance.get("evidence_metrics", {})
    state["evidence_total"] += int(metrics.get("key_items_total", 0))
    state["evidence_located"] += int(metrics.get("key_items_located", 0))
    state["evidence_rate"] = state["evidence_located"] / state["evidence_total"] if state["evidence_total"] else 1.0


def gate_metrics(connection: psycopg.Connection[Any], papers: list[dict[str, Any]], max_escalation: float, min_evidence: float) -> dict[str, Any]:
    rows = []
    for paper in papers:
        record = existing_profile(connection, paper["paper_id"])
        if record:
            rows.append((paper["paper_id"], record))
    schema_success = sum(not validate_profile(row[1]["profile"]) for row in rows)
    evidence_total = sum(int(row[1]["provenance"].get("evidence_metrics", {}).get("key_items_total", 0)) for row in rows)
    evidence_located = sum(int(row[1]["provenance"].get("evidence_metrics", {}).get("key_items_located", 0)) for row in rows)
    escalated = sum(bool(row[1]["provenance"].get("fallback_attempted")) for row in rows)
    idempotent_changes = 0
    for paper_id, record in rows:
        outcome = upsert_profile(connection, {"paper_id": paper_id, **record})
        idempotent_changes += outcome != "skipped"
    target = len(papers)
    metrics = {
        "target": target,
        "profiles": len(rows),
        "schema_success_rate": schema_success / target if target else 1.0,
        "idempotent_changes": idempotent_changes,
        "key_evidence_rate": evidence_located / evidence_total if evidence_total else 0.0,
        "escalation_rate": escalated / target if target else 0.0,
        "max_escalation_rate": max_escalation,
        "min_key_evidence_rate": min_evidence,
    }
    metrics["passed"] = (
        metrics["schema_success_rate"] == 1.0
        and idempotent_changes == 0
        and metrics["key_evidence_rate"] >= min_evidence
        and metrics["escalation_rate"] <= max_escalation
    )
    return metrics


def pipeline_run_start(connection: psycopg.Connection[Any], args: argparse.Namespace) -> int:
    try:
        with connection.cursor() as cursor:
            cursor.execute(
                "INSERT INTO ops.pipeline_run (pipeline_name, pipeline_version, status, parameters) VALUES (%s,%s,'running',%s) RETURNING pipeline_run_id",
                (PIPELINE_NAME, PROFILE_VERSION, Jsonb(vars_for_record(args))),
            )
            run_id = cursor.fetchone()[0]
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    return run_id


def pipeline_run_finish(connection: psycopg.Connection[Any], run_id: int, status: str, state: dict[str, Any], error: str | None = None) -> None:
    connection.rollback()
    try:
        with connection.cursor() as cursor:
            cursor.execute(
                "UPDATE ops.pipeline_run SET finished_at=now(), status=%s, statistics=%s, error=%s WHERE pipeline_run_id=%s",
                (status, Jsonb(sanitize_value(state)), sanitize_value(error), run_id),
            )
        connection.commit()
    except Exception:
        connection.rollback()
        raise


def vars_for_record(args: argparse.Namespace) -> dict[str, Any]:
    return {key: str(value) if isinstance(value, Path) else value for key, value in vars(args).items() if key != "func"}


def signal_stop(_signum: int, _frame: Any) -> None:
    global STOP_REQUESTED
    STOP_REQUESTED = True


def run_command(args: argparse.Namespace) -> None:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    signal.signal(signal.SIGTERM, signal_stop)
    signal.signal(signal.SIGINT, signal_stop)
    auth = understanding.shared.load_auth(args.auth)
    understanding.validate_auth(auth)
    with psycopg.connect(args.database_url) as connection:
        manifest = load_or_create_manifest(connection, args.seed)
        run_id = pipeline_run_start(connection, args)
        state: dict[str, Any] = {
            "status": "running", "pipeline_run_id": run_id, "stage": STAGES[0][0], "target": STAGES[0][1],
            "completed": 0, "inserted": 0, "updated": 0, "skipped": 0, "escalated": 0, "failed": 0,
            "tokens": 0, "evidence_total": 0, "evidence_located": 0, "evidence_rate": None,
            "started_at": utc_now(), "started_epoch": time.time(), "latest_error": None, "gates": [],
        }
        save_state(state)
        try:
            for stage_name, configured_target in STAGES:
                target = len(manifest) if configured_target is None else min(configured_target, len(manifest))
                papers = manifest[:target]
                state.update({"stage": stage_name, "target": target, "completed": 0, "inserted": 0, "updated": 0, "skipped": 0, "escalated": 0, "failed": 0, "tokens": 0, "evidence_total": 0, "evidence_located": 0, "evidence_rate": None, "started_epoch": time.time()})
                pending: list[dict[str, Any]] = []
                profiles_by_id = existing_profiles(connection)
                for paper in papers:
                    existing = profiles_by_id.get(paper["paper_id"])
                    if not existing:
                        pending.append(paper)
                        continue
                    source, _ = source_for(paper)
                    digest = input_hash(paper, source)
                    if existing["provenance"].get("input_hash") == digest and not validate_profile(existing["profile"]):
                        state_add_profile(state, existing["provenance"], "skipped")
                    else:
                        pending.append(paper)
                save_state(state)

                with ThreadPoolExecutor(max_workers=args.workers) as executor:
                    active: dict[Any, dict[str, Any]] = {}
                    iterator = iter(pending)
                    for _ in range(args.workers):
                        try:
                            paper = next(iterator)
                        except StopIteration:
                            break
                        active[executor.submit(process_paper, auth, paper, args.fuzzy_threshold, args.escalation_evidence_threshold)] = paper
                    while active and not STOP_REQUESTED:
                        done, _ = wait(active, return_when=FIRST_COMPLETED)
                        for future in done:
                            paper = active.pop(future)
                            try:
                                result = future.result()
                                atomic_json(checkpoint_path(paper["paper_id"]), sanitize_value(result))
                                outcome = upsert_profile(connection, result)
                                checkpoint_path(paper["paper_id"]).unlink(missing_ok=True)
                                state_add_profile(state, result["provenance"], outcome)
                                append_jsonl(RESULTS_FILE, {"at": utc_now(), "stage": stage_name, "paper_id": paper["paper_id"], "outcome": outcome, "tokens": result["tokens"], "escalated": result["escalated"], "evidence_rate": result["evidence_located"] / result["evidence_total"] if result["evidence_total"] else 1.0, "seconds": result["elapsed_seconds"]})
                            except Exception as error:  # one paper must not destroy the checkpoint
                                connection.rollback()
                                state["completed"] += 1
                                state["failed"] += 1
                                state["latest_error"] = f"paper_id={paper['paper_id']} {type(error).__name__}: {error}"
                                append_jsonl(RESULTS_FILE, {"at": utc_now(), "stage": stage_name, "paper_id": paper["paper_id"], "outcome": "failed", "error": state["latest_error"]})
                            save_state(state)
                            try:
                                next_paper = next(iterator)
                            except StopIteration:
                                continue
                            active[executor.submit(process_paper, auth, next_paper, args.fuzzy_threshold, args.escalation_evidence_threshold)] = next_paper

                if STOP_REQUESTED:
                    state["status"] = "stopped"
                    save_state(state)
                    pipeline_run_finish(connection, run_id, "failed", state, "stopped by signal")
                    return
                gate = gate_metrics(connection, papers, args.max_escalation_rate, args.min_key_evidence_rate)
                gate["stage"] = stage_name
                gate["checked_at"] = utc_now()
                state["gates"].append(gate)
                print("GATE " + json.dumps(gate, ensure_ascii=False), flush=True)
                if not gate["passed"]:
                    state["status"] = "gate_failed"
                    save_state(state)
                    pipeline_run_finish(connection, run_id, "failed", state, f"{stage_name} gate failed")
                    return
            state["status"] = "success"
            state["finished_at"] = utc_now()
            save_state(state)
            pipeline_run_finish(connection, run_id, "success", state)
        except Exception as error:
            connection.rollback()
            state["status"] = "failed"
            state["latest_error"] = f"{type(error).__name__}: {error}"
            save_state(state)
            pipeline_run_finish(connection, run_id, "failed", state, state["latest_error"])
            raise


def pid_running(pid: int) -> bool:
    try:
        os.kill(pid, 0)
        return True
    except (OSError, ProcessLookupError):
        return False


def current_pid() -> int | None:
    try:
        pid = int(PID_FILE.read_text().strip())
    except (OSError, ValueError):
        return None
    return pid if pid_running(pid) else None


def start_command(args: argparse.Namespace) -> None:
    if pid := current_pid():
        raise SystemExit(f"pipeline already running with PID {pid}")
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    command = [
        sys.executable, str(Path(__file__).resolve()), "run", "--auth", str(args.auth), "--database-url", args.database_url,
        "--workers", str(args.workers), "--seed", str(args.seed), "--max-escalation-rate", str(args.max_escalation_rate),
        "--min-key-evidence-rate", str(args.min_key_evidence_rate), "--fuzzy-threshold", str(args.fuzzy_threshold),
        "--escalation-evidence-threshold", str(args.escalation_evidence_threshold),
    ]
    with LOG_FILE.open("a", encoding="utf-8") as log:
        process = subprocess.Popen(command, stdout=log, stderr=subprocess.STDOUT, start_new_session=True, cwd=REPO)
    PID_FILE.write_text(f"{process.pid}\n", encoding="utf-8")
    print(json.dumps({"pid": process.pid, "log": str(LOG_FILE), "status_command": f"python3 {Path(__file__).relative_to(REPO)} status"}, indent=2))


def status_command(_args: argparse.Namespace) -> None:
    state = read_json(STATE_FILE, {"status": "not_started", "stage": "idle", "target": 1, "completed": 0})
    pid = current_pid()
    print(state.get("progress_bar") or progress_line(state))
    print(json.dumps({"pid": pid, "running": bool(pid), "status": state.get("status"), "stage": state.get("stage"), "schema_success_rate": state.get("gates", [{}])[-1].get("schema_success_rate") if state.get("gates") else None, "escalation_rate": state.get("escalated", 0) / max(1, state.get("completed", 0)), "evidence_rate": state.get("evidence_rate"), "tokens": state.get("tokens", 0), "latest_error": state.get("latest_error"), "log": str(LOG_FILE)}, ensure_ascii=False, indent=2))


def stop_command(_args: argparse.Namespace) -> None:
    pid = current_pid()
    if not pid:
        print("pipeline is not running")
        return
    os.kill(pid, signal.SIGTERM)
    print(f"sent SIGTERM to PID {pid}")


def calibrate_command(args: argparse.Namespace) -> None:
    root = storage_path('iclr-paper-understanding-benchmark')
    manifest = {row["sample_id"]: row for row in read_jsonl(root / "manifest_50.jsonl")}
    rows = [row for row in read_jsonl(root / "outputs/one_shot.jsonl") if "profile" in row]
    total = located = 0
    for row in rows:
        source = Path(manifest[row["sample_id"]]["markdown_path"]).read_text(encoding="utf-8", errors="replace")
        metrics = localize_key_evidence(row["profile"], source, args.fuzzy_threshold)
        total += metrics["key_items_total"]
        located += metrics["key_items_located"]
    print(json.dumps({"papers": len(rows), "key_items": total, "located": located, "rate": located / total if total else 1.0, "fuzzy_threshold": args.fuzzy_threshold}, indent=2))


def self_test_command(_args: argparse.Namespace) -> None:
    source = "First paragraph has exact evidence.\n\nThe model initially relies on IWL but gradually improves inferences by using the prompt."
    norm, mapping = normalize_with_map(source)
    candidates = text_candidates(source)
    exact = locate_quote("exact   evidence", source, norm, mapping, candidates, 0.70)
    fuzzy = locate_quote("The model initially relies on IWL ... ICL emerges only later", source, norm, mapping, candidates, 0.70)
    assert exact["located"] and exact["method"] == "exact"
    assert fuzzy["located"] and fuzzy["method"] == "fuzzy"
    fixture = {
        "summary": "x", "research_problem": {"statement": "x", "evidence": [], "confidence": 1.0},
        "motivation": {"statement": "x", "evidence": [], "confidence": 1.0}, "prior_work_gap": {"statement": "x", "evidence": [], "confidence": 1.0},
        "key_insight": {"statement": "x", "evidence": [], "confidence": 1.0}, "contributions": [],
        "method": {"overview": "x", "components": [], "mechanism_chain": [], "assumptions": []}, "claims": [],
        "experiments": {"datasets": [], "baselines": [], "metrics": [], "main_results": [], "ablations": []},
        "limitations": [], "review_risks": [], "research_type": ["analysis"],
    }
    assert validate_profile(fixture) == []
    cleaned = sanitize_value({"text": "before\x00after", "nested": ["\x00"]})
    assert cleaned == {"text": "before\ufffdafter", "nested": ["\ufffd"]}
    assert normalize_research_types({"research_type": ["Experimental", "systems", "unknown"]}) == {
        "research_type": ["empirical", "system"]
    }
    print("self-test: ok")


def add_common(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--auth", type=Path, default=Path.home() / "auth")
    parser.add_argument("--database-url", default=DATABASE_URL)
    parser.add_argument("--workers", type=int, choices=range(1, MAX_WORKERS + 1), default=4)
    parser.add_argument("--seed", type=int, default=1701)
    parser.add_argument("--max-escalation-rate", type=float, default=0.10)
    parser.add_argument("--min-key-evidence-rate", type=float, default=0.90)
    parser.add_argument("--fuzzy-threshold", type=float, default=0.70)
    parser.add_argument("--escalation-evidence-threshold", type=float, default=0.60)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(required=True)
    for name, function in (("start", start_command), ("run", run_command)):
        command = subparsers.add_parser(name)
        add_common(command)
        command.set_defaults(func=function)
    subparsers.add_parser("status").set_defaults(func=status_command)
    subparsers.add_parser("stop").set_defaults(func=stop_command)
    calibration = subparsers.add_parser("calibrate-locator")
    calibration.add_argument("--fuzzy-threshold", type=float, default=0.70)
    calibration.set_defaults(func=calibrate_command)
    subparsers.add_parser("self-test").set_defaults(func=self_test_command)
    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
