#!/usr/bin/env python3
"""Build results/comparison_result/comparison_result.pdf (+ the three best policies as .c files): compare the three 20-attempt CORAL runs
   20-all-seeds-tanh (2026-10-09_004013), 20-all-seeds-abs (2026-10-11_130334), 20-one-seed-abs (2026-10-09_162748).
Reads each run's report data.json plus the policy source from the run's agent worktree (git show)."""
import collections, datetime as dt, difflib, hashlib, html, json, math, os, re, subprocess
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
from reportlab.lib import colors
from reportlab.lib.pagesizes import landscape, letter
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import inch
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import (BaseDocTemplate, Frame, Image, NextPageTemplate, PageBreak, PageTemplate, Paragraph, Spacer, Table, TableStyle, XPreformatted, KeepTogether)

RES = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(RES)
OUTDIR = os.path.join(RES, "comparison_result")
os.makedirs(OUTDIR, exist_ok=True)
OUT = os.path.join(OUTDIR, "comparison_result.pdf")
FIG = os.path.join(os.environ.get("TMPDIR", "/tmp"), "cmp_figs")
os.makedirs(FIG, exist_ok=True)

RUNS = collections.OrderedDict([
    ("20-all-seeds-tanh", dict(dir="2026-10-09_004013", rep="report_2026-10-09_004013_zscore-tanh-scoring_20-attempt-cap",
                               setup="All 7 reference seeds + noop start", scoring="z-score vs noop baseline, squashed with tanh, weighted with bytes read / refaults (branch master)")),
    ("20-all-seeds-abs", dict(dir="2026-10-11_130334", rep="report_2026-10-11_130334_all-seeds_20-attempt-cap",
                              setup="All 7 reference seeds + noop start", scoring="absolute throughput (ops/s)")),
    ("20-one-seed-abs", dict(dir="2026-10-09_162748", rep="report_2026-10-09_162748_single-seed-s3fifo_20-attempt-cap",
                             setup="S3-FIFO is the only seed (starting file)", scoring="absolute throughput (ops/s)")),
])
BLUE, ORANGE, AQUA, RED = "#2a78d6", "#eb6834", "#1baf7a", "#c0392b"
INK, INK2, GRID, SURF = "#0b0b0b", "#52514e", "#dcdbd6", "#fcfcfb"
RUNCOL = {"20-all-seeds-tanh": "#7a5cc7", "20-all-seeds-abs": BLUE, "20-one-seed-abs": ORANGE}


# ------------------------------------------------------------------ data
def key(src):
    keep = [l.rstrip() for l in src.splitlines() if l.strip() and not l.strip().startswith("//")]
    return hashlib.sha1("\n".join(keep).encode()).hexdigest()[:10]


SEEDS = ("fifo", "mru", "s3fifo", "sampling", "get_scan", "mglru", "lhd")
ref_src = {n: open(f"{REPO}/seed/reference/{n}.c").read() for n in SEEDS}
ref_key = {key(v): n for n, v in ref_src.items()}


def banner(src):
    L = src.splitlines()
    i = next(j for j, l in enumerate(L) if l.startswith("// EVOLVE-BLOCK-START"))
    out = []
    for l in L[i + 1:]:
        if not l.startswith("//"):
            break
        out.append(l[3:].strip())
    return " ".join(out)


noop_desc = banner(subprocess.run(["git", "show", "absolute-throughput-score:seed/noop.c"], cwd=REPO, capture_output=True, text=True).stdout)

data = collections.OrderedDict()
for name, r in RUNS.items():
    d = json.load(open(f"{RES}/{r['rep']}/data.json"))
    A = []
    for a in d["attempts"]:
        t = a["tput"]["value"] if isinstance(a["tput"], dict) else a["tput"]
        if not t:
            continue                                  # crashed / no score
        A.append(dict(n=a["n"], hash=a["hash"], short=a["short"], title=a["title"], cls=a["cls"], tput=float(t), key=a["key"], ref=ref_key.get(a["key"]),
                      score=a.get("score"), submit=a["submit"], code_lines=a.get("code_lines")))
    ncr = len(d["attempts"]) - len(A)
    data[name] = dict(A=A, crashed=ncr, n_all=len(d["attempts"]), d=d, ag=f"{RES}/cache-ext-get-scan/{r['dir']}/agents/captain-nemo")
    first, last = d["attempts"][0]["submit"], d["attempts"][-1]["submit"]
    data[name]["minutes"] = (dt.datetime.fromisoformat(last) - dt.datetime.fromisoformat(first)).total_seconds() / 60

