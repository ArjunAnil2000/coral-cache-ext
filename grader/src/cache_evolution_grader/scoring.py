"""Scoring glue for the CORAL grader: probes, weights, calibration, feedback.

Mirrors how mem-evolve's coordinator scored get_scan.toml:
  * probes  = evaluator.DEFAULT_PROBES + config-declared json_extract probes
              (built node-side; see evolution/worker.py build_probes_from_specs)
  * weights = [scoring.weights]; probes without positive weight or with
              direction "record" are not scored
  * score   = sum_w(w * tanh(+-z)) / sum_w(w), z against frozen noop-baseline
              mean/stddev (update_during_evolution = false)

The functions here are pure (no `evaluator`, no `coral`, no ssh): probes are
built on the node by remote/eval_remote.py from the same specs.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any, Dict, List

from cache_evolution_grader.normalization import NormalizationState

# Defaults reproduce mem-evolve/cache_policy_evolution/get_scan.toml.
DEFAULT_PROBE_SPECS: List[Dict[str, Any]] = [
    {
        "type": "json_extract",
        "name": "throughput",
        "results_file": "results.json",
        "json_path": "throughput_ops_per_sec",
        "direction": "maximize",
        "unit": "ops/s",
    }
]
DEFAULT_WEIGHTS: Dict[str, float] = {
    "throughput": 2.0,
    "cgroup_iostat": 0.5,
    "cgroup_memstat": 0.25,
}


def fingerprint(specs, weights, benchmark: str, baseline_src: str) -> str:
    """Identify what calibration stats are valid for. A change in any of
    these triggers recalibration instead of silently reusing stale stats."""
    blob = json.dumps(
        {"specs": specs, "weights": weights, "benchmark": benchmark, "baseline": baseline_src},
        sort_keys=True,
    )
    return hashlib.sha256(blob.encode()).hexdigest()[:16]


def load_stats(path: str, fp: str):
    """Return (NormalizationState, meta) if path holds stats for `fp`, else None."""
    try:
        with open(path) as f:
            data = json.load(f)
    except (OSError, ValueError):
        return None
    if data.get("fingerprint") != fp:
        return None
    return NormalizationState.from_dict(data["state"]), data.get("meta", {})


def save_stats(path: str, fp: str, state: NormalizationState, meta: Dict[str, Any]) -> None:
    import os

    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w") as f:
        json.dump({"fingerprint": fp, "meta": meta, "state": state.to_dict()}, f, indent=2)
    os.replace(tmp, path)


def invalid_required_probes(probes: Dict[str, Dict[str, Any]], required: List[str]) -> List[str]:
    """Probes that silently degrade to value 0 (missing file, bad json_path)
    report a summary starting with '(' — treat as failure, not a 0 score."""
    bad = []
    for name in required:
        p = probes.get(name)
        if p is None or str(p.get("summary", "")).startswith("("):
            bad.append(f"{name}: {p.get('summary') if p else 'probe missing from result'}")
    return bad


def format_feedback(
    scored: Dict[str, Any], probes: Dict[str, Dict[str, Any]], wall: float, calib_meta: Dict[str, Any]
) -> str:
    lines = [
        f"score={scored['score']:.4f} (tanh-squashed weighted z-score vs noop baseline) wall={wall:.1f}s",
        "Per-probe: raw value | baseline mean +- std | z | direction | weight | contribution (tanh of signed z, in [-1,1])",
    ]
    comps = scored["components"]
    for name in sorted(comps):
        c = comps[name]
        p = probes.get(name, {})
        direction = p.get("direction", "?")
        lines.append(
            f"  - {name}: {p.get('value', float('nan')):.6g} {p.get('unit', '')} | "
            f"{c['mean']:.6g} +- {c['stddev']:.4g} (n={c['n']}) | z={c['z']:+.2f} | "
            f"{direction} | w={c['weight']:g} | contrib={c['contribution']:+.3f}"
        )
    if scored["skipped"]:
        lines.append(f"  skipped (baseline n/stddev insufficient): {', '.join(scored['skipped'])}")
    unscored = sorted(set(probes) - set(comps) - set(scored["skipped"]))
    for name in unscored:
        lines.append(f"  - {name} (not scored): {probes[name].get('summary', '')}")
    lines.append(
        "Higher is better. Throughput (w=2.0) dominates: lowering bytes read (cgroup_iostat) "
        "does not compensate for a throughput regression."
    )
    if calib_meta:
        lines.append(
            f"Calibration: noop baseline, {calib_meta.get('successes', '?')}/{calib_meta.get('attempted', '?')} "
            f"runs at {calib_meta.get('timestamp', '?')}."
        )
    return "\n".join(lines)
