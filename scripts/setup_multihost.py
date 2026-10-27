#!/usr/bin/env python3
"""Prepare a multi-host evolution: one CORAL agent per CloudLab host, each bound to its own host.

    scripts/setup_multihost.sh [--instances cloudlab-instances.md] [--agents N] [--per-host-attempts 20]
                               [--no-deploy] [--no-calibrate] [--dry-run]

Steps (each idempotent):
  1. read the hosts from cloudlab-instances.md and split them into N buckets (N = number of hosts unless --agents)
  2. check every host is reachable and runs the cache-ext kernel
  3. write hosts.json (the buckets + per-host budget) next to task.yaml
  4. update task.yaml: agents.count, grader.parallel.max_workers, grader.args.hosts_file/per_host_budget,
     run.stop.max_real_attempts (= N * per-host attempts); `--tune` evals are refused unless --allow-tune
  5. deploy node/ (and the forced-command eval key) to every host with node/install_remote.sh
  6. if the scoring mode has a calibration step (tanh), pre-calibrate the baseline on every host in parallel
Then start the evolution with:  coral start -c task.yaml
"""
import argparse
import concurrent.futures as cf
import json
import os
import re
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "grader" / "src"))
from cache_evolution_grader import hosts as hostlib  # noqa: E402  (pure python, no coral import)

SSH = ["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=20", "-o", "StrictHostKeyChecking=accept-new"]
MARK = "# multihost-managed"


def log(msg):
    print(f"[setup_multihost] {msg}", flush=True)


def check_host(target):
    r = subprocess.run(SSH + [target, "uname -r"], capture_output=True, text=True, timeout=90)
    kernel = r.stdout.strip()
    if r.returncode != 0:
        return target, False, f"ssh failed: {(r.stderr or '').strip()[-200:]}"
    if "cache-ext" not in kernel:
        return target, False, f"kernel is {kernel!r}, not a cache-ext kernel (run node/setup_node.sh on it first)"
    return target, True, kernel


def deploy(target):
    r = subprocess.run([str(REPO / "node" / "install_remote.sh"), target], capture_output=True, text=True)
    return target, r.returncode == 0, (r.stdout + r.stderr).strip().splitlines()[-1:] if r.returncode else "ok"


def calibrate(target, cfg_args):
    py = Path.home() / ".local/share/uv/tools/coral/bin/python"
    py = str(py) if py.exists() else sys.executable
    env = dict(os.environ, PYTHONPATH=str(REPO / "grader" / "src"))
    stats = cfg_args["stats_path"].replace("{host}", hostlib.host_slug(target))
    cmd = [py, "-m", "cache_evolution_grader.calibrate", f"ssh_target={target}", f"stats_path={stats}"]
    if cfg_args.get("ssh_key"):
        cmd.append(f"ssh_key={cfg_args['ssh_key']}")
    r = subprocess.run(cmd, capture_output=True, text=True, env=env)
    tail = [l for l in r.stdout.splitlines() if "throughput" in l or "stats at" in l]
    return target, r.returncode == 0, (tail[-1] if tail else (r.stderr or r.stdout)[-300:])


def read_arg(text, key, default=None):
    m = re.search(rf"^\s*{key}:\s*(.+?)\s*(?:#.*)?$", text, re.M)
    return m.group(1).strip().strip('"') if m else default


def set_line(text, pattern, new_line, insert_after=None):
    """Replace the first line matching `pattern`, else insert `new_line` after the line matching `insert_after`."""
    if re.search(pattern, text, re.M):
        return re.sub(pattern, lambda m: new_line, text, count=1, flags=re.M)
    if insert_after is None:
        raise SystemExit(f"task.yaml: cannot place {new_line!r}")
    m = re.search(insert_after, text, re.M)
    if not m:
        raise SystemExit(f"task.yaml: anchor {insert_after!r} not found for {new_line!r}")
    return text[:m.end()] + "\n" + new_line + text[m.end():]


