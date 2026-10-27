"""CORAL grader for cache_ext policy evolution on the get_scan workload.

Topology: CORAL (manager, agents, THIS grader subprocess) runs on a dev host
with no special kernel. Agents only edit the policy .c file. To grade, this
grader ssh-es to a CloudLab node (remote.py -> remote/eval_remote.py), which
compiles the policy, attaches it via BPF struct_ops, runs the cgroup-isolated
get_scan benchmark, and returns the raw probe values. Scoring happens HERE.

Scoring for the get_scan workload: probes = evaluator DEFAULT_PROBES + a `throughput` json_extract
probe (results.json -> throughput_ops_per_sec, maximize); weights
throughput=2.0, cgroup_iostat=0.5, cgroup_memstat=0.25; each probe is
z-scored against frozen stats from the `noop` baseline, tanh-squashed, and
combined as a weighted mean. The node's raw `score` is ignored.

All knobs live in task.yaml `grader.args` (see DEFAULTS below).

Calibration: the noop baseline stats are computed lazily on the first grade
(or ahead of time with `python -m cache_evolution_grader.calibrate`) by one
remote call that compiles baseline_noop.c once and runs it `calibrate_runs`
times, and are cached as JSON at `stats_path` (local to this host). The file
carries a fingerprint of (probe specs, weights, benchmark, ssh target,
baseline source); a mismatch triggers recalibration. Stats are then frozen
(never updated by graded policies), matching update_during_evolution = false.

Serialization: the node holds the exclusive eval flock (struct_ops slot,
shared cache_ext/policies/), so concurrent grader subprocesses just queue
there. A local flock only prevents two graders calibrating at once.

Timeout budget (task.yaml grader.timeout must exceed all of this):
  lock_wait + compile + eval_timeout (+ calibrate_runs * eval_timeout on the
  very first grade if not pre-calibrated), see remote.total_timeout().
"""

import fcntl
import os
import time
from pathlib import Path

from coral.grader import TaskGrader

from cache_evolution_grader import hosts as hostlib, remote, scoring
from cache_evolution_grader.normalization import NormalizationState, extract_raw_values

BASELINE_SOURCE = Path(__file__).with_name("baseline_noop.c")

DEFAULTS = {
    "policy_file": "noop.c",
    # --- ssh backend ---
    "ssh_target": None,              # single-host mode, e.g. "evo-eval@c220g1-030815.wisc.cloudlab.us"
    "hosts_file": None,              # multi-host mode: hosts.json from scripts/setup_multihost.sh (overrides ssh_target)
    "per_host_budget": 0,            # multi-host: real evals allowed per agent/host (0 = unlimited); from hosts.json if unset
    "allow_tune": True,              # multi-host: False refuses `coral eval --tune` (no host time used) so every eval spends the budget
    "ssh_key": None,                 # path to the (forced-command) private key; None = ssh default
    "ssh_options": [],               # extra ssh args, e.g. ["-p", "2222"]
    "ssh_connect_timeout": 15,
    "remote_command": "sudo -n env PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin "
                      "python3.11 /mydata/coral-cache-evolution/node/eval_remote.py",
    # --- benchmark / scoring ---
    "benchmark": "bench/get_scan/run_with_policy.sh",   # relative to node/ in the deployed repo
    "eval_timeout": 180,             # per-eval timeout (s)
    "calibrate_runs": 8,             # noop baseline runs for the z-score stats
    "min_n": 2,
    "squash": "tanh",
    "lock_wait": 600,                # node-side eval-lock wait
    "stats_path": "~/.cache/cache_evolution_grader/get_scan_noop_stats.json",   # "{host}" is replaced by the node's short name
    "weights": scoring.DEFAULT_WEIGHTS,
    "probes": scoring.DEFAULT_PROBE_SPECS,
    "required_probes": ["throughput"],
}


