# ICLR Reviewer

[中文说明](README.zh-CN.md)

<!-- DAILY_ACTIVITY:START -->
## New in the Last 3 Days

<details open>
<summary>2026-09-09 - 19 newly analyzed papers, 0 common Agents added</summary>

| Year | Paper | Topic | Research tags |
|---:|---|---|---|
| 2024 | [Vision-Language Integration in Multimodal Video Transformers (Partially) Aligns with the Brain](https://openreview.net/forum?id=LWqeF78c1q) | applications to neuroscience & cognitive science | multimodal learning, vision-language models, video transformers |
| 2024 | [Alignment-Enhancing Parallel Code Generation for Semi-Supervised Code Translation](https://openreview.net/forum?id=XK7kyCVjqr) | unsupervised, self-supervised, semi-supervised, and supervised representation learning | code translation, semi-supervised learning, synthetic parallel data |
| 2024 | [Learning Forward Compatible Representation in Class Incremental Learning by Increasing Effective Rank](https://openreview.net/forum?id=EvszuxrPTb) | transfer learning, meta learning, and lifelong learning | class-incremental learning, continual learning, forward compatibility |
| 2025 | [Improved Noise Schedule for Diffusion Training](https://openreview.net/forum?id=j3U6CJLhqw) | generative models | diffusion models, noise schedules, log SNR |
| 2025 | [DualTime: A Dual-Adapter Language Model for Time Series Multimodal Representation Learning](https://openreview.net/forum?id=oVCVCo3laS) | learning on time series and dynamical systems | multimodal representation learning, time series, clinical text |
| 2025 | [TokenFormer: Rethinking Transformer Scaling with Tokenized Model Parameters](https://openreview.net/forum?id=oQ4igHyh3N) | foundation or frontier models, including LLMs | foundation models, large language models, Transformer architecture |
| 2025 | [RegMix: Data Mixture as Regression for Language Model Pre-training](https://openreview.net/forum?id=5BjQOUXq7i) | foundation or frontier models, including LLMs | language model pre-training, data mixture optimization, regression modeling |
| 2025 | [DreamMakeup: Face Makeup Customization using Latent Diffusion Models](https://openreview.net/forum?id=WUibctXLT7) | generative models | facial makeup customization, image editing, latent diffusion models |
| 2025 | [SimXRD-4M: Big Simulated X-ray Diffraction Data and Crystal Symmetry Classification Benchmark](https://openreview.net/forum?id=mkuB677eMM) | datasets and benchmarks | powder X-ray diffraction, crystallographic informatics, simulated dataset |
| 2026 | [GRAFTa: A Graph Attentional Few-Shot Audio Tagging Network](https://openreview.net/forum?id=QWYNKkg8mN) | transfer learning, meta learning, and lifelong learning | few-shot learning, multi-label classification, audio tagging |
| 2026 | [Improving MoE Performance and Efficiency with Plug-and-Play Intra-Layer Specialization and Cross-Layer Coupling Losses](https://openreview.net/forum?id=nY91ZOfB5M) | foundation or frontier models, including LLMs | Mixture-of-Experts, expert specialization, routing stability |
| 2026 | [Rethinking Preference Alignment for Diffusion Models with Classifier-Free Guidance](https://openreview.net/forum?id=l9dRkT8u1I) | generative models | diffusion models, preference alignment, classifier-free guidance |
| 2026 | [Scaling up Multi-Turn Off-Policy RL and Multi-Agent Tree Search for LLM Step-Provers](https://openreview.net/forum?id=TfwePIKzXJ) | neurosymbolic & hybrid AI systems (physics-informed, logic & formal reasoning, etc.) | formal theorem proving, large language models, reinforcement learning |
| 2026 | [Learning Convolutional Representations via Generalized Stein’s Method: A Training-Free Approach](https://openreview.net/forum?id=SF8NYACPfb) | unsupervised, self-supervised, semi-supervised, and supervised representation learning | training-free representation learning, convolutional neural networks, Stein's method |
| 2026 | [We Generate What You Need: Efficient Data Supplement via Model Prediction Discrepancy for Heterogeneous Federated Learning](https://openreview.net/forum?id=6DdkSELUh0) | other topics in machine learning (i.e., none of the above) | federated learning, data heterogeneity, global class imbalance |
| 2026 | [Bounds of Chain-of-Thought Robustness: Reasoning Steps, Embed Norms, and Beyond](https://openreview.net/forum?id=cusZbViSLd) | applications to computer vision, audio, language, and other modalities | chain-of-thought robustness, prompt perturbation, Lipschitz analysis |
| 2026 | [Token-Complexity based Routing Technique within Mixture of Experts Architecture for Large Language Model](https://openreview.net/forum?id=miyzT0uhhF) | generative models | mixture of experts, token-level routing, token complexity |
| 2026 | [SIG-Chat: Spatial Intent-Guided Conversational Gesture Generation Involving How, When and Where](https://openreview.net/forum?id=1XYG3pVCWf) | generative models | conversational gesture generation, spatial intent, co-speech gestures |
| 2026 | [Exponential Low-Rank Adapters](https://openreview.net/forum?id=JVyPNQCT8E) | foundation or frontier models, including LLMs | parameter-efficient fine-tuning, LoRA, matrix exponential |

</details>

<details>
<summary>2026-09-08 - 0 newly analyzed papers, 0 common Agents added</summary>

No public paper additions on this day.

</details>

<details>
<summary>2026-09-07 - 0 newly analyzed papers, 0 common Agents added</summary>

No public paper additions on this day.

</details>
<!-- DAILY_ACTIVITY:END -->

---

<!-- WEEKLY_ACTIVITY:START -->
## Added Last Week

| Period | Newly analyzed papers | Year distribution | Top research tags |
|---|---:|---|---|
| 2026-08-31 - 2026-09-06 | 20 | 2024: 4, 2025: 6, 2026: 10 | online learning (2), LLM agents (2), label shift (1), generalized label shift (1), recurrent neural networks (1), real-time recurrent learning (1), semantic segmentation (1), certified robustness (1), randomized smoothing (1), object detection (1) |
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
| No common agents added in the last 30 days | - | - |
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
