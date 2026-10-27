"""Multi-host support: which CloudLab node an agent evaluates on, and its per-host attempt budget.

`scripts/setup_multihost.sh` splits cloudlab-instances.md into buckets (one per agent) and writes
`hosts.json`:

    {"per_host_budget": 20, "buckets": [["aanil3@pc306.emulab.net"], ["aanil3@pc309.emulab.net"], ...]}

At grade time the grader binds each agent to one bucket (first agent to submit claims the first free
bucket; the claim is stored under .coral/private and so lasts for the run) and evaluates only on that
bucket's hosts. Different agents therefore never use the same node, which also keeps the node-side
eval lock uncontended.
"""

import fcntl
import json
import os
import re
from pathlib import Path

HOST_LINE = re.compile(r"^\s*(?:ssh\s+)?([A-Za-z0-9._-]+@[A-Za-z0-9._-]+)\s*$")


def parse_instances(text):
    """Hosts from cloudlab-instances.md: lines like `ssh user@host` or `user@host`; `#`/markdown lines ignored."""
    hosts = []
    for line in text.splitlines():
        m = HOST_LINE.match(line)
        if m and m.group(1) not in hosts:
            hosts.append(m.group(1))
    return hosts


def split_buckets(hosts, n_agents):
    """Round-robin hosts into n_agents non-empty buckets (host i -> bucket i % n_agents)."""
    if n_agents < 1:
        raise ValueError("need at least one agent")
    if n_agents > len(hosts):
        raise ValueError(f"{n_agents} agents but only {len(hosts)} host(s): an agent needs a host of its own")
    buckets = [[] for _ in range(n_agents)]
    for i, h in enumerate(hosts):
        buckets[i % n_agents].append(h)
    return buckets


def load_hosts_file(path):
    d = json.loads(Path(path).read_text())
    buckets = d["buckets"]
    if not buckets or any(not b for b in buckets):
        raise ValueError(f"{path}: every bucket needs at least one host")
    seen = [h for b in buckets for h in b]
    if len(seen) != len(set(seen)):
        raise ValueError(f"{path}: a host appears in more than one bucket")
    return buckets, int(d.get("per_host_budget") or 0)


def claim_bucket(claims_path, agent_id, n_buckets):
    """Index of the bucket bound to agent_id, claiming the lowest free one on first sight (flock-guarded)."""
    claims_path = Path(claims_path)
    claims_path.parent.mkdir(parents=True, exist_ok=True)
    with open(str(claims_path) + ".lock", "w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        claims = json.loads(claims_path.read_text()) if claims_path.exists() else {}
        if agent_id not in claims:
            free = [i for i in range(n_buckets) if i not in claims.values()]
            if not free:
                raise RuntimeError(
                    f"agent {agent_id!r} has no host bucket: all {n_buckets} are claimed by {sorted(claims)}. "
                    "Re-run scripts/setup_multihost.sh so agents.count matches the number of buckets."
                )
            claims[agent_id] = free[0]
            tmp = str(claims_path) + ".tmp"
            Path(tmp).write_text(json.dumps(claims, indent=1))
            os.replace(tmp, claims_path)
        return claims[agent_id]


def real_attempts_used(attempts_dir, agent_id, exclude_hash=None):
    """Finalized real (budget-counted) attempts this agent has made. grader_error and tune attempts do not count."""
    n = 0
    for f in Path(attempts_dir).glob("*.json"):
        try:
            d = json.loads(f.read_text())
        except (OSError, ValueError):
            continue
        if d.get("agent_id") != agent_id or d.get("commit_hash") == exclude_hash:
            continue
        if (d.get("metadata") or {}).get("budget_class") == "real":
            n += 1
    return n


def host_slug(target):
    """`aanil3@pc306.emulab.net` -> `pc306` (used in per-host stats file names)."""
    return target.split("@")[-1].split(".")[0]