noop_base = None
for a in json.load(open(f"{RES}/{RUNS['20-all-seeds-tanh']['rep']}/data.json"))["attempts"][:1]:
    noop_base = (a["tput"]["base_mean"], a["tput"]["base_std"], a["tput"]["base_n"])

s3_all = [(nm, a["tput"]) for nm, v in data.items() for a in v["A"] if a["ref"] == "s3fifo"]
S3 = [t for _, t in s3_all]
s3_mean, s3_sd = float(np.mean(S3)), float(np.std(S3, ddof=1))

# best selections per run
sel = []
for nm, v in data.items():
    A = v["A"]
    own = max([a for a in A if a["score"] is not None], key=lambda a: a["score"])
    real = [a for a in A if a["cls"] == "real"]
    top_real = max(real, key=lambda a: a["tput"])
    top_ev = max([a for a in real if not a["ref"]], key=lambda a: a["tput"])
    sel.append((nm, own, top_real, top_ev))
overall = max((a for nm, v in data.items() for a in v["A"] if a["cls"] == "real"), key=lambda a: a["tput"])
overall_run = next(nm for nm, v in data.items() if overall in v["A"])
best_src = subprocess.run(["git", "show", f"{overall['hash']}:noop.c"], cwd=data[overall_run]["ag"], capture_output=True, text=True, check=True).stdout
assert not overall["ref"]

# ------------------------------------------------------------------ figures
plt.rcParams.update({"font.size": 8, "axes.titlesize": 9, "axes.labelsize": 8, "xtick.labelsize": 7.5, "ytick.labelsize": 7.5, "axes.edgecolor": GRID,
                     "axes.labelcolor": INK2, "xtick.color": INK2, "ytick.color": INK2, "text.color": INK, "axes.facecolor": SURF, "figure.facecolor": SURF,
                     "axes.grid": True, "grid.color": GRID, "grid.linewidth": 0.5, "axes.spines.top": False, "axes.spines.right": False, "legend.frameon": False,
                     "legend.fontsize": 7.5, "axes.titleweight": "bold", "axes.titlelocation": "left"})
ymin = min(a["tput"] for v in data.values() for a in v["A"]) - 25
ymax = max(a["tput"] for v in data.values() for a in v["A"]) + 25


def fig_attempts():
    fig, axs = plt.subplots(1, 3, figsize=(10, 3.5), sharey=True)
    for ax, (nm, v) in zip(axs, data.items()):
        A = v["A"]
        ax.axhline(s3_mean, color=INK2, lw=0.9, ls="--")
        ax.axhspan(s3_mean - s3_sd, s3_mean + s3_sd, color=INK2, alpha=0.1, lw=0)
        for a in A:
            c = AQUA if a["ref"] else BLUE
            ax.plot(a["n"], a["tput"], "^" if a["cls"] == "tune" else "o", color=c, ms=5, mec=SURF, mew=0.6, mfc=c if a["cls"] != "tune" else "none")
        if nm == overall_run:
            ax.plot(overall["n"], overall["tput"], marker="*", color=RED, ms=14, mec=SURF)
            ax.annotate(f"overall best {overall['tput']:.1f}", (overall["n"], overall["tput"]), textcoords="offset points", xytext=(8, 6), fontsize=7, color=RED)
        ax.set_title(f"{nm}  ({len(A)} scored)")
        ax.set_xlabel("attempt number")
        ax.set_ylim(ymin, ymax)
    axs[0].set_ylabel("measured throughput (ops/s)")
    fig.text(0.01, -0.02, "teal = unmodified reference seed, blue = evolved, hollow triangle = --tune attempt, red star = overall best. Dashed line / band: unmodified S3-FIFO, mean ± 1 sd over all runs.", fontsize=7, color=INK2)
    p = f"{FIG}/attempts.png"; fig.savefig(p, dpi=200, bbox_inches="tight", facecolor=SURF); plt.close(fig); return p


