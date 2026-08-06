# ICLR Reviewer

[中文说明](README.zh-CN.md)

<!-- DAILY_ACTIVITY:START -->
## New in the Last 3 Days

<details open>
<summary>2026-08-07 - 19 newly analyzed papers, 0 common Agents added</summary>

| Year | Paper | Topic | Research tags |
|---:|---|---|---|
| 2024 | [BMAD: Benchmarks for Medical Anomaly Detection](https://openreview.net/forum?id=2SuA42Mq1c) | datasets and benchmarks | medical anomaly detection, medical imaging, benchmark datasets |
| 2024 | [Enhancing Offline Reinforcement Learning with an Optimal Supported Dataset](https://openreview.net/forum?id=1Akd36hG9z) | reinforcement learning | offline reinforcement learning, behavior regularization, distribution correction estimation |
| 2024 | [AROID: Improving Adversarial Robustness through Online Instance-wise Data Augmentation](https://openreview.net/forum?id=ufZp6pvOvE) | general machine learning (i.e., none of the above) | adversarial robustness, adversarial training, automated data augmentation |
| 2025 | [Towards Lightweight Deep Watermarking Framework](https://openreview.net/forum?id=j7b4mm7Ec9) | applications to computer vision, audio, language, and other modalities | deep watermarking, lightweight neural networks, copyright protection |
| 2025 | [Consistency-based Black-box Uncertainty Quantification for Text-to-SQL by Similarity Aggregation](https://openreview.net/forum?id=ofiZbAmrZh) | foundation or frontier models, including LLMs | uncertainty quantification, black-box models, text-to-SQL |
| 2025 | [Adaptive Threshold Sampling for Fast Noisy Submodular Maximization](https://openreview.net/forum?id=vtCkb4KJxr) | optimization | submodular maximization, noisy value oracles, adaptive sampling |
| 2025 | [Coreset Spectral Clustering](https://openreview.net/forum?id=1qgZXeMTTU) | learning on graphs and other geometries & topologies | spectral clustering, coresets, kernel k-means |
| 2025 | [G-Transformer for Conditional Average Potential Outcome Estimation over Time](https://openreview.net/forum?id=XUJcsLvpaQ) | causal reasoning | causal inference, potential outcomes, conditional average potential outcomes |
| 2025 | [Learning to Watermark LLM-generated Text via Reinforcement Learning](https://openreview.net/forum?id=r6aX67YhD9) | alignment, fairness, safety, privacy, and societal considerations | LLM watermarking, model-level watermarking, text provenance |
| 2026 | [Do Vision-Language Models Respect Contextual Integrity in Location Disclosure?](https://openreview.net/forum?id=64Ea2Dx0JJ) | datasets and benchmarks | datasets and benchmarks, vision-language models, contextual integrity |
| 2026 | [Closed-form $\ell_r$ norm scaling with data for overparameterized linear regression and diagonal linear networks under $\ell_p$ bias](https://openreview.net/forum?id=qPKTDOJ5Xs) | learning theory | learning theory, overparameterized linear regression, minimum-norm interpolation |
| 2026 | [Death of the Novel(ty): Beyond N-Gram Novelty as a Metric for Textual Creativity](https://openreview.net/forum?id=z2idLjqzBe) | foundation or frontier models, including LLMs | computational creativity, text evaluation, n-gram novelty |
| 2026 | [Compact Attention: Exploiting Structured Spatio-Temporal Sparsity for Fast Video Generation](https://openreview.net/forum?id=NLsUsrOIuh) | generative models | video generation, video diffusion transformers, sparse attention |
| 2026 | [Tokenisation over Bounded Alphabets is Hard](https://openreview.net/forum?id=Xhf9YqwlM4) | foundation or frontier models, including LLMs | tokenisation, tokenization, computational complexity |
| 2026 | [MVR: Multi-view Video Reward Shaping for Reinforcement Learning](https://openreview.net/forum?id=7lw6s9ELfr) | reinforcement learning | reinforcement learning, reward shaping, vision-language models |
| 2026 | [InfoDet: A Dataset for Infographic Element Detection](https://openreview.net/forum?id=Wj0Sc9WBHZ) | datasets and benchmarks | datasets and benchmarks, infographic understanding, object detection |
| 2026 | [SEDiT: Mask-Free Video Subtitle Erasure with Prompt Instruction](https://openreview.net/forum?id=MIRtxjuZF6) | applications to computer vision, audio, language, and other modalities | video editing, subtitle erasure, video inpainting |
| 2026 | [Generation is Required for Data-Efficient Perception](https://openreview.net/forum?id=N7ziRPTNdT) | unsupervised, self-supervised, semi-supervised, and supervised representation learning | representation learning, generative models, compositional generalization |
| 2026 | [Can LLM Agents Assist Dynamic Network Simulation? A Case Study on Email Networks and Phishing Synthesis](https://openreview.net/forum?id=pPNtJDpY6q) | foundation or frontier models, including LLMs | dynamic network simulation, LLM agents, multi-agent systems |

</details>

<details>
<summary>2026-08-06 - 0 newly analyzed papers, 0 common Agents added</summary>

No public paper additions on this day.

</details>

<details>
<summary>2026-08-05 - 0 newly analyzed papers, 0 common Agents added</summary>

No public paper additions on this day.

</details>
<!-- DAILY_ACTIVITY:END -->

---

<!-- WEEKLY_ACTIVITY:START -->
## Added Last Week

**2026-07-27 - 2026-08-02:** No public additions.
<!-- WEEKLY_ACTIVITY:END -->

---

## Project Overview

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

## Visual Overview

### From Manuscript to Actionable Review

The workflow converts a paper into an evidence map, runs independent role-based reviews, resolves disagreements through AC synthesis, and produces scores with reasons and revision priorities.

<p align="center">
  <img src="docs/images/promo/01-iclr-reviewer-workflow.png" alt="ICLR Reviewer workflow from manuscript input to evidence-grounded review report" width="720">
</p>

### Common Agent Groups

Fourteen common agents cover orchestration, core scientific review, optional extended review, meta-decision, and independent citation auditing. Specialist roles complement the core panel rather than replacing it.

<p align="center">
  <img src="docs/images/promo/02-common-agent-groups.png" alt="Grouped ICLR Reviewer agents and their collaboration structure" width="720">
</p>

### Evidence, Reasons, and Counterfactuals

Every material concern follows a traceable chain from claim and evidence to gap, impact, required fix, and plausible score change. Reviewer silence remains `unknown`, not agreement.

<p align="center">
  <img src="docs/images/promo/03-evidence-to-reason.png" alt="Evidence-grounded review reasoning, scoring, and rebuttal assessment" width="720">
</p>

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
