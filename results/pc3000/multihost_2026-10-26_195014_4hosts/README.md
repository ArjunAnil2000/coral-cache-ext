# Multi-host CORAL run 2026-10-26_195014

4 agents, one per host (pc252, pc257, pc258, pc318), absolute-throughput scoring, 20 real evals per host. Overall best: pc252 #70 `69132a21` score 686.1.

| File | What it is |
|---|---|
| `report_2026-10-26_195014.pdf` | Per-host summary, progress figures, top attempts, all attempts per host, best policies with code. |
| `data.json` | Attempts, per-host baselines, cost and run info. |
| `best/best_overall_*.c`, `best/best_overall.json` | Highest-scoring real attempt across hosts. |
| `best/<host>_best_*.c` | Highest-scoring real attempt on each host. |

Rebuild: `python3 results/pc3000/multihost_report.py /home/aanil/Desktop/ldos/arjua-forks/coral-runs/multihost-maximize-throughput/results/cache-ext-get-scan/2026-10-26_195014`