def fig_best_so_far():
    fig, ax = plt.subplots(figsize=(10, 3.1))
    ax.axhline(s3_mean, color=INK2, lw=0.9, ls="--")
    for nm, v in data.items():
        real = [a for a in v["A"] if a["cls"] == "real"]
        real.sort(key=lambda a: a["n"])
        x = list(range(1, len(real) + 1)); y = list(np.maximum.accumulate([a["tput"] for a in real]))
        ax.step(x, y, where="post", color=RUNCOL[nm], lw=1.6, label=nm)
        ax.plot(x[-1], y[-1], "o", color=RUNCOL[nm], ms=4)
        ax.annotate(f"{y[-1]:.1f}", (x[-1], y[-1]), textcoords="offset points", xytext=(5, -3), fontsize=7, color=RUNCOL[nm])
    ax.set_xlabel("real attempts submitted (tune attempts excluded)")
    ax.set_ylabel("best throughput so far (ops/s)")
    ax.set_xlim(0.8, 21.5)
    ax.set_xticks(range(1, 21, 1))
    ax.set_title("Best-so-far measured throughput, by run (dashed: unmodified S3-FIFO mean)")
    ax.legend(loc="lower right")
    p = f"{FIG}/bsf.png"; fig.savefig(p, dpi=200, bbox_inches="tight", facecolor=SURF); plt.close(fig); return p


def fig_seeds():
    names = ["noop"] + list(SEEDS)
    fig, ax = plt.subplots(figsize=(10, 3.1))
    for i, n in enumerate(names):
        for j, (nm, v) in enumerate(data.items()):
            vals = [a["tput"] for a in v["A"] if a["ref"] == n]
            if n == "noop" and nm == "20-all-seeds-tanh" and noop_base:
                ax.errorbar(i + (j - 1) * 0.2, noop_base[0], yerr=noop_base[1], fmt="s", color=RUNCOL[nm], ms=5, capsize=2, lw=1)
                continue
            if vals:
                ax.plot([i + (j - 1) * 0.2] * len(vals), vals, "o", color=RUNCOL[nm], ms=5.5, mec=SURF, mew=0.7)
    for nm in data:
        ax.plot([], [], "o", color=RUNCOL[nm], label=nm)
    ax.set_xticks(range(len(names)))
    ax.set_xticklabels([n + (".c" if n != "noop" else " (8-run calib.)") for n in names])
    ax.set_ylabel("throughput (ops/s)")
    ax.set_title("Unmodified seed policies: every measurement, by run")
    ax.legend(loc="lower right", ncol=3)
    p = f"{FIG}/seeds.png"; fig.savefig(p, dpi=200, bbox_inches="tight", facecolor=SURF); plt.close(fig); return p


# ------------------------------------------------------------------ pdf helpers
FONTS = os.path.join(matplotlib.get_data_path(), "fonts", "ttf")
pdfmetrics.registerFont(TTFont("DV", f"{FONTS}/DejaVuSans.ttf"))
pdfmetrics.registerFont(TTFont("DV-B", f"{FONTS}/DejaVuSans-Bold.ttf"))
pdfmetrics.registerFont(TTFont("DVM", f"{FONTS}/DejaVuSansMono.ttf"))
pdfmetrics.registerFontFamily("DV", normal="DV", bold="DV-B", italic="DV", boldItalic="DV-B")
cINK, cINK2 = colors.HexColor(INK), colors.HexColor(INK2)
HDR, ZEBRA, HILITE = colors.HexColor("#ecebe7"), colors.HexColor("#f6f5f2"), colors.HexColor("#fde9e5")
PAGE = landscape(letter)
AW = PAGE[0] - 1.0 * inch
H1 = ParagraphStyle("h1", fontName="DV-B", fontSize=14, leading=17, textColor=cINK, spaceBefore=2, spaceAfter=5)
H2 = ParagraphStyle("h2", fontName="DV-B", fontSize=9.5, leading=12, textColor=cINK, spaceBefore=7, spaceAfter=3)
BODY = ParagraphStyle("body", fontName="DV", fontSize=8, leading=10.5, textColor=cINK, spaceAfter=3)
NOTE = ParagraphStyle("note", fontName="DV", fontSize=6.8, leading=8.6, textColor=cINK2, spaceBefore=1, spaceAfter=2)
HCELL = ParagraphStyle("hcell", fontName="DV-B", fontSize=6.6, leading=7.8, textColor=cINK)
CELL = ParagraphStyle("cell", fontName="DV", fontSize=6.8, leading=8.2, textColor=cINK)
CODE = ParagraphStyle("code", fontName="DVM", fontSize=5.3, leading=6.1, textColor=cINK)


