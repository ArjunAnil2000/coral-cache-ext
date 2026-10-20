# coral-cache-evolution

> **Branch `one-host-one-seed-score-maximize-throughput`:** single-seed experiment, score = absolute throughput (ops/s). S3-FIFO is the only starting policy
> (`seed/noop.c`); no other example policies are provided; 20-attempt bounded run.

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
dev host:  coral start -> agent edits noop.c (S3-FIFO seed) -> grader (score = measured throughput)
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
│   ├── noop.c                   the single seed: S3-FIFO (filename kept for the grader's policy_file);
│   │                            the ONLY graded file
│   └── reference/               cache_ext API headers only (no example policies)
├── grader/                      CORAL grader package (runs on the dev host)
│   ├── src/cache_evolution_grader/
│   │   ├── grader.py            one remote eval -> score = measured throughput (ops/s)
│   │   ├── remote.py            ssh client (one retry on connection failure)
│   │   └── scoring.py           throughput probe spec, required-probe check, feedback text
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
└── scripts/sync_reference.sh    refreshes the cache_ext API headers in seed/reference/ from the submodule
```

## Scoring

**The score is the absolute throughput, in operations per second, that the benchmark
measured while the submitted policy was attached. The agent maximizes it.** There is no
baseline calibration, z-score, `tanh` squash or weighting: the grader returns the
`throughput_ops_per_sec` number the benchmark wrote to `results.json`, unmodified.

- one attempt = one remote eval (compile, attach, ~30 s measured phase after a warmup)
- the other probes (bytes read, refaults, wallclock) are listed in the feedback text for
  diagnosis but do not affect the score. A missing or non-positive throughput fails the
  attempt instead of scoring 0
- the unmodified S3-FIFO seed has no recorded baseline on this branch yet; the old no-op policy measured about 1210-1225 ops/s on the node

Measurement noise is real: repeated evals of identical code differ by roughly 1-2%
(occasionally much more: one re-submission of code that had measured about 1259 ops/s
twice came out at 1165), so single evals can't distinguish small gains. Repeat evals
(e.g. 8) before comparing policies.

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
