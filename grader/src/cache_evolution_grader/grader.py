"""CORAL grader for the cache_ext policy-evolution dry-plumbing run.

Wraps mem-evolve's standalone `evaluator` package (compile_policy + evaluate)
almost unmodified, per the migration plan in mem-evolve/coral-learnings.md.
This is deliberately the minimal version: no normalization.py scoring, no
real seed set — just prove compile -> BPF struct_ops attach -> cgroup
benchmark -> score works end to end when driven by a CORAL grader
subprocess instead of the old worker_server.py HTTP daemon.

Serialization note: BPF struct_ops attach is a global, exclusive, root-only
kernel operation (one attach slot per kernel), and compile_policy() mutates
the shared cache_ext/policies/ directory in place (see its docstring) — both
must be serialized across concurrent grader subprocesses. The old
worker_server.py used an in-process threading.Lock (_EVAL_LOCK); that doesn't
work across separate grader subprocesses, so this uses a flock-based file
lock instead. With agents.count == 1 today there's no actual concurrency,
but the lock is cheap to keep in place before that changes.
"""

import fcntl
import os
import sys
from pathlib import Path

from coral.grader import TaskGrader

# Root of the existing mem-evolve/cache_policy_evolution checkout on whatever
# host this grader runs on. Override via MEM_EVOLVE_ROOT if the layout
# differs (e.g. CloudLab's documented /mydata/evo_cache/cache_policy_evolution).
MEM_EVOLVE_ROOT = Path(
    os.environ.get(
        "MEM_EVOLVE_ROOT",
        "/mydata/evo_cache/cache_policy_evolution",
    )
)

LOCK_PATH = "/run/evo_cache/eval.lock"


class Grader(TaskGrader):
    def evaluate(self):
        sys.path.insert(0, str(MEM_EVOLVE_ROOT))
        from evaluator import compile_policy, evaluate  # noqa: E402  (path must be set first)

        policy_file = self.args.get("policy_file", "noop.c")
        benchmark_script = self.args.get(
            "benchmark_script",
            str(MEM_EVOLVE_ROOT / "eval" / "get_scan" / "run_with_policy.sh"),
        )
        eval_timeout = int(self.args.get("eval_timeout", 60))

        policy_src = (self.codebase_path / policy_file).read_text()
        policies_dir = str(MEM_EVOLVE_ROOT.parent / "cache_ext" / "policies")

        os.makedirs(os.path.dirname(LOCK_PATH), exist_ok=True)
        lock_fd = open(LOCK_PATH, "w")
        try:
            fcntl.flock(lock_fd, fcntl.LOCK_EX)

            compiled = compile_policy(policy_src, policies_dir)
            if not compiled.ok:
                return self.fail(f"compile failed: {compiled.error}")

            result = evaluate(
                compiled.binary_path,
                benchmark_script,
                timeout=eval_timeout,
            )
        finally:
            fcntl.flock(lock_fd, fcntl.LOCK_UN)
            lock_fd.close()

        if not result.ok:
            return self.fail(result.feedback_text())

        return self.score(result.score, result.feedback_text())
