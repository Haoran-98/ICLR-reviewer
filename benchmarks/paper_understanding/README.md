# Paper-understanding comparison

This benchmark compares three structured-understanding pipelines on the same
50 ICLR 2024-2026 main-track papers. It deliberately excludes embeddings,
clustering, and taxonomy assignment.

```bash
python3 benchmarks/paper_understanding/benchmark.py self-test
python3 benchmarks/paper_understanding/benchmark.py sample
python3 benchmarks/paper_understanding/benchmark.py run --resume --workers 3
python3 benchmarks/paper_understanding/benchmark.py judge --resume --workers 3
python3 benchmarks/paper_understanding/benchmark.py report
python3 benchmarks/paper_understanding/benchmark.py status
```

Large checkpoints are written to `/data_big/iclr-paper-understanding-benchmark`.
The weak model performs extraction; the configured strong model performs
anonymized per-paper comparison.

The selected production policy is recorded in `selected_pipeline.json`: use
the weak-model one-shot path by default and escalate to the weak-model
section-grounded path only when deterministic evidence checks fail.
