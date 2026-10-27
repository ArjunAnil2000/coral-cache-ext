# Does the host change the best policy's performance?

**Question.** In the 4-host run each agent evolved on its own machine, and the bests looked very different (712 ops/s on pc309, 607 on pc320). Is that the policy or the host?

**Experiment.** The best policy of that run (`7e6df4dc`, region-CLOCK, 712.2 ops/s on pc309; file `../multihost_2026-10-21_003256_4hosts/best/best_overall_pc309_7e6df4dc_712.2.c`) was run **unchanged** on all four hosts, interleaved with two unmodified controls: the no-op policy (kernel default reclaim) and MGLRU. Per host: 1 warm-up eval of the best policy (not in the means), then 8 rounds of {best, no-op, MGLRU} with the order rotated each round, so each host has 8 measurements of each policy (100 evals in total, 0 failures). The four hosts ran in parallel, one eval at a time each, using the grader's remote evaluator directly (no agents, no LLM cost).

## Result (throughput, ops/s, mean ± 95% CI of 8 evals)

| host | best policy | no-op | MGLRU | gain vs no-op [95% CI] | gain vs MGLRU [95% CI] | speed index (no-op) |
|---|---|---|---|---|---|---|
| pc306 | 711.4 ± 4.8 | 636.4 ± 8.1 | 664.0 ± 7.6 | +11.8% [+10.6, +13.0] | +7.1% [+6.0, +8.3] | 1.039 |
| pc309 | 711.1 ± 4.9 | 640.9 ± 7.1 | 665.5 ± 9.8 | +11.0% [+9.8, +12.0] | +6.9% [+5.5, +8.2] | 1.046 |
| pc319 | 707.2 ± 4.1 | 637.9 ± 6.9 | 666.0 ± 5.2 | +10.9% [+9.9, +12.0] | +6.2% [+5.4, +7.0] | 1.042 |
| pc320 | 608.3 ± 6.8 | 534.6 ± 7.1 | 573.0 ± 13.2 | +13.8% [+12.2, +15.2] | +6.2% [+4.0, +8.1] | 0.873 |

## Interpretation

1. **The host effect is a speed scale, and only pc320 is different.** pc306, pc309 and pc319 are indistinguishable in speed: the best policy gets 711.4, 711.1 and 707.2 (the difference between the extremes is 0.6%, inside the noise), and the no-op control agrees (636-641). pc320 is about **14% slower** for the best policy (608 vs ~710) and **16% slower** for the no-op control (535 vs ~638). So the 712 vs 607 gap in the 4-host run is mostly the machine, not the policy.
2. **The policy ranking is the same on every host:** best > MGLRU > no-op, with non-overlapping confidence intervals everywhere. The gain over MGLRU is stable (+6.2% to +7.1%); the gain over the no-op is +10.9% to +11.8% on the three fast hosts and +13.8% on pc320.
3. **The gain may be slightly larger on the slow host, but this is weak evidence.** Pairwise differences in the best-vs-no-op gain: pc320 vs the three fast hosts is -1.8 to -2.6 percentage points, with 95% bootstrap CIs that only just exclude zero (upper ends -0.0 to -0.9); the three fast hosts do not differ from each other. These are 6 uncorrected comparisons, so I would not claim that pc320 benefits more. If real, a plausible (untested) reason is that the slower machine is more I/O-bound, but the data here don't show that.
4. **712.2 was not a lucky maximum.** On pc309 the same code measured 711.1 ± 4.9 here (range 703-717), in line with the 711.2 and 712.2 seen during the run.
5. **Noise and order effects.** Run-to-run noise is small for this setup: cv 0.7-1.3% for the best policy, 1.3-1.6% for the no-op. Throughput drifted by at most 1.1% over the 25 evals on a host (pc306 -0.5%, pc309 +0.6%, pc319 +0.1%, pc320 +1.1%), with policies interleaved, so drift does not explain the differences. The warm-up eval (first eval on a host after idle) was 731.6 on pc306, above all eight later evals (703-719), and 709.0, 691.4 and 610.7 on the others, so there is no consistent first-eval effect; one early measurement can be a few percent off in either direction.

## Caveats

- 8 evals per cell: the confidence intervals are bootstrap/t intervals on small samples.
- Each host is a different physical machine and was measured at one point in time (about 25 minutes); I did not repeat the experiment on another day or swap policies between machines of the same speed class beyond the three fast ones.
- The best policy was evolved on pc309; it is not necessarily the best policy for the other hosts.

## Files

| File | What it is |
|---|---|
| `compare-between-hosts.pdf` | Summary table, plots (all dots per host, gain with CIs, run-order view) and per-cell statistics |
| `summary.json` | All statistics (per host and policy: n, mean, sd, CI, min, max, MiB read, refaults; gains; pairwise tests; drift) |
| `raw/<host>.jsonl` | One line per eval: host, policy, round, throughput, bytes read, refaults, wall time |
| `run_compare.py`, `analyze.py` | Experiment runner and analysis |
| `figures/` | Figures used in the PDF |

Re-run: `PYTHONPATH=<worktree>/grader/src ~/.local/share/uv/tools/coral/bin/python run_compare.py 8`, then `python3 analyze.py`.
