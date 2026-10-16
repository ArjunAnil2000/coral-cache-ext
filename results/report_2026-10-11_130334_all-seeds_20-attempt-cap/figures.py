"""Figures for the run 2026-10-11_130334 report (all seeds). Style per the dataviz skill:
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


def fig_throughput(d, A, base_mean, base_sd):
    fig, ax = plt.subplots(figsize=(W, 3.6))
    ax.axhline(base_mean, color=INK2, lw=0.9, ls="--")
    cols = [AQUA if a["ref"] else BLUE for a in A]
    ax.bar([a["n"] for a in A], [a["tput"] for a in A], color=cols, width=0.62)
    for a in A:
        label(ax, f"{a['tput']:.0f}", (a["n"], a["tput"]), (0, 3), size=6.3)
        if a["ref"]:
            label(ax, a["ref"], (a["n"], a["tput"]), (0, 13), size=6, color=INK2)
    ax.set_xticks([a["n"] for a in A])
    ax.set_xticklabels([f"#{a['n']}" for a in A], fontsize=6.5)
    ax.set_ylim(min(a["tput"] for a in A) - 40, max(a["tput"] for a in A) + 30)
    ax.set_ylabel("throughput = score (ops/s)")
    ax.set_title(f"Score per attempt (submission order) — dashed: unmodified S3-FIFO, all measurements pooled, {base_mean:.1f} ops/s")
    ax.set_xlabel("teal = unmodified reference policy (named), blue = agent-evolved. Attempt #10 crashed and has no score (gap).")
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


def fig_repeats(d, A, prev_refs, groups):
    """Same code measured in several runs: each unmodified reference policy (earlier runs vs this run) + re-run evolved designs."""
    names = [n for n in ("fifo", "mru", "s3fifo", "sampling", "get_scan", "mglru", "lhd") if any(a["ref"] == n for a in A)]
    fig, ax = plt.subplots(figsize=(W, 3.4))
    cols = []
    for n in names:
        cols.append((f"{n}.c", [p["tput"] for p in prev_refs if p["ref"] == n], [a["tput"] for a in A if a["ref"] == n]))
    for g in groups:
        if not g["ref"]:
            cols.append((f"evolved\n{g['label']}", [], g["t"]))
    for i, (nm, old, new) in enumerate(cols):
        if old:
            ax.plot(i - 0.1 + np.linspace(-0.03, 0.03, len(old)), old, "o", color=BLUE, ms=5.5, mec=SURF, mew=0.8, label=None)
            label(ax, " / ".join(f"{v:.0f}" for v in old), (i - 0.1, max(old)), (-4, 7), size=6, ha="right")
        ax.plot(i + 0.1 + np.linspace(-0.03, 0.03, len(new)), new, "^", color=ORANGE, ms=6, mec=SURF, mew=0.8, label=None)
        label(ax, " / ".join(f"{v:.0f}" for v in new), (i + 0.1, max(new)), (4, 7), size=6, ha="left")
    ax.set_xticks(range(len(cols)))
    ax.set_xticklabels([c[0] for c in cols], fontsize=7)
    ax.set_ylabel("throughput (ops/s)")
    allv = [v for c in cols for v in c[1] + c[2]]
    ax.set_ylim(min(allv) - 25, max(allv) + 30)
    ax.set_xlim(-0.6, len(cols) - 0.4)
    ax.set_title("Identical code measured more than once: unmodified references (blue = earlier runs, orange = this run) and re-run evolved designs")
    from matplotlib.lines import Line2D
    ax.legend(handles=[Line2D([], [], marker="o", ls="", color=BLUE, label="earlier runs"), Line2D([], [], marker="^", ls="", color=ORANGE, label="this run")], loc="lower right")
    return save(fig, "f3_repeats.png")


def make_all(d, A, base_mean, base_sd, prev_refs, groups):
    return dict(tput=fig_throughput(d, A, base_mean, base_sd), io=fig_io(d, A), cross=fig_repeats(d, A, prev_refs, groups))
