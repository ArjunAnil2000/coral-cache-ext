# Does the 712 ops/s policy hold up on the four new hosts?

The best policy of the earlier 4-host run (`7e6df4dc`, region-CLOCK, 712.2 ops/s on pc309; evolved on
pc306/pc309/pc319/pc320) run unchanged on the current hosts pc252, pc257, pc258, pc318, interleaved with the
unmodified no-op and MGLRU controls. 8 evals per policy per host (rotated order) plus one warm-up per host.
100 evals, 0 failures.

| Host | best (ops/s) | no-op | MGLRU | gain vs no-op | gain vs MGLRU |
|---|---|---|---|---|---|
| pc252 | 702.8 | 644.1 | 663.3 | +9.1% | +6.0% |
| pc257 | 700.1 | 631.9 | 660.5 | +10.8% | +6.0% |
| pc258 | 694.9 | 630.6 | 657.5 | +10.2% | +5.7% |
| pc318 | 699.7 | 628.5 | 658.6 | +11.3% | +6.3% |

| File | What it is |
|---|---|
| `compare-new-hosts.pdf` | Per-host table, dot/bar figure, gains with bootstrap CIs, run-order drift. |
| `summary.json` | All statistics. |
| `raw/<host>.jsonl` | One line per eval, nothing filtered. |
| `run_compare.py`, `analyze.py` | Copies of `../compare-between-hosts/` scripts with the host list changed. |

Rerun: `PYTHONPATH=<worktree>/grader/src ~/.local/share/uv/tools/coral/bin/python run_compare.py 8`, then `python3 analyze.py`.
