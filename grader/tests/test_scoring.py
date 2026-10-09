"""Local tests: the grader (score = absolute throughput), the ssh client, the wire
protocol of node/eval_remote.py and the seed-file format. No BPF / CloudLab needed.

Run: python -I grader/tests/test_scoring.py   (from repo root)
"""
import math
import os
import sys
import tempfile
import types
import unittest
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

# Stub coral.grader.TaskGrader (real one is only on the node).
coral = types.ModuleType("coral"); cg = types.ModuleType("coral.grader")


class TaskGrader:
    def __init__(self, args=None, codebase_path=None):
        self.args = args or {}
        self.codebase_path = str(codebase_path or ".")  # real coral passes a str

    def fail(self, msg):
        return ("fail", msg)

    def score(self, v, msg=""):
        return ("score", v, msg)


cg.TaskGrader = TaskGrader
sys.modules.setdefault("coral", coral); sys.modules["coral.grader"] = cg

from cache_evolution_grader import grader, remote, scoring  # noqa: E402

def probes(tp, io=3.0e8, mem=50000):
    return {
        "throughput": {"value": tp, "direction": "maximize", "unit": "ops/s", "summary": f"throughput_ops_per_sec={tp:.2f} ops/s"},
        "cgroup_iostat": {"value": io, "direction": "minimize", "unit": "B", "summary": f"rbytes={io:.3g}"},
        "cgroup_memstat": {"value": mem, "direction": "minimize", "unit": "", "summary": f"refaults={mem}"},
        "wallclock": {"value": 40.0, "direction": "minimize", "unit": "s", "summary": "wallclock: 40.00s"},
    }


def fake_result(tp, ok=True, pr=None):
    return SimpleNamespace(ok=ok, error="" if ok else "bench failed", wallclock_sec=40.0,
                           probes=pr if pr is not None else probes(tp), stderr_tail="",
                           feedback_text=lambda: "fb")


class ScoringTests(unittest.TestCase):
    def test_feedback_names_the_score_and_lists_probes(self):
        txt = scoring.format_feedback(probes(1234.5), 40.0)
        self.assertIn("score = throughput = 1234.50 ops/s", txt)
        self.assertIn("<- SCORE", txt)
        for name in ("cgroup_iostat", "cgroup_memstat", "wallclock"):
            self.assertIn(name, txt)
        self.assertNotIn("tanh", txt); self.assertNotIn("z=", txt)

    def test_invalid_required_probe(self):
        pr = {"throughput": {"summary": "(missing results file /x)"}}
        self.assertTrue(scoring.invalid_required_probes(pr, ["throughput"]))
        self.assertFalse(scoring.invalid_required_probes(probes(1000.0), ["throughput"]))


