#!/usr/bin/env python3.11
"""Node-side evaluator for the CORAL grader's SSH backend.

Runs ON the CloudLab node (as root, via `sudo -n`), invoked over ssh by
grader/src/cache_evolution_grader/remote.py. Reads ONE JSON request on stdin,
writes ONE JSON response on stdout (everything else goes to stderr), so a
forced-command ssh key (see remote/install_remote.sh) can only ever do this.

Request:
  {
    "policy_src":       "<combined BPF+loader .c>",
    "runs":             1,                   # evals of the same compiled binary
    "benchmark":        "bench/get_scan/run_with_policy.sh",  # relative to this directory (node/)
    "probes":           [ {json_extract spec}, ... ],        # added to DEFAULT_PROBES
    "weights":          {probe: weight},
    "eval_timeout":     180,
    "lock_wait":        600
  }

Response:
  {"status": "ok",      "compile": {"ok": bool, "error": str, "stderr_tail": str},
                        "results": [EvaluationResult.to_dict(), ...]}   # [] if compile failed
  {"status": "busy",    "error": "..."}      # eval lock not acquired within lock_wait
  {"status": "error",   "error": "..."}      # bad request / internal error

Serialization: struct_ops attach is global and exclusive and compile_policy()
mutates cache_ext/policies/ in place, so compile + all `runs` evals happen
under one flock.

Raw scores from evaluate() are NOT used; the grader scores locally from the
returned probe values.
"""

import fcntl
import json
import os
import signal
import sys
import time
import traceback
from pathlib import Path

# Everything is located relative to this file: <repo>/node/eval_remote.py, with
# the vendored evaluator in node/evaluator, harnesses in node/bench, and the
# cache_ext submodule in <repo>/third_party/cache_ext. Env overrides are for tests.
NODE_DIR = Path(os.environ.get("EVO_NODE_DIR") or Path(__file__).resolve().parent)
REPO_ROOT = NODE_DIR.parent
CACHE_EXT_DIR = Path(os.environ.get("EVO_CACHE_EXT_DIR") or REPO_ROOT / "third_party" / "cache_ext")
CGROUP_PATH = os.environ.get("CACHE_EXT_CGROUP", "/sys/fs/cgroup/cache_ext_evo_bench")
LOCK_PATH = os.environ.get("EVO_LOCK_PATH", "/run/evo_cache/eval.lock")

# Keep the protocol channel clean: anything the evaluator/compiler prints to
# stdout must not corrupt the JSON response.
_RESPONSE_FD = os.dup(1)
os.dup2(2, 1)


def respond(obj):
    data = (json.dumps(obj, default=str) + "\n").encode()
    os.write(_RESPONSE_FD, data)


def _on_signal(signum, _frame):
    # ssh dropped (SIGHUP) or grader timed out (SIGTERM): unwind so
    # evaluate()'s `finally` cleanup detaches the policy and kills the loader.
    raise SystemExit(128 + signum)


for _sig in (signal.SIGHUP, signal.SIGTERM, signal.SIGINT):
    signal.signal(_sig, _on_signal)


def acquire_lock(wait):
    os.makedirs(os.path.dirname(LOCK_PATH), exist_ok=True)
    fd = open(LOCK_PATH, "w")
    deadline = time.monotonic() + wait
    while True:
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            return fd
        except OSError:
            if time.monotonic() >= deadline:
                fd.close()
                return None
            time.sleep(1.0)


def resolve_benchmark(rel):
    """Only benchmarks inside node/bench are runnable: the ssh key must not be
    a general root-exec primitive beyond 'compile+run a policy'."""
    root = (NODE_DIR / "bench").resolve()
    p = (NODE_DIR / rel).resolve()
    if root not in p.parents or not p.is_file():
        raise ValueError(f"benchmark {rel!r} is not a file under {root}")
    return str(p)


def build_probes(specs):
    from evaluator import DEFAULT_PROBES, JsonExtractProbe

    probes = list(DEFAULT_PROBES)
    for s in specs:
        kind = (s.get("type") or "").lower()
        if kind not in ("json_extract", "json"):
            raise ValueError(f"unknown probe type {kind!r}")
        probes.append(
            JsonExtractProbe(
                name=s["name"],
                results_path=s["results_file"],
                json_path=s["json_path"],
                direction=s.get("direction", "maximize"),
                unit=s.get("unit", ""),
            )
        )
    return probes


def handle(req):
    sys.path.insert(0, str(NODE_DIR))
    from evaluator import compile_policy, evaluate

    benchmark = resolve_benchmark(req["benchmark"])
    source_dir = str(CACHE_EXT_DIR)
    policies_dir = os.path.join(source_dir, "policies")
    runs = max(1, int(req.get("runs", 1)))
    eval_timeout = int(req.get("eval_timeout", 180))
    weights = {k: float(v) for k, v in (req.get("weights") or {}).items()}

    lock = acquire_lock(int(req.get("lock_wait", 600)))
    if lock is None:
        return {"status": "busy", "error": f"eval lock {LOCK_PATH} not acquired within {req.get('lock_wait', 600)}s"}
    try:
        compiled = compile_policy(req["policy_src"], policies_dir)
        comp = {
            "ok": bool(compiled.ok),
            "error": compiled.error or "",
            "stderr_tail": (compiled.stderr_tail or "")[-3000:],
        }
        if not compiled.ok:
            return {"status": "ok", "compile": comp, "results": []}
        results = []
        for _ in range(runs):
            res = evaluate(
                compiled.binary_path,
                benchmark,
                timeout=eval_timeout,
                cwd=source_dir,
                cgroup_path=CGROUP_PATH,
                probes=build_probes(req.get("probes") or []),
                weights=weights,
            )
            results.append(res.to_dict())
        return {"status": "ok", "compile": comp, "results": results}
    finally:
        lock.close()  # releases the flock


def main():
    try:
        req = json.loads(sys.stdin.read())
        respond(handle(req))
    except SystemExit:
        raise
    except Exception as e:
        traceback.print_exc()
        respond({"status": "error", "error": f"{type(e).__name__}: {e}"})


if __name__ == "__main__":
    main()
