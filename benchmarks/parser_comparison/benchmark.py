#!/usr/bin/env python3
"""Reproducible 100-paper comparison of existing Markdown, Docling, and MinerU."""

from __future__ import annotations

import argparse
import csv
import json
import math
import os
import random
import re
import shlex
import shutil
import signal
import statistics
import subprocess
import sys
import threading
import time
from collections import Counter, defaultdict
from datetime import datetime, timezone
from difflib import SequenceMatcher
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


ROOT = Path(os.environ.get("ICLR_PARSER_BENCHMARK_ROOT", "/data_big/iclr-parser-benchmark"))
MANIFEST = ROOT / "manifest.jsonl"
RUNS = ROOT / "runs.json"
METRICS = ROOT / "metrics.jsonl"
JUDGMENTS = ROOT / "judgments.jsonl"
REPO_DIR = Path(__file__).resolve().parent
DATABASE_URL = os.environ.get(
    "ICLR_DATABASE_URL", "postgresql://yhr@127.0.0.1:55432/iclr_reviewer"
)
DOCLING_PYTHON = ROOT / "venvs/docling/bin/python"
MINERU_BIN = ROOT / "venvs/mineru/bin/mineru-kit"
MINERU_HOME = ROOT / "mineru_home"
METHODS = ("existing", "docling", "mineru")
WORD_RE = re.compile(r"[A-Za-z][A-Za-z0-9_-]{1,}|[\u4e00-\u9fff]")
HEADING_RE = re.compile(r"(?m)^\s{0,3}#{1,6}\s+(.+?)\s*$")
DATA_IMAGE_RE = re.compile(r"!\[[^\]]*\]\(data:image/[^;]+;base64,[A-Za-z0-9+/=\s]+\)")


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def read_jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    rows = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            rows.append(json.loads(line))
    return rows


def write_jsonl(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows),
        encoding="utf-8",
    )
    temporary.replace(path)


