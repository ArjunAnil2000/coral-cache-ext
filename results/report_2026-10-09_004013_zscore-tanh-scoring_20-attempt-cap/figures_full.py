"""Figures for the FULL report. Style per the dataviz skill: thin marks, recessive grid, ink-colored text,
<=3 categorical hues (validated all-pairs), direct labels on selected points."""
import collections
import os

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.patheffects as pe
import numpy as np

import analysis as an

BLUE, ORANGE, AQUA = "#2a78d6", "#eb6834", "#1baf7a"
INK, INK2, GRID, SURF = "#0b0b0b", "#52514e", "#dcdbd6", "#fcfcfb"
OUT = os.path.join(an.HERE, "figures", "full")
os.makedirs(OUT, exist_ok=True)
plt.rcParams.update({
    "font.size": 8, "axes.titlesize": 9, "axes.labelsize": 8, "xtick.labelsize": 7.5, "ytick.labelsize": 7.5,
    "axes.edgecolor": GRID, "axes.labelcolor": INK2, "xtick.color": INK2, "ytick.color": INK2, "text.color": INK,
    "axes.facecolor": SURF, "figure.facecolor": SURF, "axes.grid": True, "grid.color": GRID, "grid.linewidth": 0.5,
    "axes.spines.top": False, "axes.spines.right": False, "legend.frameon": False, "legend.fontsize": 7.5,
    "axes.titleweight": "bold", "axes.titlelocation": "left",
})
W = 10.0
HALO = [pe.withStroke(linewidth=2.2, foreground=SURF)]
REF_OFF = {"get_scan": (0, -11), "s3fifo": (-4, 8), "mglru": (6, -10), "sampling": (0, -11), "lhd": (6, -11)}


def put_label(ax, text, xy, off, color=INK, size=6.8, ha="center"):
    ax.annotate(text, xy, textcoords="offset points", xytext=off, fontsize=size, color=color, ha=ha, path_effects=HALO)


def save(fig, name):
    p = os.path.join(OUT, name)
    fig.savefig(p, dpi=220, bbox_inches="tight", facecolor=SURF)
    plt.close(fig)
    return p


def mk(a):
    return dict(real=("o", BLUE), tune=("^", ORANGE))[a["cls"]]


def fig_timeline(d):
    A, (bm, bs) = d["attempts"], d["base"]["tput"]
    fig, ax = plt.subplots(figsize=(W, 3.15))
    ax.axhspan(bm - 2 * bs, bm + 2 * bs, color=BLUE, alpha=0.07, lw=0)
    ax.axhspan(bm - bs, bm + bs, color=BLUE, alpha=0.12, lw=0)
    ax.axhline(bm, color=INK2, lw=0.9, ls="--")
    for cls, lab_ in (("real", "real attempt"), ("tune", "--tune attempt")):
        pts = [a for a in A if a["cls"] == cls]
        m, c = mk(pts[0])
        ax.plot([a["n"] for a in pts], [a["t"] for a in pts], m, color=c, ms=5, lw=0, label=lab_, mec=SURF, mew=0.8)
    ax.plot([a["n"] for a in A], [a["t"] for a in A], color=GRID, lw=0.8, zorder=0)
    best = max(A, key=lambda a: a["t"])
    worst = min(A, key=lambda a: a["t"])
    for a, off in ((best, (0, 8)), (worst, (-26, 2))):
        put_label(ax, f"#{a['n']} {a['t']:.0f}", (a["n"], a["t"]), off)
    for a in A:
        if a["ref"]:
            put_label(ax, a["ref"], (a["n"], a["t"]), REF_OFF.get(a["ref"], (0, -11)), color="#0f7a55", size=6.5)
    ax.set_xlabel("attempt # (chronological)")
    ax.set_ylabel("throughput (ops/s)")
    ax.set_title(f"Measured throughput per attempt (dashed = noop mean {bm:.1f}; bands = ±1σ, ±2σ; σ = {bs:.1f}, n = {d['base']['n']})")
    ax.set_xticks(range(1, len(A) + 1))
    ax.set_ylim(min(a["t"] for a in A) - 30, max(a["t"] for a in A) + 22)
    ax.legend(loc="lower center", bbox_to_anchor=(0.4, 0.02), ncol=2)
    return save(fig, "f1_timeline.png")


