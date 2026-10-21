# Report for CORAL run 2026-10-20_173036 — one-host-all-seeds-score-maximize-throughput

all seven reference policies available; score = absolute measured throughput (ops/s). Host: pc319.emulab.net. 20 real attempts (17 scored, 3 crashed), 0 tune.

| File | What it is |
|---|---|
| `report_2026-10-20_173036.pdf` | Summary, score figures, all attempts, best evolved policy with code (changed lines highlighted vs the closest seed), caveats. |
| `data.json` | Extracted attempt, session and gateway data. |
| `best/best_policy.c`, `best/best_policy.json` | Highest-scoring real attempt (#18 `e8ecbcfc`, 679.3). |
| `best_evolved_policy.c` | Best agent-evolved attempt (#18 `e8ecbcfc`, 679.3); written only if it differs from the best policy. |
| `figures/` | Figures used in the PDF. |

Rebuild: `python3 results/pc3000/runreport.py <worktree> abs all pc319` (needs the gitignored run directory `/home/aanil/Desktop/ldos/arjua-forks/coral-runs/one-host-all-seeds-score-maximize-throughput/results/cache-ext-get-scan/2026-10-20_173036`).