def f(x, n=1):
    return f"{x:,.{n}f}"


def sg(x, n=1):
    return f"{x:+,.{n}f}"


def tbl(rows, widths, fs=7, align=None, highlight=()):
    rows = [[Paragraph(str(c), HCELL) if i == 0 else (Paragraph(str(c), CELL) if isinstance(c, str) and len(c) > 22 else c) for c in row] for i, row in enumerate(rows)]
    widths = [w * inch for w in widths]
    if sum(widths) > AW:
        widths = [w * AW / sum(widths) for w in widths]
    t = Table(rows, colWidths=widths, repeatRows=1, hAlign="LEFT")
    st = [("FONT", (0, 0), (-1, -1), "DV", fs), ("FONT", (0, 0), (-1, 0), "DV-B", fs), ("BACKGROUND", (0, 0), (-1, 0), HDR), ("LINEBELOW", (0, 0), (-1, 0), 0.6, cINK2),
          ("LINEBELOW", (0, -1), (-1, -1), 0.6, cINK2), ("TOPPADDING", (0, 0), (-1, -1), 2), ("BOTTOMPADDING", (0, 0), (-1, -1), 2), ("LEFTPADDING", (0, 0), (-1, -1), 3),
          ("RIGHTPADDING", (0, 0), (-1, -1), 3), ("VALIGN", (0, 0), (-1, -1), "MIDDLE"), ("TEXTCOLOR", (0, 0), (-1, -1), cINK)]
    for i in range(1, len(rows)):
        if i % 2 == 0:
            st.append(("BACKGROUND", (0, i), (-1, i), ZEBRA))
    for i in highlight:
        st.append(("BACKGROUND", (0, i), (-1, i), HILITE))
    for ci, a in enumerate(align or []):
        if a == "R":
            st.append(("ALIGN", (ci, 0), (ci, -1), "RIGHT"))
    t.setStyle(TableStyle(st))
    return t


def img(path, width=AW, maxh=None):
    from PIL import Image as PI
    w, h = PI.open(path).size
    ht = width * h / w
    if maxh and ht > maxh:
        ht, width = maxh, maxh * w / h
    return Image(path, width=width, height=ht, hAlign="LEFT")


def footer(canvas, doc):
    canvas.saveState()
    canvas.setFont("DV", 6.5); canvas.setFillColor(cINK2)
    canvas.drawString(0.5 * inch, 0.3 * inch, "Comparison of three 20-attempt CORAL runs · cache-ext get_scan · 20-all-seeds-tanh vs 20-all-seeds-abs vs 20-one-seed-abs")
    canvas.drawRightString(PAGE[0] - 0.5 * inch, 0.3 * inch, f"page {doc.page}")
    canvas.restoreState()


# ------------------------------------------------------------------ build
def code_listing(src, ref_lines):
    lines = src.splitlines()
    sm = difflib.SequenceMatcher(a=ref_lines, b=lines, autojunk=False)
    changed = set()
    for tag, i1, i2, j1, j2 in sm.get_opcodes():
        if tag != "equal":
            changed.update(range(j1, j2))
    out = []
    for i, line in enumerate(lines):
        txt = html.escape(line.replace("\t", "    "))
        pre = f"{i+1:4d} "
        out.append(f'{pre}<font backColor="#fde9e5">{txt if txt else " "}</font>' if i in changed else pre + txt)
    return [XPreformatted("\n".join(out), CODE)]


