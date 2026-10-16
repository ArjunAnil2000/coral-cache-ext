# Reports for CORAL run 2026-10-09_004013 (cache-ext get_scan, 20-attempt cap)

**Kind of run:** `master`-branch scoring (weighted `tanh` of z-scores vs the noop baseline, score in [-1, 1]), 20-attempt cap,
28 evals in total (20 real + 8 tune). This folder lives at `results/report_2026-10-09_004013_zscore-tanh-scoring_20-attempt-cap/`
(moved here from the repo root `report/`; the scripts below still work from this location).
The run's raw output is `results/cache-ext-get-scan/2026-10-09_004013/` (gitignored).

Two reports, marked by date and time of creation (both made on 2026-10-09):

| File | Pages | What it is |
|---|---|---|
| `report_2026-10-09_1027_full.pdf` | 18 | Full report: every attempt, workload and node details, noise analysis, ranking, timing, agent/LLM usage, gateway, provenance. |
| `report_2026-10-09_1043_slim.pdf` | 5 | Slim report: only the parameters used in the score normalization (throughput, bytes read, refaults), evolved policies vs the noop baseline, and the best evolved policy (#17 `61054f8b`). |

Note: the 10:27 full report was regenerated from the same data and logic after it was accidentally overwritten
by the slim build; its content is unchanged but the file is a rebuild.

## Rebuilding
- `data.json` — all numbers extracted from the run (`extract.py` re-creates it from `results/cache-ext-get-scan/2026-10-09_004013`, which is gitignored).
- `analysis.py` — shared statistics.
- Full: `figures_full.py` + `build_full.py` → `figures/full/`.
- Slim: `figures_slim.py` + `build_slim.py` → `figures/slim/`, also writes `best_policy.c` (the best evolved policy's `noop.c`).

```bash
python3 build_full.py   # writes report_2026-10-09_1027_full.pdf
python3 build_slim.py   # writes report_2026-10-09_1043_slim.pdf
```
