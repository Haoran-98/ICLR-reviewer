# Parser comparison

This benchmark compares the existing ICLR Markdown corpus with Docling and
MinerU on the same 100-paper, main-track-only sample. Large parser outputs and
model files stay under `/data_big/iclr-parser-benchmark`; this directory keeps
only the reproducible driver and final summary.

Show resumable progress at any time:

```bash
python3 benchmarks/parser_comparison/benchmark.py status
```