def main():
    story = []
    figs = dict(attempts=fig_attempts(), bsf=fig_best_so_far(), seeds=fig_seeds())

    # ---- page 1: overview
    story += [Paragraph("Comparison of three 20-attempt CORAL evolution runs", H1), Paragraph("The runs", H2)]
    rows = [["Run (this report's name)", "CORAL run dir", "Seeds available to the agent", "Scoring (what the agent maximized)", "Attempts (scored real / tune / crashed)", "Wall time", "Highest measured throughput (real)"]]
    for nm, v in data.items():
        r = RUNS[nm]; A = v["A"]
        rows.append([nm, r["dir"], r["setup"], r["scoring"], f"{sum(a['cls']=='real' for a in A)} / {sum(a['cls']=='tune' for a in A)} / {v['crashed']}", f"{v['minutes']:.0f} min",
                     f"{f(max(a['tput'] for a in A if a['cls']=='real'),1)} ops/s"])
    story.append(tbl(rows, [1.25, 1.2, 1.6, 2.5, 1.2, 0.6, 1.2], align=["L", "L", "L", "L", "L", "R", "R"]))
    story.append(Paragraph("All three runs: one Claude Code agent (claude-opus-5-5), 20 real attempts as the stop condition (--tune attempts are graded identically but do not count toward the cap), the same CloudLab node and the same GET-SCAN LevelDB benchmark (4 threads, 95% GET / 5% SCAN, 64 MB page-cache cgroup, 30 s measured phase). Throughput in this report is always the raw ops/s the benchmark measured, even for the tanh run whose own score was a squashed z-score.", NOTE))
    hi = overall
    story.append(Paragraph("Headline", H2))
    ev_best = {s_[0]: s_[2] for s_ in sel}
    bullets = [
        f"<b>Highest measured throughput of any real attempt: {f(hi['tput'],1)} ops/s</b> — <b>{overall_run}</b>, attempt #{hi['n']} (<font name='DVM'>{hi['short']}</font>), an evolved S3-FIFO variant "
        f"({sg(100*(hi['tput']/s3_mean-1),1)}% vs the unmodified S3-FIFO mean of {f(s3_mean,1)} ops/s, n={len(S3)}). Its full code follows the comparison tables, then the best evolved policy of each of the other two runs.",
        f"The three runs' best real throughputs are {', '.join(f'{nm} {f(ev_best[nm]['tput'],1)}' for nm in data)} ops/s — within about {f(100*(hi['tput']-min(ev_best[nm]['tput'] for nm in data))/hi['tput'],1)}% of each other.",
        f"<b>Noise is as large as the differences.</b> Unmodified S3-FIFO alone measured {f(min(S3),1)} … {f(max(S3),1)} ops/s ({f(100*(max(S3)-min(S3))/s3_mean,1)}% of its mean) across {len(S3)} runs/attempts, and identical code re-run inside a run moved by up to several percent (see the noise table). "
        f"No run's best is clearly separated from the unmodified S3-FIFO or from the other runs' bests.",
        "There is no evidence here that seeding all seven policies beat seeding S3-FIFO alone, or that the tanh/bytes-weighted score beat raw throughput: every run's best is a small modification of S3-FIFO (or, in 20-all-seeds-abs, an unmodified MGLRU measurement)."]
    for b in bullets:
        story.append(Paragraph("• " + b, BODY))

    # ---- seeds
    story += [PageBreak(), Paragraph("Seed policies", H1)]
    story.append(Paragraph("Every run starts from <font name='DVM'>seed/noop.c</font> (the no-op / kernel-default-reclaim policy, except 20-one-seed-abs whose starting file is S3-FIFO). The two all-seeds runs also exposed seven complete reference policies in <font name='DVM'>reference/</font> that the agent could copy or adapt; 20-one-seed-abs exposed none. Measurements are single evals of the unmodified file.", BODY))
    rows = [["Seed", "What it does", "tanh run: measured (ops/s)", "all-seeds-abs: measured", "one-seed-abs: measured"]]
    rows.append(["noop.c", noop_desc, f"calibration: {f(noop_base[0],1)} ± {f(noop_base[1],1)} (n={noop_base[2]}, not attempts)" if noop_base else "-", "not evaluated", "not available (S3-FIFO is the start)"])
    for n in SEEDS:
        cells = []
        for nm, v in data.items():
            m = [a for a in v["A"] if a["ref"] == n]
            cells.append(", ".join(f"#{a['n']}: {f(a['tput'],1)}" for a in m) or ("start file" if (nm == "20-one-seed-abs" and n == "s3fifo") else "not run" if nm != "20-one-seed-abs" else "not available"))
        rows.append([n + ".c", banner(ref_src[n]), *cells])
    story.append(tbl(rows, [0.7, 4.3, 1.7, 1.7, 1.6], fs=6.6, align=["L", "L", "L", "L", "L"]))
    story.append(Paragraph(f"Unmodified S3-FIFO is the only seed measured in all three runs: {', '.join(f'{nm} {f(t,1)}' for nm, t in s3_all)} ops/s (mean {f(s3_mean,1)}, sd {f(s3_sd,1)}, n={len(S3)}). The agents ran the other reference policies unmodified only as baselines before adapting them.", NOTE))

    # ---- figures
    story += [PageBreak(), Paragraph("Seeds, every attempt, and best-so-far", H1), img(figs["seeds"], AW, 2.15 * inch), Spacer(1, 3), img(figs["attempts"], AW, 2.75 * inch), Spacer(1, 3), img(figs["bsf"], AW, 2.15 * inch)]

    # ---- best per run
    story += [PageBreak(), Paragraph("Best policy of each run", H1)]
    rows = [["Run", "Selection", "Attempt", "Class", "Policy / change", "Throughput (ops/s)", "vs unmodified S3-FIFO mean"]]
    hl = []
    for nm, own, top_real, top_ev in sel:
        for lab, a in (("run's own score (saved as best/)", own), ("highest measured throughput, real attempts", top_real), ("highest measured throughput, evolved (non-seed) real", top_ev)):
            tag = f"#{a['n']}  {a['short']}"
            rows.append([nm, lab, tag, a["cls"], (a["ref"] + ".c unmodified — " if a["ref"] else "") + a["title"][:150], f(a["tput"], 2), f"{sg(100*(a['tput']/s3_mean-1),2)}%"])
            if a is overall and lab.startswith("highest measured throughput, real"):
                hl.append(len(rows) - 1)
    story.append(tbl(rows, [1.2, 2.0, 0.9, 0.4, 3.9, 0.8, 0.9], fs=6.4, align=["L", "L", "L", "L", "L", "R", "R"], highlight=hl))
    story.append(Paragraph("Shaded: the overall best (highest measured throughput among all real attempts in the three runs). The tanh run's own score ranked a different attempt first because that score rewarded fewer bytes read and refaults as well as throughput; the comparison here is by measured throughput only.", NOTE))
    # noise table: re-measured identical code
    story.append(Paragraph("Identical code measured more than once (noise)", H2))
    rows = [["Run", "Code (attempts)", "Measurements (ops/s)", "Range % of mean"]]
    for nm, v in data.items():
        g = collections.OrderedDict()
        for a in v["A"]:
            g.setdefault(a["key"], []).append(a)
        for k, ms in g.items():
            if len(ms) > 1:
                t = [m["tput"] for m in ms]
                rows.append([nm, (ms[0]["ref"] + ".c unmodified" if ms[0]["ref"] else ms[0]["title"][:62]) + f"  (#{', #'.join(str(m['n']) for m in ms)})", ", ".join(f(x, 1) for x in t), f(100 * (max(t) - min(t)) / np.mean(t), 1)])
    story.append(tbl(rows, [1.2, 5.3, 2.5, 1.0], fs=6.4, align=["L", "L", "L", "R"]))
    story.append(Paragraph(f"The overall best (#{overall['n']} in {overall_run}) was measured once. Its closest relative in the same run, b631bf1b (the same design with a 1/15 small queue), measured 1273.7, 1257.4 and 1273.1 ops/s — a mean near 1268 — so the true level of this design is probably a little below its single 1277.7 reading.", NOTE))

    # ---- best policy: diff + code
    story += [NextPageTemplate("code"), PageBreak(), Paragraph(f"The best policy: {overall_run} attempt #{overall['n']} ({overall['short']}), {f(overall['tput'],2)} ops/s", H1)]
    story.append(Paragraph(f"<b>What it is:</b> {html.escape(overall['title'])}. In practice it is the S3-FIFO reference policy with four small changes (diff below), made by the agent in the 20-all-seeds-tanh run (its commit message says a bigger small queue had cut I/O in an earlier eval):", BODY))
    ref_lines = ref_src["s3fifo"].splitlines()
    best_lines = best_src.splitlines()
    sm = difflib.SequenceMatcher(a=ref_lines, b=best_lines, autojunk=False)
    changed = set()
    diff_rows = []
    for tag, i1, i2, j1, j2 in sm.get_opcodes():
        if tag != "equal":
            changed.update(range(j1, j2))
    expl = ["<b>1. Small queue 1/15 → 1/8 of the cache</b> (<font name='DVM'>cache_size / 15 → cache_size / 8</font>): new folios are kept in the small FIFO longer before eviction decisions move them, so more one-touch pages are filtered in the small queue before reaching the main queue.",
            "<b>2. Scan awareness</b>: reuses the harness-pinned <font name='DVM'>scan_pids</font> map (userspace loader reopens <font name='DVM'>/sys/fs/bpf/cache_ext/scan_pids</font>) and adds <font name='DVM'>is_scanning_pid()</font>.",
            "<b>3. Gated ghost admission</b> (<font name='DVM'>if (!is_scanning_pid() &amp;&amp; folio_in_ghost(folio))</font>): a re-read of a recently evicted page by the scan thread no longer jumps straight into the main queue; only GET-thread reuse earns that.",
            "<b>4. Ghost history 4× larger</b> (<font name='DVM'>ghost_map max_entries = 4 × cache_size</font>): remembers evictions for longer, so the Zipf-hot GET keys are recognised on return."]
    for e in expl:
        story.append(Paragraph(e, BODY))
    story.append(Paragraph("Source file: <font name='DVM'>results/best/run3_best_throughput_2d5d649a.c</font> (and <font name='DVM'>noop.c</font> at that commit in the run's agent worktree). Highlighted lines in the listing below are the lines that differ from the S3-FIFO reference.", NOTE))
    story.append(Paragraph("Full source", H2))
    story += code_listing(best_src, ref_lines)
    # the best evolved policy of the other runs, so every run has its own policy listing
    for nm, own, top_real, top_ev in sel:
        if top_ev is overall:
            continue
        src = subprocess.run(["git", "show", f"{top_ev['hash']}:noop.c"], cwd=data[nm]["ag"], capture_output=True, text=True, check=True).stdout
        sm2 = difflib.SequenceMatcher(a=ref_lines, b=src.splitlines(), autojunk=False)
        nchg = sum(j2 - j1 for tag, i1, i2, j1, j2 in sm2.get_opcodes() if tag != "equal")
        story.append(NextPageTemplate("code"))
        story.append(PageBreak())
        story.append(Paragraph(f"Best evolved policy of {nm}: attempt #{top_ev['n']} ({top_ev['short']}), {f(top_ev['tput'],2)} ops/s", H1))
        story.append(Paragraph(f"<b>What it is:</b> {html.escape(top_ev['title'])}. Its {len(src.splitlines())}-line source differs from the S3-FIFO reference (<font name='DVM'>seed/reference/s3fifo.c</font>) in {nchg} lines (highlighted below). It is the highest-throughput real attempt in this run that is not an unmodified seed ({sg(100*(top_ev['tput']/s3_mean-1),2)}% vs the unmodified S3-FIFO mean).", BODY))
        story.append(Paragraph("Source file: <font name='DVM'>best/best_policy.c</font> in the run's report folder holds this run's own-score best; this attempt's file is <font name='DVM'>noop.c</font> at that commit in the run's agent worktree.", NOTE))
        story += code_listing(src, ref_lines)
    return story


