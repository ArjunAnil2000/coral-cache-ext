# Report for CORAL run 2026-10-09_102552 — absolute-throughput scoring, 5-attempt cap

Same layout as `report_2026-10-09_004013_zscore-tanh-scoring_20-attempt-cap/` (the earlier run), adapted to this run's scoring:
the score is the measured throughput in ops/s (branch `absolute-throughput-score`), so there is no baseline calibration, z-score or weights.

| File | What it is |
|---|---|
| `report_<date>_<time>.pdf` | The report (8 pages): run summary, environment/workload, per-attempt results with all recorded probes and derived per-operation metrics, score figure, cross-run comparison of identical reference code, best attempt, timing, agent sessions and LLM usage, permission denials, gateway, context, what was not measured. |
| `data.json` | Every number extracted from the run (and the first run's reference points used for comparison). |
| `best_evolved_policy.c` | `noop.c` of the agent-evolved attempt (#4 `0e985cef`). The highest-scoring attempt overall (#3) was the unmodified reference `mru.c`. |
| `extract.py`, `analysis.py`, `figures.py`, `build_report.py`, `figures/` | Rebuild: `python3 extract.py && python3 build_report.py` (needs `results/cache-ext-get-scan/2026-10-09_102552`, which is gitignored). |

Notes
- This run has no noop evaluation. Where a baseline appears it is the 8-run noop calibration of the first run and is labelled "external".
- The unmodified reference attempts (get_scan, s3fifo, sampling) ran byte-identical code in both runs; the cross-run section compares them.
