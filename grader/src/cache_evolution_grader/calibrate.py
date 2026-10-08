"""Pre-calibrate noop baseline stats: python -m cache_evolution_grader.calibrate [--force] [key=value ...]

Run on the CORAL host before `coral start` so the first agent grade does not
pay for calibration. key=value pairs override grader.args (ssh_target is
required, e.g. ssh_target=aanil3@c220g1-030815.wisc.cloudlab.us ssh_key=...).
"""
import os
import sys

from cache_evolution_grader import grader


def main(argv):
    force = "--force" in argv
    overrides = dict(a.split("=", 1) for a in argv if "=" in a)
    cfg = grader.load_config(overrides)
    if force and os.path.exists(cfg["stats_path"]):
        os.remove(cfg["stats_path"])
    with grader.LocalLock(cfg["stats_path"] + ".lock", wait=cfg["lock_wait"]):
        state, meta = grader.ensure_calibration(cfg)
    print(f"stats at {cfg['stats_path']}: {meta}")
    for name, w in sorted(state.probes.items()):
        print(f"  {name}: n={w.n} mean={w.mean:.6g} std={w.stddev:.4g}")


if __name__ == "__main__":
    main(sys.argv[1:])