class Doc(BaseDocTemplate):
    pass


def build():
    story = main()
    doc = Doc(OUT, pagesize=PAGE, leftMargin=0.5 * inch, rightMargin=0.5 * inch, topMargin=0.45 * inch, bottomMargin=0.5 * inch,
              title="Comparison of three 20-attempt CORAL runs", author="coral-cache-evolution")
    W, H = PAGE
    main_frame = Frame(0.5 * inch, 0.5 * inch, W - inch, H - 0.95 * inch, id="m", leftPadding=0, rightPadding=0, topPadding=0, bottomPadding=0)
    colw = (W - inch - 0.2 * inch) / 2
    code_frames = [Frame(0.5 * inch + i * (colw + 0.2 * inch), 0.5 * inch, colw, H - 0.95 * inch, id=f"c{i}", leftPadding=0, rightPadding=0, topPadding=0, bottomPadding=0) for i in range(2)]
    doc.addPageTemplates([PageTemplate(id="main", frames=[main_frame], onPage=footer), PageTemplate(id="code", frames=code_frames, onPage=footer)])
    doc.build(story)
    print("wrote", OUT)
    # the best evolved policy of each run, as standalone files next to the PDF
    for nm, own, top_real, top_ev in sel:
        src = subprocess.run(["git", "show", f"{top_ev['hash']}:noop.c"], cwd=data[nm]["ag"], capture_output=True, text=True, check=True).stdout
        p = os.path.join(OUTDIR, f"{nm}_best_{top_ev['short']}_{top_ev['tput']:.1f}opss.c")
        open(p, "w").write(src)
        print("wrote", p, len(src.splitlines()), "lines")


if __name__ == "__main__":
    build()
