# TODO

Status as of 2026-10-07: SSH-backend grader implemented and committed; local tests
pass (19). **Verified:** `coral validate` passes end to end against node `c220g1-030815`
(real TaskGrader API, remote compile/attach/get_scan, 8-run noop calibration, seed score
0.0104 ~ 0 as expected); forced-command key is restricted; Bedrock model id answers via
litellm. Noop baseline: throughput 1219.7 +- 30.8 ops/s (n=8, ~2.5% std), iostat
3.19e8 +- 7.7e6, ~40s per eval. **Not yet verified:** a full `coral start` agent run,
the model call through CORAL's :4001 gateway, whether Claude Code honors the injected
ANTHROPIC_API_KEY over a stored login.

## Next steps

1. ~~Validate the Bedrock model id~~ DONE 2026-10-07: `bedrock/us.anthropic.claude-opus-5-5` answered a litellm call with the creds in `litellm-creds.sh`. Still untested *through CORAL's gateway* (alias `claude-sonnet` actually routes to Opus 5.5; consider renaming the alias).
2. ~~`coral validate`~~ DONE (stats cached at `~/.cache/cache_evolution_grader/get_scan_noop_stats.json`; delete if the node changes).
3. Note the noise floor: a single noop re-run scores ~N(0, ~0.3) per component, so small scores are noise; consider repeats before trusting small wins.
4. `coral start -c task.yaml`; confirm an attempt lands in `.coral/public/attempts/`
   and model calls go through the :4001 gateway.

## Open questions to resolve before going past the dry run

- Whether CORAL ever runs multiple grader subprocesses concurrently for
  the same task (vs. queuing evaluations itself) — determines whether the
  `node-side flock in `remote/eval_remote.py` is a safety net for a rare race or the
  only thing standing between two concurrent BPF attach attempts. Not
  resolved by the research in `mem-evolve/coral-learnings.md`; also not
  exercisable with `agents.count: 1` as currently configured.
- Whether/how `.coral/public/` (notes/attempts/skills) can be pre-seeded
  with `mem-evolve`'s existing findings (e.g. the throughput-exp writeup,
  the scoring-function fix from 2026-08-13) so a fresh CORAL run starts
  with prior-run context instead of from scratch.
- Cost model for running a persistent Claude Code agent session per
  evolution attempt vs. the old mutator/planner/frontier short
  chat-completion-call pattern.

## Explicitly deferred — not part of this dry run

- **Real seed set.** Swap `seed/noop.c` for `vulcan_scan_resist.c` /
  `vulcan_scan_class.c` / the full `get_scan.toml` workload once the
  plumbing is proven. `get_scan.toml` has the most complete existing
  write-up and a direct throughput probe — natural first real target per
  `mem-evolve/coral-learnings.md`'s "suggested first migration step."
- **`agents.count` above 1** — multi-agent coordination, islands. Raising
  this is also what would actually exercise the open question above about
  concurrent grader subprocesses.
- **Real scoring.** DONE in code (untested on node): grader now applies get_scan.toml
  probes/weights + noop-baseline z-score/tanh (see grader.py docstring). Still to do:
  run `python -m cache_evolution_grader.calibrate` on the node and sanity-check the stats.
- **Old-coordinator retirement decision.** Whether `mem-evolve`'s
  `evolve.py` / `worker_server.py` / `start_workers.sh` fleet keeps running
  in parallel as a fallback, or gets archived once this pilot validates
  against known-good results (e.g. reproducing `exp1--baseline`'s
  throughput numbers).