def load_runs() -> dict:
    try:
        return json.loads(RUNS.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def save_run(method: str, payload: dict) -> None:
    runs = load_runs()
    runs[method] = {**runs.get(method, {}), **payload, "updated_at": now()}
    RUNS.parent.mkdir(parents=True, exist_ok=True)
    RUNS.write_text(json.dumps(runs, indent=2, ensure_ascii=False), encoding="utf-8")


def normalize(text: str) -> str:
    return " ".join(WORD_RE.findall(text.lower()))


def tokens(text: str) -> list[str]:
    return WORD_RE.findall(text.lower())


def load_auth(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[7:]
        try:
            parts = shlex.split(line)
        except ValueError:
            continue
        if len(parts) == 1 and "=" in parts[0]:
            key, value = parts[0].split("=", 1)
            values[key] = value
    return values


class GpuMonitor:
    def __init__(self) -> None:
        self.peak_mib = 0
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, daemon=True)

    def _run(self) -> None:
        while not self._stop.wait(0.25):
            try:
                output = subprocess.run(
                    ["nvidia-smi", "--query-compute-apps=used_memory", "--format=csv,noheader,nounits"],
                    capture_output=True,
                    text=True,
                    timeout=3,
                    check=False,
                ).stdout
                total = sum(int(line.strip()) for line in output.splitlines() if line.strip().isdigit())
                self.peak_mib = max(self.peak_mib, total)
            except (OSError, subprocess.TimeoutExpired, ValueError):
                pass

    def __enter__(self):
        self._thread.start()
        return self

    def __exit__(self, *_args):
        self._stop.set()
        self._thread.join(timeout=2)


def artifact_path(row: dict, role: str) -> str | None:
    candidates = row.get("artifacts", {}).get(role, [])
    return next((path for path in candidates if Path(path).is_file()), None)


def sample_command(args: argparse.Namespace) -> None:
    import psycopg

    query = """
        SELECT p.paper_id, p.year, p.forum_id, p.accepted_main, p.pdf_url,
               v.title, v.abstract, v.keywords,
               COALESCE(areas.labels, '{}') AS areas,
               COALESCE(files.artifacts, '{}') AS artifacts
        FROM core.main_papers p
        JOIN core.latest_paper_version v USING (paper_id)
        LEFT JOIN (
            SELECT pa.paper_id, array_agg(DISTINCT ea.raw_label) AS labels
            FROM core.paper_area pa
            JOIN core.explicit_area ea USING (explicit_area_id)
            GROUP BY pa.paper_id
        ) areas USING (paper_id)
        LEFT JOIN (
            SELECT paper_id, jsonb_object_agg(artifact_role, object_paths) AS artifacts
            FROM (
                SELECT ca.paper_id, ca.artifact_role,
                       array_agg(ra.object_path ORDER BY ra.artifact_id) AS object_paths
                FROM core.artifact ca
                JOIN raw.artifact ra ON ra.artifact_id = ca.raw_artifact_id
                WHERE ca.availability = 'available'
                GROUP BY ca.paper_id, ca.artifact_role
            ) grouped_files
            GROUP BY paper_id
        ) files USING (paper_id)
        ORDER BY p.year, p.paper_id
    """
    with psycopg.connect(DATABASE_URL) as connection, connection.cursor() as cursor:
        cursor.execute(query)
        columns = [column.name for column in cursor.description]
        candidates = [dict(zip(columns, row)) for row in cursor.fetchall()]

    eligible = []
    for row in candidates:
        row["artifacts"] = dict(row["artifacts"] or {})
        canonical_pdf = Path(f"/data_big/iclr_reviews/fulltext/pdf/{row['year']}/{row['forum_id']}.pdf")
        canonical_markdown = Path(f"/data_big/iclr_reviews/fulltext/markdown/{row['year']}/{row['forum_id']}.md")
        pdf = str(canonical_pdf) if canonical_pdf.is_file() else artifact_path(row, "pdf")
        markdown = str(canonical_markdown) if canonical_markdown.is_file() else artifact_path(row, "markdown")
        if not markdown or (not pdf and not args.allow_missing_pdf):
            continue
        row["pdf_path"] = pdf or str(ROOT / "source_pdfs" / f"{row['forum_id']}.pdf")
        row["pdf_missing_at_sample_time"] = not bool(pdf)
        row["markdown_path"] = markdown
        row.pop("artifacts", None)
        row["accepted_main"] = bool(row["accepted_main"])
        row["keywords"] = list(row["keywords"] or [])
        row["areas"] = list(row["areas"] or [])
        eligible.append(row)

    rng = random.Random(args.seed)
    selected: list[dict] = []
    year_quotas = {2024: 34, 2025: 33, 2026: 33}
    if args.count != 100:
        base, extra = divmod(args.count, 3)
        year_quotas = {year: base + (index < extra) for index, year in enumerate((2024, 2025, 2026))}
    for year, quota in year_quotas.items():
        pool = [row for row in eligible if row["year"] == year]
        rng.shuffle(pool)
        accepted_quota = round(quota * sum(row["accepted_main"] for row in pool) / len(pool))
        for accepted, status_quota in ((True, accepted_quota), (False, quota - accepted_quota)):
            buckets: dict[str, list[dict]] = defaultdict(list)
            for row in pool:
                if row["accepted_main"] == accepted:
                    area = sorted(row["areas"])[0] if row["areas"] else "unknown"
                    buckets[area].append(row)
            keys = list(buckets)
            rng.shuffle(keys)
            picked = 0
            while picked < status_quota and keys:
                for key in list(keys):
                    if buckets[key]:
                        selected.append(buckets[key].pop())
                        picked += 1
                        if picked >= status_quota:
                            break
                    else:
                        keys.remove(key)
    selected.sort(key=lambda row: (row["year"], row["forum_id"]))
    for index, row in enumerate(selected, 1):
        row["sample_id"] = f"p{index:03d}"
    write_jsonl(MANIFEST, selected)
    print(json.dumps({"manifest": str(MANIFEST), "papers": len(selected)}, ensure_ascii=False))


def prepare_pdfs_command(args: argparse.Namespace) -> None:
    manifest = read_jsonl(MANIFEST)
    missing = [row for row in manifest if not Path(row["pdf_path"]).is_file()]
    token_path = Path("/data_big/iclr_reviews/fulltext/openreview.token")
    token = token_path.read_text(encoding="utf-8").strip() if token_path.exists() else ""
    headers = {"User-Agent": "ICLR-reviewer-parser-benchmark/1.0"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    failures = []
    for index, paper in enumerate(missing, 1):
        target = Path(paper["pdf_path"])
        target.parent.mkdir(parents=True, exist_ok=True)
        url = paper.get("pdf_url") or f"https://openreview.net/pdf?id={paper['forum_id']}"
        if url.startswith("/"):
            url = "https://openreview.net" + url
        try:
            request = Request(url, headers=headers)
            with urlopen(request, timeout=180) as response:
                payload = response.read()
            if not payload.startswith(b"%PDF"):
                raise ValueError(f"response is not PDF ({len(payload)} bytes)")
            temporary = target.with_suffix(".pdf.tmp")
            temporary.write_bytes(payload)
            temporary.replace(target)
            print(f"[{index}/{len(missing)}] {paper['sample_id']} {len(payload)} bytes", flush=True)
        except Exception as error:
            failures.append({"sample_id": paper["sample_id"], "error": f"{type(error).__name__}: {error}"})
        if index < len(missing):
            time.sleep(args.interval)
    save_run("pdf_preparation", {"status": "complete" if not failures else "partial",
                                  "requested": len(missing), "failures": failures})
    if failures:
        raise SystemExit(f"Failed to download {len(failures)} PDFs")


def output_path(method: str, paper: dict) -> Path:
    if method == "existing":
        return Path(paper["markdown_path"])
    return ROOT / "outputs" / method / f"{paper['sample_id']}.md"


def parse_existing(_args: argparse.Namespace) -> None:
    manifest = read_jsonl(MANIFEST)
    started = time.perf_counter()
    total_bytes = 0
    failures = []
    for paper in manifest:
        try:
            total_bytes += len(Path(paper["markdown_path"]).read_bytes())
        except OSError as error:
            failures.append({"sample_id": paper["sample_id"], "error": str(error)})
    elapsed = time.perf_counter() - started
    save_run("existing", {
        "status": "complete", "papers": len(manifest), "failures": failures,
        "elapsed_seconds": elapsed, "peak_gpu_mib": 0, "output_bytes": total_bytes,
        "note": "Source generation time unavailable; elapsed time is read-only cost.",
    })


def parse_docling(args: argparse.Namespace) -> None:
    # Run this subcommand with Docling's isolated Python environment.
    from docling.document_converter import DocumentConverter

    manifest = read_jsonl(MANIFEST)[: args.limit or None]
    destination = ROOT / "outputs/docling"
    destination.mkdir(parents=True, exist_ok=True)
    converter = DocumentConverter()
    failures = []
    timings = []
    started = time.perf_counter()
    save_run("docling", {"status": "running", "papers": len(manifest), "completed": 0})
    with GpuMonitor() as gpu:
        for index, paper in enumerate(manifest, 1):
            target = output_path("docling", paper)
            if args.resume and target.exists() and target.stat().st_size > 100:
                continue
            one_started = time.perf_counter()
            try:
                result = converter.convert(paper["pdf_path"])
                target.write_text(result.document.export_to_markdown(), encoding="utf-8")
                timings.append(time.perf_counter() - one_started)
            except Exception as error:  # The benchmark must continue after parser failures.
                failures.append({"sample_id": paper["sample_id"], "error": f"{type(error).__name__}: {error}"})
            save_run("docling", {
                "status": "running", "papers": len(manifest), "completed": index,
                "failures": failures, "elapsed_seconds": time.perf_counter() - started,
                "peak_gpu_mib": gpu.peak_mib,
            })
    outputs = list(destination.glob("*.md"))
    save_run("docling", {
        "status": "complete", "papers": len(manifest), "completed": len(outputs),
        "failures": failures, "elapsed_seconds": time.perf_counter() - started,
        "per_paper_seconds": timings, "peak_gpu_mib": gpu.peak_mib,
        "output_bytes": sum(path.stat().st_size for path in outputs),
    })


def sync_mineru_outputs(manifest: list[dict], raw_output: Path, final_output: Path) -> int:
    for paper in manifest:
        candidates = sorted(
            raw_output.rglob(f"{paper['sample_id']}*.md"),
            key=lambda path: path.stat().st_size,
            reverse=True,
        )
        if candidates:
            shutil.copy2(candidates[0], output_path("mineru", paper))
    return sum(output_path("mineru", paper).exists() for paper in manifest)


def parse_mineru(args: argparse.Namespace) -> None:
    manifest = read_jsonl(MANIFEST)[: args.limit or None]
    inputs = ROOT / "mineru_inputs"
    raw_output = ROOT / "outputs/mineru_raw"
    final_output = ROOT / "outputs/mineru"
    for directory in (inputs, raw_output, final_output):
        directory.mkdir(parents=True, exist_ok=True)
    if args.force:
        shutil.rmtree(raw_output)
        raw_output.mkdir(parents=True)
    sync_mineru_outputs(manifest, raw_output, final_output)
    pending = [paper for paper in manifest if not output_path("mineru", paper).exists()] if args.resume else manifest
    selected_names = {f"{paper['sample_id']}.pdf" for paper in pending}
    for link in inputs.glob("*.pdf"):
        if link.name not in selected_names:
            link.unlink()
    for paper in pending:
        link = inputs / f"{paper['sample_id']}.pdf"
        if not link.exists():
            link.symlink_to(paper["pdf_path"])
    if not pending:
        save_run("mineru", {
            "status": "complete", "papers": len(manifest), "completed": len(manifest),
            "failures": [], "tier": args.tier, "device": "cpu",
        })
        print("All MinerU outputs already exist.")
        return
    command = [str(MINERU_BIN), "parse", str(inputs), "--output", str(raw_output),
               "--format", "markdown", "--tier", args.tier, "--pages", "all"]
    environment = {**os.environ, "MINERU_HOME": str(MINERU_HOME)}
    started = time.perf_counter()
    log_path = ROOT / "logs/mineru.log"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    save_run("mineru", {
        "status": "running", "papers": len(manifest), "pending": len(pending),
        "command": command, "tier": args.tier, "device": "cpu",
    })
    interrupted = False
    with log_path.open("a", encoding="utf-8") as log, GpuMonitor() as gpu:
        process = subprocess.Popen(
            command, env=environment, text=True, stdout=log, stderr=subprocess.STDOUT,
        )
        try:
            returncode = process.wait()
        except KeyboardInterrupt:
            interrupted = True
            try:
                process.send_signal(signal.SIGINT)
                returncode = process.wait(timeout=30)
            except subprocess.TimeoutExpired:
                process.terminate()
                try:
                    returncode = process.wait(timeout=15)
                except subprocess.TimeoutExpired:
                    process.kill()
                    returncode = process.wait()
    completed = sync_mineru_outputs(manifest, raw_output, final_output)
    outputs = list(final_output.glob("*.md"))
    failures = [paper["sample_id"] for paper in manifest if not output_path("mineru", paper).exists()]
    save_run("mineru", {
        "status": "paused" if interrupted else ("complete" if returncode == 0 and not failures else "partial"),
        "returncode": returncode, "papers": len(manifest), "completed": completed,
        "failures": failures, "elapsed_seconds": time.perf_counter() - started,
        "peak_gpu_mib": gpu.peak_mib,
        "output_bytes": sum(path.stat().st_size for path in outputs), "log": str(log_path),
        "tier": args.tier, "device": "cpu",
    })
    if returncode and not interrupted:
        raise SystemExit(returncode)


def section_flags(text: str) -> dict[str, bool]:
    headings = " ".join(HEADING_RE.findall(text)).lower()
    plain_heading_lines = []
    for line in text.splitlines():
        line = line.strip()
        if 2 <= len(line) <= 100:
            letters = [character for character in line if character.isalpha()]
            looks_like_heading = bool(re.match(r"^(?:\d+(?:\.\d+)*|[A-Z])\s+", line)) or (
                letters and sum(character.isupper() for character in letters) / len(letters) >= 0.65
            )
            if not looks_like_heading:
                continue
            compact = re.sub(r"[^a-z]", "", line.lower())
            if any(
                name in compact
                for name in (
                    "abstract", "introduction", "method", "approach", "model",
                    "experiment", "evaluation", "result", "conclusion", "discussion",
                    "reference", "bibliography",
                )
            ):
                plain_heading_lines.append(compact)
    headings += " " + " ".join(plain_heading_lines)
    return {
        "abstract": "abstract" in headings,
        "introduction": "introduction" in headings,
        "method": any(word in headings for word in ("method", "approach", "model")),
        "experiment": any(word in headings for word in ("experiment", "evaluation", "result")),
        "conclusion": any(word in headings for word in ("conclusion", "discussion")),
        "references": any(word in headings for word in ("reference", "bibliography")),
    }


def repetition_rate(text: str) -> float:
    paragraphs = [normalize(item) for item in re.split(r"\n\s*\n", text) if len(normalize(item)) >= 80]
    return 0.0 if not paragraphs else 1 - len(set(paragraphs)) / len(paragraphs)


def visible_text(text: str) -> str:
    return DATA_IMAGE_RE.sub("![embedded image]", text)


def metric_for(paper: dict, method: str, text: str, pdf_chars: int) -> dict:
    raw_chars = len(text)
    text = visible_text(text)
    normalized = normalize(text)
    token_set = set(tokens(text))
    title_tokens = set(tokens(paper["title"]))
    abstract_tokens = set(tokens(paper.get("abstract") or ""))
    keyword_tokens = set(tokens(" ".join(paper.get("keywords") or [])))
    title_recall = len(title_tokens & set(tokens(text[:5000]))) / max(1, len(title_tokens))
    abstract_recall = len(abstract_tokens & token_set) / max(1, len(abstract_tokens))
    keyword_recall = len(keyword_tokens & token_set) / max(1, len(keyword_tokens))
    sections = section_flags(text)
    clean = 1 - min(1.0, (text.count("�") + text.count("\x00") * 10) / max(1, len(text)) * 1000)
    repeat = repetition_rate(text)
    length_ratio = len(normalized) / max(1, pdf_chars)
    coverage = max(0.0, 1 - abs(math.log(max(0.05, length_ratio))))
    section_score = sum(sections.values()) / len(sections)
    score = 100 * (
        0.15 * title_recall + 0.25 * abstract_recall + 0.05 * keyword_recall
        + 0.20 * section_score + 0.10 * sections["references"]
        + 0.10 * clean + 0.05 * (1 - repeat) + 0.10 * coverage
    )
    headings = HEADING_RE.findall(text)
    return {
        "sample_id": paper["sample_id"], "paper_id": paper["paper_id"], "method": method,
        "quality_score": round(score, 4), "title_recall": round(title_recall, 4),
        "abstract_recall": round(abstract_recall, 4), "keyword_recall": round(keyword_recall, 4),
        "section_score": round(section_score, 4), "sections": sections,
        "heading_count": len(headings), "table_rows": len(re.findall(r"(?m)^\s*\|.*\|\s*$", text)),
        "formula_markers": len(re.findall(r"\$\$|\\\[|\\begin\{(?:equation|align)", text)),
        "figure_mentions": len(re.findall(r"(?i)\bfig(?:ure)?\.?\s*\d+", text)),
        "citation_markers": len(re.findall(r"\[[0-9, -]{1,20}\]|\\cite\{", text)),
        "replacement_chars": text.count("�"), "repeat_rate": round(repeat, 5),
        "text_chars": len(text), "raw_chars": raw_chars,
        "embedded_image_bytes": raw_chars - len(text),
        "html_tables": len(re.findall(r"(?i)<table\b", text)),
        "length_ratio_vs_pdftotext": round(length_ratio, 4),
        "clean_score": round(clean, 4), "coverage_score": round(coverage, 4),
    }


def score_command(_args: argparse.Namespace) -> None:
    rows = []
    for paper in read_jsonl(MANIFEST):
        reference = subprocess.run(
            ["pdftotext", "-layout", paper["pdf_path"], "-"], capture_output=True,
            text=True, errors="replace", timeout=180, check=False,
        ).stdout
        pdf_chars = len(normalize(reference))
        for method in METHODS:
            path = output_path(method, paper)
            if not path.exists():
                rows.append({"sample_id": paper["sample_id"], "paper_id": paper["paper_id"],
                             "method": method, "error": "missing_output"})
                continue
            rows.append(metric_for(paper, method, path.read_text(encoding="utf-8", errors="replace"), pdf_chars))
    write_jsonl(METRICS, rows)
    print(json.dumps({"metrics": str(METRICS), "rows": len(rows)}))


def excerpt(text: str, limit: int = 5000) -> str:
    text = visible_text(text)
    headings = "\n".join(line for line in text.splitlines() if HEADING_RE.match(line))[:2000]
    tail_match = re.search(r"(?im)^#{0,3}\s*(references|bibliography)\b", text)
    tail = text[tail_match.start():tail_match.start() + 1500] if tail_match else text[-1000:]
    return (text[:limit] + "\n[HEADINGS]\n" + headings + "\n[TAIL]\n" + tail)[:8500]


def parse_json_text(text: str) -> dict:
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text, flags=re.S)
    return json.loads(text)


def post_json(url: str, body: dict, headers: dict[str, str], timeout: int = 900) -> dict:
    request = Request(url, json.dumps(body).encode(), {"Content-Type": "application/json", **headers}, method="POST")
    last_error: Exception | None = None
    for attempt in range(4):
        try:
            with urlopen(request, timeout=timeout) as response:
                return json.loads(response.read().decode())
        except HTTPError as error:
            detail = error.read().decode(errors="replace")
            last_error = RuntimeError(f"HTTP {error.code}: {detail[:500]}")
            if error.code < 500 and error.code != 429:
                break
        except (URLError, TimeoutError) as error:
            last_error = error
        time.sleep(2**attempt)
    raise RuntimeError(f"API request failed: {last_error}")


def judge_prompt(paper: dict, metric_rows: list[dict]) -> str:
    candidates = {}
    for method in METHODS:
        path = output_path(method, paper)
        candidates[method] = excerpt(path.read_text(encoding="utf-8", errors="replace")) if path.exists() else "[MISSING]"
    return f"""You are comparing three PDF-to-Markdown parsers for one scientific paper.
Judge fidelity to the paper, not writing style. Prefer correct reading order, complete sections,
tables/formulas/captions/references, and low corruption or duplication. Database title and abstract
are trusted anchors. Return JSON only with keys ranking (all three method names), confidence (0..1),
winner, reasons (object keyed by method), and unresolved (boolean).

TITLE: {paper['title']}
ABSTRACT: {paper.get('abstract') or ''}
AUTOMATIC METRICS: {json.dumps(metric_rows, ensure_ascii=False)}
CANDIDATES: {json.dumps(candidates, ensure_ascii=False)}
"""


def weak_completion(auth: dict[str, str], prompt: str) -> tuple[dict, dict]:
    required = ("OPENAI_BASE_URL", "OPENAI_API_KEY", "OPENAI_WEAK_MODEL_ID")
    missing = [key for key in required if not auth.get(key)]
    if missing:
        raise RuntimeError("Missing weak API fields: " + ", ".join(missing))
    payload = post_json(
        auth["OPENAI_BASE_URL"].rstrip("/") + "/responses",
        {"model": auth["OPENAI_WEAK_MODEL_ID"], "input": prompt, "max_output_tokens": 1200},
        {"Authorization": f"Bearer {auth['OPENAI_API_KEY']}"},
    )
    return parse_json_text(response_text(payload)), payload.get("usage") or {}


def response_text(payload: dict) -> str:
    return "".join(
        str(content.get("text", ""))
        for item in payload.get("output", []) for content in item.get("content", [])
        if content.get("type") == "output_text"
    )


def strong_completion(auth: dict[str, str], prompt: str) -> tuple[dict, dict]:
    required = ("OPENAI_BASE_URL", "OPENAI_API_KEY", "OPENAI_STRONG_MODEL_ID")
    missing = [key for key in required if not auth.get(key)]
    if missing:
        raise RuntimeError("Missing strong API fields: " + ", ".join(missing))
    payload = post_json(
        auth["OPENAI_BASE_URL"].rstrip("/") + "/responses",
        {"model": auth["OPENAI_STRONG_MODEL_ID"], "input": prompt, "max_output_tokens": 1400},
        {"Authorization": f"Bearer {auth['OPENAI_API_KEY']}"},
    )
    return parse_json_text(response_text(payload)), payload.get("usage") or {}


def judge_command(args: argparse.Namespace) -> None:
    auth = load_auth(args.auth)
    manifest = {row["sample_id"]: row for row in read_jsonl(MANIFEST)}
    grouped: dict[str, list[dict]] = defaultdict(list)
    for row in read_jsonl(METRICS):
        if "quality_score" in row:
            grouped[row["sample_id"]].append(row)
    previous = {row["sample_id"]: row for row in read_jsonl(JUDGMENTS)} if args.resume else {}
    candidates = []
    for sample_id, rows in grouped.items():
        scores = sorted((row["quality_score"] for row in rows), reverse=True)
        if len(scores) == 3 and (scores[0] - scores[1] <= args.margin or scores[0] - scores[-1] <= args.spread):
            candidates.append((sample_id, rows))
    for index, (sample_id, rows) in enumerate(candidates, 1):
        if sample_id in previous:
            continue
        prompt = judge_prompt(manifest[sample_id], rows)
        try:
            result, usage = weak_completion(auth, prompt)
            record = {"sample_id": sample_id, "weak": result, "weak_usage": usage}
            if result.get("unresolved") or float(result.get("confidence", 0)) < args.confidence:
                strong, strong_usage = strong_completion(auth, prompt)
                record.update({"strong": strong, "strong_usage": strong_usage})
        except Exception as error:
            record = {"sample_id": sample_id, "error": f"{type(error).__name__}: {error}"}
        previous[sample_id] = record
        write_jsonl(JUDGMENTS, [previous[key] for key in sorted(previous)])
        print(f"[{index}/{len(candidates)}] {sample_id}", flush=True)
    print(json.dumps({"conflicts": len(candidates), "judged": len(previous)}, ensure_ascii=False))


def mean(values: list[float]) -> float | None:
    return round(statistics.mean(values), 4) if values else None


def report_command(_args: argparse.Namespace) -> None:
    metrics = read_jsonl(METRICS)
    runs = load_runs()
    judgments = read_jsonl(JUDGMENTS)
    by_method: dict[str, list[dict]] = defaultdict(list)
    for row in metrics:
        if "quality_score" in row:
            by_method[row["method"]].append(row)
    summary = {}
    for method in METHODS:
        rows = by_method[method]
        run = runs.get(method, {})
        elapsed = run.get("elapsed_seconds")
        count = len(rows)
        summary[method] = {
            "parsed": count,
            "failures": len(run.get("failures") or []),
            "quality_score": mean([row["quality_score"] for row in rows]),
            "abstract_recall": mean([row["abstract_recall"] for row in rows]),
            "section_score": mean([row["section_score"] for row in rows]),
            "heading_count": mean([row["heading_count"] for row in rows]),
            "repeat_rate": mean([row["repeat_rate"] for row in rows]),
            "elapsed_seconds": round(elapsed, 2) if elapsed is not None else None,
            "seconds_per_paper": round(elapsed / count, 3) if elapsed and count else None,
            "peak_gpu_mib": run.get("peak_gpu_mib"),
            "output_mib": round((run.get("output_bytes") or 0) / 1024**2, 3),
        }
    winners = Counter()
    for record in judgments:
        verdict = record.get("strong") or record.get("weak") or record.get("local") or {}
        if verdict.get("winner") in METHODS:
            winners[verdict["winner"]] += 1
    csv_path = REPO_DIR / "results.csv"
    with csv_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=["method", *next(iter(summary.values())).keys()])
        writer.writeheader()
        for method in METHODS:
            writer.writerow({"method": method, **summary[method]})
    report = [
        "# ICLR PDF Parser Comparison (100 Papers)", "",
        f"Generated: {now()}", "",
        "## Scope", "",
        "Three paths are compared on the same stratified ICLR 2024-2026 main-track sample: the existing Markdown corpus, Docling 2.130.0, and MinerU 4.0.7. Database title, abstract, keywords, and PDF text are used as non-LLM anchors. The configured OPENAI_WEAK model adjudicates close automatic scores; the strong API is called only when the weak model remains uncertain.", "",
        "## Results", "",
        "| Method | Parsed | Failures | Quality /100 ↑ | Abstract recall ↑ | Section score ↑ | Seconds/paper ↓ | Peak GPU MiB ↓ | Output MiB |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for method in METHODS:
        item = summary[method]
        report.append(
            f"| {method} | {item['parsed']} | {item['failures']} | {item['quality_score']} | "
            f"{item['abstract_recall']} | {item['section_score']} | {item['seconds_per_paper']} | "
            f"{item['peak_gpu_mib']} | {item['output_mib']} |"
        )
    report += [
        "", "## Adjudication", "",
        f"Close cases judged: {len(judgments)}. Final winners among those cases: {dict(winners)}.", "",
        "## Interpretation", "",
        "- `quality_score` is a reproducible proxy, not human transcription accuracy: it combines title/abstract/keyword recovery, section coverage, references, text coverage, duplication, and encoding cleanliness.",
        "- Existing Markdown generation time is unavailable. Its timing is only file-read cost and must not be compared as parser throughput.",
        "- Peak GPU memory is sampled device-wide; parser runs require the local Qwen service to be stopped so the value remains attributable.",
        "- Tables and formulas are counted as preservation signals, but definitive cell/formula accuracy requires a manually annotated subset.", "",
        "## Artifacts", "",
        f"- Manifest and raw outputs: `{ROOT}`",
        f"- Machine-readable metrics: `{METRICS}`",
        f"- Conflict judgments: `{JUDGMENTS}`",
        f"- CSV summary: `{csv_path}`", "",
        "## Reproduction", "",
        "```bash",
        "python3 benchmarks/parser_comparison/benchmark.py sample",
        "python3 benchmarks/parser_comparison/benchmark.py parse-existing",
        f"{DOCLING_PYTHON} benchmarks/parser_comparison/benchmark.py parse-docling --resume",
        "python3 benchmarks/parser_comparison/benchmark.py parse-mineru --tier standard",
        "python3 benchmarks/parser_comparison/benchmark.py score",
        "python3 benchmarks/parser_comparison/benchmark.py judge --resume",
        "python3 benchmarks/parser_comparison/benchmark.py report",
        "```", "",
    ]
    (REPO_DIR / "report.md").write_text("\n".join(report), encoding="utf-8")
    (REPO_DIR / "summary.json").write_text(json.dumps({"summary": summary, "winners": winners}, indent=2), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))


