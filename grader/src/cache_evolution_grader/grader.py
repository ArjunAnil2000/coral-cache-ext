"""CORAL grader for cache_ext policy evolution on the get_scan workload.

Scores the way mem-evolve's coordinator did for get_scan.toml (as changed on
2026-08-13): probes = evaluator DEFAULT_PROBES + a `throughput` json_extract
probe (results.json -> throughput_ops_per_sec, maximize); weights
throughput=2.0, cgroup_iostat=0.5, cgroup_memstat=0.25; each probe is
z-scored against frozen stats from the `noop` baseline, tanh-squashed, and
combined as a weighted mean. `result.score` from evaluator.evaluate() (a raw
unit-less weighted sum) is ignored.

All knobs live in task.yaml `grader.args` (see DEFAULTS below).

Calibration: the noop baseline stats are computed lazily on the first grade
(or ahead of time with `python -m cache_evolution_grader.calibrate`), under
the same flock as grading, and cached as JSON at `stats_path` (default
/run/evo_cache/get_scan_noop_stats.json). The file carries a fingerprint of
(probe specs, weights, benchmark, baseline source); a mismatch triggers
recalibration. /run is tmpfs, so stats are recomputed after a reboot, which
is desirable: they describe the machine's current state. Stats are then
frozen (never updated by graded policies), matching
update_during_evolution = false. To use hand-frozen stats, place a file with
the right fingerprint at stats_path, or point stats_path somewhere durable.

Serialization: BPF struct_ops attach is global/exclusive and compile_policy()
mutates the shared cache_ext/policies/ dir, so compile + eval (and
calibration) happen under a cross-process flock. The lock wait is polled with
a deadline (`lock_wait`) so we return a useful failure instead of being
killed by the CORAL grader timeout.

Timeout budget (task.yaml grader.timeout must exceed all of this):
  lock_wait + compile + eval_timeout (+ calibrate_runs * eval_timeout on the
  very first grade if not pre-calibrated).
"""

import fcntl
import os
import sys
import time
from pathlib import Path

from coral.grader import TaskGrader

from cache_evolution_grader import scoring
from cache_evolution_grader.normalization import NormalizationState, extract_raw_values

MEM_EVOLVE_ROOT = Path(
    os.environ.get("MEM_EVOLVE_ROOT", "/mydata/evo_cache/cache_policy_evolution")
)
LOCK_PATH = "/run/evo_cache/eval.lock"

DEFAULTS = {
    "policy_file": "noop.c",
    "benchmark_script": None,        # -> MEM_EVOLVE_ROOT/eval/get_scan/run_with_policy.sh
    "source_dir": None,              # -> MEM_EVOLVE_ROOT/../cache_ext (benchmark cwd, policies/)
    "baseline_source": None,         # -> MEM_EVOLVE_ROOT/seeds/noop.c
    "eval_timeout": 180,             # get_scan.toml `timeout`
    "calibrate_runs": 8,             # get_scan.toml `calibrate_runs`
    "min_n": 2,
    "squash": "tanh",
    "lock_wait": 600,
    "stats_path": "/run/evo_cache/get_scan_noop_stats.json",
    "weights": scoring.DEFAULT_WEIGHTS,
    "probes": scoring.DEFAULT_PROBE_SPECS,
    "required_probes": ["throughput"],
}


def load_config(args):
    cfg = dict(DEFAULTS)
    cfg.update({k: v for k, v in (args or {}).items() if v is not None})
    cfg["benchmark_script"] = cfg["benchmark_script"] or str(
        MEM_EVOLVE_ROOT / "eval" / "get_scan" / "run_with_policy.sh"
    )
    cfg["source_dir"] = cfg["source_dir"] or str(MEM_EVOLVE_ROOT.parent / "cache_ext")
    cfg["baseline_source"] = cfg["baseline_source"] or str(MEM_EVOLVE_ROOT / "seeds" / "noop.c")
    cfg["weights"] = {k: float(v) for k, v in cfg["weights"].items()}
    cfg["eval_timeout"] = int(cfg["eval_timeout"])
    cfg["calibrate_runs"] = int(cfg["calibrate_runs"])
    cfg["min_n"] = int(cfg["min_n"])
    cfg["lock_wait"] = int(cfg["lock_wait"])
    return cfg


