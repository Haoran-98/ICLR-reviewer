# 50-paper structured-understanding comparison

Papers: **50**; strong-model judgments completed: **50**. Extraction used `gpt-5.6-luna` and blind judging used `gpt-5.6-sol`.
Domain representation, clustering, and taxonomy assignment are outside this experiment.

| Method | Complete | Wins | Composite | Correctness | Completeness | Grounding | Cross-section | Restraint | Review utility | Quote match | Tokens/paper | Seconds/paper |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| One-shot structured extraction | 50 | 22 | 4.5067 | 4.38 | 4.68 | 4.3 | 4.72 | 4.3 | 4.66 | 0.5406 | 18013.6 | 60.466 |
| Section-grounded hierarchical extraction | 50 | 21 | 4.5067 | 4.52 | 4.54 | 4.7 | 4.56 | 4.3 | 4.42 | 0.5477 | 62613.6 | 194.728 |
| DocETL-style planned extraction | 50 | 7 | 4.0333 | 3.92 | 4.38 | 3.56 | 4.34 | 3.74 | 4.26 | 0.4658 | 49949.9 | 159.318 |

## Paired comparison

- One-shot minus hierarchical: `{"mean": 0.0, "ci95_low": -0.1833, "ci95_high": 0.1833}`.
- One-shot minus DocETL-style: `{"mean": 0.4733, "ci95_low": 0.27, "ci95_high": 0.69}`.
- Hierarchical minus DocETL-style: `{"mean": 0.4733, "ci95_low": 0.24, "ci95_high": 0.7167}`.

Intervals are paired 95% bootstrap intervals over the strong judge's six equally weighted scores. The one-shot and hierarchical pipelines are tied on mean composite quality; both outperform the DocETL-style pipeline in this sample.

## Robustness checks

- Wins by year: `{"2024": {"one_shot": 10, "grounded_hierarchical": 7}, "2025": {"one_shot": 6, "docetl_style": 3, "grounded_hierarchical": 8}, "2026": {"one_shot": 6, "docetl_style": 4, "grounded_hierarchical": 6}}`.
- Wins by acceptance: `{"rejected": {"one_shot": 12, "grounded_hierarchical": 12, "docetl_style": 2}, "accepted": {"one_shot": 10, "grounded_hierarchical": 9, "docetl_style": 5}}`.
- Wins by input length: `{"short": {"one_shot": 6, "grounded_hierarchical": 7, "docetl_style": 2}, "long": {"one_shot": 10, "grounded_hierarchical": 10, "docetl_style": 1}, "medium": {"one_shot": 6, "docetl_style": 4, "grounded_hierarchical": 4}}`.
- Mean judge confidence: `0.875`.
- Extraction plus judging used `7714988` tokens; strong judging used `1186132`.

## Decision

Use one-shot structured extraction as the default path. It ties the hierarchical method on aggregate judged quality, wins 22 versus 21 papers, and uses about 29% of its extraction tokens. Escalate to the hierarchical path when evidence checks fail, required fields are missing, claims conflict, or a review request needs unusually strict traceability. Do not use the DocETL-style planner in the production path for this corpus.

The strong judge receives anonymized, deterministically shuffled candidates. Quote match is a mechanical exact-match audit after whitespace normalization; it does not prove that a quote supports the associated claim. The model judge is evidence, not human ground truth.
