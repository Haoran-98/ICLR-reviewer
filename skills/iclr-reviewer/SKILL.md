---
name: iclr-reviewer
description: Review research manuscripts from an ICLR perspective using an evidence-grounded reviewer panel, explicit score reasons, AC synthesis, citation checks, revision priorities, and optional rebuttal analysis. Use when reviewing or scoring a paper, checking submission readiness, diagnosing likely reviewer objections, explaining acceptance risk, or analyzing reviewer comments and author responses from PDF, LaTeX, Markdown, or pasted manuscript text.
---

# ICLR Reviewer

Review the supplied manuscript as an ICLR submission even when its target venue is different. Explain every material judgment from manuscript evidence and preserve uncertainty.

## Required References

Read these files completely before reviewing:

- `references/reviewer-panel.md`: reviewer roles, routing, scoring, and confidence
- `references/report-contract.md`: required evidence ledger and final report structure

## Input

Accept a manuscript path, PDF, LaTeX project, Markdown file, pasted text, or a manuscript plus reviewer comments and rebuttal. Read the full available manuscript and supplement. State which artifacts were unavailable; do not infer their contents.

Use the user's language unless requested otherwise.

## Workflow

1. Build a manuscript map.
   - Extract the problem, claimed gap, main claims, method, assumptions, experiments, limitations, and stated contributions.
   - Attach a page, section, figure, table, equation, or short quote anchor to each important claim.

2. Route the reviewer panel.
   - Always run the core method, evidence, novelty, clarity, and ethics/reproducibility roles.
   - Add at most three domain specialists when the manuscript requires expertise beyond the core panel.
   - Keep role assessments independent until AC synthesis. Do not let a favorable role erase another role's fatal concern.

3. Test claim support.
   - For every central claim, identify supporting theory, experiment, comparison, ablation, robustness result, or citation.
   - Label support as `supported`, `partially_supported`, `unsupported`, or `not_verifiable`.
   - Distinguish missing evidence from evidence that contradicts the claim.

4. Audit references conservatively.
   - Check whether cited work appears to support the surrounding statement when the cited source is available.
   - Never invent bibliographic facts or claim verification without access to the source.
   - Label inaccessible citation claims `not_verifiable`.

5. Score independently, then synthesize.
   - Give each active reviewer role an ICLR rating and confidence with explicit reasons.
   - Have the AC resolve disagreements from the manuscript evidence. Do not calculate a simple average.
   - Separate fatal blockers, major concerns, and minor concerns.

6. Produce actionable revisions.
   - Tie every recommendation to a specific concern and expected review impact.
   - State the smallest evidence or text change that would resolve it.
   - Include a counterfactual: what score movement is plausible if the issue is resolved, and what uncertainty remains.

7. Enter rebuttal mode when reviewer comments or an author response are supplied.
   - Track each concern as `resolved`, `partially_resolved`, `unresolved`, or `unknown`.
   - Distinguish reviewer acknowledgment from silence.
   - Explain why a score increase is or is not justified; never treat a promised increase as a completed score change.

## Guardrails

- Do not fabricate results, citations, experiments, reviewer identities, or score changes.
- Do not reward polished prose when central claims lack evidence.
- Do not penalize unconventional work merely for being unconventional; identify the concrete validity or significance issue.
- Do not rewrite the manuscript as the main output unless the user asks for revision text.
- Make uncertainty visible. A confident score requires broad access to the manuscript and evidence.
