#!/usr/bin/env python3
"""Run the same policy on every host, interleaved with unmodified controls, to separate host speed from policy effect.

usage: run_compare.py [reps=8]
Per host (hosts run in parallel, one eval at a time each): 1 discarded-for-stats warm-up eval of the best policy, then
`reps` rounds of {best, noop, mglru} with the order rotated each round (so no policy always runs first or last).
Raw results go to raw/<host>.jsonl (one JSON line per eval); nothing is scored or filtered here.
Needs the coral tool venv (grader.load_config imports coral):
  PYTHONPATH=<worktree>/grader/src ~/.local/share/uv/tools/coral/bin/python run_compare.py
"""
import glob, json, os, sys, threading, time

from cache_evolution_grader import grader, remote

HERE = os.path.dirname(os.path.abspath(__file__))
WT = "/home/aanil/Desktop/ldos/arjua-forks/coral-runs/multihost-maximize-throughput"
BEST = glob.glob(f"{HERE}/../multihost_2026-10-21_003256_4hosts/best/best_overall_*.c")[0]
POLICIES = {"best": open(BEST).read(), "noop": open(f"{WT}/seed/noop.c").read(), "mglru": open(f"{WT}/seed/reference/mglru.c").read()}
HOSTS = ["pc252", "pc257", "pc258", "pc318"]
REPS = int(sys.argv[1]) if len(sys.argv) > 1 else 8
os.makedirs(f"{HERE}/raw", exist_ok=True)


def one(host, policy, rnd, seq):
    cfg = grader.load_config({"ssh_target": f"aanil3@{host}.emulab.net", "ssh_key": os.path.expanduser("~/.ssh/coral_eval_ed25519")})
    rec = dict(host=host, policy=policy, round=rnd, seq=seq, t_start=time.time(), warmup=(rnd == -1))
    try:
        compiled, results = remote.run_remote(cfg, POLICIES[policy], runs=1)
        r = results[0]
        rec.update(ok=bool(compiled.ok and r.ok), wall=r.wallclock_sec)
        if rec["ok"]:
            p = r.probes
            rec.update(tput=p["throughput"]["value"], rbytes=p["cgroup_iostat"]["value"], refault=p["cgroup_memstat"]["value"])
        else:
            rec["error"] = (r.feedback_text() if compiled.ok else str(compiled.error))[:300]
    except Exception as e:  # transient ssh/node trouble: record and keep going
        rec.update(ok=False, error=f"{type(e).__name__}: {e}"[:300])
    rec["t_end"] = time.time()
    return rec


def run_host(host):
    order = ["best", "noop", "mglru"]
    seq = 0
    with open(f"{HERE}/raw/{host}.jsonl", "a") as out:
        plan = [("best", -1)] + [(pol, rnd) for rnd in range(REPS) for pol in order[rnd % 3:] + order[:rnd % 3]]
        for pol, rnd in plan:
            rec = one(host, pol, rnd, seq); seq += 1
            out.write(json.dumps(rec) + "\n"); out.flush()
            print(f"{host} #{seq}/{len(plan)} {pol:6s} round {rnd:2d} -> {rec.get('tput')} {'' if rec['ok'] else rec.get('error')}", flush=True)


if __name__ == "__main__":
    print("best policy file:", os.path.basename(BEST), "| reps", REPS, flush=True)
    ts = [threading.Thread(target=run_host, args=(h,)) for h in HOSTS]
    [t.start() for t in ts]; [t.join() for t in ts]
    print("done", flush=True)
