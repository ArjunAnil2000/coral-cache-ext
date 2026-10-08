# TODO

## Status (2026-10-08)

The repo is self-contained (`node/` + `third_party/cache_ext` submodule) and the SSH
eval backend is deployed to the CloudLab node `c220g1-030815` at
`/mydata/coral-cache-evolution`.

**Verified**
- Local tests pass (19), including `node/eval_remote.py` run as a real subprocess
  against a stub evaluator.
- On the node, from the self-contained tree: forced-command key is restricted (no
  shell, path escapes rejected), benchmark stack builds from the repo
  (`node/bench/get_scan/setup.sh`), and a real `noop` compile + eval returns valid
  probes.
- Bedrock model `bedrock/us.anthropic.claude-opus-5-5` answers via litellm.
- A full 5-attempt `coral start` run (before the self-contained move, same
  grader logic): 0 grader errors, scores 0.72 / 0.65 / 0.48 / 0.43 / -0.31, agent
  traffic went through the :4001 gateway to Bedrock.
- Re-measuring the best policy (8 runs) against a `noop` control (8 runs): policy
  score 0.79 ± 0.24, throughput 1271 ± 22 ops/s; noop 0.005 ± 0.23, 1224 ± 14 ops/s
  (about +4% throughput). Single-eval leaderboard scores are optimistic.

**After the move:** `coral validate` passes on the self-contained tree
(`/mydata/coral-cache-evolution`, new benchmark DB at `/mydata/coral_get_scan_db`).
New noop calibration (n=8): throughput 1211.6 ± 24 ops/s, iostat 3.20e8 ± 6.1e6,
refaults 51369 ± 1465. The unchanged `noop` seed scored **-0.50** on that validate
run (throughput z=-0.88, the other probes at ~0). That is within the single-eval
noise seen before (noop controls ranged about -0.3..+0.4) but at the edge of it, so
re-check with repeated noop evals before trusting any score near 0. A fresh
`coral start` on the new tree has not been run yet.

**Second run (self-contained tree, 2026-10-08):** 5 real attempts + 1 tune, 0 grader
errors; scores 0.59 (best, `bc478261`: S3-FIFO + three lists using the scan_pids
oracle), 0.53, 0.52, 0.45, 0.27. Policy saved at `results/best/best_policy_run2_bc478261.c`.
**Noise finding:** the agent submitted the same policy twice (second time with a
comment-only diff) and got **0.92 as a `--tune` eval and 0.52 as a real eval**. Our grader
treats tune and real evals identically, so this is pure single-eval noise: a spread of
~0.4 on identical code, larger than the ±0.2-0.3 estimated earlier. Treat any single
score as +-0.4; rank policies only after repeats (e.g. 8 evals each). The run also
stalled 6 h because the dev laptop suspended (lid closed) mid-eval; use
`systemd-inhibit` or disable lid suspend for long runs. Bedrock returned 503s for ~7 min
at start and recovered by itself.

## Next steps

1. Run repeated `noop` evals on the new tree (e.g. 8) to confirm the baseline is stable and
   the -0.50 seed score was noise, then a bounded `coral start` and compare with the
   pre-move run.
2. Exercise `node/setup_node.sh` on a genuinely fresh node (it has only been
   syntax-checked; the existing node was provisioned before it was written).
3. Decide how to handle the agent reading material outside its worktree. Agents run
   as the same OS user as CORAL, so a path restriction can't be enforced without
   `agents.sandbox` or `agents.isolate_user` (the latter needs CORAL to run as root).
   The first run's agent found and reused earlier results from elsewhere on the
   machine; results are not independent unless that is closed off.
4. Repeat evals of any policy worth reporting (single-eval noise is about ±0.2–0.3).
5. The first run's gateway log showed a 400 for model `claude-sonnet-5`; an alias was
   added to `litellm_config.yaml`. Check the next run's gateway log is clean.

## Open questions

- Whether CORAL ever runs multiple grader subprocesses concurrently for one task.
  Its default is serial (`grader.parallel.max_workers: 1`); the node-side flock in
  `node/eval_remote.py` is the safety net if that is raised. Not exercisable with
  `agents.count: 1`.
- Whether `.coral/public/` (notes, attempts, skills) can be pre-seeded with prior
  findings so a fresh run starts with context.
- Cost of a persistent Claude Code agent session per run (Bedrock billing) compared
  with short chat-completion calls.
- Whether Claude Code honours CORAL's injected `ANTHROPIC_API_KEY` in every case
  (gateway logs showed requests arriving, so it did in the first run).

## Deferred

- **Real seed set.** `seed/noop.c` is the dry-run seed. Other starting policies need
  the `vulcan_bpf` headers (nested submodule, already staged at compile time) and
  would be added under `seed/`.
- **`agents.count` > 1**, islands.
- **Multiple nodes:** one CORAL instance per node. A multi-node grader (a list of
  `ssh_target`s with per-node calibration stats) is not implemented.
- **Pinning the CORAL version** instead of installing from `main`.