def fig_score_vs_tput(d):
    A = d["attempts"]
    fig, ax = plt.subplots(figsize=(W / 2 - 0.2, 3.1))
    for cls, lab_ in (("real", "real"), ("tune", "--tune")):
        pts = [a for a in A if a["cls"] == cls]
        m, c = mk(pts[0])
        ax.plot([a["t"] for a in pts], [a["score"] for a in pts], m, color=c, ms=5, lw=0, label=lab_, mec=SURF, mew=0.8)
    ax.axhline(1.0, color=INK2, lw=0.6, ls=":")
    ax.set_xlabel("throughput (ops/s)")
    ax.set_ylabel("grader score")
    ax.set_title("Score vs throughput (score saturates near 1)")
    ax.legend(loc="center left")
    return save(fig, "f2_score_vs_tput.png")


def fig_tradeoff(d):
    A = d["attempts"]
    fig, ax = plt.subplots(figsize=(W / 2 - 0.2, 3.1))
    ax.axhline(0, color=INK2, lw=0.6)
    ax.axvline(0, color=INK2, lw=0.6)
    for cls, lab_ in (("real", "real"), ("tune", "--tune")):
        pts = [a for a in A if a["cls"] == cls]
        m, c = mk(pts[0])
        ax.plot([a["dio_pct"] for a in pts], [a["dt_pct"] for a in pts], m, color=c, ms=5, lw=0, label=lab_, mec=SURF, mew=0.8)
    off = {"get_scan": (22, -3), "s3fifo": (-16, 6), "mglru": (16, -9), "sampling": (20, 2), "lhd": (12, -9)}
    for a in A:
        if a["ref"]:
            put_label(ax, a["ref"], (a["dio_pct"], a["dt_pct"]), off.get(a["ref"], (14, -3)), color="#0f7a55", size=6.5)
    best = max(A, key=lambda a: a["t"])
    put_label(ax, f"best #{best['n']}", (best["dio_pct"], best["dt_pct"]), (-18, 6))
    ax.set_xlabel("bytes read vs noop (%)   (negative = fewer bytes read)")
    ax.set_ylabel("throughput vs noop (%)")
    ax.set_title("Throughput vs I/O reduction")
    ax.legend(loc="lower right")
    return save(fig, "f3_tradeoff.png")


def fig_groups(d, G):
    bm, bs = d["base"]["tput"]
    gs = [g for g in G if g["n"] >= 2]
    fig, ax = plt.subplots(figsize=(W, 3.0))
    ax.axhspan(bm - bs, bm + bs, color=BLUE, alpha=0.12, lw=0)
    ax.axhline(bm, color=INK2, lw=0.9, ls="--")
    for i, g in enumerate(gs):
        xs = i + np.linspace(-0.12, 0.12, g["n"])
        for x, m in zip(xs, g["members"]):
            mk_, c = mk(m)
            ax.plot(x, m["t"], mk_, color=c, ms=5, mec=SURF, mew=0.8)
        ax.plot([i - 0.22, i + 0.22], [g["mean"]] * 2, color=INK, lw=1.4)
        ax.text(i, g["min"] - 5, f"n={g['n']}\nrange {100*(g['max']-g['min'])/g['mean']:.1f}%", ha="center", va="top", fontsize=6.5, color=INK2)
    ax.set_xticks(range(len(gs)))
    ax.set_xticklabels([f"{g['gid']}\n{g['members'][0]['short']}" + (f"\n({g['ref']})" if g["ref"] else "") for g in gs], fontsize=6.5)
    ax.set_xlim(-0.6, len(gs) - 0.4)
    lo = min(g["min"] for g in gs)
    ax.set_ylim(lo - 40, max(max(g["max"] for g in gs), bm + bs) + 12)
    ax.set_ylabel("throughput (ops/s)")
    ax.set_title("Identical-code repeat measurements (tick = group mean; band = noop ±1σ)")
    return save(fig, "f4_groups.png")