def _load_evaluator():
    if str(MEM_EVOLVE_ROOT) not in sys.path:
        sys.path.insert(0, str(MEM_EVOLVE_ROOT))
    from evaluator import compile_policy, evaluate  # noqa: E402

    return compile_policy, evaluate


class LockTimeout(Exception):
    pass


class EvalLock:
    """Cross-process flock with a bounded wait."""

    def __init__(self, path=LOCK_PATH, wait=600):
        self.path, self.wait, self.fd = path, wait, None

    def __enter__(self):
        os.makedirs(os.path.dirname(self.path), exist_ok=True)
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


def ensure_calibration(cfg, compile_policy=None, evaluate=None, now=time.time):
    """Return (NormalizationState, meta) for the noop baseline.

    MUST be called while holding the eval lock (compiles + runs benchmarks).
    Raises RuntimeError with a human-readable message on failure.
    """
    if compile_policy is None or evaluate is None:
        compile_policy, evaluate = _load_evaluator()
    specs = cfg["probes"]
    baseline_src = Path(cfg["baseline_source"]).read_text()
    fp = scoring.fingerprint(specs, cfg["weights"], cfg["benchmark_script"], baseline_src)
    cached = scoring.load_stats(cfg["stats_path"], fp)
    if cached is not None:
        return cached

    policies_dir = os.path.join(cfg["source_dir"], "policies")
    compiled = compile_policy(baseline_src, policies_dir)
    if not compiled.ok:
        raise RuntimeError(f"calibration: noop baseline failed to compile: {compiled.error}")

    state = NormalizationState(squash=cfg["squash"], min_n=cfg["min_n"])
    errors, ok = [], 0
    for i in range(cfg["calibrate_runs"]):
        res = evaluate(
            compiled.binary_path,
            cfg["benchmark_script"],
            timeout=cfg["eval_timeout"],
            cwd=cfg["source_dir"],
            probes=scoring.build_probes(specs),
            weights=cfg["weights"],
        )
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


class Grader(TaskGrader):
    def evaluate(self):
        try:
            cfg = load_config(self.args)
            compile_policy, evaluate = _load_evaluator()
        except Exception as e:  # bad config / missing MEM_EVOLVE_ROOT
            return self.fail(f"grader setup error (MEM_EVOLVE_ROOT={MEM_EVOLVE_ROOT}): {e}")

        try:
            policy_src = (self.codebase_path / cfg["policy_file"]).read_text()
        except OSError as e:
            return self.fail(f"cannot read policy file {cfg['policy_file']}: {e}")

        policies_dir = os.path.join(cfg["source_dir"], "policies")
        try:
            with EvalLock(wait=cfg["lock_wait"]):
                try:
                    state, meta = ensure_calibration(cfg, compile_policy, evaluate)
                except Exception as e:
                    return self.fail(f"grader calibration error (not your policy's fault): {e}")

                compiled = compile_policy(policy_src, policies_dir)
                if not compiled.ok:
                    return self.fail(f"compile failed: {compiled.error}")

                result = evaluate(
                    compiled.binary_path,
                    cfg["benchmark_script"],
                    timeout=cfg["eval_timeout"],
                    cwd=cfg["source_dir"],
                    probes=scoring.build_probes(cfg["probes"]),
                    weights=cfg["weights"],
                )
        except LockTimeout as e:
            return self.fail(f"grader busy: {e}; resubmit")
        except Exception as e:
            return self.fail(f"grader internal error: {type(e).__name__}: {e}")

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
        return self.score(
            scored["score"], scoring.format_feedback(scored, result.probes, result.wallclock_sec, meta)
        )
