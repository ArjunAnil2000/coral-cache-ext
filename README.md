# coral-cache-evolution

A [CORAL](https://github.com/Human-Agent-Society/CORAL) task for evolving Linux
page-cache eviction policies, written as eBPF `cache_ext` struct_ops programs,
against a GET-SCAN LevelDB workload. An autonomous Claude Code agent edits one
policy file; a grader compiles it on a CloudLab node, runs the benchmark under
the policy, and scores it.

The repo is **self-contained**: everything the task uses is in this directory
(the `cache_ext` project comes in as a git submodule).

Status and open items: `TODO.md`. Operational runbook: `how-to-run.md`.

## Topology

CORAL's manager, agents and grader subprocess all run on **one host** (the "dev
host", no special kernel needed). Agents only edit a `.c` file. To grade, the
grader ssh-es to a **CloudLab node** that has the booted `6.6.8-cache-ext`
kernel, `clang-14`, `bpftool` and the benchmark stack:

```
dev host:  coral start -> agent edits noop.c -> grader (scoring, calibration stats)
                                                   |  ssh (forced-command key)
node:      node/eval_remote.py: flock -> compile_policy -> attach struct_ops
                                -> get_scan benchmark -> raw probe values (JSON)
```

The grader is deterministic code, not an LLM, so agents cannot tamper with
grading. Scoring happens on the dev host from the probe values the node returns.

**Why SSH instead of running CORAL on the node:** CORAL has no remote-worker
concept, but its grader is just a subprocess, so it can reach out. This keeps the
agent runtime, the LLM gateway and the AWS credentials off the node.

**Security model.** `node/install_remote.sh` installs a dedicated passphrase-less
key as a *forced-command* key: it can only run `node/eval_remote.py` (as root via
`sudo -n`), with no shell, pty or forwarding. Agents run as the same user as
CORAL and could read the private key, but it gives them no shell on the node.
`eval_remote.py` also refuses benchmark paths outside `node/bench/`. Compiling and
attaching an agent-written policy as root is inherent to the task.

**Serialization.** Attaching a struct_ops program is a global, exclusive kernel
slot and `compile_policy()` mutates `cache_ext/policies/` in place, so
`eval_remote.py` holds `/run/evo_cache/eval.lock` (bounded wait) across compile and
all evals of a request. CORAL itself grades serially by default
(`grader.parallel.max_workers: 1`).

## Layout

```
.
├── task.yaml                    CORAL config: task description (the agent's problem
│                                statement), grader args, 1 claude_code agent, gateway :4001
├── litellm_config.yaml          Bedrock model routing for CORAL's LiteLLM gateway
├── seed/
│   ├── noop.c                   starting policy (no-op = the score baseline); the ONLY graded file
│   └── reference/               cache_ext headers + reference policies for the agent to read
├── grader/                      CORAL grader package (runs on the dev host)
│   ├── src/cache_evolution_grader/
│   │   ├── grader.py            calibration + remote call + scoring
│   │   ├── remote.py            ssh client (one retry on connection failure)
│   │   ├── scoring.py           probe specs, weights, stats cache, feedback text
│   │   ├── normalization.py     online z-score + tanh squash
│   │   ├── calibrate.py         pre-calibration CLI
│   │   └── baseline_noop.c      noop baseline used for calibration (not the agent's copy)
│   └── tests/test_scoring.py    local tests (stubbed coral; real eval_remote.py vs stub evaluator)
├── node/                        everything that runs ON the CloudLab node
│   ├── eval_remote.py           request/response server behind the forced command
│   ├── install_remote.sh        dev host: key + rsync repo to node + authorized_keys entry
│   ├── setup_node.sh            on a FRESH node: kernel, toolchain, bench stack
│   ├── evaluator/               compile_policy / evaluate / probes (stdlib only)
│   ├── targets/                 combined-file splitter + compile pipeline
│   ├── policy_lib/evo_dump.h    header staged into policies/ at compile time
│   └── bench/get_scan/          run_with_policy.sh (the benchmark), setup.sh (its build)
├── third_party/cache_ext/       submodule (pinned): policy Makefile + headers, nested vulcan_bpf
└── scripts/sync_reference.sh    regenerates seed/reference/ from the submodule
```

## Scoring

Per eval the node returns raw probe values; the grader scores them against
frozen stats of the `noop` baseline (8 calibration runs, cached locally):

- probes: `throughput` (ops/s from the benchmark's `results.json`, maximize,
  weight **2.0**), `cgroup_iostat` (bytes read, minimize, 0.5), `cgroup_memstat`
  (refaults, minimize, 0.25); wallclock and policy counters are recorded, not scored
- score = weighted mean of `tanh(±z)` per probe, in [-1, 1]; 0 = same as noop
- throughput is scored directly because bytes read alone would reward a policy whose
  throughput regressed
- stats are frozen after calibration and fingerprinted on (probes, weights, ssh
  target + benchmark, baseline source); a mismatch recalibrates automatically

Measurement noise is real: the noop baseline's throughput std is ~2.5%, and a
single eval of an unchanged policy moves the score by roughly ±0.2–0.3. Repeat
evals before trusting small differences.

## Design decisions

- **`agents.count: 1`** for now; multi-agent is a later decision.
- **LiteLLM/Bedrock, not direct Claude auth.** CORAL's gateway (`:4001`) routes the
  agent's calls to AWS Bedrock; CORAL injects `ANTHROPIC_BASE_URL`/key into the
  agent's environment. Usage is billed to the AWS account, not a Claude subscription.
- **One node per CORAL instance.** Struct_ops attach can't be parallelised within a
  kernel; for more throughput run one CORAL instance per node.
- **Paths on the node** derive from where the repo is deployed
  (`/mydata/coral-cache-evolution` by default). The benchmark DB defaults to
  `/mydata/coral_get_scan_db` (override with `DB_DIR`).
