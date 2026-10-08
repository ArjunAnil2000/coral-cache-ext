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

## Topology: CORAL runs here, grading runs on the node over SSH

CORAL's manager, agents and grader subprocess share one host and CORAL has
no remote-worker concept — but the grader is just a subprocess, so it can
reach out. Here CORAL and its agent(s) run on the **dev host** (no special
kernel needed; agents only edit `.c` files). To grade, the grader ssh-es to
the **CloudLab node**, which has the booted `6.6.8-cache-ext` kernel,
`clang-14`/`bpftool` and the benchmark cgroup:

```
dev host:  coral start -> agent edits seed/noop.c -> grader (scoring, calibration stats)
                                                        |  ssh (forced-command key)
node:      eval_remote.py: flock -> compile_policy -> attach struct_ops
                           -> get_scan benchmark -> probe values (JSON)
```

The grader is deterministic code (not an LLM): it keeps CORAL's property that
agents can't tamper with grading. Scoring (noop-baseline z-score + tanh) is
done locally from the probe values the node returns.

The ssh key is a dedicated **forced-command** key (`remote/install_remote.sh`):
it can only run `eval_remote.py`, with no shell/pty/forwarding, so an agent
that reads `~/.ssh/coral_eval_ed25519` (agents run as the same user) still
can't get a shell on the node. `eval_remote.py` also refuses benchmark paths
outside `MEM_EVOLVE_ROOT/eval`. Compiling/attaching an agent-written policy as
root is inherent to the task.

## Repo layout

```
coral-cache-evolution/
├── task.yaml                # CORAL task config: 1 agent, claude_code runtime,
│                            # LiteLLM gateway on :4001, grader entrypoint + args
├── litellm_config.yaml      # Bedrock model routing for the gateway
├── seed/noop.c              # dry-run placeholder policy (agent's starting point)
├── remote/
│   ├── eval_remote.py       # runs ON the node: lock, compile, attach, benchmark -> JSON
│   └── install_remote.sh    # one-time: key + script + forced-command authorized_keys
└── grader/
    ├── pyproject.toml
    ├── tests/test_scoring.py        # local tests (stubbed coral; real eval_remote.py subprocess vs stub evaluator)
    └── src/cache_evolution_grader/
        ├── grader.py        # Grader: calibration + remote call + scoring
        ├── remote.py        # ssh client (retry on connection failure)
        ├── scoring.py       # probe specs, weights, stats cache, feedback text
        ├── normalization.py # verbatim copy of mem-evolve evolution/normalization.py
        ├── calibrate.py     # pre-calibration CLI
        └── baseline_noop.c  # noop baseline used for calibration (not the agent's copy)
```

## Key design decisions baked into this scaffold

- **`agents.count: 1`** — multi-agent is an explicit "later" decision.
- **LiteLLM/Bedrock, not direct Claude auth** — model calls route through
  CORAL's own gateway (`litellm_config.yaml`) with AWS Bedrock credentials,
  never a direct Anthropic API key. Gateway on **:4001** to avoid colliding
  with the old coordinator's proxy on :4000.
- **Evaluation is remote and serialized on the node.** Struct_ops attach is a
  global exclusive slot and `compile_policy()` mutates `cache_ext/policies/`,
  so `eval_remote.py` holds `/run/evo_cache/eval.lock` (bounded wait) across
  compile + all evals of one request. Concurrent graders queue there.
- **Scoring mirrors `get_scan.toml` (2026-08-13)**: throughput=2.0,
  cgroup_iostat=0.5, cgroup_memstat=0.25, z-scored against frozen noop stats,
  tanh-squashed. Stats are cached locally (`stats_path`) with a fingerprint
  of (probes, weights, ssh target + benchmark, baseline source).
- **Scaling out later**: one CORAL instance per node (as in coral-learnings.md);
  a multi-node grader would be a list of `ssh_target`s with per-node
  calibration stats — not implemented.
