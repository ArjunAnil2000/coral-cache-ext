# How to run

Operational runbook. Design: `README.md`. Status/open items: `TODO.md`.
Everything runs on the **dev host** (this machine) except what `eval_remote.py`
does on the CloudLab node.

## Prerequisites

- Node reachable: `ssh aanil3@<host> true` (host in `cloudlab-instances.md`),
  already provisioned with the cache-ext kernel, `clang-14`, `bpftool`, the
  `cache_ext_evo_bench` cgroup, the get_scan stack, and the mem-evolve checkout
  at `/mydata/evo_cache/` (`setup_node.sh` does this on a fresh node).
- Dev host: `coral` CLI (needs Python 3.11-3.13; on a 3.14-only box:
  `uv python install 3.12 && uv tool install --force --python 3.12 git+https://github.com/Human-Agent-Society/CORAL.git`),
  `claude` CLI for the `claude_code` runtime, `ssh`.

## 1. One-time: install the SSH backend on the node

```bash
./remote/install_remote.sh aanil3@<host>      # key ~/.ssh/coral_eval_ed25519, script, forced command
```
Then set `grader.args.ssh_target` / `ssh_key` in `task.yaml` (already filled for
the current node). Re-run after a node is replaced.

## 2. Tests (no node needed)

```bash
python3 -I grader/tests/test_scoring.py
```

## 3. Bedrock credentials + model id

```bash
source ./litellm-creds.sh      # AWS_ACCESS_KEY_ID / AWS_SECRET_ACCESS_KEY / AWS_DEFAULT_REGION
```
`litellm_config.yaml` maps alias `claude-sonnet` to the Bedrock model id.
**The model id has not been validated yet** (credentials have).

## 4. Pre-calibrate the noop baseline (~8 evals, ~6 min)

```bash
cd grader && PYTHONPATH=src python3 -m cache_evolution_grader.calibrate \
  ssh_target=aanil3@<host> ssh_key=~/.ssh/coral_eval_ed25519     # add --force to redo
```
Needs `coral` importable (use the grader venv) — or just let the first grade do it
(then the grader timeout must cover it; `task.yaml` does).

## 5. Launch

```bash
coral validate -c task.yaml     # runs the grader on the seed
coral start -c task.yaml
```

## 6. Verify

```bash
coral status; coral log
ls .coral/public/attempts/
curl -s localhost:4001/health
```
On the node afterwards: `sudo bpftool struct_ops show` (nothing attached) and
`sudo fuser /run/evo_cache/eval.lock` (nobody holding it).

## Troubleshooting

- `grader infrastructure error ... ssh`: node down/unreachable or key not installed.
- `eval node busy`: another eval (or a stale old-coordinator run) holds the node lock.
- `compile failed`: the message includes clang's stderr from the node.
- Stats stale after changing probes/weights/baseline: automatic (fingerprint);
  after a node move: delete `stats_path` or pass `--force`.