def fig_running_best(d):
    A = d["attempts"]
    fig, axs = plt.subplots(1, 2, figsize=(W, 3.0))
    n = [a["n"] for a in A]
    for ax, key, lab_, c in ((axs[0], "score", "grader score", BLUE), (axs[1], "t", "throughput (ops/s)", ORANGE)):
        v = np.maximum.accumulate([a[key] for a in A])
        ax.plot(n, [a[key] for a in A], "o", color=GRID, ms=3.5, lw=0)
        ax.step(n, v, where="post", color=c, lw=1.5)
        ax.set_xlabel("attempt #")
        ax.set_ylabel(lab_)
        ax.set_title(f"Running best: {lab_}")
    return save(fig, "f5_running_best.png")


def fig_latency(d):
    A = d["attempts"]
    fig, ax = plt.subplots(figsize=(W / 2 - 0.2, 3.0))
    lat = [a["eval_latency_s"] for a in A]
    ax.bar([a["n"] for a in A], lat, color=[BLUE if a["cls"] == "real" else ORANGE for a in A], width=0.65)
    med = float(np.median(lat[1:]))
    ax.axhline(med, color=INK2, lw=0.8, ls="--")
    ax.text(len(A) + 0.5, med + 8, f"median excl. #1: {med:.0f}s", ha="right", fontsize=7, color=INK2)
    ax.annotate(f"#1: {lat[0]:.0f}s (incl. noop calibration)", (1, lat[0]), textcoords="offset points", xytext=(8, -4), fontsize=7)
    ax.set_xlabel("attempt #")
    ax.set_ylabel("submit → graded (s)")
    ax.set_xticks(range(1, len(A) + 1, 3))
    ax.set_title("Eval latency (blue real, orange --tune)")
    return save(fig, "f6_latency.png")


