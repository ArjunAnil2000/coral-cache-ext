# Report for CORAL run 2026-10-20_173041 — one-host-one-seed-score-maximize-throughput

S3-FIFO is the only seed; score = absolute measured throughput (ops/s). Host: pc320.emulab.net. 20 real attempts (19 scored, 1 crashed), 0 tune.

| File | What it is |
|---|---|
| `report_2026-10-20_173041.pdf` | Summary, score figures, all attempts, best evolved policy with code (changed lines highlighted vs the closest seed), caveats. |
| `data.json` | Extracted attempt, session and gateway data. |
| `best/best_policy.c`, `best/best_policy.json` | Highest-scoring real attempt (#6 `46ce09fd`, 540.8). |
| `best_evolved_policy.c` | Best agent-evolved attempt (#6 `46ce09fd`, 540.8); written only if it differs from the best policy. |
| `figures/` | Figures used in the PDF. |

Rebuild: `python3 results/pc3000/runreport.py <worktree> abs one pc320` (needs the gitignored run directory `/home/aanil/Desktop/ldos/arjua-forks/coral-runs/one-host-one-seed-score-maximize-throughput/results/cache-ext-get-scan/2026-10-20_173041`).
