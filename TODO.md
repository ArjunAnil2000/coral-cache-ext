# TODO

Status as of 2026-10-05: repo scaffolded and committed locally
(`/home/aanil/Desktop/ldos/arjua-forks/coral-cache-evolution/`, commit
`cb67d1e`). **Nothing has actually run yet.** Everything below is blocked
on the CloudLab node being reachable, since `coral start` has to execute
there (see README's "Why this has to run on the CloudLab node" section) —
this local checkout is staging only.

## Blocked on

- **CloudLab node unreachable.** Both `pc288.emulab.net` and
  `pc320.emulab.net` (`mem-evolve/cloudlab-instances.md`) timed out on SSH
  when checked on 2026-10-05 (general internet egress from the dev machine
  worked fine, so it's the node/reservation, not a local network issue).
  This differs from the "permission denied" symptom `mem-evolve/CLAUDE.md`
  already documents for a lapsed reservation (that's a stale-key case,
  fixed by re-provisioning) — a timeout more likely means the node itself
  isn't up. **Confirm the CloudLab reservation is actually still live
  before assuming a stale key and re-provisioning** — if the reservation
  expired outright, re-provision per `mem-evolve/setup_cloudlab.sh` and
  update `mem-evolve/cloudlab-instances.md`, same as the existing doc's
  documented recovery path.

## Immediate next steps, once the node is reachable

1. **Transfer this repo to the node.** Either push to a remote git host
   and clone there, or `rsync`/`scp` this local checkout directly to e.g.
   `/mydata/evo_cache/coral-cache-evolution/`.
2. **Install the `coral` CLI on the node.** Confirmed not installed on the
   dev machine; not yet checked on the node (it was unreachable at scaffold
   time).
   ```
   curl -fsSL https://raw.githubusercontent.com/Human-Agent-Society/CORAL/main/install.sh | sh
   ```
3. **Fill in `litellm_config.yaml`'s Bedrock model id `TODO`.** The dev
   machine's local copy of `mem-evolve/litellm-creds.sh` only exports
   `AWS_ACCESS_KEY_ID` — the secret key, region, and the exact
   `bedrock/anthropic.claude-...` model id string live only on the node (or
   wherever the old coordinator's actual running litellm proxy config is).
   Confirm there before first run; the current file in this repo has a
   literal `"bedrock/anthropic.claude-sonnet-TODO"` placeholder that will
   fail if run as-is.
4. **Source the Bedrock creds before `coral start`:**
   `source <path-to-mem-evolve>/litellm-creds.sh`. Do not copy secrets into
   this repo.
5. **Confirm `MEM_EVOLVE_ROOT`** in
   `grader/src/cache_evolution_grader/grader.py` matches the node's real
   `cache_policy_evolution` path. Defaults to
   `/mydata/evo_cache/cache_policy_evolution` per `mem-evolve/CLAUDE.md`'s
   documented layout; override via the `MEM_EVOLVE_ROOT` env var if the
   node's actual checkout lives somewhere else.
6. **Confirm the cache_ext kernel/toolchain is already set up on whichever
   node this runs on** — booted `6.6.8-cache-ext` kernel, `clang-14`,
   `bpftool`, the `cache_ext_bench` cgroup (`setup_isolation.sh` already
   run). This dry run assumes the existing `mem-evolve` setup on that node
   is intact; it does not redo `setup_cloudlab.sh`.
7. **First run:** from `coral-cache-evolution/` on the node, `coral start
   -c task.yaml`.
8. **Verify the run actually worked:**
   - `coral` CLI installed, `coral --version` runs.
   - The single agent's worktree was created and it can see `seed/noop.c`.
   - The agent made at least one commit.
   - The grader subprocess ran `compile_policy()` → `evaluate()` against
     the real kernel/cgroup without erroring.
   - A score came back and the attempt appears under
     `.coral/public/attempts/`.
   - The agent's model calls went through the port-4001 gateway using
     Bedrock credentials (check gateway logs / confirm no direct
     `ANTHROPIC_API_KEY` path was used).
   - No collision with the old coordinator's port-4000 proxy (it was idle
     when checked, but the ports are deliberately kept distinct regardless
     of whether both happen to be running).

## Open questions to resolve before going past the dry run

- Whether CORAL ever runs multiple grader subprocesses concurrently for
  the same task (vs. queuing evaluations itself) — determines whether the
  `fcntl.flock` lock in `grader.py` is a safety net for a rare race or the
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