def fig_gateway_time(d):
    gw = d["gateway"]
    t0 = min(an.dt.datetime.fromisoformat(r["ts"]) for r in gw)
    bins = collections.defaultdict(collections.Counter)
    for r in gw:
        t = an.dt.datetime.fromisoformat(r["ts"])
        bins[int((t - t0).total_seconds() // 300)][r["status"]] += 1
    nb = max(bins) + 1
    fig, axs = plt.subplots(1, 2, figsize=(W, 3.0), gridspec_kw=dict(width_ratios=[1.35, 1]))
    ax = axs[0]
    bottom = np.zeros(nb)
    for st, c in ((200, BLUE), (400, ORANGE), (503, AQUA)):
        v = np.array([bins[b][st] for b in range(nb)])
        ax.bar(np.arange(nb) * 5 + 2.5, v, bottom=bottom, width=4.0, color=c, label=f"HTTP {st}")
        bottom += v
    ax.set_ylim(0, max(bottom) * 1.32)
    ax.set_xlabel("minutes since first gateway request")
    ax.set_ylabel("requests per 5 min")
    ax.set_title("Gateway requests by HTTP status")
    ax.legend(loc="upper left", ncol=3)
    ax = axs[1]
    x = [r["dur_ms"] / 1000 for r in gw if r["status"] == 200]
    ax.hist(x, bins=np.arange(0, 66, 3), color=BLUE, edgecolor=SURF, lw=0.6)
    for p in (50, 90):
        ax.axvline(np.percentile(x, p), color=INK2, lw=0.8, ls="--")
        ax.text(np.percentile(x, p) + 0.8, ax.get_ylim()[1] * 0.92, f"p{p}={np.percentile(x, p):.1f}s", fontsize=7, color=INK2)
    ax.set_xlabel("response time of successful (200) requests (s)")
    ax.set_ylabel("requests")
    ax.set_title("Model response time")
    return save(fig, "f7_gateway.png")


def fig_sessions(d):
    S = d["sessions"]
    n = [s["idx"] for s in S]
    fig, axs = plt.subplots(1, 3, figsize=(W, 2.9))
    ctx = [(s.get("cache_read", 0) + s.get("cache_create", 0) + s.get("in_tok", 0)) / 1e6 for s in S]
    out = [s.get("out_tok", 0) / 1e3 for s in S]
    cum = [s.get("cost_usd", 0) or 0 for s in S]
    cost = [cum[0]] + [b - a for a, b in zip(cum, cum[1:])]   # total_cost_usd is cumulative across resumed sessions
    for ax, v, lab_, ttl, c in ((axs[0], ctx, "million tokens", "Context tokens read per session", BLUE),
                                (axs[1], out, "thousand tokens", "Output tokens per session", ORANGE),
                                (axs[2], cost, "USD (Claude Code estimate)", "Estimated cost per session (Δ of cumulative)", AQUA)):
        ax.bar(n, v, color=c, width=0.7)
        ax.set_xlabel("session #")
        ax.set_ylabel(lab_)
        ax.set_title(ttl)
    return save(fig, "f8_sessions.png")


def fig_hist(d, G):
    A = d["attempts"]
    bm, bs = d["base"]["tput"]
    fig, ax = plt.subplots(figsize=(W / 2 - 0.2, 3.0))
    ax.hist([a["t"] for a in A], bins=np.arange(1050, 1300, 10), color=BLUE, edgecolor=SURF, lw=0.6)
    ax.axvline(bm, color=INK2, lw=1, ls="--")
    ax.axvspan(bm - bs, bm + bs, color=INK2, alpha=0.12, lw=0)
    ax.text(bm - bs - 2, ax.get_ylim()[1] * 0.95, "noop mean ±1σ ", fontsize=7, color=INK2, va="top", ha="right")
    ax.set_xlabel("throughput (ops/s)")
    ax.set_ylabel("attempts")
    ax.set_title("Distribution of attempt throughput (all 28)")
    return save(fig, "f10_hist.png")


def fig_rank(d, G):
    bm, bs = d["base"]["tput"]
    gs = sorted(G, key=lambda g: g["mean"])
    fig, ax = plt.subplots(figsize=(W, 0.24 * len(gs) + 0.9))
    y = np.arange(len(gs))
    err = [1.96 * g["sd"] / np.sqrt(g["n"]) if g["n"] > 1 else 0 for g in gs]
    ax.axvline(bm, color=INK2, lw=0.9, ls="--")
    ax.axvspan(bm - bs, bm + bs, color=BLUE, alpha=0.12, lw=0)
    ax.errorbar([g["mean"] for g in gs], y, xerr=err, fmt="o", color=BLUE, ms=4.5, lw=1.2, capsize=2.5, mec=SURF)
    ax.set_yticks(y)
    ax.set_yticklabels([f"{g['gid']} {g['members'][0]['short']}  n={g['n']}" + (f"  [{g['ref']}]" if g["ref"] else "") for g in gs], fontsize=7)
    ax.set_xlabel("mean throughput over repeats (ops/s); bars = ±1.96·sd/√n where n≥2")
    ax.set_title("Distinct code versions ranked by mean throughput")
    ax.grid(axis="y", visible=False)
    return save(fig, "f11_rank.png")


def make_all(d, G):
    return dict(timeline=fig_timeline(d), score=fig_score_vs_tput(d), tradeoff=fig_tradeoff(d), groups=fig_groups(d, G),
                best=fig_running_best(d), latency=fig_latency(d), gateway=fig_gateway_time(d), sessions=fig_sessions(d),
                hist=fig_hist(d, G), rank=fig_rank(d, G))
