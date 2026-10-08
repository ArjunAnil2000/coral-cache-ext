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
        self.codebase_path = Path(codebase_path or ".")

    def fail(self, msg):
        return ("fail", msg)

    def score(self, v, msg=""):
        return ("score", v, msg)


cg.TaskGrader = TaskGrader
sys.modules.setdefault("coral", coral); sys.modules["coral.grader"] = cg

from cache_evolution_grader import grader, scoring  # noqa: E402
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


class FlowTests(unittest.TestCase):
    """Grader.evaluate control flow with fakes patched in."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        (Path(self.tmp) / "noop.c").write_text("// policy")
        (Path(self.tmp) / "base.c").write_text("// base")
        self.args = {
            "baseline_source": str(Path(self.tmp) / "base.c"),
            "stats_path": str(Path(self.tmp) / "stats.json"),
            "calibrate_runs": 4, "source_dir": self.tmp, "benchmark_script": "b.sh", "lock_wait": 2,
        }
        self.base_vals = iter([(1000, 1e9, 100), (1100, 1.1e9, 110), (900, 0.9e9, 90), (1000, 1e9, 100)])
        self.next_policy = (1000, 1e9, 100)
        self.compile_ok = True
        self.n_eval = 0
        grader.LOCK_PATH = str(Path(self.tmp) / "lock")
        grader.EvalLock.__init__.__defaults__ = (grader.LOCK_PATH, 600)
        grader._load_evaluator = lambda: (self.compile, self.evaluate)
        grader.scoring.build_probes = lambda specs: []

    def compile(self, src, d):
        return SimpleNamespace(ok=self.compile_ok, error="boom", binary_path=src)

    def evaluate(self, binary, script, **kw):
        self.n_eval += 1
        v = self.next_policy if binary == "// policy" else next(self.base_vals)
        return SimpleNamespace(ok=True, error="", wallclock_sec=30.0, probes=probes(*v),
                               feedback_text=lambda: "fb")

    def grade(self):
        g = grader.Grader(args=self.args, codebase_path=self.tmp)
        return g.evaluate()

    def test_calibrates_once_then_scores(self):
        r1 = self.grade()
        self.assertEqual(r1[0], "score"); self.assertEqual(self.n_eval, 5)
        self.assertAlmostEqual(r1[1], 0.0, places=6)
        self.next_policy = (700, 0.5e9, 100)  # throughput regression, iostat win
        r2 = self.grade()
        self.assertEqual(self.n_eval, 6)  # no recalibration
        self.assertLess(r2[1], 0)
        self.assertIn("throughput", r2[2])

    def test_compile_failure(self):
        self.grade(); self.compile_ok = False
        self.assertEqual(self.grade()[0], "fail")


if __name__ == "__main__":
    unittest.main()