def update_task_yaml(path, n_agents, per_host, hosts_file, allow_tune=False):
    t = Path(path).read_text()
    t = set_line(t, r"^  count:.*$", f"  count: {n_agents}  {MARK}", r"^agents:\s*$")
    t = set_line(t, r"^  parallel:.*\n    max_workers:.*$", f"  parallel:  {MARK}\n    max_workers: {n_agents}", r"^  direction: .*$")
    t = set_line(t, r"^    hosts_file:.*$", f"    hosts_file: {hosts_file}  {MARK}", r"^    policy_file:.*$")
    t = set_line(t, r"^    per_host_budget:.*$", f"    per_host_budget: {per_host}  {MARK}", r"^    hosts_file:.*$")
    t = set_line(t, r"^    allow_tune:.*$", f"    allow_tune: {'true' if allow_tune else 'false'}  {MARK}", r"^    per_host_budget:.*$")
    if re.search(r"^    stats_path:", t, re.M):     # only scoring modes with a calibration step have one
        t = set_line(t, r"^    stats_path:.*$", "    stats_path: ~/.cache/cache_evolution_grader/get_scan_noop_stats_{host}.json")
    t = set_line(t, r"^  stop:.*\n    max_real_attempts:.*$", f"  stop:  {MARK}\n    max_real_attempts: {n_agents * per_host}", r"^run:\s*$")
    Path(path).write_text(t)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--instances", default=str(REPO / "cloudlab-instances.md"))
    ap.add_argument("--agents", type=int, help="number of CORAL agents (default: number of hosts)")
    ap.add_argument("--per-host-attempts", type=int, default=20, help="real evaluations each agent may use (default 20)")
    ap.add_argument("--task", default=str(REPO / "task.yaml"))
    ap.add_argument("--allow-tune", action="store_true", help="keep `coral eval --tune` usable (unbudgeted). Default: refuse it, "
                    "so every eval spends the per-host budget and the global attempt cap is reachable")
    ap.add_argument("--no-deploy", action="store_true")
    ap.add_argument("--no-calibrate", action="store_true")
    ap.add_argument("--dry-run", action="store_true", help="print the plan, change nothing")
    a = ap.parse_args()

    hosts = hostlib.parse_instances(Path(a.instances).read_text())
    if not hosts:
        raise SystemExit(f"no `ssh user@host` lines found in {a.instances}")
    n = a.agents or len(hosts)
    buckets = hostlib.split_buckets(hosts, n)
    log(f"{len(hosts)} host(s) -> {n} agent(s)")
    for i, b in enumerate(buckets):
        log(f"  bucket {i}: {', '.join(b)}")
    log(f"per-host budget {a.per_host_attempts} real evals -> run.stop.max_real_attempts = {n * a.per_host_attempts}")
    if a.dry_run:
        return

    with cf.ThreadPoolExecutor(len(hosts)) as ex:
        bad = [(t, why) for t, ok, why in ex.map(check_host, hosts) if not ok]
    if bad:
        for t, why in bad:
            log(f"UNUSABLE {t}: {why}")
        raise SystemExit(1)
    log("all hosts reachable and running a cache-ext kernel")

    hosts_file = REPO / "hosts.json"
    hosts_file.write_text(json.dumps({"per_host_budget": a.per_host_attempts, "buckets": buckets}, indent=1) + "\n")
    update_task_yaml(a.task, n, a.per_host_attempts, str(hosts_file), a.allow_tune)
    log(f"wrote {hosts_file} and updated {a.task}")

    text = Path(a.task).read_text()
    cfg_args = {"stats_path": read_arg(text, "stats_path"), "ssh_key": read_arg(text, "ssh_key")}
    if not cfg_args["stats_path"]:
        a.no_calibrate = True                                # absolute-throughput scoring: nothing to calibrate
        log("task.yaml has no stats_path (no calibration step in this scoring mode)")
    if not a.no_deploy:
        log("deploying node/ to every host ...")
        with cf.ThreadPoolExecutor(len(hosts)) as ex:
            for t, ok, msg in ex.map(deploy, hosts):
                log(f"  {t}: {'deployed' if ok else 'FAILED ' + str(msg)}")
                if not ok:
                    raise SystemExit(1)
    if not a.no_calibrate:
        log("calibrating the no-op baseline on every host in parallel (about 8 evals each) ...")
        with cf.ThreadPoolExecutor(len(hosts)) as ex:
            res = list(ex.map(lambda t: calibrate(t, cfg_args), hosts))
        for t, ok, msg in res:
            log(f"  {t}: {'ok' if ok else 'FAILED'} {msg}")
        if not all(ok for _, ok, _ in res):
            raise SystemExit("calibration failed on at least one host (see above)")
    log("ready. Start the evolution with:  source ./litellm-creds.sh && coral start -c task.yaml")


if __name__ == "__main__":
    main()
