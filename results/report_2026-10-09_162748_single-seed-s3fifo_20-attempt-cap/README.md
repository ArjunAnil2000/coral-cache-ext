# Report for CORAL run 2026-10-09_162748 — single seed (S3-FIFO), absolute-throughput scoring, 20-attempt cap

Branch `20-evol-one-seed`: S3-FIFO is the only starting policy (`seed/noop.c`); no other example policies were available to the agent.
Same layout as the earlier `report_*` folders; scoring is the raw measured throughput (ops/s).

| File | What it is |
|---|---|
| `report_<date>_<time>.pdf` | The report: run summary, environment/workload, per-attempt results (with probes and derived per-operation metrics, crashed attempts listed separately), score figures, repeated-measurement noise analysis (seed measured in three runs; re-run evolved designs), best attempt, timing, agent sessions and LLM usage, permission denials, gateway, what was not measured. |
| `data.json` | Every number extracted from the run. |
| `best_evolved_policy.c` | `noop.c` of the best real (non-tune) evolved attempt (#5 `30ecfc5d`, LFU-with-history). Its re-run (#7) scored 1223.6 vs 1276.6, so the gain is not distinguishable from noise. |
| `extract.py`, `analysis.py`, `figures.py`, `build_report.py`, `figures/` | Rebuild: `python3 extract.py && python3 build_report.py` (needs `results/cache-ext-get-scan/2026-10-09_162748`, which is gitignored). |

Notes
- The reference for all Δ values is the unmodified S3-FIFO seed measured in this run (#1, #29); the seed's measurements from the two earlier runs are shown for noise context.
- 29 attempts = 20 real + 9 `--tune` (tune does not count toward the cap); #8 and #13 crashed without a score.
