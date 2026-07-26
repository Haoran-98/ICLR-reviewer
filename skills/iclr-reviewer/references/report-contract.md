# Review Report Contract

Produce the following sections. Keep findings concrete and ordered by severity.

## 1. Verdict

- AC rating: one of `10`, `8`, `6`, `5`, `3`, `1`
- Confidence: `1-5`
- One-paragraph decision rationale
- Primary acceptance condition or rejection blocker

## 2. Manuscript Map

Summarize the problem, gap, method, contributions, central claims, and evaluation design. Mark unclear or missing elements.

## 3. Independent Reviewer Results

For every active role, report:

| Reviewer role | Rating | Confidence | Main reason | Evidence anchor |
|---|---:|---:|---|---|

The evidence anchor must identify a page, section, figure, table, equation, or short quote. Use `not located` when the manuscript does not contain the expected evidence.

## 4. Strengths

List only strengths supported by the manuscript. Explain why each strength matters for ICLR.

## 5. Concern Ledger

Give every concern a stable ID such as `C1`.

| ID | Severity | Concern | Manuscript evidence | Why it matters | Required resolution |
|---|---|---|---|---|---|

Use severity `fatal`, `major`, or `minor`. Avoid vague entries such as “experiments are weak”; name the missing comparison, control, population, metric, proof step, or robustness test.

## 6. Claim-Evidence Audit

| Claim | Support status | Supporting evidence | Gap or contradiction |
|---|---|---|---|

Use only `supported`, `partially_supported`, `unsupported`, or `not_verifiable`.

## 7. Questions for the Authors

Ask questions whose answers could change the rating. Do not use questions as disguised criticism when the concern is already established.

## 8. Prioritized Revision Plan

For each action, include:

- linked concern IDs;
- exact change or experiment;
- expected review impact;
- plausible rating after resolution;
- remaining uncertainty.

## 9. Rebuttal Assessment

Include only when reviewer comments or an author response are supplied.

| Concern | Response status | Evidence in response | Reviewer acknowledgment | Score implication |
|---|---|---|---|---|

Use response status `resolved`, `partially_resolved`, `unresolved`, or `unknown`. Reviewer silence is `unknown`, not agreement. Explain both successful score increases and failures to increase.

## 10. Citation Audit

List verified, contradicted, and `not_verifiable` citation claims. Do not imply external verification when only the manuscript bibliography was inspected.
