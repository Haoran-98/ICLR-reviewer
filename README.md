# ICLR Reviewer

[中文说明](README.zh-CN.md)

ICLR Reviewer turns public ICLR papers, reviews, author responses, and decisions into reproducible datasets and multi-agent review infrastructure. It supports research on ICLR scoring behavior, review trends, rebuttal outcomes, acceptance factors, and evidence-grounded reviewer and author simulations.

The project applies an ICLR review perspective even when evaluating work intended for another venue: originality, technical soundness, empirical evidence, clarity, reproducibility, ethics, and venue fit. Its goal is not to imitate identifiable people, but to build auditable review models from public historical evidence while preserving uncertainty and counterfactual assumptions.

## Use as a Codex Skill

Clone the repository and install the included skill:

```bash
git clone https://github.com/Haoran-98/ICLR-reviewer.git
cd ICLR-reviewer
mkdir -p "$HOME/.codex/skills"
ln -s "$PWD/skills/iclr-reviewer" "$HOME/.codex/skills/iclr-reviewer"
```

Restart Codex, then review a PDF, LaTeX project, Markdown manuscript, or pasted paper:

```text
$iclr-reviewer Review /path/to/paper.pdf and explain every score and revision priority.
```

For an agent that does not auto-discover Codex skills:

```text
Read skills/iclr-reviewer/SKILL.md and use it to review /path/to/paper.pdf.
```

The review returns independent role scores, manuscript-grounded strengths and concerns, a claim-evidence audit, an AC decision, confidence, prioritized revisions, and the reason each change could affect the rating. When reviewer comments and an author response are provided, it also evaluates which concerns were resolved and why a score change is or is not justified.

## Repository Contents

- ICLR 2024-2026 main-track title, abstract, and topic catalogs
- Python scripts for deterministic filtering, extraction, batching, validation, and reviewer-archetype generation
- A grouped generic reviewer panel and collaboration rules
- An installable `$iclr-reviewer` Codex skill

The repository contains no paper PDFs, Workshop records, credentials, API request or response logs, or local filesystem paths.

## Grouped Reviewer Agents

The public panel is defined in [`agents/reviewer_groups.json`](agents/reviewer_groups.json):

- Core reviewers: best-justified case, critical review, method soundness, evidence and experiments, novelty and positioning, writing, ethics and reproducibility
- Extended reviewers: domain application, ablation evidence, reproducibility, and non-expert accessibility
- Decision and audit: AC / Meta-Reviewer and an independent Citation Auditor

The generic panel always runs. Up to three relevant domain specialists may be added. The AC resolves disagreements from manuscript evidence, fatal concerns cannot be averaged away, and citation auditing remains independent from the AC.

### Available Agent Groups

<!-- AGENT_GROUPS:START -->
| Group | Agent | Purpose | Added |
|---|---|---|---|
| Orchestration | `iclr_reviewer_orchestrator` (ICLR Reviewer Orchestrator) | Routes the panel, preserves independent reviews, and produces the final evidence-grounded report. | 2026-07-26 |
| Core reviewers | `best_justified` (Best-Justified Reviewer) | Builds the strongest manuscript-supported case for acceptance. | 2026-07-26 |
| Core reviewers | `critical` (Critical Reviewer) | Finds the most consequential unresolved failure mode. | 2026-07-26 |
| Core reviewers | `method_soundness` (Method Soundness Reviewer) | Checks formulation, assumptions, derivations, algorithms, and leakage. | 2026-07-26 |
| Core reviewers | `evidence_experiment` (Evidence and Experiment Reviewer) | Audits baselines, controls, metrics, ablations, statistics, and robustness. | 2026-07-26 |
| Core reviewers | `novelty_positioning` (Novelty and Positioning Reviewer) | Tests the claimed contribution against the closest related work. | 2026-07-26 |
| Core reviewers | `writing_clarity` (Writing and Clarity Reviewer) | Checks definitions, logical flow, figures, tables, and readability. | 2026-07-26 |
| Core reviewers | `ethics_reproducibility` (Ethics and Reproducibility Reviewer) | Checks harms, data rights, privacy, misuse, limitations, and reproducibility. | 2026-07-26 |
| Extended reviewers | `domain_application` (Domain Application Reviewer) | Validates domain assumptions, utility, and evaluation realism. | 2026-07-26 |
| Extended reviewers | `evidence_ablation` (Ablation Reviewer) | Tests whether evidence isolates the contribution of each component. | 2026-07-26 |
| Extended reviewers | `reproducibility` (Reproducibility Reviewer) | Reconstructs the implementation and experimental protocol from the paper. | 2026-07-26 |
| Extended reviewers | `novice_advocate` (Novice Advocate) | Identifies unexplained prerequisites and inaccessible presentation. | 2026-07-26 |
| Decision and audit | `ac_meta_reviewer` (AC / Meta-Reviewer) | Resolves reviewer disagreements from evidence without averaging away blockers. | 2026-07-26 |
| Decision and audit | `citation_auditor` (Citation Auditor) | Independently checks citation existence and claim support when sources are available. | 2026-07-26 |
<!-- AGENT_GROUPS:END -->

