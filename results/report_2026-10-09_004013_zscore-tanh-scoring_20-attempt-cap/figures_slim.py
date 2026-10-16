"""Figures for the slim report: evolved policies vs the noop baseline on the three scored probes."""
import os

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

import analysis as an

BLUE, ORANGE = "#2a78d6", "#eb6834"
INK, INK2, GRID, SURF = "#0b0b0b", "#52514e", "#dcdbd6", "#fcfcfb"
OUT = os.path.join(an.HERE, "figures", "slim")
os.makedirs(OUT, exist_ok=True)
plt.rcParams.update({
    "font.size": 8, "axes.titlesize": 9, "axes.labelsize": 8, "xtick.labelsize": 7.5, "ytick.labelsize": 7.5,
    "axes.edgecolor": GRID, "axes.labelcolor": INK2, "xtick.color": INK2, "ytick.color": INK2, "text.color": INK,
    "axes.facecolor": SURF, "figure.facecolor": SURF, "axes.grid": True, "grid.color": GRID, "grid.linewidth": 0.5,
    "axes.spines.top": False, "axes.spines.right": False, "legend.frameon": False, "legend.fontsize": 7.5,
    "axes.titleweight": "bold", "axes.titlelocation": "left",
})
W = 10.0
PROBES = [("t", "tput", "Throughput vs baseline (%)  — higher is better", "dt_pct"),
          ("io_v", "io", "Bytes read vs baseline (%)  — lower is better", "dio_pct"),
          ("rf_v", "rf", "Refaults vs baseline (%)  — lower is better", "drf_pct")]


def save(fig, name):
    p = os.path.join(OUT, name)
    fig.savefig(p, dpi=220, bbox_inches="tight", facecolor=SURF)
    plt.close(fig)
    return p


def fig_vs_baseline(d, evolved, best_group):
    """Bars: every evolved attempt's % difference from baseline, per scored probe. Band = baseline ±1σ."""
    fig, axs = plt.subplots(3, 1, figsize=(W, 6.4), sharex=True)
    xs = [a["n"] for a in evolved]
    in_best = {m["n"] for m in best_group["members"]}
    for ax, (_, key, ttl, pk) in zip(axs, PROBES):
        mu, sd = d["base"][key]
        band = 100 * sd / mu
        ax.axhspan(-band, band, color=INK2, alpha=0.13, lw=0)
        ax.axhline(0, color=INK2, lw=0.9)
        vals = [a[pk] for a in evolved]
        cols = [BLUE if a["cls"] == "real" else ORANGE for a in evolved]
        ax.bar(xs, vals, color=cols, width=0.62, edgecolor=[INK if a["n"] in in_best else SURF for a in evolved],
               linewidth=[1.4 if a["n"] in in_best else 0.5 for a in evolved])
        ax.set_ylabel("% vs baseline")
        ax.set_title(f"{ttl}   (shaded: baseline ±1σ = ±{band:.2f}%)")
    axs[-1].set_xticks(xs)
    axs[-1].set_xticklabels([str(x) for x in xs], fontsize=7)
    axs[-1].set_xlabel("attempt # (evolved policies only; blue = real, orange = --tune; black outline = best evolved policy's three measurements)")
    return save(fig, "f1_vs_baseline.png")


def fig_best(d, group):
    fig, axs = plt.subplots(1, 3, figsize=(W, 2.7))
    ms = group["members"]
    for ax, (k, key, ttl, _) in zip(axs, PROBES):
        mu, sd = d["base"][key]
        scale = 1e6 if key == "io" else 1.0
        ax.axhspan((mu - sd) / scale, (mu + sd) / scale, color=INK2, alpha=0.13, lw=0)
        ax.axhline(mu / scale, color=INK2, lw=0.9, ls="--")
        xs = np.arange(len(ms))
        vals = [m[k] / scale for m in ms]
        ax.plot(xs, vals, "o", color=BLUE, ms=6, mec=SURF, mew=0.8)
        ax.hlines(np.mean(vals), -0.35, len(ms) - 0.65, color=INK, lw=1.4)
        for x, m, v in zip(xs, ms, vals):
            ax.annotate(f"#{m['n']} {'tune' if m['cls']=='tune' else 'real'}", (x, v), textcoords="offset points", xytext=(0, 8), ha="center", fontsize=6.5)
        ax.set_xticks(xs)
        ax.set_xticklabels([m["short"] for m in ms], fontsize=7)
        ax.set_xlim(-0.6, len(ms) - 0.4)
        unit = {"tput": "ops/s", "io": "MB", "rf": "refaults"}[key]
        ax.set_ylabel(unit)
        ax.set_title({"tput": "Throughput", "io": "Bytes read", "rf": "Refaults"}[key])
    return save(fig, "f2_best.png")


def make_all(d, evolved, best_group):
    return dict(vs=fig_vs_baseline(d, evolved, best_group), best=fig_best(d, best_group))
