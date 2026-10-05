# coral-cache-evolution

Dry-plumbing CORAL task for the `mem-evolve`/`cache_policy_evolution`
page-cache policy evolution project (`arjua-forks/mem-evolve/`). This is a
deliberately separate repo, not a subdirectory of `mem-evolve/` — CORAL
gives each agent its own git worktree of `workspace.repo_path` (`./seed`),
and keeping that isolated avoids mixing CORAL's `.coral/` runtime state into
the existing research repo's history.

**This is not a real experiment.** The only goal right now is proving the
full pipeline works end to end, before any decisions about real seeds,
multiple agents, or retiring the old coordinator get made. See `TODO.md`
for the actionable checklist and everything still open.

Background / full migration research: `mem-evolve/coral-learnings.md`.

## What this proves (once run)

One CORAL agent edits `seed/noop.c` → the grader
(`grader/src/cache_evolution_grader/grader.py`) compiles it against the real
`cache_ext` toolchain → attaches it via BPF struct_ops → runs it under the
cgroup-isolated benchmark → returns a score → the attempt shows up under
`.coral/public/attempts/`.

## Why this has to run on the CloudLab node, not a dev machine

CORAL's manager, its agent(s), and the grader subprocess all share **one
host** — there's no remote-worker concept (`agents.count` spawns agents on
one machine; no config field targets a remote host). The grader is what
compiles, attaches BPF struct_ops, and runs the cgroup benchmark, and all
of that needs the booted `6.6.8-cache-ext` kernel, pinned `clang-14`/
`bpftool`, and the benchmark cgroup — which exist **only** on the CloudLab
node. `coral start` must be invoked there.

This is a step back from the old architecture in one respect: `evolve.py`
(the old coordinator) only needed `clang`/`bpftool` to compile and shipped
binaries over HTTP to separate worker nodes that held the kernel —
coordinator and kernel-host could be different machines. CORAL collapses
that split into one host.

## Repo layout

```
coral-cache-evolution/
├── task.yaml                # CORAL task config: 1 agent, claude_code runtime,
│                             # LiteLLM gateway on :4001, grader entrypoint
├── litellm_config.yaml      # Bedrock model routing for the gateway (has a TODO —
│                             # exact model id not yet confirmed, see TODO.md)
├── seed/
│   └── noop.c                # dry-run placeholder policy (copied from
│                              # mem-evolve/cache_policy_evolution/seeds/noop.c)
└── grader/
    ├── pyproject.toml        # depends on "coral"
    └── src/cache_evolution_grader/
        ├── __init__.py
        └── grader.py          # wraps evaluator.compile_policy + evaluate()
                                 # from mem-evolve/cache_policy_evolution,
                                 # under an flock-based eval lock
```

## Key design decisions baked into this scaffold

- **`agents.count: 1`** — multi-agent is an explicit "later" decision, not
  part of this dry run.
- **LiteLLM/Bedrock, not direct Claude auth** — the agent's model calls
  route through CORAL's own gateway (`litellm_config.yaml`), configured with
  the same AWS Bedrock credentials `mem-evolve`'s old coordinator already
  uses, not a direct Anthropic API key. The agent *runtime* is still
  `claude_code` — CORAL auto-injects the gateway URL/key into Claude Code
  sessions.
- **Gateway on port 4001**, not 4000 — the old coordinator's LiteLLM proxy
  also wants port 4000; kept distinct to avoid any collision if both are
  ever up at once.
- **`evaluator.compile_policy()`/`evaluate()` reused via `MEM_EVOLVE_ROOT`**
  (env var, defaults to `/mydata/evo_cache/cache_policy_evolution`) rather
  than vendored into this repo — `evaluator/` is already standalone (no
  imports from `evolution/` or any LLM code), so this is a thin wrapper, not
  a port.
- **flock-based eval lock**, wrapping both `compile_policy()` (which
  mutates the shared `cache_ext/policies/` dir in place) and `evaluate()`
  (which attaches a global, exclusive, root-only BPF struct_ops slot) — the
  old `worker_server.py` only needed to lock `evaluate()` in-process
  (`threading.Lock`), because compiling happened on the coordinator,
  separate from the worker. Collapsing coordinator+worker onto one host
  means both operations now need to serialize across grader subprocesses.
