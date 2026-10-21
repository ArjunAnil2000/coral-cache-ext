#!/usr/bin/env python3
"""Four-way comparison of the 2026-10-20 coral runs (one per branch/host).

Writes results/comparison_result_4way/{comparison_result_4way.pdf, <branch>_best_<hash>_<score>.c x4}.
Needs the four report folders (data.json) and the gitignored run dirs under coral-runs/<branch>/results/.
"""
import difflib, glob, html, json, os, subprocess

import matplotlib
import matplotlib.pyplot as plt
import numpy as np
from reportlab.lib import colors
from reportlab.lib.pagesizes import landscape, letter
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import inch
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import (BaseDocTemplate, Frame, Image, NextPageTemplate, PageBreak, PageTemplate, Paragraph,
                                Spacer, Table, TableStyle, XPreformatted)

matplotlib.use("Agg")
RES = os.path.dirname(os.path.abspath(__file__))
RUNS = "/home/aanil/Desktop/ldos/arjua-forks/coral-runs"
OUTDIR = f"{RES}/comparison_result_4way"
os.makedirs(f"{OUTDIR}/figures", exist_ok=True)
ORDER = ["one-host-all-seeds-score-tanh", "one-host-one-seed-score-tanh",
         "one-host-all-seeds-score-maximize-throughput", "one-host-one-seed-score-maximize-throughput"]
SHORT = {"one-host-all-seeds-score-tanh": "all-seeds / tanh", "one-host-one-seed-score-tanh": "one-seed / tanh",
         "one-host-all-seeds-score-maximize-throughput": "all-seeds / max-throughput", "one-host-one-seed-score-maximize-throughput": "one-seed / max-throughput"}
COL = {"one-host-all-seeds-score-tanh": "#2a78d6", "one-host-one-seed-score-tanh": "#eb6834",
       "one-host-all-seeds-score-maximize-throughput": "#1baf7a", "one-host-one-seed-score-maximize-throughput": "#8e5bd0"}
DESC = {  # what each best policy does (from reading its diff against the ancestor seed)
    "one-host-all-seeds-score-tanh": "A rewrite in the spirit of get_scan.c: two lists with no per-folio map for scan pages. Folios added by a scan thread "
        "(the harness's scan_pids map) go to a FIFO SCAN list; everything else goes to a GEN list run as a CLOCK with a 2-bit frequency counter "
        "(kept in a hash map for GEN folios only; an access bumps the counter and does not move the folio). A non-scan access to a scan folio promotes it "
        "to GEN. Eviction drains the SCAN list head first (oldest, already consumed scan pages), then the GEN head.",
    "one-host-one-seed-score-tanh": "Unmodified S3-FIFO except for one rule: a ghost-map hit (a folio re-referenced soon after eviction) re-enters the small "
        "probation queue with freq=1, so one more access promotes it, instead of going straight to the main queue. A 12-line diff.",
    "one-host-all-seeds-score-maximize-throughput": "MGLRU (multi-generational LRU port) with one change: folios added by a scan thread (found through the pinned "
        "scan_pids map, reused by the loader) are inserted into the youngest generation instead of the normal placement. The agent reported that every "
        "variant that demoted scan folios lost throughput, so it tried protecting them.",
    "one-host-one-seed-score-maximize-throughput": "S3-FIFO plus scan-thread detection without the harness map: a thread that adds at least 25% of all folios in an "
        "epoch of 2^11 adds is treated as the scanner. Its folios go to a dedicated SCAN list that is evicted first, and its accesses do not count as hotness. "
        "A reserve of cache/256 and a frequency cap of 3 are also used. This attempt is a re-measurement of an earlier design (#3 5397e6b9), identical apart from a comment.",
}


def git(*a, cwd):
    r = subprocess.run(["git", *a], cwd=cwd, capture_output=True, text=True)
    return r.stdout if r.returncode == 0 else ""


def norm(src):
    return [l.rstrip() for l in src.splitlines()]


