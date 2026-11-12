#!/usr/bin/env python3
"""Build, validate, and snapshot the unified ICLR PostgreSQL database."""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import mimetypes
import os
import re
import shutil
import subprocess
import sys
import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

import psycopg
from psycopg.types.json import Jsonb


YEARS = (2024, 2025, 2026)
REPO = Path(__file__).resolve().parents[1]
DATA = Path(os.environ.get('ICLR_DATA_DIR', REPO/'.local-data'))
DATABASE_HOME = Path(os.environ.get('ICLR_DATABASE_HOME', DATA/'database'))
DEFAULT_SOURCE = Path(os.environ.get("ICLR_REVIEWS_ROOT", DATA/'iclr_reviews'))
DEFAULT_STORE = Path(os.environ.get("ICLR_OBJECT_STORE", DATA/'objects'))
DEFAULT_STATE = Path(os.environ.get("ICLR_DATABASE_STATE", DATABASE_HOME/'state'))
DEFAULT_URL = os.environ.get(
    "ICLR_DATABASE_URL", "host=127.0.0.1 port=55432 dbname=iclr_reviewer"
)
DEFAULT_OPENREVIEW_TOKEN = Path(os.environ.get('ICLR_OPENREVIEW_TOKEN_FILE', DEFAULT_SOURCE/'fulltext/openreview.token'))
TOKEN_EXPIRES_SECONDS = 7 * 24 * 60 * 60
TOKEN_REFRESH_SECONDS = TOKEN_EXPIRES_SECONDS - 60 * 60

