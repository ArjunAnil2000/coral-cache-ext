"""Tests for multi-host support (host parsing, buckets, agent->host binding, per-host budget). No CloudLab needed.

Run: python -I grader/tests/test_hosts.py   (from repo root)
"""
import json
import sys
import tempfile
import types
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

# grader.py imports coral.grader.TaskGrader; stub it the same way test_scoring.py does.
coral = types.ModuleType("coral"); cg = types.ModuleType("coral.grader")
cg.TaskGrader = type("TaskGrader", (), {})
coral.grader = cg
sys.modules.setdefault("coral", coral); sys.modules.setdefault("coral.grader", cg)

from cache_evolution_grader import grader, hosts  # noqa: E402


class ParseAndSplit(unittest.TestCase):
    def test_parse_instances(self):
        txt = "# cloudlab instances\n\nssh aanil3@pc306.emulab.net\nssh aanil3@pc319.emulab.net\n  aanil3@pc309.emulab.net  \nsome prose line\nssh aanil3@pc306.emulab.net\n"
        self.assertEqual(hosts.parse_instances(txt), ["aanil3@pc306.emulab.net", "aanil3@pc319.emulab.net", "aanil3@pc309.emulab.net"])

    def test_split_one_per_agent(self):
        self.assertEqual(hosts.split_buckets(["a@1", "a@2", "a@3"], 3), [["a@1"], ["a@2"], ["a@3"]])

    def test_split_round_robin_when_fewer_agents(self):
        self.assertEqual(hosts.split_buckets(["a@1", "a@2", "a@3", "a@4", "a@5"], 2), [["a@1", "a@3", "a@5"], ["a@2", "a@4"]])

    def test_more_agents_than_hosts_rejected(self):
        with self.assertRaises(ValueError):
            hosts.split_buckets(["a@1"], 2)

    def test_host_slug(self):
        self.assertEqual(hosts.host_slug("aanil3@pc306.emulab.net"), "pc306")

    def test_hosts_file_rejects_shared_host(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "hosts.json"
            p.write_text(json.dumps({"buckets": [["a@1"], ["a@1"]]}))
            with self.assertRaises(ValueError):
                hosts.load_hosts_file(p)


class ClaimsAndBudget(unittest.TestCase):
    def test_claims_are_stable_and_distinct(self):
        with tempfile.TemporaryDirectory() as d:
            c = Path(d) / "private" / "claims.json"
            a = hosts.claim_bucket(c, "captain-nemo", 2)
            b = hosts.claim_bucket(c, "captain-ahab", 2)
            self.assertEqual({a, b}, {0, 1})
            self.assertEqual(hosts.claim_bucket(c, "captain-nemo", 2), a)   # stable on repeat
            with self.assertRaises(RuntimeError):
                hosts.claim_bucket(c, "third", 2)                            # no free bucket

    def _attempt(self, d, h, agent, cls):
        (Path(d) / f"{h}.json").write_text(json.dumps({"commit_hash": h, "agent_id": agent, "metadata": {"budget_class": cls}}))

    def test_budget_counts_only_this_agents_real_attempts(self):
        with tempfile.TemporaryDirectory() as d:
            for i in range(3): self._attempt(d, f"r{i}", "nemo", "real")
            self._attempt(d, "t", "nemo", "tune"); self._attempt(d, "g", "nemo", "grader_error"); self._attempt(d, "o", "ahab", "real")
            self.assertEqual(hosts.real_attempts_used(d, "nemo"), 3)
            self.assertEqual(hosts.real_attempts_used(d, "nemo", exclude_hash="r0"), 2)


class BindHost(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        (self.root / "public" / "attempts").mkdir(parents=True)
        hf = self.root / "hosts.json"
        hf.write_text(json.dumps({"per_host_budget": 2, "buckets": [["u@pc1.x.net"], ["u@pc2.x.net"]]}))
        self.cfg = grader.load_config({"hosts_file": str(hf), "stats_path": str(self.root / "stats_{host}.json")})

    def tearDown(self):
        self.tmp.cleanup()

    def bind(self, agent, h="c", tune=False):
        return grader.bind_host(self.cfg, self.root, agent, h, tune)

    def test_agents_get_distinct_hosts_and_stats(self):
        a, _ = self.bind("nemo"); b, _ = self.bind("ahab")
        self.assertNotEqual(a["ssh_target"], b["ssh_target"])
        self.assertNotEqual(a["stats_path"], b["stats_path"])
        self.assertTrue(a["stats_path"].endswith("stats_pc1.json"))
        self.assertEqual(self.bind("nemo")[0]["ssh_target"], a["ssh_target"])

    def test_budget_enforced(self):
        for i in range(2):
            (self.root / "public" / "attempts" / f"r{i}.json").write_text(
                json.dumps({"commit_hash": f"r{i}", "agent_id": "nemo", "metadata": {"budget_class": "real"}}))
        with self.assertRaises(RuntimeError) as cm:
            self.bind("nemo", h="new")
        self.assertIn("budget exhausted", str(cm.exception))
        self.assertIn("sleep", str(cm.exception))
        cfg, _ = self.bind("nemo", h="new", tune=True)       # tune is allowed (and unbudgeted) unless allow_tune is False
        self.assertTrue(cfg["ssh_target"].startswith("u@pc"))
        self.bind("ahab", h="new")                          # another agent is unaffected

    def test_tune_refused_when_disabled(self):
        self.cfg["allow_tune"] = False
        with self.assertRaises(RuntimeError) as cm:
            self.bind("nemo", tune=True)
        self.assertIn("--tune", str(cm.exception))
        self.bind("nemo")                                   # real evals still work

    def test_note_shows_progress(self):
        _, note = self.bind("nemo")
        self.assertIn("Real eval 1/2", note)

    def test_single_host_mode_unchanged(self):
        cfg = grader.load_config({"ssh_target": "u@h"})
        out, note = grader.bind_host(cfg, self.root, "nemo", "c", False)
        self.assertIs(out, cfg); self.assertEqual(note, "")


if __name__ == "__main__":
    unittest.main()
