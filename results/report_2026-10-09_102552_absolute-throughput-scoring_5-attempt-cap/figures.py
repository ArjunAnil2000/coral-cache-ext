"""Figures for the run 2026-10-09_102552 report (absolute-throughput scoring). Style per the dataviz skill:
thin marks, recessive grid, ink text, <=3 validated categorical hues, direct labels."""
import os

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.patheffects as pe
import numpy as np

import analysis as an

BLUE, ORANGE, AQUA = "#2a78d6", "#eb6834", "#1baf7a"
INK, INK2, GRID, SURF = "#0b0b0b", "#52514e", "#dcdbd6", "#fcfcfb"
OUT = os.path.join(an.HERE, "figures")
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


def label(ax, text, xy, off, color=INK, size=7, ha="center"):
    ax.annotate(text, xy, textcoords="offset points", xytext=off, fontsize=size, color=color, ha=ha, path_effects=HALO)


def save(fig, name):
    p = os.path.join(OUT, name)
    fig.savefig(p, dpi=220, bbox_inches="tight", facecolor=SURF)
    plt.close(fig)
    return p


def policy_name(a):
    return (a["ref"] + ".c (unmodified)") if a["ref"] else "evolved v1"


def fig_throughput(d):
    A = d["attempts"]
    bm, bs = d["prev"]["base"]["tput"]
    fig, ax = plt.subplots(figsize=(W, 3.4))
    ax.axhspan(bm - 2 * bs, bm + 2 * bs, color=INK2, alpha=0.07, lw=0)
    ax.axhspan(bm - bs, bm + bs, color=INK2, alpha=0.13, lw=0)
    ax.axhline(bm, color=INK2, lw=0.9, ls="--")
    cols = [AQUA if a["ref"] else BLUE for a in A]
    ax.bar([a["n"] for a in A], [a["tput"] for a in A], color=cols, width=0.55)
    for a in A:
        label(ax, f"{a['tput']:.1f}", (a["n"], a["tput"]), (0, 4))
    ax.set_xticks([a["n"] for a in A])
    ax.set_xticklabels([f"#{a['n']}  {policy_name(a)}\n{a['short']}" for a in A], fontsize=7)
    lo = min(a["tput"] for a in A)
    ax.set_ylim(lo - 60, max(a["tput"] for a in A) + 25)
    ax.set_ylabel("throughput = score (ops/s)")
    ax.set_title(f"Score (measured throughput) per attempt — dashed/bands: run-1 noop reference {bm:.1f} ± {bs:.1f} (±1σ, ±2σ), external to this run")
    ax.text(0.01, 0.97, "teal = unmodified reference policy, blue = agent-evolved", transform=ax.transAxes, ha="left", va="top", fontsize=7, color=INK2)
    return save(fig, "f1_throughput.png")


def fig_io(d):
    A = d["attempts"]
    fig, axs = plt.subplots(1, 2, figsize=(W, 3.3))
    for ax, key, xl in ((axs[0], "rbytes_mib", "bytes read from disk during the measured phase (MiB)"), (axs[1], "refault_file", "file refaults during the measured phase")):
        ax.plot([a[key] for a in A], [a["tput"] for a in A], "o", color=BLUE, ms=6, mec=SURF, mew=0.8)
        for a in A:
            label(ax, f"#{a['n']} {a['ref'] or 'v1'}", (a[key], a["tput"]), (6, 4), ha="left", size=6.8)
        xs = np.array([a[key] for a in A]); ys = np.array([a["tput"] for a in A])
        ax.set_xlabel(xl)
        ax.set_ylabel("throughput (ops/s)")
        ax.set_title(f"Throughput vs {'bytes read' if key == 'rbytes_mib' else 'refaults'}  (Pearson r = {an.pearson(xs, ys):+.2f}, n = 5)")
    return save(fig, "f2_io.png")


def fig_crossrun(d):
    A = d["attempts"]
    refs = d["prev"]["refs"]
    bm, bs = d["prev"]["base"]["tput"]
    names = ["get_scan", "s3fifo", "sampling"]
    fig, ax = plt.subplots(figsize=(W, 3.2))
    ax.axhspan(bm - bs, bm + bs, color=INK2, alpha=0.13, lw=0)
    ax.axhline(bm, color=INK2, lw=0.9, ls="--")
    for i, n in enumerate(names):
        r1 = [p["tput"] for p in refs if p["ref"] == n]
        r2 = [a["tput"] for a in A if a["ref"] == n]
        x1 = i - 0.12 + np.linspace(-0.04, 0.04, len(r1))
        ax.plot(x1, r1, "o", color=BLUE, ms=6, mec=SURF, mew=0.8, label="run 1 (z-score scoring, 2026-10-09_004013)" if i == 0 else None)
        ax.plot([i + 0.12] * len(r2), r2, "^", color=ORANGE, ms=6, mec=SURF, mew=0.8, label="run 2 (absolute-throughput scoring, 2026-10-09_102552)" if i == 0 else None)
        label(ax, " / ".join(f"{v:.1f}" for v in sorted(r1, reverse=True)), (x1[0], max(r1)), (-9, 0), ha="right", size=6.8)
        for v in r2:
            label(ax, f"{v:.1f}", (i + 0.12, v), (8, 0), ha="left", size=6.8)
    ax.set_xticks(range(len(names)))
    ax.set_xticklabels([f"{n}.c (unmodified)" for n in names])
    ax.set_xlim(-0.6, len(names) - 0.4)
    ax.set_ylabel("throughput (ops/s)")
    ax.set_title("Identical policy code measured in both runs (band: run-1 noop ±1σ)")
    ax.legend(loc="lower right")
    return save(fig, "f3_crossrun.png")


def make_all(d):
    return dict(tput=fig_throughput(d), io=fig_io(d), cross=fig_crossrun(d))