def load_config(args):
    cfg = dict(DEFAULTS)
    cfg.update({k: v for k, v in (args or {}).items() if v is not None})
    if not cfg["ssh_target"] and not cfg["hosts_file"]:
        raise ValueError("grader.args.ssh_target (single host) or grader.args.hosts_file (multi-host) is required")
    cfg["weights"] = {k: float(v) for k, v in cfg["weights"].items()}
    for k in ("eval_timeout", "calibrate_runs", "min_n", "lock_wait", "ssh_connect_timeout", "per_host_budget"):
        cfg[k] = int(cfg[k])
    cfg["stats_path"] = os.path.expanduser(cfg["stats_path"])
    if cfg["hosts_file"]:
        cfg["hosts_file"] = os.path.expanduser(cfg["hosts_file"])
    if cfg["ssh_key"]:
        cfg["ssh_key"] = os.path.expanduser(cfg["ssh_key"])
    return cfg


class LockTimeout(Exception):
    pass


class LocalLock:
    """Cross-process flock with a bounded wait (only guards local calibration)."""

    def __init__(self, path, wait=600):
        self.path, self.wait, self.fd = path, wait, None

    def __enter__(self):
        os.makedirs(os.path.dirname(os.path.abspath(self.path)), exist_ok=True)
        self.fd = open(self.path, "w")
        deadline = time.monotonic() + self.wait
        while True:
            try:
                fcntl.flock(self.fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                return self
            except OSError:
                if time.monotonic() >= deadline:
                    self.fd.close()
                    raise LockTimeout(f"could not acquire {self.path} within {self.wait}s")
                time.sleep(1.0)

    def __exit__(self, *exc):
        try:
            fcntl.flock(self.fd, fcntl.LOCK_UN)
        finally:
            self.fd.close()


def calibration_fingerprint(cfg, baseline_src):
    return scoring.fingerprint(
        cfg["probes"], cfg["weights"], f"{cfg['ssh_target']}:{cfg['benchmark']}", baseline_src
    )


def ensure_calibration(cfg, run_remote=None, now=time.time):
    """Return (NormalizationState, meta) for the noop baseline.

    Raises RuntimeError with a human-readable message on failure. Callers
    should hold LocalLock(stats_path + '.lock') so two graders don't both
    calibrate.
    """
    run_remote = run_remote or remote.run_remote
    baseline_src = BASELINE_SOURCE.read_text()
    fp = calibration_fingerprint(cfg, baseline_src)
    cached = scoring.load_stats(cfg["stats_path"], fp)
    if cached is not None:
        return cached

    try:
        compiled, results = run_remote(cfg, baseline_src, runs=cfg["calibrate_runs"])
    except (remote.RemoteError, remote.RemoteBusy) as e:
        raise RuntimeError(f"calibration: {e}")
    if not compiled.ok:
        raise RuntimeError(f"calibration: noop baseline failed to compile: {compiled.error} {compiled.stderr_tail[-400:]}")

    state = NormalizationState(squash=cfg["squash"], min_n=cfg["min_n"])
    errors, ok = [], 0
    for i, res in enumerate(results):
        if not res.ok:
            errors.append(f"run {i}: {res.error}")
            continue
        bad = scoring.invalid_required_probes(res.probes, cfg["required_probes"])
        if bad:
            errors.append(f"run {i}: invalid probe(s) {bad}")
            continue
        state.update(extract_raw_values(res.probes))
        ok += 1
    if ok < cfg["min_n"]:
        raise RuntimeError(
            f"calibration: only {ok}/{cfg['calibrate_runs']} noop runs succeeded "
            f"(need >= {cfg['min_n']}); errors: {errors[:3]}"
        )
    meta = {"successes": ok, "attempted": cfg["calibrate_runs"], "timestamp": int(now()), "errors": errors}
    scoring.save_stats(cfg["stats_path"], fp, state, meta)
    return state, meta


def bind_host(cfg, coral_root, agent_id, commit_hash, tune):
    """Multi-host mode: pick this agent's node and enforce its real-eval budget.

    Returns (cfg for that node, note for the feedback). Single-host mode (no hosts_file) returns cfg unchanged.
    Raises RuntimeError when the agent's budget is spent; CORAL records that as a grader error, which does
    not count toward run.stop.max_real_attempts.
    """
    if not cfg["hosts_file"]:
        return cfg, ""
    if tune and not cfg["allow_tune"]:
        raise RuntimeError(
            "`--tune` evals are disabled in this run: every evaluation spends one of your per-host real "
            "evaluations. Resubmit without --tune (and think before submitting; there is no free sweep)."
        )
    buckets, file_budget = hostlib.load_hosts_file(cfg["hosts_file"])
    budget = cfg["per_host_budget"] or file_budget
    agent = agent_id or "validate"
    idx = hostlib.claim_bucket(Path(coral_root) / "private" / "host_claims.json", agent, len(buckets))
    attempts_dir = Path(coral_root) / "public" / "attempts"
    used = hostlib.real_attempts_used(attempts_dir, agent, exclude_hash=commit_hash)
    if budget and not tune and used >= budget:
        raise RuntimeError(
            f"Host budget exhausted: agent {agent} already used {used}/{budget} real evaluations on "
            f"{buckets[idx][0]}. No further evals are allowed for this agent. Write up your final notes, then do NOT "
            "end the session early: the run only stops when every agent has spent its budget, and a quickly ending "
            "session is restarted at a cost. Run `sleep 540` (one command per turn, repeated) until the run is stopped."
        )
    bucket = buckets[idx]
    target = bucket[used % len(bucket)]
    out = dict(cfg)
    out["ssh_target"] = target
    if cfg.get("stats_path"):            # scoring modes with a calibration step keep one stats file per node
        out["stats_path"] = cfg["stats_path"].replace("{host}", hostlib.host_slug(target))
    left = f", {budget - used - 1} left after this one" if budget and not tune else ""
    note = f"Host: {hostlib.host_slug(target)} (dedicated to agent {agent}). Real eval {used + 1}/{budget}{left}." \
        if budget and not tune else f"Host: {hostlib.host_slug(target)} (dedicated to agent {agent})."
    return out, note


class Grader(TaskGrader):
    def evaluate(self):
        try:
            cfg = load_config(self.args)
        except Exception as e:
            return self.fail(f"grader setup error: {e}")

        host_note = ""
        if cfg["hosts_file"]:
            tasks = getattr(self, "tasks", None) or []
            meta_ = (tasks[0].metadata if tasks else None) or {}
            cfg, host_note = bind_host(cfg, Path(self.private_dir).parent, meta_.get("agent_id"),
                                       meta_.get("commit_hash") or Path(self.codebase_path).name, self.tune)

        try:
            policy_src = (Path(self.codebase_path) / cfg["policy_file"]).read_text()
        except OSError as e:
            return self.fail(f"cannot read policy file {cfg['policy_file']}: {e}")

        try:
            with LocalLock(cfg["stats_path"] + ".lock", wait=cfg["lock_wait"]):
                try:
                    state, meta = ensure_calibration(cfg)
                except Exception as e:
                    return self.fail(f"grader calibration error (not your policy's fault): {e}")
            compiled, results = remote.run_remote(cfg, policy_src, runs=1)
        except LockTimeout as e:
            return self.fail(f"grader busy: {e}; resubmit")
        except remote.RemoteBusy as e:
            return self.fail(f"eval node busy: {e}; resubmit")
        except remote.RemoteError as e:
            return self.fail(f"grader infrastructure error (not your policy's fault; resubmit): {e}")
        except Exception as e:
            return self.fail(f"grader internal error: {type(e).__name__}: {e}")

        if not compiled.ok:
            return self.fail(f"compile failed: {compiled.error}\n{compiled.stderr_tail}")
        result = results[0]
        if not result.ok:
            return self.fail(result.feedback_text())

        bad = scoring.invalid_required_probes(result.probes, cfg["required_probes"])
        if bad:
            return self.fail(
                "benchmark ran but required probe(s) produced no value: "
                + "; ".join(bad)
                + "\n"
                + result.feedback_text()
            )

        scored = state.score(result.probes, cfg["weights"])
        if not scored["components"]:
            return self.fail(
                "no probe could be normalized (baseline stddev 0 or n too small); "
                "grader calibration is degenerate.\n" + result.feedback_text()
            )
        feedback = scoring.format_feedback(scored, result.probes, result.wallclock_sec, meta)
        if host_note:
            feedback = f"{feedback}\n{host_note}"
        return self.score(scored["score"], feedback)