def status_command(_args: argparse.Namespace) -> None:
    manifest = read_jsonl(MANIFEST)
    runs = load_runs()
    status = {"papers": len(manifest), "metrics": len(read_jsonl(METRICS)), "judgments": len(read_jsonl(JUDGMENTS)), "methods": {}}
    for method in METHODS:
        completed = sum(output_path(method, row).exists() for row in manifest)
        run = runs.get(method, {})
        if method == "mineru" and run.get("status") == "running":
            completed = len({path.stem for path in (ROOT / "outputs/mineru_raw").rglob("p*.md")})
        elapsed = run.get("elapsed_seconds") or 0
        if run.get("status") == "running" and run.get("updated_at"):
            elapsed = max(elapsed, (datetime.now(timezone.utc) - datetime.fromisoformat(run["updated_at"])).total_seconds())
        eta = elapsed / completed * (len(manifest) - completed) if completed and run.get("status") == "running" else None
        status["methods"][method] = {
            **run,
            "completed": completed, "percent": round(100 * completed / max(1, len(manifest)), 1),
            "elapsed_seconds": round(elapsed, 1),
            "eta_seconds": round(eta) if eta is not None else None,
        }
    print(json.dumps(status, ensure_ascii=False, indent=2))


def watch_command(args: argparse.Namespace) -> None:
    try:
        while True:
            status_command(args)
            if all(load_runs().get(method, {}).get("status") in {"complete", "failed"} for method in METHODS):
                return
            time.sleep(args.interval)
    except KeyboardInterrupt:
        return


