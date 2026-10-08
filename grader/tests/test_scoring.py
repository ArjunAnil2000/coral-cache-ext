"""Local tests: normalization/scoring math and grader control flow with a
stubbed `coral` and fake evaluator. No BPF / CloudLab needed.

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
from cache_evolution_grader.normalization import NormalizationState, extract_raw_values  # noqa: E402

W = scoring.DEFAULT_WEIGHTS


def probes(tp, io, mem):
    return {
        "throughput": {"value": tp, "direction": "maximize", "unit": "ops/s", "summary": "x"},
        "cgroup_iostat": {"value": io, "direction": "minimize", "unit": "B", "summary": "x"},
        "cgroup_memstat": {"value": mem, "direction": "minimize", "unit": "", "summary": "x"},
        "wallclock": {"value": 30.0, "direction": "minimize", "unit": "s", "summary": "x"},
        "policy_counters": {"value": 0, "direction": "record", "unit": "", "summary": "x"},
    }


def baseline_state():
    st = NormalizationState(min_n=2)
    for tp, io, mem in [(1000, 1e9, 100), (1100, 1.1e9, 110), (900, 0.9e9, 90), (1000, 1e9, 100)]:
        st.update(extract_raw_values(probes(tp, io, mem)))
    return st


class MathTests(unittest.TestCase):
    def test_baseline_mean_scores_zero_and_tanh_bounded(self):
        st = baseline_state()
        mean = st.probes["throughput"].mean
        r = st.score(probes(mean, st.probes["cgroup_iostat"].mean, st.probes["cgroup_memstat"].mean), W)
        self.assertAlmostEqual(r["score"], 0.0, places=9)
        r = st.score(probes(1e9, 1, 1), W)
        self.assertLessEqual(r["score"], 1.0)
        self.assertGreater(r["score"], 0.99)
        self.assertIn("wallclock", [] if "wallclock" in r["components"] else ["wallclock"])  # weight 0 -> unscored

    def test_tanh_value(self):
        st = baseline_state()
        sd = st.probes["throughput"].stddev
        r = st.score({"throughput": {"value": st.probes["throughput"].mean + sd, "direction": "maximize"}}, W)
        self.assertAlmostEqual(r["score"], math.tanh(1.0), places=9)

    def test_throughput_regression_with_iostat_win_loses_to_throughput_win(self):
        st = baseline_state()
        sd_io = st.probes["cgroup_iostat"].stddev
        m = lambda n: st.probes[n].mean
        sd_tp = st.probes["throughput"].stddev
        regress = st.score(probes(m("throughput") - 1.5 * sd_tp, m("cgroup_iostat") - 2 * sd_io, m("cgroup_memstat")), W)
        win = st.score(probes(m("throughput") + 1.0 * sd_tp, m("cgroup_iostat"), m("cgroup_memstat")), W)
        self.assertLess(regress["score"], win["score"])
        self.assertLess(regress["score"], 0)  # the 2026-08-13 motivating case

    def test_zero_variance_probe_skipped(self):
        st = NormalizationState(min_n=2)
        for _ in range(3):
            st.update({"throughput": 5.0})
        r = st.score({"throughput": {"value": 6.0, "direction": "maximize"}}, W)
        self.assertEqual(r["skipped"], ["throughput"]); self.assertEqual(r["score"], 0.0)

    def test_stats_roundtrip_and_fingerprint(self):
        st = baseline_state()
        fp = scoring.fingerprint(scoring.DEFAULT_PROBE_SPECS, W, "b.sh", "src")
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "s.json")
            scoring.save_stats(p, fp, st, {"successes": 4})
            got, meta = scoring.load_stats(p, fp)
            self.assertAlmostEqual(got.probes["throughput"].mean, st.probes["throughput"].mean)
            self.assertIsNone(scoring.load_stats(p, "other"))

    def test_feedback_contains_components(self):
        st = baseline_state()
        pr = probes(800, 1e9, 100)
        txt = scoring.format_feedback(st.score(pr, W), pr, 31.0, {"successes": 4, "attempted": 4})
        for s in ("throughput", "cgroup_iostat", "z=", "contrib="):
            self.assertIn(s, txt)

    def test_invalid_required_probe(self):
        pr = {"throughput": {"summary": "(missing results file /x)"}}
        self.assertTrue(scoring.invalid_required_probes(pr, ["throughput"]))


def fake_result(vals, ok=True):
    return SimpleNamespace(ok=ok, error="" if ok else "bench failed", wallclock_sec=30.0, probes=probes(*vals),
                           stderr_tail="", feedback_text=lambda: "fb")


class FlowTests(unittest.TestCase):
    """Grader.evaluate control flow with a fake remote backend."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        (Path(self.tmp) / "noop.c").write_text("// policy")
        self.args = {
            "ssh_target": "u@node", "stats_path": str(Path(self.tmp) / "stats.json"),
            "calibrate_runs": 4, "lock_wait": 2,
        }
        self.base_vals = [(1000, 1e9, 100), (1100, 1.1e9, 110), (900, 0.9e9, 90), (1000, 1e9, 100)]
        self.next_policy = (1000, 1e9, 100)
        self.compile_ok = True
        self.raise_exc = None
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
        if src == "// policy":
            return comp, [fake_result(self.next_policy)]
        return comp, [fake_result(v) for v in self.base_vals[:runs]]

    def grade(self):
        return grader.Grader(args=self.args, codebase_path=self.tmp).evaluate()

    def test_calibrates_once_then_scores(self):
        r1 = self.grade()
        self.assertEqual(r1[0], "score")
        self.assertEqual([c[1] for c in self.calls], [4, 1])  # one calibration call (4 runs), one eval
        self.assertAlmostEqual(r1[1], 0.0, places=6)
        self.next_policy = (700, 0.5e9, 100)  # throughput regression, iostat win
        r2 = self.grade()
        self.assertEqual(len(self.calls), 3)  # no recalibration
        self.assertLess(r2[1], 0)
        self.assertIn("throughput", r2[2])

    def test_compile_failure_includes_compiler_output(self):
        self.grade(); self.compile_ok = False
        r = self.grade()
        self.assertEqual(r[0], "fail"); self.assertIn("clang: error", r[1])

    def test_infrastructure_errors_are_labelled(self):
        self.grade()
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


if __name__ == "__main__":
    unittest.main()
