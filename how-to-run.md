# How to run

Operational runbook. Design: `README.md`. Status and open items: `TODO.md`.
Everything runs on the **dev host** (this machine) except what
`node/eval_remote.py` does on the CloudLab node. This repo is self-contained;
nothing outside it is needed except the node's OS-level toolchain.

## Prerequisites

**Dev host**
- `coral` CLI. It needs Python 3.11-3.13; on a 3.14-only machine:
  ```bash
  curl -LsSf https://astral.sh/uv/install.sh | sh        # if uv is missing
  uv python install 3.12
  uv tool install --force --python 3.12 git+https://github.com/Human-Agent-Society/CORAL.git
  export PATH="$HOME/.local/bin:$PATH"
  ```
- `claude` (Claude Code CLI) for the `claude_code` agent runtime, plus `ssh` and `rsync`.
- Submodules initialised (do NOT use `--recursive`: cache_ext nests a kernel tree):
  ```bash
  git submodule update --init third_party/cache_ext
  git -C third_party/cache_ext submodule update --init vulcan_bpf
  ```
- AWS Bedrock credentials in `./litellm-creds.sh` (gitignored; exports
  `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`, `AWS_DEFAULT_REGION`).

**CloudLab node** (hostname in `cloudlab-instances.md`, gitignored; set it in
`task.yaml` `grader.args.ssh_target`)
- Either a node that already has the `6.6.8-cache-ext+` kernel, `clang-14`,
  `bpftool`, libbpf and `python3.11` (go to step 1), or a fresh one (step 0).

## 0. Fresh node only: provision it

```bash
./node/install_remote.sh <user@host>             # deploys the repo to /mydata/coral-cache-evolution
ssh <user@host> /mydata/coral-cache-evolution/node/setup_node.sh          # kernel install + reboot
# after the reboot:
ssh <user@host> /mydata/coral-cache-evolution/node/setup_node.sh --post-reboot
```
(`setup_node.sh` has not been exercised on a fresh node yet; see `TODO.md`.)

## 1. Deploy the SSH backend (every time `node/` or the submodule changes)

```bash
./node/install_remote.sh <user@host>             # idempotent
ssh <user@host> /mydata/coral-cache-evolution/node/bench/get_scan/setup.sh setup   # once per node: builds the benchmark
```
This generates `~/.ssh/coral_eval_ed25519`, rsyncs the repo to the node, and installs
the key as a forced-command key. Set `ssh_target` / `ssh_key` in `task.yaml`.

## 2. Local tests (no node needed)

```bash
python3 -I grader/tests/test_scoring.py
```

## 3. Validate the whole pipeline

```bash
coral validate .       # checks task.yaml, then runs the grader on seed/noop.c
```
The first grade calibrates the `noop` baseline (8 evals, ~6 min) and caches stats at
`~/.cache/cache_evolution_grader/get_scan_noop_stats.json`; the seed should then score ~0.
To calibrate ahead of time (needs the grader's deps, e.g. the `coral` tool venv):
```bash
PYTHONPATH=grader/src ~/.local/share/uv/tools/coral/bin/python -m cache_evolution_grader.calibrate \
  ssh_target=<user@host> ssh_key=~/.ssh/coral_eval_ed25519          # add --force to redo
```

## 4. Run the agent

```bash
source ./litellm-creds.sh
export PATH="$HOME/.local/bin:$PATH"
coral start -c task.yaml run.stop.max_real_attempts=5     # bounded; drop the override for an open-ended run
```
This starts CORAL's gateway on `:4001`, creates a git worktree of `seed/` and launches
one Claude Code agent as a child process of the manager (`run.session: local`; CORAL's
default would wrap it in tmux, ours does not). The agent edits `noop.c` and submits with `coral eval`;
the grader ships it to the node and returns a score plus per-probe feedback. Without
`max_real_attempts` it runs until you stop it.

## 5. Monitor and collect

```bash
coral status          # manager/agent health, attempt counts, best score
coral log             # leaderboard
coral ui              # web dashboard
curl -s localhost:4001/health
pgrep -af 'claude -p'  # the agent process (its cwd is agents/<name>/ in the run dir)
coral stop            # stop a run
```
Run output is under `results/cache-ext-get-scan/<run>/` (gitignored): `.coral/public/attempts/*.json`
(one per attempt, with the score and feedback), `agents/<name>/` (the agent's worktree, a git repo).
To extract a policy: `git -C results/cache-ext-get-scan/<run>/agents/<name> show <commit>:noop.c`.

## After a run: check the node is clean

```bash
ssh <user@host> 'sudo bpftool struct_ops show; sudo fuser /run/evo_cache/eval.lock'   # nothing attached, nobody holding it
```

## Troubleshooting

- `grader infrastructure error ... ssh`: node unreachable or the key isn't installed; rerun step 1.
- `eval node busy`: another eval holds the node's lock (`/run/evo_cache/eval.lock`).
- `compile failed`: the message carries clang's stderr from the node.
- Stats stale after changing probes, weights, baseline or node: automatic (fingerprint); or delete
  the stats file.
- A new node's first eval is slow and not representative: the benchmark DB is created on first use.
- Gateway 400 "Invalid model name": add the requested name as an alias in `litellm_config.yaml`.