def main() -> None:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)
    sample = sub.add_parser("sample")
    sample.add_argument("--count", type=int, default=100)
    sample.add_argument("--seed", type=int, default=20260927)
    sample.add_argument("--allow-missing-pdf", action="store_true")
    sample.set_defaults(func=sample_command)
    prepare = sub.add_parser("prepare-pdfs")
    prepare.add_argument("--interval", type=float, default=2.4)
    prepare.set_defaults(func=prepare_pdfs_command)
    sub.add_parser("parse-existing").set_defaults(func=parse_existing)
    docling = sub.add_parser("parse-docling")
    docling.add_argument("--resume", action="store_true")
    docling.add_argument("--limit", type=int)
    docling.set_defaults(func=parse_docling)
    mineru = sub.add_parser("parse-mineru")
    mineru.add_argument("--tier", choices=("basic", "standard"), default="standard")
    mineru.add_argument("--limit", type=int)
    mineru.add_argument("--force", action="store_true")
    mineru.add_argument("--resume", action="store_true")
    mineru.set_defaults(func=parse_mineru)
    sub.add_parser("score").set_defaults(func=score_command)
    judge = sub.add_parser("judge")
    judge.add_argument("--auth", type=Path, default=Path.home() / "auth")
    judge.add_argument("--margin", type=float, default=3.0)
    judge.add_argument("--spread", type=float, default=6.0)
    judge.add_argument("--confidence", type=float, default=0.7)
    judge.add_argument("--resume", action="store_true")
    judge.set_defaults(func=judge_command)
    sub.add_parser("report").set_defaults(func=report_command)
    sub.add_parser("status").set_defaults(func=status_command)
    watch = sub.add_parser("watch")
    watch.add_argument("--interval", type=float, default=10)
    watch.set_defaults(func=watch_command)
    args = parser.parse_args()
    ROOT.mkdir(parents=True, exist_ok=True)
    args.func(args)


if __name__ == "__main__":
    main()