class FlowTests(unittest.TestCase):
    """Grader.evaluate control flow with a fake remote backend."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        (Path(self.tmp) / "noop.c").write_text("// policy")
        self.args = {"ssh_target": "u@node", "lock_wait": 2}
        self.throughput = 1234.5
        self.compile_ok = True
        self.raise_exc = None
        self.probes_override = None
        self.calls = []
        self._orig_run_remote = remote.run_remote
        remote.run_remote = self.fake_remote

    def tearDown(self):
        remote.run_remote = self._orig_run_remote

    def fake_remote(self, cfg, src, runs=1, **kw):
        self.calls.append((src, runs))
        if self.raise_exc:
            raise self.raise_exc
        comp = SimpleNamespace(ok=self.compile_ok, error="boom", stderr_tail="clang: error: x")
        if not self.compile_ok:
            return comp, []
        return comp, [fake_result(self.throughput, pr=self.probes_override)]

    def grade(self):
        return grader.Grader(args=self.args, codebase_path=self.tmp).evaluate()

    def test_score_is_the_absolute_throughput(self):
        r = self.grade()
        self.assertEqual(r[0], "score")
        self.assertEqual(r[1], 1234.5)               # unmodified: not normalized, not squashed
        self.assertIn("1234.50 ops/s", r[2])
        self.assertEqual(self.calls, [("// policy", 1)])   # exactly one remote eval; no calibration

    def test_score_exceeds_one_and_tracks_throughput_exactly(self):
        for tp in (900.0, 1211.6, 1277.7, 1500.0):
            self.throughput = tp
            self.assertEqual(self.grade()[1], tp)

    def test_other_probes_do_not_change_the_score(self):
        self.probes_override = probes(1250.0, io=1.0e6, mem=1)      # tiny I/O: must not help
        a = self.grade()[1]
        self.probes_override = probes(1250.0, io=9.9e9, mem=10**9)  # huge I/O: must not hurt
        self.assertEqual(a, self.grade()[1])

    def test_missing_or_nonpositive_throughput_fails_not_scores_zero(self):
        self.probes_override = probes(0.0)
        r = self.grade(); self.assertEqual(r[0], "fail"); self.assertIn("no usable result", r[1])
        self.probes_override = dict(probes(1000.0)); self.probes_override["throughput"] = {"value": 0.0, "summary": "(missing results file)"}
        r = self.grade(); self.assertEqual(r[0], "fail"); self.assertIn("required probe", r[1])

    def test_compile_failure_includes_compiler_output(self):
        self.compile_ok = False
        r = self.grade()
        self.assertEqual(r[0], "fail"); self.assertIn("clang: error", r[1])

    def test_infrastructure_errors_are_labelled(self):
        self.raise_exc = remote.RemoteError("ssh down")
        r = self.grade(); self.assertEqual(r[0], "fail"); self.assertIn("not your policy", r[1])
        self.raise_exc = remote.RemoteBusy("lock")
        r = self.grade(); self.assertIn("busy", r[1])

    def test_missing_ssh_target(self):
        del self.args["ssh_target"]
        r = self.grade(); self.assertEqual(r[0], "fail"); self.assertIn("ssh_target", r[1])


class RemoteClientTests(unittest.TestCase):
    CFG = {"ssh_target": "u@h", "ssh_key": "/k", "ssh_connect_timeout": 7, "ssh_options": ["-p", "22"],
           "remote_command": "run", "benchmark": "b.sh", "probes": [], "weights": {}, "eval_timeout": 10, "lock_wait": 5}

    def test_argv(self):
        a = remote.ssh_argv(self.CFG)
        self.assertEqual(a[0], "ssh"); self.assertIn("BatchMode=yes", a); self.assertIn("ConnectTimeout=7", a)
        self.assertEqual(a[-2:], ["u@h", "run"]); self.assertIn("-i", a)

    def test_transient_retried_once(self):
        n = []

        def call(cfg, req, t):
            n.append(1)
            if len(n) == 1:
                raise remote._Transient("conn")
            return {"status": "ok", "compile": {"ok": True}, "results": []}
        c, r = remote.run_remote(self.CFG, "x", _call=call)
        self.assertEqual(len(n), 2); self.assertTrue(c.ok)

    def test_busy_and_error(self):
        with self.assertRaises(remote.RemoteBusy):
            remote.run_remote(self.CFG, "x", _call=lambda *a: {"status": "busy", "error": "l"})
        with self.assertRaises(remote.RemoteError):
            remote.run_remote(self.CFG, "x", _call=lambda *a: {"status": "error", "error": "e"})

    def test_result_feedback_text(self):
        d = {"ok": False, "error": "e", "score": 0, "wallclock_sec": 1.0, "probes": {"p": {"summary": "s"}},
             "stdout_tail": "", "stderr_tail": "tail"}
        t = remote._result(d).feedback_text()
        self.assertIn("FAIL", t); self.assertIn("tail", t)


STUB_EVALUATOR = """
import json, os
from types import SimpleNamespace
DEFAULT_PROBES = []
class JsonExtractProbe:
    def __init__(self, **kw): self.kw = kw
def compile_policy(src, d):
    if "BAD" in src: return SimpleNamespace(ok=False, error="compile", stderr_tail="syntax error", binary_path=None)
    return SimpleNamespace(ok=True, error="", stderr_tail="", binary_path="/bin/true")
class R:
    def to_dict(self): return {"ok": True, "error": "", "score": 0.0, "wallclock_sec": 1.0,
        "probes": {"throughput": {"value": 5.0, "summary": "5 ops/s"}}, "stdout_tail": "noise", "stderr_tail": ""}
def evaluate(binary, bench, **kw):
    print("stdout noise that must not corrupt the protocol")
    assert os.path.isfile(bench)
    return R()
