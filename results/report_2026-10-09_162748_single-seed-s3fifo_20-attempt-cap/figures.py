"""Figures for the run 2026-10-09_162748 report (single seed: S3-FIFO). Style per the dataviz skill:
thin marks, recessive grid, ink text, <=3 categorical hues, direct labels."""
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


def fig_throughput(d, A, seed_mean, seed_sd):
    fig, ax = plt.subplots(figsize=(W, 3.6))
    ax.axhline(seed_mean, color=INK2, lw=0.9, ls="--")
    cols = [AQUA if a["ref"] else (ORANGE if a["cls"] == "tune" else BLUE) for a in A]
    ax.bar([a["n"] for a in A], [a["tput"] for a in A], color=cols, width=0.62)
    for a in A:
        label(ax, f"{a['tput']:.0f}", (a["n"], a["tput"]), (0, 3), size=6.3)
    ax.set_xticks([a["n"] for a in A])
    ax.set_xticklabels([f"#{a['n']}" for a in A], fontsize=6.5)
    ax.set_ylim(min(a["tput"] for a in A) - 40, max(a["tput"] for a in A) + 18)
    ax.set_ylabel("throughput = score (ops/s)")
    ax.set_title(f"Score per attempt (in submission order) — dashed: mean of the unmodified S3-FIFO seed in this run, {seed_mean:.1f} ops/s")
    ax.set_xlabel("teal = unmodified seed, blue = evolved (real), orange = evolved (--tune). Attempts #8 and #13 crashed and have no score (gaps).")
    return save(fig, "f1_throughput.png")


def fig_io(d, A):
    fig, axs = plt.subplots(1, 2, figsize=(W, 3.3))
    for ax, key, xl in ((axs[0], "rbytes_mib", "bytes read from disk during the measured phase (MiB)"), (axs[1], "refault_file", "file refaults during the measured phase")):
        xs = np.array([a[key] for a in A], float); ys = np.array([a["tput"] for a in A], float)
        ax.plot(xs, ys, "o", color=BLUE, ms=5, mec=SURF, mew=0.8)
        for a in A:
            label(ax, f"#{a['n']}", (a[key], a["tput"]), (5, 3), ha="left", size=6.3)
        ax.set_xlabel(xl)
        ax.set_ylabel("throughput (ops/s)")
        ax.set_title(f"Throughput vs {'bytes read' if key == 'rbytes_mib' else 'refaults'}  (Pearson r = {an.pearson(xs, ys):+.2f}, n = {len(A)})")
    return save(fig, "f2_io.png")


def fig_repeats(d, A, seed_runs, groups):
    """Repeated measurements of identical code: the seed in three runs + the evolved designs the agent re-ran in this run."""
    fig, ax = plt.subplots(figsize=(W, 3.3))
    cols = [("S3-FIFO seed\n(this run)", [a["tput"] for a in A if a["ref"]], BLUE)]
    for name, vals in seed_runs:
        cols.append((f"S3-FIFO seed\n{name}", vals, ORANGE))
    for g in groups:
        cols.append((f"{g['label']}\n(this run)", g["t"], BLUE))
    for i, (nm, vals, c) in enumerate(cols):
        x = i + np.linspace(-0.06, 0.06, len(vals)) if len(vals) > 1 else [i]
        ax.plot(x, vals, "o", color=c, ms=6, mec=SURF, mew=0.8)
        for xx, v in zip(x, sorted(vals, reverse=True) if len(vals) > 1 else vals):
            pass
        label(ax, " / ".join(f"{v:.1f}" for v in vals), (i, max(vals)), (0, 7), size=6.5)
    ax.set_xticks(range(len(cols)))
    ax.set_xticklabels([c[0] for c in cols], fontsize=6.8)
    ax.set_ylabel("throughput (ops/s)")
    lo = min(min(c[1]) for c in cols); hi = max(max(c[1]) for c in cols)
    ax.set_ylim(lo - 15, hi + 20)
    ax.set_title("Identical code measured more than once (blue = this run, orange = earlier runs)")
    return save(fig, "f3_repeats.png")


def make_all(d, A, seed_mean, seed_sd, seed_runs, groups):
    return dict(tput=fig_throughput(d, A, seed_mean, seed_sd), io=fig_io(d, A), cross=fig_repeats(d, A, seed_runs, groups))
