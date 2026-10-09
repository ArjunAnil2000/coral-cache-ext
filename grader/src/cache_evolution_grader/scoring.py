"""Scoring glue for the CORAL grader: probe specs, required-probe check, feedback text.

The score of an attempt is the ABSOLUTE measured throughput of the benchmark under the
submitted policy, in operations per second (higher is better). There is no baseline
normalization, z-scoring or squashing: the grader returns the number the benchmark
measured. The other probes (bytes read, refaults, wallclock) are reported in the
feedback for diagnosis but do not affect the score.

The functions here are pure (no `evaluator`, no `coral`, no ssh): probes are built on
the node by node/eval_remote.py from the same specs.
"""

from __future__ import annotations

from typing import Any, Dict, List

# The throughput probe: read from the benchmark's results.json. Its value is the score.
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

SCORE_PROBE = "throughput"


def invalid_required_probes(probes: Dict[str, Dict[str, Any]], required: List[str]) -> List[str]:
    """Probes that silently degrade to value 0 (missing file, bad json_path)
    report a summary starting with '(' -- treat as failure, not a score of 0."""
    bad = []
    for name in required:
        p = probes.get(name)
        if p is None or str(p.get("summary", "")).startswith("("):
            bad.append(f"{name}: {p.get('summary') if p else 'probe missing from result'}")
    return bad


def format_feedback(probes: Dict[str, Dict[str, Any]], wall: float) -> str:
    """Feedback text shown to the agent: the score (= throughput) plus every probe's value."""
    tput = float(probes[SCORE_PROBE]["value"])
    lines = [
        f"score = throughput = {tput:.2f} ops/s (absolute; higher is better) wall={wall:.1f}s",
        "Probes (only throughput is the score; the rest are for diagnosis):",
    ]
    for name in sorted(probes):
        p = probes[name]
        tag = "  <- SCORE" if name == SCORE_PROBE else ""
        lines.append(f"  - {name}: {p.get('summary', '')}{tag}")
    lines.append(
        "Note: repeated evaluations of identical code vary by roughly 1-2% (occasionally more), "
        "so differences of a few ops/s between attempts are within noise; resubmit to confirm."
    )
    return "\n".join(lines)