"""


class RemoteProtocolTests(unittest.TestCase):
    """Run node/eval_remote.py as a real subprocess against a stub evaluator."""

    def setUp(self):
        import subprocess, json  # noqa: E401
        self.subprocess, self.json = subprocess, json
        self.tmp = Path(tempfile.mkdtemp())
        root = self.tmp / "node"
        (root / "evaluator").mkdir(parents=True); (root / "bench" / "get_scan").mkdir(parents=True)
        (root / "evaluator" / "__init__.py").write_text(STUB_EVALUATOR)
        (root / "bench" / "get_scan" / "run_with_policy.sh").write_text("#!/bin/bash\n")
        self.env = dict(os.environ, EVO_NODE_DIR=str(root), EVO_CACHE_EXT_DIR=str(self.tmp), EVO_LOCK_PATH=str(self.tmp / "lock"))
        self.script = str(Path(__file__).resolve().parents[2] / "node" / "eval_remote.py")

    def call(self, **req):
        base = {"policy_src": "ok", "runs": 2, "benchmark": "bench/get_scan/run_with_policy.sh",
                "probes": [], "weights": {}, "eval_timeout": 5, "lock_wait": 2}
        base.update(req)
        p = self.subprocess.run([sys.executable, self.script], input=self.json.dumps(base),
                                capture_output=True, text=True, env=self.env, timeout=30)
        return self.json.loads(p.stdout.strip().splitlines()[-1]), p

    def test_ok_runs(self):
        r, p = self.call()
        self.assertEqual(r["status"], "ok"); self.assertEqual(len(r["results"]), 2)
        self.assertEqual(len(p.stdout.strip().splitlines()), 1)  # stub's stdout noise was diverted

    def test_compile_failure(self):
        r, _ = self.call(policy_src="BAD")
        self.assertFalse(r["compile"]["ok"]); self.assertEqual(r["results"], [])

    def test_benchmark_path_escape_rejected(self):
        r, _ = self.call(benchmark="../../etc/passwd")
        self.assertEqual(r["status"], "error")

    def test_busy_lock(self):
        import fcntl
        fd = open(self.tmp / "lock", "w"); fcntl.flock(fd, fcntl.LOCK_EX)
        r, _ = self.call(lock_wait=1)
        self.assertEqual(r["status"], "busy"); fd.close()


class SeedFormatTests(unittest.TestCase):
    """The seed (seed/noop.c, S3-FIFO) must be a complete single-file policy the
    node's pipeline can split and compile. (Compiling/running them is checked on the node.)"""

    ROOT = Path(__file__).resolve().parents[2]

    def seeds(self):
        return [self.ROOT / "seed" / "noop.c"]

    def test_all_seeds_split_and_are_self_consistent(self):
        sys.path.insert(0, str(self.ROOT / "node"))
        from targets.code_splitter import split_sections
        for f in self.seeds():
            src = f.read_text()
            with self.subTest(seed=f.name):
                bpf, loader = split_sections(src)
                self.assertTrue(bpf.strip() and loader.strip(), "splitter found no sections")
                self.assertEqual(src.count("// EVOLVE-BLOCK-START"), 2)
                self.assertEqual(src.count("// EVOLVE-BLOCK-END"), 2)
                self.assertIn("evo_policy_ops", bpf)
                self.assertIn("struct cache_ext_ops", bpf)
                self.assertIn('#include "evo_policy.skel.h"', loader)
                self.assertIn("evo_policy_bpf__", loader)
                self.assertNotIn("getchar", loader)           # harness runs the loader with no stdin
                self.assertIn("SIGTERM", loader)              # evaluator stops it with INT then TERM
                for opt in ("'w'", "'s'", "'c'"):             # harness always passes -w -s -c
                    self.assertIn(opt, loader)
                self.assertNotIn("cache_ext_" + f.stem + "_bpf", src)

    def test_description_under_the_kernel_banner(self):
        for f in self.seeds():
            lines = f.read_text().splitlines()
            with self.subTest(seed=f.name):
                i = lines.index("// SECTION: BPF KERNEL CODE")
                j = lines.index("// EVOLVE-BLOCK-START", i)
                desc = lines[j + 1]
                self.assertTrue(desc.startswith("// ") and len(desc) > 20, f"no description: {desc!r}")


if __name__ == "__main__":
    unittest.main()