# ------------------------------------------------------------------ load
R = {}
for b in ORDER:
    rep = glob.glob(f"{RES}/report_2026-10-20_*{b}_20-attempt-cap")[0]
    d = json.load(open(f"{rep}/data.json"))
    ag = glob.glob(f"{RUNS}/{b}/results/cache-ext-get-scan/{d['run']}/agents/captain-nemo")[0]
    A = d["attempts"]
    for a in A:
        a["src"] = git("show", f"{a['hash']}:noop.c", cwd=ag)
    real = [a for a in A if a["cls"] == "real"]
    scored = [a for a in real if not a["crashed"]]
    best = max(scored, key=lambda a: a["score"])
    mx = max(scored, key=lambda a: a["tput"])
    refs = {"noop" if d["seeds"] == "all" else "s3fifo": open(f"{RUNS}/{b}/seed/noop.c").read()}
    if d["seeds"] == "all":
        for f in sorted(glob.glob(f"{RUNS}/{b}/seed/reference/*.c")):
            refs[os.path.basename(f)[:-2]] = open(f).read()
    sims = sorted(((difflib.SequenceMatcher(None, norm(v), norm(best["src"]), autojunk=False).ratio(), n) for n, v in refs.items()), reverse=True)
    byshort = {a["short"]: a for a in A}
    root, c = None, best
    while c:
        root = c; c = byshort.get(c["parent"])
    if sims[0][0] >= 0.80:
        anc, how = sims[0][1], f"closest seed by line similarity ({sims[0][0]:.0%})"
    else:
        anc = root["ref"] or sims[0][1]
        how = f"heavily rewritten (closest seed only {sims[0][0]:.0%} similar); lineage root is attempt #{root['n']} ({root['ref'] or 'n/a'}.c)"
    ndiff = sum(1 for l in difflib.unified_diff(norm(refs[anc]), norm(best["src"]), lineterm="", n=0) if l[:1] in "+-" and l[:3] not in ("+++", "---"))
    R[b] = dict(d=d, A=A, real=real, scored=scored, best=best, mx=mx, refs=refs, anc=anc, how=how, sims=sims, ndiff=ndiff, rep=rep,
                unmod=[a for a in scored if a["ref"] == anc], ag=ag)
    open(f"{OUTDIR}/{b}_best_{best['short']}_{best['score']:.3f}.c".replace("_0.", "_0.") if d["mode"] == "tanh" else
         f"{OUTDIR}/{b}_best_{best['short']}_{best['score']:.1f}opss.c", "w").write(best["src"])

# ------------------------------------------------------------------ figures
INK, INK2, GRID, SURF = "#0b0b0b", "#52514e", "#dcdbd6", "#fcfcfb"
plt.rcParams.update({"font.size": 8, "axes.edgecolor": GRID, "axes.labelcolor": INK2, "xtick.color": INK2, "ytick.color": INK2, "text.color": INK,
                     "axes.facecolor": SURF, "figure.facecolor": SURF, "axes.grid": True, "grid.color": GRID, "grid.linewidth": 0.5,
                     "axes.spines.top": False, "axes.spines.right": False, "axes.titleweight": "bold", "axes.titlelocation": "left"})


def save(fig, name):
    p = f"{OUTDIR}/figures/{name}"; fig.savefig(p, dpi=200, bbox_inches="tight", facecolor=SURF); plt.close(fig); return p


fig, axs = plt.subplots(2, 2, figsize=(10, 5.6))
for ax, b in zip(axs.flat, ORDER):
    r = R[b]; tanh = r["d"]["mode"] == "tanh"
    for a in r["A"]:
        if a["crashed"]:
            ax.plot(a["n"], 0.02, "x", color="#c0392b", transform=ax.get_xaxis_transform(), clip_on=False); continue
        if a["cls"] != "real":
            ax.bar(a["n"], a["score"], color="#c9c8c3", width=0.65)
        elif a["ref"]:
            ax.bar(a["n"], a["score"], facecolor=SURF, edgecolor=COL[b], hatch="////", lw=0.8, width=0.65)
        else:
            ax.bar(a["n"], a["score"], color=COL[b], width=0.65)
    ax.axhline(r["best"]["score"], color=INK2, lw=0.7, ls="--")
    sc = [a["score"] for a in r["A"] if not a["crashed"]]
    ax.set_ylim((min(sc + [0]) * 1.25) if tanh else min(sc) * 0.8, max(sc) * 1.1)
    ax.set_xticks(range(1, len(r["A"]) + 1, 2)); ax.tick_params(labelsize=6.5)
    ax.set_title(f"{SHORT[b]} ({r['d']['host']}) — best {r['best']['score']:.3f}" if tanh else f"{SHORT[b]} ({r['d']['host']}) — best {r['best']['score']:.1f} ops/s", fontsize=8.5)
    ax.set_ylabel("score (tanh z)" if tanh else "ops/s")
