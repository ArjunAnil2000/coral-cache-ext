# TODO

## Status (2026-10-08)

All earlier runs, their results and the cached noop calibration were deleted on
2026-10-08 to start from scratch. Nothing is running. The next run recalibrates the noop
baseline on its first grade (8 evals, ~6 min) or via the calibrate CLI (see how-to-run.md).

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
- Single-eval noise is large. The same code scored 0.92 and 0.52 on two evals (our grader
  treats `--tune` and real evals identically), and the unchanged noop seed has scored -0.50.
  Never rank policies from single evals; repeat (e.g. 8 evals each) before comparing.
- The score is dominated by bytes-read / refault z-scores when those baselines are tight
  (a ~5% drop is ~3 sigma and saturates tanh), so score rank and throughput rank can differ.
  If throughput is the goal, report absolute throughput alongside the score.
- The agent reads the grader source by CORAL's design (`.claude/grader/` is a symlink to
  `grader/`). It also found earlier results elsewhere on the machine when the task
  description pointed at them; keep any reference material inside the worktree.
- A run freezes if the dev machine suspends (lid closed): use `systemd-inhibit` or
  disable lid suspend. Bedrock occasionally returns 503s for several minutes; the agent's
  built-in retries ride it out.
- `run.session: local` means no tmux; the agent is a child process of the manager.

## Next steps

1. Fresh bounded `coral start` (nothing queued yet); calibrate first so the first agent
   eval is not slowed by it.
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