AREA_CANONICAL = {
    "general machine learning (i.e., none of the above)": "other_machine_learning",
    "other topics in machine learning (i.e., none of the above)": "other_machine_learning",
    "infrastructure, software libraries, hardware, etc.": "infrastructure_systems",
    "infrastructure, software libraries, hardware, systems, etc.": "infrastructure_systems",
    "societal considerations including fairness, safety, privacy": "alignment_fairness_safety_privacy",
    "alignment, fairness, safety, privacy, and societal considerations": "alignment_fairness_safety_privacy",
    "visualization or interpretation of learned representations": "interpretability_explainability",
    "interpretability and explainable ai": "interpretability_explainability",
}
FULLTEXT_INDEX_VERSION = "text_first_v2"
WORD_RE = re.compile(r"[A-Za-z][A-Za-z0-9_-]{1,}|[\u4e00-\u9fff]")
MARKDOWN_HEADING_RE = re.compile(r"(?m)^\s{0,3}(#{1,6})\s+(.+?)\s*$")
CAPTION_RE = re.compile(
    r"^\s*(Figure|Fig\.?|Table)\s+([A-Za-z]?\d+(?:\.\d+)?[a-z]?)\s*[:.]?\s*(.*)$",
    re.IGNORECASE,
)
THEOREM_RE = re.compile(
    r"^\s*(Theorem|Lemma|Proposition|Corollary|Definition|Algorithm)"
    r"\s*([A-Za-z]?\d+(?:\.\d+)*)?\s*[:.]?\s*(.*)$",
    re.IGNORECASE,
)
EQUATION_RE = re.compile(r"\b(?:Equation|Eq\.?)\s*\(?([A-Za-z]?\d+(?:\.\d+)?)\)?|\\tag\{([^}]+)\}", re.IGNORECASE)
DATA_IMAGE_RE = re.compile(r"!\[[^\]]*\]\(data:image/[^;]+;base64,[A-Za-z0-9+/=\s]+\)")


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def json_text(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def content_hash(value: Any) -> str:
    return hashlib.sha256(json_text(value).encode()).hexdigest()


def file_hash(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(4 * 1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def json_safe(value: Any) -> Any:
    if isinstance(value, str):
        return value.replace("\x00", "\ufffd")
    if isinstance(value, list):
        return [json_safe(item) for item in value]
    if isinstance(value, dict):
        return {key: json_safe(item) for key, item in value.items()}
    return value


def load_json(path: Path) -> dict[str, Any]:
    return json_safe(json.loads(path.read_text(encoding="utf-8")))


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


def write_jsonl(path: Path, rows: Iterable[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    with temporary.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n")
    temporary.replace(path)


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    with path.open(encoding="utf-8") as handle:
        return [json.loads(line) for line in handle if line.strip()]


def token_claims(token: str) -> dict[str, Any]:
    try:
        payload = token.split(".")[1]
        return json.loads(base64.urlsafe_b64decode(payload + "=" * (-len(payload) % 4)))
    except (IndexError, ValueError, json.JSONDecodeError) as error:
        raise ValueError("OpenReview token is not a valid JWT") from error


def token_refresh_due(token: str, now: float | None = None) -> bool:
    claims = token_claims(token)
    issued_at = int(claims.get("iat") or 0)
    expires_at = int(claims.get("exp") or 0)
    current = time.time() if now is None else now
    return not issued_at or not expires_at or current >= min(
        issued_at + TOKEN_REFRESH_SECONDS, expires_at - 60 * 60
    )


def slug(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", value.lower()).strip("_")


def canonical_area(label: str) -> str:
    return AREA_CANONICAL.get(label.strip().lower(), slug(label))


def lightweight_fulltext_index(text: str) -> dict[str, Any]:
    """Create cheap retrieval metadata without interpreting visual or mathematical content."""
    text = DATA_IMAGE_RE.sub("![embedded image]", text.replace("\x00", "\ufffd"))
    headings = []
    heading_offsets: set[int] = set()
    page = 1
    page_at_offset: list[tuple[int, int]] = [(0, page)]
    for match in re.finditer(r"(?m)^---\s*$", text):
        page += 1
        page_at_offset.append((match.end(), page))

    def page_number(offset: int) -> int:
        selected = 1
        for boundary, number_ in page_at_offset:
            if boundary > offset:
                break
            selected = number_
        return selected

    for match in MARKDOWN_HEADING_RE.finditer(text):
        heading_offsets.add(match.start())
        headings.append({
            "text": match.group(2).strip(),
            "level": len(match.group(1)),
            "char_start": match.start(),
            "page_number": page_number(match.start()),
        })

    objects: dict[tuple[str, str], dict[str, Any]] = {}
    unnamed = Counter()

    def add_object(
        object_type: str,
        key: str,
        label: str,
        caption: str | None,
        start: int,
        end: int,
        confidence: float,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        identity = (object_type, key)
        if identity in objects:
            objects[identity]["occurrence_count"] += 1
            if caption and not objects[identity].get("caption"):
                objects[identity]["caption"] = caption
            return
        objects[identity] = {
            "object_type": object_type,
            "object_key": key,
            "label": label,
            "caption": caption or None,
            "page_number": page_number(start),
            "char_start": start,
            "char_end": end,
            "occurrence_count": 1,
            "confidence": confidence,
            "metadata": metadata or {},
        }

    for line_match in re.finditer(r"(?m)^.*$", text):
        line = line_match.group().strip()
        if not line:
            continue
        caption = CAPTION_RE.match(line)
        if caption:
            object_type = "table" if caption.group(1).lower() == "table" else "figure"
            number_ = caption.group(2).lower()
            label = f"{object_type.title()} {caption.group(2)}"
            add_object(
                object_type,
                f"{object_type}:{number_}",
                label,
                caption.group(3).strip(),
                line_match.start(),
                line_match.end(),
                0.95,
            )
        theorem = THEOREM_RE.match(line)
        if theorem:
            kind = theorem.group(1).lower()
            object_type = "algorithm" if kind == "algorithm" else "theorem"
            number_ = theorem.group(2)
            if number_:
                key = f"{object_type}:{kind}:{number_.lower()}"
                label = f"{theorem.group(1).title()} {number_}"
            else:
                unnamed[(object_type, kind)] += 1
                key = f"{object_type}:{kind}:unnumbered-{unnamed[(object_type, kind)]}"
                label = theorem.group(1).title()
            add_object(
                object_type,
                key,
                label,
                theorem.group(3).strip(),
                line_match.start(),
                line_match.end(),
                0.9,
                {"kind": kind},
            )
        for equation in EQUATION_RE.finditer(line):
            number_ = equation.group(1) or equation.group(2)
            add_object(
                "equation",
                f"equation:{number_.lower()}",
                f"Equation {number_}",
                None,
                line_match.start() + equation.start(),
                line_match.start() + equation.end(),
                0.75,
            )

        if line_match.start() not in heading_offsets and len(line) <= 100:
            letters = [character for character in line if character.isalpha()]
            looks_like_heading = bool(re.match(r"^(?:\d+(?:\.\d+)*|[A-Z])\s+", line)) or (
                letters and sum(character.isupper() for character in letters) / len(letters) >= 0.65
            )
            compact_letters = re.sub(r"[^a-z]", "", line.lower())
            section_terms = (
                "abstract", "introduction", "relatedwork", "background", "preliminaries",
                "method", "approach", "model", "framework", "experiment", "evaluation",
                "result", "analysis", "discussion", "limitation", "conclusion", "reference",
                "appendix",
            )
            if looks_like_heading and any(term in compact_letters for term in section_terms):
                compact = re.sub(r"\s+", " ", line)
                headings.append({
                    "text": compact,
                    "level": None,
                    "char_start": line_match.start(),
                    "page_number": page_number(line_match.start()),
                })

    object_rows = sorted(objects.values(), key=lambda item: (item["char_start"], item["object_type"]))
    object_counts = dict(Counter(item["object_type"] for item in object_rows))
    lower = text.lower()
    routing_signals = {
        "deep_parse_policy": "review_triggered_only",
        "deep_parse_requested": False,
        "theory_sensitive": object_counts.get("theorem", 0) >= 3 or lower.count(" proof") >= 5,
        "result_table_sensitive": object_counts.get("table", 0) > 0 and any(
            token in lower for token in ("state-of-the-art", "state of the art", "baseline", "outperform")
        ),
        "ablation_sensitive": "ablation" in lower,
        "visual_method_sensitive": object_counts.get("figure", 0) > 0 and any(
            token in lower for token in ("architecture", "framework overview", "method overview")
        ),
        "short_or_incomplete_text": len(text.strip()) < 5000,
    }
    return {
        "content_hash": hashlib.sha256(text.encode()).hexdigest(),
        "char_count": len(text),
        "token_count": len(WORD_RE.findall(text)),
        "page_count": len(page_at_offset),
        "headings": sorted(headings, key=lambda item: item["char_start"]),
        "objects": object_rows,
        "object_counts": object_counts,
        "routing_signals": routing_signals,
    }


def recorded_pdf_hashes(source: Path) -> dict[str, tuple[str, int | None]]:
    hashes: dict[str, tuple[str, int | None]] = {}
    manifests = source / "fulltext" / "manifests"
    for path in (manifests / "batch_runs.jsonl", manifests / "rejected_runs.jsonl"):
        if not path.is_file():
            continue
        with path.open(encoding="utf-8") as handle:
            for line in handle:
                try:
                    item = json.loads(line)
                except json.JSONDecodeError:
                    continue
                paper_id = item.get("openreview_id")
                sha = item.get("pdf_sha256")
                if paper_id and sha:
                    hashes[str(paper_id)] = (str(sha), item.get("pdf_bytes"))
    return hashes


def milliseconds(value: Any) -> datetime | None:
    if value in (None, ""):
        return None
    try:
        return datetime.fromtimestamp(int(value) / 1000, timezone.utc)
    except (TypeError, ValueError, OSError):
        return None


def number(value: Any) -> float | None:
    if value in (None, ""):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    match = re.search(r"-?\d+(?:\.\d+)?", str(value))
    return float(match.group()) if match else None


def actor_role(item: dict[str, Any]) -> str:
    role = str(item.get("role") or "").lower()
    signature = str(item.get("signature") or item.get("reviewer_signature") or "")
    if role == "author" or "/Authors" in signature:
        return "author"
    if "Chair" in signature or "Program_Chairs" in signature or role == "chair":
        return "chair"
    if role == "reviewer" or "/Reviewer" in signature:
        return "reviewer"
    return "unknown"


def review_fields(item: dict[str, Any]) -> dict[str, Any]:
    return {
        "summary": item.get("summary") or item.get("summary_text"),
        "strengths": item.get("strengths") or item.get("strengths_text"),
        "weaknesses": item.get("weaknesses") or item.get("weaknesses_text"),
        "questions": item.get("questions") or item.get("questions_text"),
        "ethics_concerns": item.get("details_of_ethics_concerns"),
    }


def unwrap_openreview_content(content: dict[str, Any]) -> dict[str, Any]:
    unwrapped: dict[str, Any] = {}
    for key, value in content.items():
        if isinstance(value, dict) and "value" in value:
            unwrapped[key] = value["value"]
        else:
            unwrapped[key] = value
    return unwrapped


def review_id(item: dict[str, Any], forum_id: str, position: int) -> str:
    existing = item.get("id") or item.get("ranpox_id")
    if existing:
        return str(existing)
    seed = f"{forum_id}\0{item.get('reviewer_id')}\0{position}\0{content_hash(review_fields(item))}"
    return "synthetic-review-" + hashlib.sha256(seed.encode()).hexdigest()[:20]


def event_id(item: dict[str, Any], forum_id: str, position: int) -> str:
    if item.get("id"):
        return str(item["id"])
    seed = f"{forum_id}\0{position}\0{item.get('replyto')}\0{item.get('comment')}"
    return "synthetic-event-" + hashlib.sha256(seed.encode()).hexdigest()[:20]


def raw_note_payload(item: dict[str, Any], note_id: str, forum_id: str, note_type: str) -> dict[str, Any]:
    payload = dict(item)
    payload.setdefault("id", note_id)
    payload.setdefault("forum", forum_id)
    payload["_normalized_note_type"] = note_type
    return payload


def inventory(args: argparse.Namespace) -> dict[str, Any]:
    source = args.source.resolve()
    state = args.state.resolve()
    papers: list[dict[str, Any]] = []
    excluded: list[dict[str, Any]] = []
    seen: dict[str, str] = {}

    for year in YEARS:
        for path in sorted((source / str(year)).rglob("*.json")):
            if path.name == "index.json":
                continue
            try:
                paper = load_json(path)
            except Exception as exc:
                excluded.append({"year": year, "source_path": str(path), "reason": f"invalid_json:{exc}"})
                continue
            forum_id = str(paper.get("openreview_id") or paper.get("forum") or "")
            if paper.get("track") != "main":
                excluded.append({
                    "year": year,
                    "forum_id": forum_id or None,
                    "source_path": str(path),
                    "reason": f"excluded_track:{paper.get('track') or 'unknown'}",
                })
                continue
            if not forum_id:
                raise ValueError(f"main-track record lacks OpenReview ID: {path}")
            if forum_id in seen:
                raise ValueError(f"duplicate main-track OpenReview ID {forum_id}: {seen[forum_id]} and {path}")
            seen[forum_id] = str(path)
            papers.append({
                "year": year,
                "forum_id": forum_id,
                "paper_json": str(path),
                "openreview_json": str(source / ".raw_openreview" / str(year) / f"{forum_id}.json"),
                "pdf": str(source / "fulltext" / "pdf" / str(year) / f"{forum_id}.pdf"),
                "markdown": str(source / "fulltext" / "markdown" / str(year) / f"{forum_id}.md"),
            })

    pdf_hashes = recorded_pdf_hashes(source)
    artifact_jobs: list[tuple[int, str, str, str]] = []
    for index, paper in enumerate(papers):
        for kind in ("paper_json", "openreview_json", "pdf", "markdown"):
            path = Path(paper[kind])
            if path.is_file():
                artifact_jobs.append((index, kind, str(path), paper["forum_id"]))

    def inspect(job: tuple[int, str, str, str]) -> tuple[int, str, dict[str, Any]]:
        index, kind, raw_path, forum_id = job
        path = Path(raw_path)
        recorded = pdf_hashes.get(forum_id) if kind == "pdf" else None
        if recorded and (recorded[1] is None or int(recorded[1]) == path.stat().st_size):
            sha, _ = recorded
            hash_source = "fulltext_manifest"
        else:
            sha = file_hash(path)
            hash_source = "computed"
        return index, kind, {
            "path": raw_path,
            "status": "available",
            "sha256": sha,
            "bytes": path.stat().st_size,
            "extension": path.suffix.lower() or ".bin",
            "mime_type": mimetypes.guess_type(path.name)[0] or "application/octet-stream",
            "hash_source": hash_source,
        }

    inspected: dict[tuple[int, str], dict[str, Any]] = {}
    with ThreadPoolExecutor(max_workers=max(1, args.hash_workers)) as executor:
        for index, kind, detail in executor.map(inspect, artifact_jobs):
            inspected[(index, kind)] = detail

    counts = Counter()
    for index, paper in enumerate(papers):
        paper["artifacts"] = {}
        for kind in ("paper_json", "openreview_json", "pdf", "markdown"):
            detail = inspected.get((index, kind))
            if detail is None:
                detail = {"path": paper[kind], "status": "missing"}
            else:
                counts[kind] += 1
                counts[f"{kind}_hash_{detail['hash_source']}"] += 1
            paper["artifacts"][kind] = detail
        for key in ("paper_json", "openreview_json", "pdf", "markdown"):
            paper.pop(key)

    raw_ids = {
        path.stem
        for year in YEARS
        for path in (source / ".raw_openreview" / str(year)).glob("*.json")
    }
    orphan_raw = sorted(raw_ids - set(seen))
    verification_candidates = sorted(
        (
            row["artifacts"]["pdf"]
            for row in papers
            if row["artifacts"]["pdf"].get("hash_source") == "fulltext_manifest"
        ),
        key=lambda item: item["sha256"],
    )[:100]
    for artifact in verification_candidates:
        actual = file_hash(Path(artifact["path"]))
        if actual != artifact["sha256"]:
            raise ValueError(f"recorded PDF hash mismatch: {artifact['path']}")

    summary = {
        "generated_at": utc_now(),
        "source_root": str(source),
        "main_papers": len(papers),
        "by_year": dict(Counter(str(row["year"]) for row in papers)),
        "available_artifacts": dict(counts),
        "excluded_records": len(excluded),
        "orphan_openreview_snapshots": orphan_raw,
        "recorded_pdf_hashes_verified": len(verification_candidates),
    }
    write_jsonl(state / "inventory.jsonl", papers)
    write_jsonl(state / "excluded.jsonl", excluded)
    write_json(state / "inventory_summary.json", summary)
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return summary


def object_store(args: argparse.Namespace) -> dict[str, Any]:
    state = args.state.resolve()
    store = args.store.resolve()
    rows = read_jsonl(state / "inventory.jsonl")
    manifest: dict[tuple[str, str], dict[str, Any]] = {}
    linked = reused = copied = 0
    for row in rows:
        for kind, artifact in row["artifacts"].items():
            if artifact["status"] != "available":
                continue
            source = Path(artifact["path"])
            sha = artifact["sha256"]
            target = store / sha[:2] / sha[2:4] / f"{sha}{artifact['extension']}"
            target.parent.mkdir(parents=True, exist_ok=True)
            if target.exists():
                if target.stat().st_size != artifact["bytes"]:
                    raise ValueError(f"object collision or truncated target: {target}")
                reused += 1
            else:
                try:
                    os.link(source, target)
                    linked += 1
                except OSError:
                    shutil.copy2(source, target)
                    copied += 1
            artifact["object_path"] = str(target)
            manifest[(artifact["path"], sha)] = {
                "source_path": artifact["path"],
                "object_path": str(target),
                "sha256": sha,
                "bytes": artifact["bytes"],
                "source_type": kind,
            }
    manifest_rows = sorted(manifest.values(), key=lambda item: (item["source_path"], item["sha256"]))
    write_jsonl(state / "object_manifest.jsonl", manifest_rows)
    write_jsonl(state / "inventory.jsonl", rows)
    summary = {"objects": len(manifest_rows), "hardlinked": linked, "reused": reused, "copied": copied}
    write_json(state / "object_store_summary.json", summary)
    print(json.dumps(summary, indent=2))
    return summary


def db_connect(url: str) -> psycopg.Connection[Any]:
    return psycopg.connect(url, autocommit=False)


def git_version() -> str:
    result = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=REPO, text=True, capture_output=True
    )
    return result.stdout.strip() if result.returncode == 0 else "unknown"


def one(cur: psycopg.Cursor[Any], query: str, params: tuple[Any, ...]) -> int:
    cur.execute(query, params)
    row = cur.fetchone()
    if row is None:
        raise RuntimeError("expected RETURNING row")
    return int(row[0])


def put_source_record(
    cur: psycopg.Cursor[Any], ingest_run_id: int, kind: str, year: int,
    forum_id: str, artifact: dict[str, Any], payload: dict[str, Any]
) -> int:
    return one(cur, """
        INSERT INTO raw.source_record(
            ingest_run_id, source_kind, source_path, conference_year, forum_id,
            sha256, byte_size, raw_payload
        ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s)
        ON CONFLICT (source_path, sha256) DO UPDATE SET source_path = EXCLUDED.source_path
        RETURNING source_record_id
    """, (
        ingest_run_id, kind, artifact["path"], year, forum_id,
        artifact["sha256"], artifact["bytes"], Jsonb(payload),
    ))


def put_raw_artifact(
    cur: psycopg.Cursor[Any], ingest_run_id: int, kind: str, artifact: dict[str, Any], source_url: str | None
) -> int | None:
    if artifact["status"] != "available":
        return None
    return one(cur, """
        INSERT INTO raw.artifact(
            ingest_run_id, source_path, object_path, sha256, extension, mime_type,
            byte_size, source_type, source_url, quality_status
        ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,'available')
        ON CONFLICT (source_path, sha256) DO UPDATE SET object_path = EXCLUDED.object_path
        RETURNING artifact_id
    """, (
        ingest_run_id, artifact["path"], artifact["object_path"], artifact["sha256"],
        artifact["extension"], artifact["mime_type"], artifact["bytes"], kind, source_url,
    ))


def put_raw_note(
    cur: psycopg.Cursor[Any], source_record_id: int, item: dict[str, Any],
    note_id: str, forum_id: str, note_type: str
) -> int:
    payload = raw_note_payload(item, note_id, forum_id, note_type)
    role = actor_role(item)
    return one(cur, """
        INSERT INTO raw.openreview_note(
            source_record_id, note_id, forum_id, reply_to, invitation, signature,
            actor_role, note_type, created_ms, modified_ms, revision_no, content_hash, raw_payload
        ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,1,%s,%s)
        ON CONFLICT (note_id, revision_no, content_hash) DO UPDATE SET source_record_id = EXCLUDED.source_record_id
        RETURNING openreview_note_id
    """, (
        source_record_id, note_id, forum_id, item.get("replyto"), item.get("invitation"),
        item.get("signature") or item.get("reviewer_signature"), role, note_type,
        item.get("tcdate"), item.get("tmdate"), content_hash(payload), Jsonb(payload),
    ))


def put_author(cur: psycopg.Cursor[Any], paper_id: int, author: Any, position: int) -> None:
    if isinstance(author, str):
        author = {"name": author}
    name = str(author.get("name") or "Anonymous").strip() or "Anonymous"
    profile_id = author.get("openreview_id")
    identity_key = str(profile_id) if profile_id else "name:" + re.sub(r"\s+", " ", name.lower())
    author_id = one(cur, """
        INSERT INTO core.author(identity_key, openreview_profile_id, name, orcid, profile)
        VALUES (%s,%s,%s,%s,%s)
        ON CONFLICT (identity_key) DO UPDATE SET
            name = EXCLUDED.name,
            orcid = COALESCE(EXCLUDED.orcid, core.author.orcid),
            profile = core.author.profile || EXCLUDED.profile
        RETURNING author_id
    """, (identity_key, profile_id, name, author.get("orcid"), Jsonb(author)))
    cur.execute("""
        INSERT INTO core.paper_author(paper_id, author_id, author_position)
        VALUES (%s,%s,%s)
        ON CONFLICT (paper_id, author_position) DO UPDATE SET author_id = EXCLUDED.author_id
    """, (paper_id, author_id, position))
    affiliations = author.get("affiliations") or []
    domains = author.get("affiliation_domains") or []
    for index, affiliation in enumerate(affiliations):
        domain = domains[index] if index < len(domains) else None
        affiliation_id = one(cur, """
            INSERT INTO core.affiliation(name, domain) VALUES (%s,%s)
            ON CONFLICT (name, domain) DO UPDATE SET name = EXCLUDED.name
            RETURNING affiliation_id
        """, (str(affiliation), domain))
        cur.execute("""
            INSERT INTO core.author_affiliation(paper_id, author_id, affiliation_id)
            VALUES (%s,%s,%s) ON CONFLICT DO NOTHING
        """, (paper_id, author_id, affiliation_id))


def put_review(
    cur: psycopg.Cursor[Any], paper_id: int, forum_id: str, item: dict[str, Any],
    source_record_id: int, position: int
) -> tuple[str, int]:
    note_id = review_id(item, forum_id, position)
    raw_note_id = put_raw_note(cur, source_record_id, item, note_id, forum_id, "official_review")
    reviewer = str(item.get("reviewer_id") or item.get("reviewer_signature") or note_id)
    alias_hash = hashlib.sha256(f"{forum_id}\0{reviewer}".encode()).hexdigest()
    review_pk = one(cur, """
        INSERT INTO core.review(paper_id, source_note_id, reviewer_alias_hash, raw_note_id, created_at)
        VALUES (%s,%s,%s,%s,%s)
        ON CONFLICT (paper_id, source_note_id) DO UPDATE SET raw_note_id = EXCLUDED.raw_note_id
        RETURNING review_id
    """, (paper_id, note_id, alias_hash, raw_note_id, milliseconds(item.get("tcdate"))))
    fields = review_fields(item)
    revision_hash = content_hash(item)
    cur.execute("SELECT review_revision_id, revision_no FROM core.review_revision WHERE review_id=%s AND content_hash=%s", (review_pk, revision_hash))
    existing = cur.fetchone()
    if existing:
        revision_pk, _ = existing
    else:
        cur.execute("SELECT coalesce(max(revision_no), 0) + 1 FROM core.review_revision WHERE review_id=%s", (review_pk,))
        revision_no = int(cur.fetchone()[0])
        revision_pk = one(cur, """
            INSERT INTO core.review_revision(
                review_id, revision_no, summary, strengths, weaknesses, questions,
                ethics_concerns, raw_content, content_hash, created_at, modified_at
            ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
            RETURNING review_revision_id
        """, (
            review_pk, revision_no, fields["summary"], fields["strengths"], fields["weaknesses"],
            fields["questions"], fields["ethics_concerns"], Jsonb(item), revision_hash,
            milliseconds(item.get("tcdate")), milliseconds(item.get("tmdate")),
        ))
    scores = {key: item.get(key) for key in ("rating", "confidence", "soundness", "contribution", "presentation")}
    cur.execute("""
        INSERT INTO core.review_score(
            review_revision_id, rating, confidence, soundness, contribution, presentation, raw_score
        ) VALUES (%s,%s,%s,%s,%s,%s,%s)
        ON CONFLICT (review_revision_id) DO UPDATE SET
            rating=EXCLUDED.rating, confidence=EXCLUDED.confidence, soundness=EXCLUDED.soundness,
            contribution=EXCLUDED.contribution, presentation=EXCLUDED.presentation, raw_score=EXCLUDED.raw_score
    """, (
        revision_pk, number(scores["rating"]), number(scores["confidence"]), number(scores["soundness"]),
        number(scores["contribution"]), number(scores["presentation"]), Jsonb(scores),
    ))
    return note_id, review_pk


def put_discussion(
    cur: psycopg.Cursor[Any], paper_id: int, forum_id: str, item: dict[str, Any],
    source_record_id: int, position: int
) -> tuple[str, int, str | None]:
    note_id = event_id(item, forum_id, position)
    role = actor_role(item)
    body = str(item.get("comment") or item.get("content") or "")
    if role == "author":
        event_type = "author_response"
        note_type = "author_response"
    elif role == "reviewer":
        event_type = "reviewer_response"
        note_type = "reviewer_comment"
    elif role == "chair" and re.search(r"remind|deadline|discussion period", body, re.I):
        event_type = "reminder"
        note_type = "reviewer_comment"
    else:
        event_type = "public_comment"
        note_type = "reviewer_comment"
    raw_note_id = put_raw_note(cur, source_record_id, item, note_id, forum_id, note_type)
    event_pk = one(cur, """
        INSERT INTO core.discussion_event(
            paper_id, source_note_id, parent_note_id, raw_note_id, actor_role, event_type,
            signature, body, created_at, modified_at, raw_content
        ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
        ON CONFLICT (paper_id, source_note_id) DO UPDATE SET
            parent_note_id=EXCLUDED.parent_note_id, body=EXCLUDED.body,
            modified_at=EXCLUDED.modified_at, raw_content=EXCLUDED.raw_content
        RETURNING discussion_event_id
    """, (
        paper_id, note_id, item.get("replyto") or item.get("reply_to") or forum_id,
        raw_note_id, role, event_type, item.get("signature"), body,
        milliseconds(item.get("tcdate") or item.get("created_ms")),
        milliseconds(item.get("tmdate") or item.get("modified_ms")), Jsonb(item),
    ))
    return note_id, event_pk, item.get("replyto") or item.get("reply_to")


def rebuild_review_revisions(cur: psycopg.Cursor[Any], note_id: str) -> int:
    cur.execute("SELECT review_id FROM core.review WHERE source_note_id=%s", (note_id,))
    row = cur.fetchone()
    if row is None:
        return 0
    review_pk = int(row[0])
    cur.execute("""
        SELECT raw_payload FROM raw.openreview_edit
        WHERE note_id=%s AND raw_payload #> '{note,content}' IS NOT NULL
        ORDER BY revision_no, openreview_edit_id
    """, (note_id,))
    historical: list[dict[str, Any]] = []
    for (payload,) in cur.fetchall():
        note = payload.get("note") or {}
        item = unwrap_openreview_content(note.get("content") or {})
        item.update({
            "id": note_id,
            "forum": note.get("forum"),
            "replyto": note.get("replyto"),
            "tcdate": note.get("cdate"),
            "tmdate": note.get("mdate") or note.get("ddate"),
            "_openreview_edit": payload,
        })
        historical.append(item)
    if not historical:
        return 0
    cur.execute("""
        SELECT raw_content FROM core.review_revision
        WHERE review_id=%s ORDER BY revision_no DESC LIMIT 1
    """, (review_pk,))
    current = cur.fetchone()[0]
    versions: list[dict[str, Any]] = []
    seen = set()
    for item in historical + [current]:
        digest = content_hash(item)
        if digest not in seen:
            seen.add(digest)
            versions.append(item)
    cur.execute("DELETE FROM core.review_revision WHERE review_id=%s", (review_pk,))
    for revision_no, item in enumerate(versions, 1):
        fields = review_fields(item)
        revision_pk = one(cur, """
            INSERT INTO core.review_revision(
                review_id, revision_no, summary, strengths, weaknesses, questions,
                ethics_concerns, raw_content, content_hash, created_at, modified_at
            ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
            RETURNING review_revision_id
        """, (
            review_pk, revision_no, fields["summary"], fields["strengths"], fields["weaknesses"],
            fields["questions"], fields["ethics_concerns"], Jsonb(item), content_hash(item),
            milliseconds(item.get("tcdate")), milliseconds(item.get("tmdate")),
        ))
        scores = {key: item.get(key) for key in ("rating", "confidence", "soundness", "contribution", "presentation")}
        cur.execute("""
            INSERT INTO core.review_score(
                review_revision_id, rating, confidence, soundness, contribution, presentation, raw_score
            ) VALUES (%s,%s,%s,%s,%s,%s,%s)
        """, (
            revision_pk, number(scores["rating"]), number(scores["confidence"]),
            number(scores["soundness"]), number(scores["contribution"]),
            number(scores["presentation"]), Jsonb(scores),
        ))
    return len(versions)


def ingest_paper(cur: psycopg.Cursor[Any], ingest_run_id: int, row: dict[str, Any]) -> Counter[str]:
    counts: Counter[str] = Counter()
    year = int(row["year"])
    forum_id = row["forum_id"]
    artifacts = row["artifacts"]
    metadata = load_json(Path(artifacts["paper_json"]["path"]))
    raw_snapshot = (
        load_json(Path(artifacts["openreview_json"]["path"]))
        if artifacts["openreview_json"]["status"] == "available"
        else {"reviews": metadata.get("reviews") or [], "rebuttals": metadata.get("rebuttals") or [], "reviewer_comments": metadata.get("reviewer_comments") or []}
    )
    metadata_source = put_source_record(
        cur, ingest_run_id, "paper_metadata", year, forum_id, artifacts["paper_json"], metadata
    )
    snapshot_source = (
        put_source_record(
            cur, ingest_run_id, "openreview_snapshot", year, forum_id,
            artifacts["openreview_json"], raw_snapshot,
        )
        if artifacts["openreview_json"]["status"] == "available"
        else metadata_source
    )
    venue_id = one(cur, """
        INSERT INTO core.venue(name, year, track) VALUES ('ICLR', %s, 'main')
        ON CONFLICT (name, year, track) DO UPDATE SET name=EXCLUDED.name RETURNING venue_id
    """, (year,))
    paper_id = one(cur, """
        INSERT INTO core.paper(
            venue_id, openreview_id, forum_id, openreview_url, pdf_url, status, track,
            accepted_main, accepted_any, source_record_id
        ) VALUES (%s,%s,%s,%s,%s,%s,'main',%s,%s,%s)
        ON CONFLICT (venue_id, forum_id) DO UPDATE SET
            openreview_url=EXCLUDED.openreview_url, pdf_url=EXCLUDED.pdf_url,
            status=EXCLUDED.status, accepted_main=EXCLUDED.accepted_main,
            accepted_any=EXCLUDED.accepted_any, source_record_id=EXCLUDED.source_record_id,
            updated_at=now()
        RETURNING paper_id
    """, (
        venue_id, metadata.get("openreview_id") or forum_id, forum_id,
        metadata.get("openreview_url"), metadata.get("pdf_url"), metadata.get("status"),
        bool(metadata.get("accepted_main")), bool(metadata.get("accepted_any")), metadata_source,
    ))
    version_payload = {
        "title": metadata.get("title") or "Untitled",
        "abstract": metadata.get("abstract"),
        "tldr": metadata.get("tldr"),
        "keywords": metadata.get("keywords") or [],
    }
    cur.execute("SELECT paper_version_id FROM core.paper_version WHERE paper_id=%s AND content_hash=%s", (paper_id, content_hash(version_payload)))
    if cur.fetchone() is None:
        cur.execute("SELECT coalesce(max(version_no), 0) + 1 FROM core.paper_version WHERE paper_id=%s", (paper_id,))
        version_no = int(cur.fetchone()[0])
        cur.execute("""
            INSERT INTO core.paper_version(
                paper_id, version_no, title, abstract, tldr, keywords, source_record_id, content_hash
            ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s)
        """, (
            paper_id, version_no, version_payload["title"], version_payload["abstract"],
            version_payload["tldr"], version_payload["keywords"], metadata_source,
            content_hash(version_payload),
        ))
    for position, author in enumerate(metadata.get("authors") or [], 1):
        put_author(cur, paper_id, author, position)
    area = str(metadata.get("primary_area") or "unknown").strip() or "unknown"
    area_id = one(cur, """
        INSERT INTO core.explicit_area(raw_label, canonical_key, first_year, last_year)
        VALUES (%s,%s,%s,%s)
        ON CONFLICT (raw_label) DO UPDATE SET
            first_year=least(core.explicit_area.first_year, EXCLUDED.first_year),
            last_year=greatest(core.explicit_area.last_year, EXCLUDED.last_year)
        RETURNING explicit_area_id
    """, (area, canonical_area(area), year, year))
    cur.execute("""
        INSERT INTO core.paper_area(paper_id, explicit_area_id, is_primary, source_record_id)
        VALUES (%s,%s,true,%s) ON CONFLICT DO NOTHING
    """, (paper_id, area_id, metadata_source))

    raw_artifacts: dict[str, int | None] = {}
    for kind, artifact in artifacts.items():
        raw_artifacts[kind] = put_raw_artifact(
            cur, ingest_run_id, kind, artifact,
            metadata.get("pdf_url") if kind == "pdf" else None,
        )
        cur.execute("""
            INSERT INTO core.artifact(paper_id, raw_artifact_id, artifact_role, availability, quality_details)
            VALUES (%s,%s,%s,%s,%s)
            ON CONFLICT (paper_id, artifact_role) DO UPDATE SET
                raw_artifact_id=EXCLUDED.raw_artifact_id,
                availability=EXCLUDED.availability,
                quality_details=EXCLUDED.quality_details
        """, (
            paper_id, raw_artifacts[kind], kind, artifact["status"],
            Jsonb({"source_path": artifact["path"]}),
        ))

    reviews = raw_snapshot.get("reviews") or metadata.get("reviews") or []
    review_map: dict[str, int] = {}
    for position, item in enumerate(reviews, 1):
        note_id, review_pk = put_review(cur, paper_id, forum_id, item, snapshot_source, position)
        review_map[note_id] = review_pk
    discussion = list(raw_snapshot.get("rebuttals") or metadata.get("rebuttals") or [])
    discussion += list(raw_snapshot.get("reviewer_comments") or metadata.get("reviewer_comments") or [])
    discussion.sort(key=lambda item: (item.get("tcdate") or 0, item.get("tmdate") or 0, item.get("id") or ""))
    event_map: dict[str, int] = {}
    parents: dict[str, str | None] = {}
    for position, item in enumerate(discussion, 1):
        note_id, event_pk, parent = put_discussion(cur, paper_id, forum_id, item, snapshot_source, position)
        event_map[note_id] = event_pk
        parents[note_id] = parent
    for note_id, event_pk in event_map.items():
        parent = parents[note_id]
        if not parent or parent == forum_id:
            continue
        if parent in review_map:
            cur.execute("UPDATE core.discussion_event SET parent_review_id=%s WHERE discussion_event_id=%s", (review_map[parent], event_pk))
        elif parent in event_map:
            cur.execute("UPDATE core.discussion_event SET parent_event_id=%s WHERE discussion_event_id=%s", (event_map[parent], event_pk))
        else:
            cur.execute("""
                INSERT INTO ops.data_quality_issue(
                    ingest_run_id, paper_id, issue_type, severity, entity_type, entity_key, details
                ) VALUES (%s,%s,'orphan_reply','warning','discussion_event',%s,%s)
                ON CONFLICT (paper_id, issue_type, entity_type, entity_key) DO UPDATE SET
                    ingest_run_id=EXCLUDED.ingest_run_id,
                    details=EXCLUDED.details
            """, (ingest_run_id, paper_id, note_id, Jsonb({"parent_note_id": parent})))

    cur.execute("""
        INSERT INTO core.decision(
            paper_id, raw_decision, decision_category, accepted_main, accepted_any, source_record_id
        ) VALUES (%s,%s,%s,%s,%s,%s)
        ON CONFLICT (paper_id, source_record_id) DO UPDATE SET
            raw_decision=EXCLUDED.raw_decision, decision_category=EXCLUDED.decision_category,
            accepted_main=EXCLUDED.accepted_main, accepted_any=EXCLUDED.accepted_any
    """, (
        paper_id, metadata.get("decision"), metadata.get("decision_category"),
        bool(metadata.get("accepted_main")), bool(metadata.get("accepted_any")), metadata_source,
    ))
    counts.update(papers=1, reviews=len(reviews), discussion_events=len(discussion))
    counts.update({f"artifact_{kind}": int(artifact["status"] == "available") for kind, artifact in artifacts.items()})
    return counts


def finalize_aliases(cur: psycopg.Cursor[Any]) -> None:
    cur.execute("SELECT explicit_area_id, canonical_key FROM core.explicit_area ORDER BY explicit_area_id")
    rows = cur.fetchall()
    canonical_ids: dict[str, int] = {}
    for area_id, key in rows:
        canonical_ids.setdefault(key, area_id)
    for area_id, key in rows:
        cur.execute("""
            INSERT INTO core.area_alias(raw_area_id, canonical_area_id, rationale)
            VALUES (%s,%s,%s)
            ON CONFLICT (raw_area_id) DO UPDATE SET canonical_area_id=EXCLUDED.canonical_area_id
        """, (area_id, canonical_ids[key], "Cross-year canonical label normalization"))


def ingest(args: argparse.Namespace) -> dict[str, Any]:
    rows = read_jsonl(args.state.resolve() / "inventory.jsonl")
    excluded = read_jsonl(args.state.resolve() / "excluded.jsonl")
    totals: Counter[str] = Counter()
    with db_connect(args.database_url) as conn:
        with conn.cursor() as cur:
            ingest_run_id = one(cur, """
                INSERT INTO raw.ingest_run(status, code_version, source_root, inventory_path)
                VALUES ('running',%s,%s,%s) RETURNING ingest_run_id
            """, (git_version(), str(args.source.resolve()), str(args.state.resolve() / "inventory.jsonl")))
        conn.commit()
        try:
            for index, row in enumerate(rows, 1):
                with conn.cursor() as cur:
                    totals.update(ingest_paper(cur, ingest_run_id, row))
                if index % args.commit_every == 0:
                    conn.commit()
                    print(f"ingested {index}/{len(rows)}", flush=True)
            with conn.cursor() as cur:
                for item in excluded:
                    cur.execute("""
                        INSERT INTO raw.excluded_record(
                            ingest_run_id, source_path, conference_year, forum_id, reason
                        ) VALUES (%s,%s,%s,%s,%s) ON CONFLICT (source_path, reason) DO NOTHING
                    """, (ingest_run_id, item["source_path"], item.get("year"), item.get("forum_id"), item["reason"]))
                finalize_aliases(cur)
                cur.execute("""
                    UPDATE raw.ingest_run SET finished_at=now(), status='success', statistics=%s
                    WHERE ingest_run_id=%s
                """, (Jsonb(dict(totals)), ingest_run_id))
            conn.commit()
        except Exception as exc:
            conn.rollback()
            with conn.cursor() as cur:
                cur.execute("""
                    UPDATE raw.ingest_run SET finished_at=now(), status='failed', error=%s
                    WHERE ingest_run_id=%s
                """, (f"{type(exc).__name__}: {exc}", ingest_run_id))
            conn.commit()
            raise
    summary = {"ingest_run_id": ingest_run_id, **dict(totals)}
    write_json(args.state.resolve() / "ingest_summary.json", summary)
    print(json.dumps(summary, indent=2))
    return summary


def fulltext_index(args: argparse.Namespace) -> dict[str, Any]:
    """Index text and object locations only; deep parsing remains review-triggered."""
    state = args.state.resolve()
    totals: Counter[str] = Counter()
    trigger_counts: Counter[str] = Counter()
    object_counts: Counter[str] = Counter()
    with db_connect(args.database_url) as conn, conn.cursor() as cur:
        cur.execute("""
            SELECT p.paper_id, p.forum_id, v.year, ca.paper_artifact_id,
                   ra.object_path, ra.source_path
            FROM core.paper p
            JOIN core.venue v USING(venue_id)
            LEFT JOIN core.artifact ca
              ON ca.paper_id=p.paper_id AND ca.artifact_role='markdown'
             AND ca.availability='available'
            LEFT JOIN raw.artifact ra ON ra.artifact_id=ca.raw_artifact_id
            ORDER BY v.year, p.paper_id
        """)
        papers = cur.fetchall()
        if args.fulltext_limit:
            papers = papers[: args.fulltext_limit]
        cur.execute("""
            SELECT paper_id, source_artifact_id, index_version, content_hash, status
            FROM semantic.paper_fulltext_index
        """)
        existing = {int(row[0]): tuple(row[1:]) for row in cur.fetchall()}

        for index, (paper_id, forum_id, year, artifact_id, object_path, source_path) in enumerate(papers, 1):
            previous = existing.get(int(paper_id))
            if previous and previous[0] == artifact_id and previous[1] == FULLTEXT_INDEX_VERSION:
                previous_status = previous[3]
                if (artifact_id is not None and previous_status == "indexed") or (
                    artifact_id is None and previous_status == "missing"
                ):
                    totals["unchanged"] += 1
                    totals[previous_status] += 1
                    continue
            path = next(
                (candidate for candidate in (object_path, source_path) if candidate and Path(candidate).is_file()),
                None,
            )
            if path is None:
                payload = {
                    "content_hash": None,
                    "char_count": 0,
                    "token_count": 0,
                    "page_count": None,
                    "headings": [],
                    "objects": [],
                    "object_counts": {},
                    "routing_signals": {"deep_parse_policy": "review_triggered_only", "deep_parse_requested": False},
                }
                status = "missing"
                error = "markdown artifact unavailable"
            else:
                try:
                    payload = lightweight_fulltext_index(Path(path).read_text(encoding="utf-8", errors="replace"))
                    status = "indexed"
                    error = None
                except Exception as exc:
                    payload = {
                        "content_hash": None,
                        "char_count": 0,
                        "token_count": 0,
                        "page_count": None,
                        "headings": [],
                        "objects": [],
                        "object_counts": {},
                        "routing_signals": {"deep_parse_policy": "review_triggered_only", "deep_parse_requested": False},
                    }
                    status = "invalid"
                    error = f"{type(exc).__name__}: {exc}"[:1000]

            cur.execute("""
                INSERT INTO semantic.paper_fulltext_index(
                    paper_id, source_artifact_id, index_version, content_hash, status,
                    processing_policy, deep_parse_status, char_count, token_count, page_count,
                    headings, object_counts, routing_signals, error
                ) VALUES (%s,%s,%s,%s,%s,'text_first_on_demand','not_requested',%s,%s,%s,%s,%s,%s,%s)
                ON CONFLICT (paper_id) DO UPDATE SET
                    source_artifact_id=EXCLUDED.source_artifact_id,
                    index_version=EXCLUDED.index_version,
                    content_hash=EXCLUDED.content_hash,
                    status=EXCLUDED.status,
                    processing_policy=EXCLUDED.processing_policy,
                    deep_parse_status=CASE
                        WHEN semantic.paper_fulltext_index.content_hash IS DISTINCT FROM EXCLUDED.content_hash
                        THEN 'not_requested'
                        ELSE semantic.paper_fulltext_index.deep_parse_status
                    END,
                    char_count=EXCLUDED.char_count,
                    token_count=EXCLUDED.token_count,
                    page_count=EXCLUDED.page_count,
                    headings=EXCLUDED.headings,
                    object_counts=EXCLUDED.object_counts,
                    routing_signals=EXCLUDED.routing_signals,
                    error=EXCLUDED.error,
                    updated_at=now()
            """, (
                paper_id, artifact_id, FULLTEXT_INDEX_VERSION, payload["content_hash"], status,
                payload["char_count"], payload["token_count"], payload["page_count"],
                Jsonb(payload["headings"]), Jsonb(payload["object_counts"]),
                Jsonb(payload["routing_signals"]), error,
            ))
            cur.execute("DELETE FROM semantic.paper_content_object WHERE paper_id=%s", (paper_id,))
            for item in payload["objects"]:
                cur.execute("""
                    INSERT INTO semantic.paper_content_object(
                        paper_id, object_type, object_key, label, caption, page_number,
                        char_start, char_end, occurrence_count, confidence, metadata
                    ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                """, (
                    paper_id, item["object_type"], item["object_key"], item["label"],
                    item["caption"], item["page_number"], item["char_start"], item["char_end"],
                    item["occurrence_count"], item["confidence"], Jsonb(item["metadata"]),
                ))
                object_counts[item["object_type"]] += 1
            for key, enabled in payload["routing_signals"].items():
                if isinstance(enabled, bool) and enabled:
                    trigger_counts[key] += 1
            totals[status] += 1
            totals["updated"] += 1
            if index % args.commit_every == 0:
                conn.commit()
                print(f"indexed {index}/{len(papers)}", flush=True)
        conn.commit()

        cur.execute("SELECT status, count(*) FROM semantic.paper_fulltext_index GROUP BY status")
        database_status = {status: int(count) for status, count in cur.fetchall()}
        cur.execute("SELECT object_type, count(*) FROM semantic.paper_content_object GROUP BY object_type")
        database_objects = {kind: int(count) for kind, count in cur.fetchall()}
        cur.execute("SELECT count(*) FROM semantic.paper_fulltext_index WHERE deep_parse_status <> 'not_requested'")
        deep_parse_started = int(cur.fetchone()[0])

    report = {
        "generated_at": utc_now(),
        "index_version": FULLTEXT_INDEX_VERSION,
        "processing_policy": "text_first_on_demand",
        "papers_considered": len(papers),
        "run_counts": dict(totals),
        "database_status": database_status,
        "database_objects": database_objects,
        "new_object_counts": dict(object_counts),
        "routing_signal_counts": dict(trigger_counts),
        "deep_parse_started": deep_parse_started,
    }
    write_json(state / "fulltext_index_report.json", report)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return report


TABLES = (
    "core.paper", "core.paper_version", "core.author", "core.affiliation", "core.paper_author",
    "core.explicit_area", "core.paper_area", "core.artifact", "core.review",
    "core.review_revision", "core.review_score", "core.discussion_event", "core.decision",
    "raw.source_record", "raw.openreview_note", "raw.openreview_edit", "raw.artifact",
    "raw.openreview_revision_probe",
    "raw.excluded_record", "ops.data_quality_issue",
    "ops.source_capability",
    "semantic.paper_fulltext_index", "semantic.paper_content_object",
)


def table_counts(cur: psycopg.Cursor[Any]) -> dict[str, int]:
    counts = {}
    for table in TABLES:
        cur.execute(f"SELECT count(*) FROM {table}")
        counts[table] = int(cur.fetchone()[0])
    return counts


def validate(args: argparse.Namespace) -> dict[str, Any]:
    state = args.state.resolve()
    inventory_rows = read_jsonl(state / "inventory.jsonl")
    expected = {
        "papers": len(inventory_rows),
        "markdown": sum(row["artifacts"]["markdown"]["status"] == "available" for row in inventory_rows),
        "pdf": sum(row["artifacts"]["pdf"]["status"] == "available" for row in inventory_rows),
    }
    checks: list[dict[str, Any]] = []
    with db_connect(args.database_url) as conn, conn.cursor() as cur:
        counts = table_counts(cur)

        def check(name: str, passed: bool, actual: Any, expected_value: Any) -> None:
            checks.append({"name": name, "passed": bool(passed), "actual": actual, "expected": expected_value})

        check("main_paper_count", counts["core.paper"] == expected["papers"], counts["core.paper"], expected["papers"])
        cur.execute("SELECT count(*) FROM core.paper WHERE track <> 'main'")
        non_main = int(cur.fetchone()[0])
        check("no_workshop_papers", non_main == 0, non_main, 0)
        cur.execute("SELECT count(*) FROM core.artifact WHERE artifact_role='markdown' AND availability='available'")
        markdown = int(cur.fetchone()[0])
        check("markdown_coverage", markdown == expected["markdown"], markdown, expected["markdown"])
        cur.execute("SELECT count(*) FROM core.artifact WHERE artifact_role='pdf' AND availability='available'")
        pdf = int(cur.fetchone()[0])
        check("pdf_coverage", pdf == expected["pdf"], pdf, expected["pdf"])
        cur.execute("SELECT count(*) FROM semantic.paper_fulltext_index")
        fulltext_rows = int(cur.fetchone()[0])
        check("fulltext_index_coverage", fulltext_rows == expected["papers"], fulltext_rows, expected["papers"])
        cur.execute("SELECT count(*) FROM semantic.paper_fulltext_index WHERE status='indexed'")
        indexed_markdown = int(cur.fetchone()[0])
        check("fulltext_markdown_coverage", indexed_markdown == expected["markdown"], indexed_markdown, expected["markdown"])
        cur.execute("SELECT count(*) FROM semantic.paper_fulltext_index WHERE deep_parse_status <> 'not_requested'")
        eager_deep_parse = int(cur.fetchone()[0])
        check("no_eager_deep_parse", eager_deep_parse == 0, eager_deep_parse, 0)
        cur.execute("SELECT count(*) FROM core.discussion_event WHERE parent_event_id IS NOT NULL AND parent_review_id IS NOT NULL")
        dual_parent = int(cur.fetchone()[0])
        check("single_parent_type", dual_parent == 0, dual_parent, 0)
        cur.execute("""
            SELECT count(*) FROM core.discussion_event child
            JOIN core.discussion_event parent ON parent.discussion_event_id=child.parent_event_id
            WHERE child.paper_id <> parent.paper_id
        """)
        cross_paper = int(cur.fetchone()[0])
        check("no_cross_paper_replies", cross_paper == 0, cross_paper, 0)
        cur.execute("SELECT count(*) FROM core.review r JOIN core.paper p USING(paper_id) WHERE r.reviewer_alias_hash IS NULL")
        missing_alias = int(cur.fetchone()[0])
        check("paper_scoped_reviewer_aliases", missing_alias == 0, missing_alias, 0)

        sample = sorted(inventory_rows, key=lambda row: hashlib.sha256(row["forum_id"].encode()).hexdigest())[:300]
        mismatches = []
        for row in sample:
            source = load_json(Path(row["artifacts"]["paper_json"]["path"]))
            cur.execute("""
                SELECT pv.title, pv.abstract, p.accepted_main, d.raw_decision
                FROM core.paper p
                JOIN core.latest_paper_version pv USING(paper_id)
                LEFT JOIN LATERAL (
                    SELECT raw_decision FROM core.decision WHERE paper_id=p.paper_id ORDER BY decision_id DESC LIMIT 1
                ) d ON true
                WHERE p.forum_id=%s
            """, (row["forum_id"],))
            database_row = cur.fetchone()
            wanted = (source.get("title") or "Untitled", source.get("abstract"), bool(source.get("accepted_main")), source.get("decision"))
            if database_row is None or tuple(database_row) != wanted:
                mismatches.append(row["forum_id"])
        check("sample_300_exact", not mismatches, mismatches[:20], [])
        cur.execute("SELECT count(*) FROM ops.data_quality_issue WHERE severity='error' AND resolved_at IS NULL")
        errors = int(cur.fetchone()[0])
        check("no_unresolved_quality_errors", errors == 0, errors, 0)
        cur.execute("""
            SELECT available, details FROM ops.source_capability
            WHERE capability_key='openreview_note_revision_content'
        """)
        capability = cur.fetchone()
        check("revision_capability_audited", capability is not None, capability is not None, True)
        cur.execute("SELECT count(*) FROM core.review_revision GROUP BY review_id HAVING count(*) > 1")
        replayable_chains = len(cur.fetchall())
        check("revision_replay_implemented", replayable_chains > 0, replayable_chains, "> 0")

    report = {
        "generated_at": utc_now(),
        "expected": expected,
        "table_counts": counts,
        "checks": checks,
        "revision_capability": capability[1] if capability else None,
        "passed": all(item["passed"] for item in checks),
    }
    write_json(state / "validation_report.json", report)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    if not report["passed"]:
        raise SystemExit(1)
    return report


def revision_audit(args: argparse.Namespace) -> dict[str, Any]:
    import openreview
    from requests.adapters import HTTPAdapter

    baseurl = "https://api2.openreview.net"
    token_file = args.token_file.expanduser()

    def token_client() -> Any:
        if not token_file.is_file():
            raise RuntimeError("OpenReview token is missing; run scripts/get_openreview_token.py")
        token = token_file.read_text(encoding="utf-8").strip()
        if token_refresh_due(token):
            raise RuntimeError("OpenReview token needs renewal; run scripts/get_openreview_token.py")
        result = openreview.api.OpenReviewClient(baseurl=baseurl, token=token)
        result.session.mount("https://", HTTPAdapter(max_retries=0))
        original_get = result.session.get
        result.session.get = lambda *pos, **kwargs: original_get(*pos, timeout=30, **kwargs)
        return result

    client = token_client()
    interval = 60 / max(1, args.requests_per_minute)
    sampled = stored = content_edits = errors = 0
    examples: list[dict[str, Any]] = []
    with db_connect(args.database_url) as conn, conn.cursor() as cur:
        cur.execute("""
            SELECT v.year, r.source_note_id, p.forum_id
            FROM core.review r
            JOIN core.paper p USING(paper_id)
            JOIN core.venue v USING(venue_id)
            WHERE r.created_at IS NOT NULL
              AND NOT EXISTS (
                  SELECT 1 FROM raw.openreview_revision_probe probe
                  WHERE probe.note_id=r.source_note_id AND probe.status='success'
              )
            ORDER BY v.year, md5(r.source_note_id)
        """)
        by_year: dict[int, list[tuple[str, str]]] = {year: [] for year in YEARS}
        for year, note_id, forum_id in cur.fetchall():
            if len(by_year[year]) < args.revision_sample_per_year:
                by_year[year].append((note_id, forum_id))
        for year in YEARS:
            for note_id, forum_id in by_year[year]:
                if token_refresh_due(client.token):
                    raise RuntimeError("OpenReview token needs renewal; run scripts/get_openreview_token.py")
                sampled += 1
                try:
                    edits = client.get_note_edits(note_id=note_id, limit=100, sort="tcdate:asc")
                    for revision_no, edit in enumerate(edits, 1):
                        payload = json_safe(edit.to_json())
                        note = payload.get("note") or {}
                        has_content = bool(note.get("content") or payload.get("replacement"))
                        content_edits += int(has_content)
                        edit_key = str(payload.get("id") or f"{note_id}-edit-{revision_no}")
                        cur.execute("""
                            INSERT INTO raw.openreview_edit(
                                note_id, edit_id, forum_id, revision_no, created_ms,
                                modified_ms, content_hash, raw_payload
                            ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s)
                            ON CONFLICT (edit_id, content_hash) DO NOTHING
                        """, (
                            note_id, edit_key, forum_id, revision_no,
                            payload.get("tcdate"), payload.get("tmdate"),
                            content_hash(payload), Jsonb(payload),
                        ))
                        stored += cur.rowcount
                    cur.execute("""
                        INSERT INTO raw.openreview_revision_probe(
                            note_id, status, edit_count, content_edit_count, error
                        ) VALUES (%s,'success',%s,%s,NULL)
                        ON CONFLICT (note_id) DO UPDATE SET
                            checked_at=now(), status='success', edit_count=EXCLUDED.edit_count,
                            content_edit_count=EXCLUDED.content_edit_count, error=NULL
                    """, (
                        note_id, len(edits),
                        sum(bool((edit.to_json().get("note") or {}).get("content")) for edit in edits),
                    ))
                    examples.append({"year": year, "note_id": note_id, "edits": len(edits), "content_edits": sum(bool((edit.to_json().get("note") or {}).get("content")) for edit in edits)})
                except Exception as exc:
                    errors += 1
                    cur.execute("""
                        INSERT INTO raw.openreview_revision_probe(note_id, status, error)
                        VALUES (%s,'failed',%s)
                        ON CONFLICT (note_id) DO UPDATE SET
                            checked_at=now(), status='failed', error=EXCLUDED.error
                    """, (note_id, f"{type(exc).__name__}: {exc}"[:1000]))
                    examples.append({"year": year, "note_id": note_id, "error": f"{type(exc).__name__}: {exc}"[:500]})
                conn.commit()
                time.sleep(interval)
        cur.execute("SELECT count(*) FROM raw.openreview_edit")
        total_stored = int(cur.fetchone()[0])
        cur.execute("""
            SELECT count(*) FROM raw.openreview_edit
            WHERE raw_payload #> '{note,content}' IS NOT NULL
               OR raw_payload ? 'replacement'
        """)
        total_content_edits = int(cur.fetchone()[0])
        cur.execute("""
            SELECT DISTINCT note_id FROM raw.openreview_edit
            WHERE raw_payload #> '{note,content}' IS NOT NULL
        """)
        normalized_revision_notes = 0
        normalized_revisions = 0
        for (note_id,) in cur.fetchall():
            count = rebuild_review_revisions(cur, note_id)
            normalized_revision_notes += int(count > 0)
            normalized_revisions += count
        available = total_content_edits > 0
        details = {
            "sampled_notes": sampled,
            "new_edit_envelopes": stored,
            "stored_edit_envelopes": total_stored,
            "edits_with_historical_content": total_content_edits,
            "normalized_revision_notes": normalized_revision_notes,
            "normalized_review_revisions": normalized_revisions,
            "errors": errors,
            "conclusion": (
                "Public OpenReview edits include replayable historical content."
                if available else
                "Public edits returned migration envelopes only; prior review content is not replayable from the public API."
            ),
            "examples": examples,
        }
        cur.execute("""
            INSERT INTO ops.source_capability(capability_key, available, details)
            VALUES ('openreview_note_revision_content',%s,%s)
            ON CONFLICT (capability_key) DO UPDATE SET
                available=EXCLUDED.available, checked_at=now(), details=EXCLUDED.details
        """, (available, Jsonb(details)))
        conn.commit()
    write_json(args.state.resolve() / "revision_capability_report.json", details | {"available": available})
    print(json.dumps(details | {"available": available}, ensure_ascii=False, indent=2))
    return details


def revision_backfill(args: argparse.Namespace) -> dict[str, Any]:
    import openreview
    from requests.adapters import HTTPAdapter

    token_file = args.token_file.expanduser()
    if not token_file.is_file():
        raise RuntimeError("OpenReview token is missing; run scripts/get_openreview_token_with_code.py")
    token = token_file.read_text(encoding="utf-8").strip()
    if token_refresh_due(token):
        raise RuntimeError("OpenReview token needs renewal; run scripts/get_openreview_token_with_code.py")
    client = openreview.api.OpenReviewClient(baseurl="https://api2.openreview.net", token=token)
    client.session.mount("https://", HTTPAdapter(max_retries=0))
    client.session.mount(client.note_edits_url, HTTPAdapter(max_retries=0))

    state = args.state.resolve()
    checkpoint_path = state / "revision_backfill_checkpoint.json"
    checkpoint = load_json(checkpoint_path) if checkpoint_path.is_file() else {"years": {}}
    interval = 60 / max(1, args.requests_per_minute)
    next_request = 0.0
    total_pages = total_seen = total_matched = total_inserted = 0
    completed_years: list[int] = []

    with db_connect(args.database_url) as conn, conn.cursor() as cur:
        cur.execute("""
            SELECT v.year, r.source_note_id, p.forum_id
            FROM core.review r
            JOIN core.paper p USING(paper_id)
            JOIN core.venue v USING(venue_id)
        """)
        review_rows: dict[int, dict[str, str]] = {year: {} for year in YEARS}
        for year, note_id, forum_id in cur.fetchall():
            review_rows[year][note_id] = forum_id
        cur.execute("SELECT note_id, max(revision_no) FROM raw.openreview_edit GROUP BY note_id")
        revision_numbers = {note_id: int(revision_no) for note_id, revision_no in cur.fetchall()}

        for year in YEARS:
            year_state = checkpoint["years"].setdefault(str(year), {"after": None, "complete": False})
            if year_state.get("complete"):
                completed_years.append(year)
                continue
            after = year_state.get("after")
            pages_this_run = 0
            domain = f"ICLR.cc/{year}/Conference"
            while True:
                if token_refresh_due(client.token):
                    raise RuntimeError("OpenReview token needs renewal; run scripts/get_openreview_token_with_code.py")
                wait = next_request - time.monotonic()
                if wait > 0:
                    time.sleep(wait)
                response = None
                for attempt in range(1, 6):
                    params = {
                        "domain": domain,
                        "limit": args.revision_page_size,
                        "sort": "id",
                    }
                    if after:
                        params["after"] = after
                    response = client.session.get(
                        client.note_edits_url,
                        params=params,
                        headers=client.headers,
                        timeout=120,
                    )
                    if response.status_code == 200:
                        break
                    body = response.json() if "json" in response.headers.get("Content-Type", "") else {}
                    if response.status_code == 429:
                        retry_after = response.headers.get("Retry-After", "unknown")
                        raise RuntimeError(f"OpenReview edits rate limit reached; retry after {retry_after} seconds")
                    retryable = response.status_code in (500, 502, 503, 504) or body.get("name") == "MaxTimeMSExpired"
                    if not retryable or attempt == 5:
                        raise RuntimeError(f"OpenReview edits request failed: HTTP {response.status_code}: {body or response.text[:500]}")
                    retry_after = response.headers.get("Retry-After", "")
                    time.sleep(int(retry_after) if retry_after.isdigit() else min(60, 2 ** attempt))
                next_request = time.monotonic() + interval
                edits = response.json().get("edits", [])
                if not edits:
                    year_state["complete"] = True
                    year_state["completed_at"] = utc_now()
                    write_json(checkpoint_path, checkpoint)
                    completed_years.append(year)
                    break

                matched = inserted = 0
                for raw_edit in edits:
                    payload = json_safe(raw_edit)
                    note = payload.get("note") or {}
                    note_id = note.get("id")
                    if note_id not in review_rows[year]:
                        continue
                    matched += 1
                    edit_key = str(payload.get("id") or f"{note_id}-{content_hash(payload)}")
                    revision_no = revision_numbers.get(note_id, 0) + 1
                    cur.execute("""
                        INSERT INTO raw.openreview_edit(
                            note_id, edit_id, forum_id, revision_no, created_ms,
                            modified_ms, content_hash, raw_payload
                        ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s)
                        ON CONFLICT (edit_id, content_hash) DO NOTHING
                    """, (
                        note_id, edit_key, note.get("forum") or review_rows[year][note_id],
                        revision_no, payload.get("tcdate"), payload.get("tmdate"),
                        content_hash(payload), Jsonb(payload),
                    ))
                    inserted += cur.rowcount
                    if cur.rowcount:
                        revision_numbers[note_id] = revision_no
                conn.commit()
                after = str(edits[-1]["id"])
                pages_this_run += 1
                total_pages += 1
                total_seen += len(edits)
                total_matched += matched
                total_inserted += inserted
                year_state.update({
                    "after": after,
                    "pages": int(year_state.get("pages") or 0) + 1,
                    "edits_seen": int(year_state.get("edits_seen") or 0) + len(edits),
                    "review_edits_matched": int(year_state.get("review_edits_matched") or 0) + matched,
                    "review_edits_inserted": int(year_state.get("review_edits_inserted") or 0) + inserted,
                    "updated_at": utc_now(),
                })
                write_json(checkpoint_path, checkpoint)
                if pages_this_run % 25 == 0:
                    print(json.dumps({"year": year, "pages": pages_this_run, "matched": total_matched, "inserted": total_inserted}), flush=True)
                if args.revision_max_pages and total_pages >= args.revision_max_pages:
                    break
                if len(edits) < args.revision_page_size:
                    year_state["complete"] = True
                    year_state["completed_at"] = utc_now()
                    write_json(checkpoint_path, checkpoint)
                    completed_years.append(year)
                    break
            if args.revision_max_pages and total_pages >= args.revision_max_pages:
                break

        if set(completed_years) == set(YEARS):
            cur.execute("""
                INSERT INTO raw.openreview_revision_probe(note_id, status, edit_count, content_edit_count, error)
                SELECT r.source_note_id, 'success', count(e.edit_id),
                       count(e.edit_id) FILTER (WHERE e.raw_payload #> '{note,content}' IS NOT NULL), NULL
                FROM core.review r
                LEFT JOIN raw.openreview_edit e ON e.note_id=r.source_note_id
                GROUP BY r.source_note_id
                ON CONFLICT (note_id) DO UPDATE SET
                    checked_at=now(), status='success', edit_count=EXCLUDED.edit_count,
                    content_edit_count=EXCLUDED.content_edit_count, error=NULL
            """)
            cur.execute("""
                SELECT DISTINCT e.note_id
                FROM raw.openreview_edit e
                JOIN core.review r ON r.source_note_id=e.note_id
                WHERE e.raw_payload #> '{note,content}' IS NOT NULL
            """)
            normalized_notes = normalized_revisions = 0
            for (note_id,) in cur.fetchall():
                count = rebuild_review_revisions(cur, note_id)
                normalized_notes += int(count > 0)
                normalized_revisions += count
            conn.commit()
        else:
            normalized_notes = normalized_revisions = 0

        cur.execute("SELECT count(*) FROM raw.openreview_edit")
        stored_edits = int(cur.fetchone()[0])
        cur.execute("SELECT count(*) FROM raw.openreview_revision_probe WHERE status='success'")
        successful_probes = int(cur.fetchone()[0])

    report = {
        "generated_at": utc_now(),
        "completed_years": completed_years,
        "pages_this_run": total_pages,
        "edits_seen_this_run": total_seen,
        "review_edits_matched_this_run": total_matched,
        "review_edits_inserted_this_run": total_inserted,
        "stored_edit_envelopes": stored_edits,
        "successful_revision_probes": successful_probes,
        "normalized_revision_notes": normalized_notes,
        "normalized_review_revisions": normalized_revisions,
        "complete": set(completed_years) == set(YEARS),
    }
    write_json(state / "revision_backfill_report.json", report)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return report


def snapshot(args: argparse.Namespace) -> dict[str, Any]:
    state = args.state.resolve()
    report = load_json(state / "validation_report.json")
    if not report.get("passed"):
        raise RuntimeError("validation must pass before snapshot")
    manifest_path = state / "object_manifest.jsonl"
    manifest_hash = file_hash(manifest_path)
    snapshot_dir = DATABASE_HOME/'snapshots'
    snapshot_dir.mkdir(parents=True, exist_ok=True)
    raw_dump_path = snapshot_dir / "database_v1.dump.tmp"
    dump_path = snapshot_dir / "database_v1.dump.zst"
    pg_dump = Path(os.environ.get("ICLR_PG_BIN", DATABASE_HOME/'runtime/bin')) / "pg_dump"
    subprocess.run([
        str(pg_dump), "--dbname", args.database_url, "--format=custom", "--compress=0",
        "--file", str(raw_dump_path),
    ], check=True)
    subprocess.run(["zstd", "-T0", "-6", "--force", str(raw_dump_path), "-o", str(dump_path)], check=True)
    raw_dump_path.unlink()
    dump_path.chmod(0o444)
    dump_hash = file_hash(dump_path)
    restore_command = "zstd -dc database_v1.dump.zst > database_v1.dump && pg_restore --dbname <target> database_v1.dump"
    with db_connect(args.database_url) as conn, conn.cursor() as cur:
        counts = table_counts(cur)
        cur.execute("""
            INSERT INTO ops.dataset_snapshot(
                name, schema_version, is_read_only, table_counts,
                object_manifest_sha256, validation_report, dump_path,
                dump_sha256, restore_command
            ) VALUES ('database_v1','database_v1',true,%s,%s,%s,%s,%s,%s)
            ON CONFLICT (name) DO UPDATE SET
                created_at=now(), table_counts=EXCLUDED.table_counts,
                object_manifest_sha256=EXCLUDED.object_manifest_sha256,
                validation_report=EXCLUDED.validation_report,
                dump_path=EXCLUDED.dump_path,
                dump_sha256=EXCLUDED.dump_sha256,
                restore_command=EXCLUDED.restore_command
        """, (Jsonb(counts), manifest_hash, Jsonb(report), str(dump_path), dump_hash, restore_command))
        conn.commit()
    summary = {
        "name": "database_v1",
        "dump_path": str(dump_path),
        "dump_sha256": dump_hash,
        "restore": restore_command,
        "object_manifest_sha256": manifest_hash,
        "table_counts": counts,
    }
    write_json(state / "snapshot_database_v1.json", summary)
    print(json.dumps(summary, indent=2))
    return summary


def migrate(args: argparse.Namespace) -> None:
    env = os.environ.copy()
    migration_url = args.database_url
    if migration_url.startswith("postgresql://"):
        migration_url = migration_url.replace("postgresql://", "postgresql+psycopg://", 1)
    env["ICLR_DATABASE_URL"] = migration_url
    subprocess.run([sys.executable, "-m", "alembic", "-c", str(REPO / "alembic.ini"), "upgrade", "head"], cwd=REPO, env=env, check=True)


def run_all(args: argparse.Namespace) -> None:
    inventory(args)
    object_store(args)
    migrate(args)
    ingest(args)
    before = None
    with db_connect(args.database_url) as conn, conn.cursor() as cur:
        before = table_counts(cur)
    ingest(args)
    with db_connect(args.database_url) as conn, conn.cursor() as cur:
        after = table_counts(cur)
    idempotency = {key: after[key] - before[key] for key in before}
    write_json(args.state.resolve() / "idempotency_report.json", idempotency)
    if any(idempotency.values()):
        raise RuntimeError(f"second ingest changed row counts: {idempotency}")
    fulltext_index(args)
    revision_audit(args)
    validate(args)
    snapshot(args)


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser()
    result.add_argument("command", choices=("inventory", "object-store", "migrate", "ingest", "fulltext-index", "revision-audit", "revision-backfill", "validate", "snapshot", "all"))
    result.add_argument("--source", type=Path, default=DEFAULT_SOURCE)
    result.add_argument("--store", type=Path, default=DEFAULT_STORE)
    result.add_argument("--state", type=Path, default=DEFAULT_STATE)
    result.add_argument("--database-url", default=DEFAULT_URL)
    result.add_argument("--hash-workers", type=int, default=4)
    result.add_argument("--commit-every", type=int, default=250)
    result.add_argument("--fulltext-limit", type=int, default=0)
    result.add_argument("--token-file", type=Path, default=DEFAULT_OPENREVIEW_TOKEN)
    result.add_argument("--revision-sample-per-year", type=int, default=5)
    result.add_argument("--revision-page-size", type=int, default=1000)
    result.add_argument("--revision-max-pages", type=int, default=0)
    result.add_argument("--requests-per-minute", type=int, default=26)
    return result


def main() -> None:
    args = parser().parse_args()
    commands = {
        "inventory": inventory,
        "object-store": object_store,
        "migrate": migrate,
        "ingest": ingest,
        "fulltext-index": fulltext_index,
        "revision-audit": revision_audit,
        "revision-backfill": revision_backfill,
        "validate": validate,
        "snapshot": snapshot,
        "all": run_all,
    }
    commands[args.command](args)


if __name__ == "__main__":
    main()