fig.text(0.5, -0.01, "solid = evolved, hatched = unmodified seed/reference, grey = tune attempt, red x = crashed; dashed = run's best. Each panel has its own scale.", ha="center", fontsize=7.5, color=INK2)
fig.tight_layout()
F1 = save(fig, "c1_scores.png")

fig, axs = plt.subplots(1, 2, figsize=(10, 3.6))
for b in ORDER:
    r = R[b]; xs = [i for i, a in enumerate(r["scored"], 1)]
    ts = [a["tput"] for a in r["scored"]]
    axs[0].plot(xs, ts, "-o", color=COL[b], ms=2.8, lw=0.8, label=SHORT[b] + f" ({r['d']['host']})")
    um = [(i, a["tput"]) for i, a in enumerate(r["scored"], 1) if a["ref"]]
    axs[0].plot([u[0] for u in um], [u[1] for u in um], "o", mfc=SURF, mec=COL[b], ms=6.5, mew=1.2)
    axs[1].step(xs, np.maximum.accumulate(ts), where="post", color=COL[b], lw=1.5)
axs[0].set_title("Throughput per scored real attempt (hollow = unmodified)", fontsize=8.5); axs[0].set_xlabel("scored real attempt"); axs[0].set_ylabel("ops/s")
axs[0].legend(fontsize=6.5, frameon=False, loc="lower right")
axs[1].set_title("Best throughput so far", fontsize=8.5); axs[1].set_xlabel("scored real attempt"); axs[1].set_ylabel("ops/s")
import matplotlib.ticker as mt
for a_ in axs: a_.xaxis.set_major_locator(mt.MaxNLocator(integer=True))
fig.text(0.5, -0.02, "Hosts differ in speed: compare shapes within a run, not levels across runs.", ha="center", fontsize=7.5, color=INK2)
fig.tight_layout()
F2 = save(fig, "c2_throughput.png")

# ------------------------------------------------------------------ PDF
ttf = os.path.join(os.path.dirname(matplotlib.__file__), "mpl-data/fonts/ttf")
for n, f in (("DV", "DejaVuSans.ttf"), ("DVB", "DejaVuSans-Bold.ttf"), ("DVM", "DejaVuSansMono.ttf")):
    pdfmetrics.registerFont(TTFont(n, os.path.join(ttf, f)))
H1 = ParagraphStyle("h1", fontName="DVB", fontSize=15, leading=19, spaceAfter=6)
H2 = ParagraphStyle("h2", fontName="DVB", fontSize=10.5, leading=14, spaceBefore=8, spaceAfter=4)
P = ParagraphStyle("p", fontName="DV", fontSize=8.2, leading=11.2, spaceAfter=3)
S = ParagraphStyle("s", fontName="DV", fontSize=6.8, leading=8.6)
CODE = ParagraphStyle("c", fontName="DVM", fontSize=5.2, leading=6.1)
PW, PH = landscape(letter); M = 0.5 * inch
doc = BaseDocTemplate(f"{OUTDIR}/comparison_result_4way.pdf", pagesize=landscape(letter), leftMargin=M, rightMargin=M, topMargin=M, bottomMargin=M,
                      title="Four-way comparison of the 2026-10-20 coral runs")
gap = 0.2 * inch; fw = (PW - 2 * M - gap) / 2
doc.addPageTemplates([PageTemplate("main", [Frame(M, M, PW - 2 * M, PH - 2 * M, id="m")]),
                      PageTemplate("code", [Frame(M, M, fw, PH - 2 * M, id="l", leftPadding=2, rightPadding=2),
                                            Frame(M + fw + gap, M, fw, PH - 2 * M, id="r", leftPadding=2, rightPadding=2)])])


def tbl(rows, widths, fs=6.8):
    rows = [[Paragraph(f"<b>{c}</b>", ParagraphStyle("hd", fontName="DVB", fontSize=fs, leading=fs + 1.6)) if i == 0 and isinstance(c, str) else c for c in row] for i, row in enumerate(rows)]
    t = Table(rows, colWidths=widths, repeatRows=1)
    t.setStyle(TableStyle([("FONT", (0, 0), (-1, -1), "DV", fs), ("FONT", (0, 0), (-1, 0), "DVB", fs), ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#ecebe6")),
                           ("VALIGN", (0, 0), (-1, -1), "TOP"), ("GRID", (0, 0), (-1, -1), 0.25, colors.HexColor(GRID)),
                           ("TOPPADDING", (0, 0), (-1, -1), 2), ("BOTTOMPADDING", (0, 0), (-1, -1), 2)]))
    return t


