# Report for CORAL run 2026-10-11_130334 — all seeds, absolute-throughput scoring, 20-attempt cap

Branch `absolute-throughput-score`: all seven reference policies (fifo, mru, s3fifo, sampling, get_scan, mglru, lhd) were available to the agent; score = raw measured throughput (ops/s). Counterpart of the single-seed run `report_2026-10-09_162748_single-seed-s3fifo_20-attempt-cap/`.

| File | What it is |
|---|---|
| `report_<date>_<time>.pdf` | The report: run summary, environment/workload, per-attempt results with probes and per-operation metrics (crashed attempt listed separately), score figures, same-code comparison against earlier runs and repeats within the run, best attempt, timing, agent sessions and LLM usage, permission denials, gateway, what was not measured. |
| `data.json` | Every number extracted from the run. |
| `best/best_policy.c`, `best/best_policy.json` | Highest-scoring attempt (#9 `3233ed4a`, the unmodified `mglru.c`, 1262.31 ops/s; its re-run #12 scored 1212.78) and its metadata. |
| `best_evolved_policy.c` | Best agent-evolved attempt (#20 `7f1ae77b`, S3-FIFO with a larger small-FIFO share, 1246.43 ops/s). |
| `extract.py`, `analysis.py`, `figures.py`, `build_report.py`, `figures/` | Rebuild: `python3 extract.py && python3 build_report.py` (needs `results/cache-ext-get-scan/2026-10-11_130334`, gitignored). |

Notes
- Δ values use the pooled unmodified S3-FIFO measurements (this run and the three earlier runs, n=6) as the common reference.
- 20 attempts, all `real`; #10 crashed without a score. An earlier start of this run (`2026-10-11_112906`) was stopped with 0 evals because Bedrock returned 503s.
