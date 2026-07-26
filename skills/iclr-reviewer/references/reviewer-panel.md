# Reviewer Panel and ICLR Scorecard

## Core Roles

| Role | Primary responsibility | Required questions |
|---|---|---|
| Best-justified | Construct the strongest evidence-based case for the work | What is genuinely new, useful, and well supported? |
| Critical | Find the most consequential failure mode | What could invalidate the central conclusion? |
| Method soundness | Check formulation, assumptions, derivations, algorithms, and leakage | Is the method correct under its stated conditions? |
| Evidence and experiments | Check baselines, metrics, controls, ablations, statistics, robustness, and compute fairness | Do the experiments isolate and support the claims? |
| Novelty and positioning | Compare the actual contribution with the closest work | Is the delta clear, material, and correctly attributed? |
| Writing and clarity | Check definitions, logical flow, figures, tables, and reproducibility of interpretation | Can a qualified reader recover exactly what was done? |
| Ethics and reproducibility | Check data rights, harms, privacy, misuse, seeds, code/data details, and limitations | Can the work be responsibly evaluated and reproduced? |

## Optional Roles

Select only when relevant, with at most three domain specialists:

- Domain application: validate domain assumptions, utility, and evaluation realism.
- Evidence/ablation: stress-test causal attribution to individual components.
- Reproducibility: reconstruct the implementation and experimental protocol from the manuscript.
- Novice advocate: identify unexplained prerequisites and inaccessible presentation.
- Citation auditor: independently verify citation existence and claim support when sources are available.

## AC Rules

- Synthesize reasons, not numerical averages.
- A fatal soundness or evidence concern cannot be canceled by writing quality or topical appeal.
- Separate manuscript facts, reviewer inference, and unresolved uncertainty.
- Prefer the lowest rating justified by an unresolved central blocker, while explaining what would change that rating.

## ICLR Overall Rating

Use the historical ICLR-style discrete scale:

| Rating | Meaning |
|---:|---|
| 10 | Strong accept: exceptionally strong, technically sound, and highly significant |
| 8 | Accept: strong contribution with no unresolved central blocker |
| 6 | Weak accept: more reasons to accept than reject; concerns appear fixable |
| 5 | Borderline: evidence is balanced or a central uncertainty remains |
| 3 | Weak reject: meaningful idea, but major unresolved validity, novelty, or evidence problems |
| 1 | Strong reject: fundamentally invalid, unsupported, out of scope, or not reviewable |

Do not invent intermediate ratings unless the user explicitly asks for a continuous scale.

## Confidence

| Confidence | Meaning |
|---:|---|
| 5 | Expert-level familiarity; manuscript and evidence were fully available |
| 4 | Strong familiarity; only minor uncertainty remains |
| 3 | Reasonable assessment with material domain or evidence uncertainty |
| 2 | Important parts were unavailable or outside expertise |
| 1 | Guess-level assessment; do not present strong conclusions |