def pc(t, st=S): return Paragraph(t, st)


def sfmt(r, v): return f"{v:.3f}" if r["d"]["mode"] == "tanh" else f"{v:.1f}"


st = [Paragraph("Four-way comparison: coral runs of 2026-10-20", H1)]
st.append(Paragraph("Four 20-real-attempt CORAL evolutions, one per branch, each on its own CloudLab host so that no two instances shared a node. "
                    "The branches cross two choices: <b>seeds</b> (all seven reference policies, or S3-FIFO only) and <b>scoring</b> "
                    "(baseline-normalised tanh z-score, or absolute throughput in ops/s). Only these four runs are compared here.", P))
rows = [["run", "scoring", "seeds", "host", "real / tune / crashed", "wall", "LLM cost", "best score", "its tput (ops/s)", "max tput (ops/s)"]]
for b in ORDER:
    r = R[b]; d = r["d"]
    rows.append([pc(f"<b>{SHORT[b]}</b>"), "tanh z-score" if d["mode"] == "tanh" else "absolute ops/s", "7 + no-op" if d["seeds"] == "all" else "S3-FIFO only",
                 d["host"], f"{len(r['real'])} / {sum(a['cls'] != 'real' for a in r['A'])} / {sum(a['crashed'] for a in r['real'])}", f"{d['wall_hours']:.2f} h",
                 f"${sum(s['cost'] for s in d['sessions']):.0f}", pc(f"#{r['best']['n']} {r['best']['short']}  <b>{sfmt(r, r['best']['score'])}</b>"),
                 f"{r['best']['tput']:.1f}", f"{r['mx']['tput']:.1f} (#{r['mx']['n']})"])
st.append(tbl(rows, [1.5 * inch, 0.85 * inch, 0.8 * inch, 0.5 * inch, 1.0 * inch, 0.5 * inch, 0.55 * inch, 1.6 * inch, 0.7 * inch, PW - 2 * M - 8.0 * inch]))
st.append(Paragraph("How to read this", H2))
for t in ("<b>The hosts are different machines.</b> All four are 2-core, ~2 GB Xeons, but the same code runs at different speeds on them: "
          "unmodified S3-FIFO measured about 645 ops/s on pc309 and 637 on pc319, while evolved S3-FIFO variants sit around 520-540 on pc320. "
          "Throughput levels are therefore not comparable across runs; only the change within a run is.",
          "<b>Scores are on two scales.</b> tanh scores (in [-1, 1]) are relative to each host's own vanilla-kernel no-op baseline (n=8, "
          "553 ± 109 ops/s on pc306 and 549 ± 101 on pc309; the std is ~20%, so z-scores are noisy). Absolute scores are raw ops/s.",
          "<b>The first evaluation on a host reads low in some runs</b> (pc319 first eval 303 vs about 640 for later unmodified policies; pc320 372 vs about 520-540 for its later attempts). "
          "I list such measurements but flag them; do not use them as a baseline.",
          "Differences of a few percent are within measurement noise (earlier runs saw 1-4% for identical code). "
          "No best policy was re-measured enough to separate it from its seed."):
    st.append(Paragraph("• " + t, P))
st.append(PageBreak())
st.append(Image(F1, width=9.2 * inch, height=9.2 * inch * 0.56 * 0.98))
st.append(PageBreak())
st.append(Image(F2, width=9.2 * inch, height=9.2 * inch * 0.36))
st.append(Paragraph("Dots are the same quantity (throughput) for every run, but each run has its own host.", P))
st.append(PageBreak())

# ---- final comparison table
st.append(Paragraph("Best evolved policy versus the seed it descends from (same host, same run)", H2))
hd = ["run (host)", "policy", "ancestor seed", "throughput ops/s", "MiB read", "MiB written", "read I/Os", "refaults", "major faults", "changed lines vs seed"]
rows = [hd]


def mean_of(xs):
    xs = [x for x in xs if x is not None]
    return sum(xs) / len(xs) if xs else None


def cell(v, f="{:.0f}"): return "n/r" if v is None else f.format(v)


def delta(v, base, f="{:+.1f}%"):
    return "" if v is None or not base else "  (" + f.format(100 * (v / base - 1)) + ")"


