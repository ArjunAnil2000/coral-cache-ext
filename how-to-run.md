# How to run

Operational runbook for launching the dry-plumbing CORAL run. For why things
are structured this way, see `README.md`; for open items / status, see
`TODO.md`. This assumes the CloudLab node is reachable — if `ssh
aanil3@<host>` times out or is refused, stop here and see `TODO.md`'s
"Blocked on" section first.

## Prerequisites (on the CloudLab node)

- The existing `mem-evolve` checkout at its usual path (default assumed
  below: `/mydata/evo_cache/cache_policy_evolution`), with the
  `6.6.8-cache-ext` kernel already booted, `clang-14`/`bpftool` installed,
  and `setup_isolation.sh` already run (so `cache_ext_bench` cgroup
  exists). This run does not redo any of `mem-evolve/setup_cloudlab.sh` —
  if that hasn't been done yet, do it first.
- Python 3.11+ and `uv` on the node (`coral`'s install script and the
  grader's `setup` step both use `uv`).
- `kernel.bpf_stats_enabled` is not required for this dry run (that's only
  for the throughput-exp profiling work), but doesn't hurt if already set.

## 1. Get this repo onto the node

From the dev machine:

```bash
# option A: push to a remote git host, then clone on the node
cd /home/aanil/Desktop/ldos/arjua-forks/coral-cache-evolution
git remote add origin <your-remote-url>
git push -u origin master
ssh aanil3@<host> "git clone <your-remote-url> /mydata/evo_cache/coral-cache-evolution"

# option B: copy directly, no remote needed
rsync -av --exclude=.git \
  /home/aanil/Desktop/ldos/arjua-forks/coral-cache-evolution/ \
  aanil3@<host>:/mydata/evo_cache/coral-cache-evolution/
```

Everything below runs **on the node**, from
`/mydata/evo_cache/coral-cache-evolution/` (adjust the path if you put it
somewhere else).

## 2. Install the CORAL CLI

```bash
curl -fsSL https://raw.githubusercontent.com/Human-Agent-Society/CORAL/main/install.sh | sh
coral --version   # sanity check
```

## 3. Fill in the Bedrock model id

Open `litellm_config.yaml` and replace the placeholder:

```yaml
model_list:
  - model_name: "claude-sonnet"
    litellm_params:
      model: "bedrock/anthropic.claude-sonnet-TODO"   # <- replace this
```

Confirm the exact model id string against whatever `mem-evolve`'s existing
litellm proxy config on this node already uses (same model the old
`[llm.mutator]` TOML blocks point at under the `claude-sonnet` alias).

## 4. Export Bedrock credentials

```bash
cd /mydata/evo_cache/cache_policy_evolution/..   # wherever mem-evolve lives on the node
source mem-evolve/litellm-creds.sh
```

This needs to export `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`, and
`AWS_DEFAULT_REGION` for `litellm_config.yaml`'s `os.environ/...`
references to resolve. The dev-machine copy of this file only had
`AWS_ACCESS_KEY_ID` — if the node's copy is similarly incomplete, add the
missing exports there (don't commit them to this repo).

## 5. Confirm `MEM_EVOLVE_ROOT`

```bash
export MEM_EVOLVE_ROOT=/mydata/evo_cache/cache_policy_evolution   # only if it differs from the default
```

The grader (`grader/src/cache_evolution_grader/grader.py`) defaults to this
path already — only set the env var if the node's actual layout differs.

## 6. Launch

```bash
cd /mydata/evo_cache/coral-cache-evolution
coral start -c task.yaml
```

This will:
- run `grader`'s `setup` step (`uv pip install -e ./grader`) to install the
  grader package into CORAL's isolated grader venv,
- start CORAL's LiteLLM gateway on port 4001 using `litellm_config.yaml`,
- spin up 1 Claude Code agent in its own git worktree of `seed/`,
- let the agent make at least one edit/commit,
- run the grader subprocess (`compile_policy()` → `evaluate()` under the
  `fcntl.flock` eval lock) against the real kernel and benchmark cgroup,
- record the result under `.coral/public/attempts/`.

## 7. Verify it worked

```bash
# the attempt record should exist with a score + feedback text
ls .coral/public/attempts/
cat .coral/public/attempts/<latest>.json   # or whatever extension CORAL uses

# confirm the agent actually edited seed/ and committed
git -C <agent-worktree-path> log --oneline   # worktree path is printed by `coral start`

# confirm the gateway, not a direct Anthropic key, backed the model calls
curl -s localhost:4001/health
env | grep ANTHROPIC_API_KEY   # should be unset/unused for this run

# confirm no collision with the old coordinator's proxy
ss -tlnp | grep ':4000\|:4001'
```

If the grader step fails, check:
- `compile_policy()` errors — usually a stale `cache_ext/policies/`
  checkout or a clang version mismatch.
- `evaluate()` timing out or failing to attach — check whether another
  process (e.g. a leftover old-coordinator run) already holds the
  struct_ops slot or the `/run/evo_cache/eval.lock` file lock.

## Stopping / cleaning up

```bash
# Ctrl-C the coral start process, or:
coral stop   # if a subcommand for this exists — check `coral --help`
```

Check `/run/evo_cache/eval.lock` and the BPF struct_ops attachment are
released after a run (`bpftool struct_ops show`) before starting another
one — a stuck lock or lingering attachment from a crashed run will block
the next `coral start`.
