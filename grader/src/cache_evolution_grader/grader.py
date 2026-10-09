"""CORAL grader for cache_ext policy evolution on the get_scan workload.

Score: the ABSOLUTE throughput, in operations per second, that the benchmark measured
while the submitted policy was attached (higher is better; CORAL maximizes it). There is
no baseline calibration, z-score, `tanh` squash or weighting: the number returned is the
`throughput_ops_per_sec` the benchmark wrote. The other probes (bytes read, refaults,
wallclock) are included in the feedback text for diagnosis only.

Topology: CORAL (manager, agents, THIS grader subprocess) runs on a dev host with no
special kernel. Agents only edit the policy .c file. To grade, this grader ssh-es to a
CloudLab node (remote.py -> node/eval_remote.py), which compiles the policy, attaches it
via BPF struct_ops, runs the cgroup-isolated get_scan benchmark once, and returns the raw
probe values. The grader reads the throughput probe and returns it as the score.

Serialization: the node holds the exclusive eval flock (struct_ops slot, shared
cache_ext/policies/), so concurrent grader subprocesses just queue there.

All knobs live in task.yaml `grader.args` (see DEFAULTS below).

Timeout budget (task.yaml grader.timeout must exceed all of this):
  lock_wait + compile + eval_timeout, see remote.total_timeout().
"""

import math
from pathlib import Path

from coral.grader import TaskGrader

from cache_evolution_grader import remote, scoring

DEFAULTS = {
    "policy_file": "noop.c",
    # --- ssh backend ---
    "ssh_target": None,              # REQUIRED, e.g. "evo-eval@c220g1-030815.wisc.cloudlab.us"
    "ssh_key": None,                 # path to the (forced-command) private key; None = ssh default
    "ssh_options": [],               # extra ssh args, e.g. ["-p", "2222"]
    "ssh_connect_timeout": 15,
    "remote_command": "sudo -n env PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin "
                      "python3.11 /mydata/coral-cache-evolution/node/eval_remote.py",
    # --- benchmark ---
    "benchmark": "bench/get_scan/run_with_policy.sh",   # relative to node/ in the deployed repo
    "eval_timeout": 180,             # per-eval timeout (s)
    "lock_wait": 600,                # node-side eval-lock wait (s)
    "probes": scoring.DEFAULT_PROBE_SPECS,
    "required_probes": [scoring.SCORE_PROBE],
}


def load_config(args):
    cfg = dict(DEFAULTS)
    cfg.update({k: v for k, v in (args or {}).items() if v is not None})
    if not cfg["ssh_target"]:
        raise ValueError("grader.args.ssh_target is required (e.g. user@host of the CloudLab node)")
    for k in ("eval_timeout", "lock_wait", "ssh_connect_timeout"):
        cfg[k] = int(cfg[k])
    if cfg["ssh_key"]:
        import os
        cfg["ssh_key"] = os.path.expanduser(cfg["ssh_key"])
    if scoring.SCORE_PROBE not in cfg["required_probes"]:
        cfg["required_probes"] = list(cfg["required_probes"]) + [scoring.SCORE_PROBE]
    return cfg


class Grader(TaskGrader):
    def evaluate(self):
        try:
            cfg = load_config(self.args)
        except Exception as e:
            return self.fail(f"grader setup error: {e}")

        try:
            policy_src = (Path(self.codebase_path) / cfg["policy_file"]).read_text()
        except OSError as e:
            return self.fail(f"cannot read policy file {cfg['policy_file']}: {e}")

        try:
            compiled, results = remote.run_remote(cfg, policy_src, runs=1)
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

        throughput = float(result.probes[scoring.SCORE_PROBE]["value"])
        if not math.isfinite(throughput) or throughput <= 0:
            return self.fail(
                f"throughput probe returned {throughput!r} (benchmark produced no usable result)\n"
                + result.feedback_text()
            )
        return self.score(throughput, scoring.format_feedback(result.probes, result.wallclock_sec))