for b in ORDER:
    r = R[b]; best = r["best"]; um = r["unmod"]
    rows.append([pc(f"<b>{SHORT[b]}</b> ({r['d']['host']})"), pc(f"best evolved #{best['n']} {best['short']}"), pc(f"{r['anc']}.c — {r['how']}"),
                 f"{best['tput']:.1f}", cell(best["rbytes_mib"]), cell(best.get("wbytes_mib")), cell(best.get("rios")), cell(best["refault"]),
                 cell(best.get("pgmajfault")), f"{r['ndiff']} added+removed (policy: {len(best['src'].splitlines())} lines)"])
    if um:
        mt = mean_of([a["tput"] for a in um])
        note = "".join(f"#{a['n']} " for a in um)
        rows.append([pc("&nbsp;"), pc(f"unmodified {r['anc']}.c, measured {len(um)}x ({note.strip()})"), pc("seed"),
                     f"{mt:.1f}{delta(best['tput'], mt)}", cell(mean_of([a['rbytes_mib'] for a in um])) + delta(best["rbytes_mib"], mean_of([a['rbytes_mib'] for a in um])),
                     cell(mean_of([a.get("wbytes_mib") for a in um])), cell(mean_of([a.get("rios") for a in um])),
                     cell(mean_of([a["refault"] for a in um])) + delta(best["refault"], mean_of([a["refault"] for a in um])),
                     cell(mean_of([a.get("pgmajfault") for a in um])), ""])
    else:
        rows.append([pc("&nbsp;"), pc(f"unmodified {r['anc']}.c: not measured in this run"), pc("seed"), "-", "-", "-", "-", "-", "-", ""])
    if r["d"]["baseline"]:
        bt = r["d"]["baseline"]["throughput"]
        rows.append([pc("&nbsp;"), pc("vanilla-kernel no-op baseline (grader calibration, n=8)"), pc("none"), f"{bt[0]:.1f} ± {bt[1]:.1f}", "", "", "", "", "", ""])
st.append(tbl(rows, [1.3 * inch, 1.9 * inch, 1.9 * inch, 1.0 * inch, 0.75 * inch, 0.6 * inch, 0.55 * inch, 0.8 * inch, 0.5 * inch, PW - 2 * M - 9.3 * inch], fs=6.4))
st.append(Spacer(1, 4))
for t in ("n/r = not recorded: the tanh feedback only reports bytes read, refaults and throughput. Percentages are best vs the unmodified-seed mean of this run.",
          "<b>Flagged baselines.</b> The unmodified-seed rows for all-seeds/tanh (get_scan, #1: 495.7) and one-seed/max-throughput (S3-FIFO, #1: 371.9) are each the run's first evaluation on a host, "
          "and first evaluations read low (see the first page). The gains against those rows are inflated and should not be quoted as improvements. "
          "The cleaner comparisons are one-seed/tanh (S3-FIFO measured twice, 645.0 and 645.6, against a best of 647.6: +0.4%, inside noise) and all-seeds/max-throughput (MGLRU 657.6 against 679.3: +3.3%, one measurement each).",
          "A policy's best score is the maximum over 20 noisy attempts, so it is biased upward relative to its seed's single measurement."):
    st.append(Paragraph("• " + t, P))

# ---- best policies
for b in ORDER:
    r = R[b]; best = r["best"]
    st.append(NextPageTemplate("code")); st.append(PageBreak())
    st.append(Paragraph(f"{SHORT[b]} ({r['d']['host']}): best policy #{best['n']} {best['short']} — score {sfmt(r, best['score'])}, {best['tput']:.1f} ops/s", H2))
    st.append(Paragraph(html.escape(DESC[b]), P))
    st.append(Paragraph(f"Agent's title for the attempt: <i>{html.escape(best['title'][:420])}</i>", P))
    st.append(Paragraph(f"Ancestor: <b>{r['anc']}.c</b>, {r['how']}. Lines that differ from the ancestor are highlighted.", P))
    ref = set(norm(r["refs"][r["anc"]]))
    out = []
    for l in best["src"].splitlines():
        e = html.escape(l.rstrip().expandtabs(4)) or " "
        out.append(f'<span backColor="#fff1b8">{e}</span>' if l.rstrip() not in ref and l.strip() else e)
    for i in range(0, len(out), 120):
        st.append(XPreformatted("\n".join(out[i:i + 120]), CODE))
    st.append(NextPageTemplate("main"))
doc.build(st)
print("built", OUTDIR)
for b in ORDER:
    r = R[b]; print(SHORT[b], r["anc"], r["how"], "diff", r["ndiff"], "unmod", [(a["n"], a["tput"]) for a in r["unmod"]])
