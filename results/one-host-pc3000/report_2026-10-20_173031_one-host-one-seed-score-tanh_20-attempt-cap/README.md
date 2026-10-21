# Report for CORAL run 2026-10-20_173031 — one-host-one-seed-score-tanh

S3-FIFO is the only seed; score = tanh-squashed weighted z-score vs the vanilla-kernel no-op baseline (throughput w=2.0, bytes read 0.5, refaults 0.25). Host: pc309.emulab.net. 20 real attempts (20 scored, 0 crashed), 0 tune.

| File | What it is |
|---|---|
| `report_2026-10-20_173031.pdf` | Summary, score figures, all attempts, best evolved policy with code (changed lines highlighted vs the closest seed), caveats. |
| `data.json` | Extracted attempt, session and gateway data. |
| `best/best_policy.c`, `best/best_policy.json` | Highest-scoring real attempt (#19 `fefe1ef1`, 0.755). |
| `best_evolved_policy.c` | Best agent-evolved attempt (#19 `fefe1ef1`, 0.755); written only if it differs from the best policy. |
| `figures/` | Figures used in the PDF. |

Rebuild: `python3 results/pc3000/runreport.py <worktree> tanh one pc309` (needs the gitignored run directory `/home/aanil/Desktop/ldos/arjua-forks/coral-runs/one-host-one-seed-score-tanh/results/cache-ext-get-scan/2026-10-20_173031`).
