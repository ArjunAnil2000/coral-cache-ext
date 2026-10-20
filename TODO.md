# TODO

## Status (2026-10-09)

**Branch `one-host-all-seeds-score-maximize-throughput`:** all seeds (noop + 7 reference policies); the grader's score is the ABSOLUTE measured throughput
in ops/s (no baseline calibration, z-score, `tanh` or weighting); the agent maximizes it. The
other probes appear in the feedback only for diagnosis. The calibration step, stats cache,
`normalization.py` and the calibrate CLI were removed on this branch.

All earlier runs and their results were deleted on 2026-10-08 to start from scratch. Nothing
is running.

The repo is self-contained (`node/` + `third_party/cache_ext` submodule) and the SSH eval
backend is deployed to the CloudLab node `c220g1-030815` at `/mydata/coral-cache-evolution`
(benchmark DB at `/mydata/coral_get_scan_db`, kept: it is data, and a fresh DB makes the
first eval unrepresentative).

**Verified (infrastructure only)**
- Local tests pass (19), including `node/eval_remote.py` as a real subprocess against a stub evaluator.
- On the node: the forced-command key is restricted (no shell, path escapes rejected), the
  benchmark stack builds from the repo, and `coral validate` passes end to end.
- Bedrock model `bedrock/us.anthropic.claude-opus-5-5` answers via litellm and through
  CORAL's :4001 gateway; two bounded `coral start` runs completed with 0 grader errors.

**Lessons from the earlier runs (operational, no results)**
- Single-eval noise is large: identical code has measured 1257-1274 ops/s across evals, and
  one re-submission of code that had measured ~1259 ops/s twice came out at 1165. The grader
  treats `--tune` and real evals identically. Never rank policies from single evals; repeat
  (e.g. 8 evals each) before comparing, and treat differences under ~1-2% as noise.
- (Master-branch scoring only) a z-score/`tanh` score saturates near 1 once a policy is a few
  sigma above a tight baseline, and bytes-read z-scores could outvote a throughput regression.
  This branch avoids both by scoring raw throughput.
- The agent reads the grader source by CORAL's design (`.claude/grader/` is a symlink to
  `grader/`). It also found earlier results elsewhere on the machine when the task
  description pointed at them; keep any reference material inside the worktree.
- A run freezes if the dev machine suspends (lid closed): use `systemd-inhibit` or
  disable lid suspend. Bedrock occasionally returns 503s for several minutes; the agent's
  built-in retries ride it out.
- `run.session: local` means no tmux; the agent is a child process of the manager.

**Seeds (2026-10-09):** the reference policies in `seed/reference/` are now one combined
file each (fifo, mru, s3fifo, sampling, get_scan, mglru, lhd), same format as `noop.c`, each with a
description under the banner. Loaders were fixed to wait for SIGINT/SIGTERM (the originals blocked
on `getchar()`, which exits immediately under the harness), to accept `-w/-s/-c`, and
`get_scan` reuses the harness-pinned `scan_pids` map. All seven compile, attach and complete a
benchmark run on the node; `grader/tests` checks their format. Also learned: CloudLab rewrites
`~/.ssh/authorized_keys` (dropped our key); the installer now uses `authorized_keys2`.

## Next steps

1. Fresh bounded `coral start` on this branch (nothing queued yet); no calibration is needed.
   Consider how to pick the final policy robustly, since the max of single noisy evals favors
   luck (e.g. re-evaluate the top few candidates several times).
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
  `ssh_target`s) is not implemented.
- **Pinning the CORAL version** instead of installing from `main`.
