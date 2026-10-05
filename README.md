# coral-cache-evolution

Dry-plumbing CORAL task for the `mem-evolve`/`cache_policy_evolution`
page-cache policy evolution project. Separate repo from `mem-evolve/` on
purpose — CORAL gives each agent its own git worktree of `workspace.repo_path`
(`./seed`), and this keeps that isolated from the existing research repo's
history and `.coral/` runtime state.

This is **not** a real experiment yet. The only goal right now is proving
the full pipeline works: one CORAL agent edits `seed/noop.c` → the grader
(`grader/src/cache_evolution_grader/grader.py`) compiles it against the real
`cache_ext` toolchain, attaches it via BPF struct_ops, runs it under the
cgroup-isolated benchmark, and returns a score → the attempt shows up under
`.coral/public/attempts/`.

Background / full migration research: `mem-evolve/coral-learnings.md`.
Plan this was built from: see chat history / `virtual-wibbling-aurora` plan.

## Status

Scaffolded locally on 2026-10-05. **Not yet run** — the CloudLab node
(`mem-evolve/cloudlab-instances.md`) was unreachable (SSH timeout on both
`pc288.emulab.net` and `pc320.emulab.net`) when this was built, so the
`coral` CLI install and first `coral start` are still pending.

## Before first run, once the node is reachable

1. Install the `coral` CLI on the node (not installed as of this scaffold):
   ```
   curl -fsSL https://raw.githubusercontent.com/Human-Agent-Society/CORAL/main/install.sh | sh
   ```
2. Fill in `litellm_config.yaml`'s `TODO` (exact Bedrock model id —
   confirm against whatever the old coordinator's litellm proxy config uses
   on the node; this local checkout's `mem-evolve/litellm-creds.sh` only has
   `AWS_ACCESS_KEY_ID`, not the secret key/region, so check the node).
3. `source <path-to-mem-evolve>/litellm-creds.sh` in the shell that runs
   `coral start` (do not copy secrets into this repo).
4. Confirm `MEM_EVOLVE_ROOT` in `grader/src/cache_evolution_grader/grader.py`
   matches this node's actual path (defaults to
   `/mydata/evo_cache/cache_policy_evolution` per `mem-evolve/CLAUDE.md`'s
   documented layout — override via the `MEM_EVOLVE_ROOT` env var if
   different).
5. `coral start -c task.yaml` from this repo's root.

## Deferred (decide later, not part of this dry run)

- Real seed set (`vulcan_scan_resist.c` / `vulcan_scan_class.c` / full
  `get_scan.toml` workload) instead of the `noop.c` placeholder.
- `agents.count` above 1 / multi-agent, islands.
- Wiring `evolution/normalization.py`'s real tanh/z-score scoring into the
  grader (currently uses `evaluate()`'s raw weighted-sum score).
- Seeding `.coral/public/notes` with `mem-evolve`'s existing throughput-exp
  findings.
- Whether `mem-evolve`'s old coordinator keeps running in parallel or gets
  retired.
