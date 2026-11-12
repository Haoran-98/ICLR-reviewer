#!/usr/bin/env python3
"""Vision-audit eight formula/table conflicts from the 40-paper parser benchmark."""

from __future__ import annotations

import argparse
import base64
import json
import re
import subprocess
import tempfile
from collections import Counter
from pathlib import Path

import benchmark
import compare_standard_40 as comparison


CASES = {
    "p013": "formula",
    "p020": "formula",
    "p027": "formula",
    "p038": "formula",
    "p007": "table",
    "p017": "table",
    "p019": "table",
    "p032": "table",
}
OUT = Path(__file__).resolve().parent / "standard_40_conflict_judgments.jsonl"


def pdf_pages(path: Path) -> int:
    output = subprocess.run(
        ["pdfinfo", str(path)], capture_output=True, text=True, timeout=30, check=True
    ).stdout
    match = re.search(r"(?m)^Pages:\s+(\d+)", output)
    if not match:
        raise RuntimeError(f"Cannot determine page count for {path}")
    return int(match.group(1))


def page_text(path: Path, page: int) -> str:
    return subprocess.run(
        ["pdftotext", "-f", str(page), "-l", str(page), "-layout", str(path), "-"],
        capture_output=True,
        text=True,
        errors="replace",
        timeout=60,
        check=False,
    ).stdout


def evidence_score(text: str, kind: str) -> float:
    lower = text.lower()
    numeric_lines = sum(len(re.findall(r"[-+]?\d+(?:\.\d+)?", line)) >= 4 for line in text.splitlines())
    if kind == "table":
        return 30 * lower.count("table") + 3 * numeric_lines + 0.02 * len(re.findall(r"\d", text))
    return (
        6 * text.count("=")
        + 5 * len(re.findall(r"[∑∏∫√≤≥≈]", text))
        + 3 * len(re.findall(r"\b(?:theorem|lemma|proof|equation|where)\b", lower))
        + numeric_lines
    )


def select_page(path: Path, kind: str) -> tuple[int, str]:
    candidates = []
    for page in range(1, min(pdf_pages(path), 12) + 1):
        text = page_text(path, page)
        candidates.append((evidence_score(text, kind), page, text))
    _score, page, text = max(candidates)
    return page, text