### Added in the Last 30 Days

<!-- RECENT_AGENTS:START -->
| Agent | Group | Added |
|---|---|---|
| `writing_clarity` (Writing and Clarity Reviewer) | Core reviewers | 2026-07-26 |
| `reproducibility` (Reproducibility Reviewer) | Extended reviewers | 2026-07-26 |
| `novice_advocate` (Novice Advocate) | Extended reviewers | 2026-07-26 |
| `novelty_positioning` (Novelty and Positioning Reviewer) | Core reviewers | 2026-07-26 |
| `method_soundness` (Method Soundness Reviewer) | Core reviewers | 2026-07-26 |
| `iclr_reviewer_orchestrator` (ICLR Reviewer Orchestrator) | Orchestration | 2026-07-26 |
| `evidence_experiment` (Evidence and Experiment Reviewer) | Core reviewers | 2026-07-26 |
| `evidence_ablation` (Ablation Reviewer) | Extended reviewers | 2026-07-26 |
| `ethics_reproducibility` (Ethics and Reproducibility Reviewer) | Core reviewers | 2026-07-26 |
| `domain_application` (Domain Application Reviewer) | Extended reviewers | 2026-07-26 |
| `critical` (Critical Reviewer) | Core reviewers | 2026-07-26 |
| `citation_auditor` (Citation Auditor) | Decision and audit | 2026-07-26 |
| `best_justified` (Best-Justified Reviewer) | Core reviewers | 2026-07-26 |
| `ac_meta_reviewer` (AC / Meta-Reviewer) | Decision and audit | 2026-07-26 |
<!-- RECENT_AGENTS:END -->

## Title and Abstract Catalog

[`raw/`](raw/) lists papers by year and main-track topic and provides one lightweight JSONL gzip index per year. Public fields are limited to topic, title, abstract, keywords, OpenReview ID, and page URL. The catalog contains no reviews, rebuttals, decisions, authors, or PDF files.

Current coverage is 38,890 main-track papers:

- 2024: 7,404 papers
- 2025: 11,672 papers
- 2026: 19,814 papers

[`raw/manifest.json`](raw/manifest.json) records paper counts, topic counts, index sizes, and SHA-256 checksums.

## Temporal Protocol

- 2024: training
- 2025: calibration
- 2026: completely held-out testing

Users may define a different split for their own experiments, but the project's historical reviewer-twin protocol does not expose 2026 evidence to profile-generation prompts.

## Installation

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

Run the local extraction pipeline:

```bash
export ICLR_REVIEWS_ROOT=/path/to/iclr_reviews
python twin_smoke/extract_priority_topics.py
python twin_smoke/prepare_priority_luna.py --batch-tokens 90000
```

The API runner reads an OpenAI-compatible configuration through `ICLR_AUTH_FILE`. Do not commit credentials, request payloads, or raw provider responses.

## Research Boundaries

- Workshop records and PDF files are excluded.
- Reviewer silence or ambiguous language is labeled `unknown`.
- Rebuttal analysis covers both score increases and failures to increase, with observations separated from causal assumptions and counterfactual conditions.
- Anonymous reviewer IDs are not used to infer real identities.
- Historical patterns support uncertainty-aware estimates, not guaranteed scores or acceptance decisions.