def aligned_excerpt(candidate: str, reference: str, limit: int = 3600) -> str:
    candidate = benchmark.visible_text(candidate)
    if len(candidate) <= limit:
        return candidate
    reference_terms = set(benchmark.tokens(reference))
    best = (-1.0, candidate[:limit])
    for start in range(0, len(candidate), limit // 2):
        chunk = candidate[start : start + limit]
        terms = set(benchmark.tokens(chunk))
        score = len(reference_terms & terms) / max(1, len(reference_terms | terms))
        if score > best[0]:
            best = (score, chunk)
    return best[1]


def render_page(pdf: Path, page: int, destination: Path) -> None:
    subprocess.run(
        [
            "pdftoppm",
            "-f",
            str(page),
            "-l",
            str(page),
            "-r",
            "130",
            "-png",
            "-singlefile",
            str(pdf),
            str(destination.with_suffix("")),
        ],
        capture_output=True,
        text=True,
        timeout=120,
        check=True,
    )


def prompt(paper: dict, kind: str, page: int, reference: str, excerpts: dict[str, str]) -> str:
    return f"""You are auditing PDF-to-Markdown fidelity for one scientific-paper page.
The attached image is the ground truth page. Compare only information visible on that page.
The candidate excerpts were automatically aligned and may include a small amount of adjacent text.
Focus especially on {kind} preservation, then text fidelity, reading order, captions, and omissions.
Do not reward verbosity or embedded images by themselves. Return JSON only with keys:
ranking (best to worst using exactly existing, docling, mineru_standard), winner,
confidence (0..1), unresolved (boolean), reasons (object keyed by method),
scores (object keyed by method, each containing text, structure, table, math integers 1..5).

TITLE: {paper['title']}
PDF PAGE: {page}
PAGE TEXT LAYER (imperfect auxiliary evidence):
{reference[:4500]}

CANDIDATE EXCERPTS:
{json.dumps(excerpts, ensure_ascii=False)}
"""


def completion(auth: dict[str, str], model_key: str, text: str, image_path: Path) -> tuple[dict, dict]:
    image_data = base64.b64encode(image_path.read_bytes()).decode()
    payload = benchmark.post_json(
        auth["OPENAI_BASE_URL"].rstrip("/") + "/responses",
        {
            "model": auth[model_key],
            "input": [
                {
                    "role": "user",
                    "content": [
                        {"type": "input_text", "text": text},
                        {"type": "input_image", "image_url": f"data:image/png;base64,{image_data}"},
                    ],
                }
            ],
            "max_output_tokens": 1400,
        },
        {"Authorization": f"Bearer {auth['OPENAI_API_KEY']}"},
    )
    return benchmark.parse_json_text(benchmark.response_text(payload)), payload.get("usage") or {}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--auth", type=Path, default=Path.home() / "auth")
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--confidence", type=float, default=0.72)
    args = parser.parse_args()

    auth = benchmark.load_auth(args.auth)
    required = ("OPENAI_BASE_URL", "OPENAI_API_KEY", "OPENAI_WEAK_MODEL_ID", "OPENAI_STRONG_MODEL_ID")
    missing = [key for key in required if not auth.get(key)]
    if missing:
        raise RuntimeError("Missing API fields: " + ", ".join(missing))

    manifest = {row["sample_id"]: row for row in benchmark.read_jsonl(benchmark.MANIFEST)}
    previous = {row["sample_id"]: row for row in benchmark.read_jsonl(OUT)} if args.resume else {}
    with tempfile.TemporaryDirectory(prefix="iclr-parser-judge-") as temporary:
        temp = Path(temporary)
        for index, (sample_id, kind) in enumerate(CASES.items(), 1):
            if sample_id in previous:
                continue
            paper = manifest[sample_id]
            pdf = Path(paper["pdf_path"])
            page, reference = select_page(pdf, kind)
            image = temp / f"{sample_id}-page-{page}.png"
            render_page(pdf, page, image)
            excerpts = {}
            for method in comparison.METHOD_LABELS:
                text = comparison.output_path(method, paper).read_text(encoding="utf-8", errors="replace")
                excerpts[method] = aligned_excerpt(text, reference)
            request_text = prompt(paper, kind, page, reference, excerpts)
            record = {"sample_id": sample_id, "kind": kind, "page": page}
            try:
                weak, usage = completion(auth, "OPENAI_WEAK_MODEL_ID", request_text, image)
                record.update({"weak": weak, "weak_usage": usage})
                if weak.get("unresolved") or float(weak.get("confidence", 0)) < args.confidence:
                    strong, strong_usage = completion(auth, "OPENAI_STRONG_MODEL_ID", request_text, image)
                    record.update({"strong": strong, "strong_usage": strong_usage})
            except Exception as error:
                record["weak_error"] = f"{type(error).__name__}: {error}"
                try:
                    strong, strong_usage = completion(auth, "OPENAI_STRONG_MODEL_ID", request_text, image)
                    record.update({"strong": strong, "strong_usage": strong_usage})
                except Exception as strong_error:
                    record["strong_error"] = f"{type(strong_error).__name__}: {strong_error}"
            previous[sample_id] = record
            benchmark.write_jsonl(OUT, [previous[key] for key in CASES if key in previous])
            verdict = record.get("strong") or record.get("weak") or {}
            print(
                f"[{index}/{len(CASES)}] {sample_id} page={page} "
                f"winner={verdict.get('winner', 'error')} confidence={verdict.get('confidence', 'N/A')}",
                flush=True,
            )


if __name__ == "__main__":
    main()
