#!/usr/bin/env python3
"""SLIM report (2026-10-09 10:43): only the parameters used in the score normalization (throughput, bytes read, refaults),
the evolved policies compared against the noop baseline, and the best evolved policy at the end."""
import collections
import difflib
import math
import os
import subprocess
import sys

import matplotlib
import numpy as np
from reportlab.lib import colors
from reportlab.lib.pagesizes import landscape, letter
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import inch
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import Image, PageBreak, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import analysis as an  # noqa: E402
import figures_slim as fg  # noqa: E402

def _find_repo(p):
    """Walk up from this folder to the repo root (the directory containing task.yaml)."""
    while p != os.path.dirname(p) and not os.path.exists(os.path.join(p, "task.yaml")):
        p = os.path.dirname(p)
    return p


REPO = _find_repo(an.HERE)
FONTS = os.path.join(matplotlib.get_data_path(), "fonts", "ttf")
pdfmetrics.registerFont(TTFont("DV", os.path.join(FONTS, "DejaVuSans.ttf")))
pdfmetrics.registerFont(TTFont("DV-B", os.path.join(FONTS, "DejaVuSans-Bold.ttf")))
pdfmetrics.registerFontFamily("DV", normal="DV", bold="DV-B", italic="DV", boldItalic="DV-B")
INK, INK2 = colors.HexColor("#0b0b0b"), colors.HexColor("#52514e")
HDR, ZEBRA, HILITE = colors.HexColor("#ecebe7"), colors.HexColor("#f6f5f2"), colors.HexColor("#dfeaf8")
PAGE = landscape(letter)
AW = PAGE[0] - 1.0 * inch
H1 = ParagraphStyle("h1", fontName="DV-B", fontSize=14, leading=17, textColor=INK, spaceBefore=2, spaceAfter=5)
H2 = ParagraphStyle("h2", fontName="DV-B", fontSize=9.5, leading=12, textColor=INK, spaceBefore=7, spaceAfter=3)
NOTE = ParagraphStyle("note", fontName="DV", fontSize=6.8, leading=8.6, textColor=INK2, spaceBefore=1, spaceAfter=2)
HCELL = ParagraphStyle("hcell", fontName="DV-B", fontSize=6.4, leading=7.6, textColor=INK)
CELL = ParagraphStyle("cell", fontName="DV", fontSize=6.4, leading=7.6, textColor=INK)
W_T, W_IO, W_RF = 2.0, 0.5, 0.25


def f(x, n=1):
    return "-" if x is None or (isinstance(x, float) and math.isnan(x)) else f"{x:,.{n}f}"


def sg(x, n=1):
    return "-" if x is None or (isinstance(x, float) and math.isnan(x)) else f"{x:+,.{n}f}"


def tbl(rows, widths, fs=6.8, align=None, hdr_rows=1, extra=None, highlight=(), bold_rows=(), wrap_from=26):
    rows = [[Paragraph(str(c), HCELL) if i < hdr_rows else (Paragraph(str(c), CELL) if isinstance(c, str) and len(c) > wrap_from else c)
             for c in r] for i, r in enumerate(rows)]
    widths = [w * inch for w in widths]
    if sum(widths) > AW:
        widths = [w * AW / sum(widths) for w in widths]
    t = Table(rows, colWidths=widths, repeatRows=hdr_rows, hAlign="LEFT")
    st = [("FONT", (0, 0), (-1, -1), "DV", fs), ("BACKGROUND", (0, 0), (-1, hdr_rows - 1), HDR),
          ("LINEBELOW", (0, hdr_rows - 1), (-1, hdr_rows - 1), 0.6, INK2), ("LINEBELOW", (0, -1), (-1, -1), 0.6, INK2),
          ("TOPPADDING", (0, 0), (-1, -1), 1.8), ("BOTTOMPADDING", (0, 0), (-1, -1), 1.8), ("LEFTPADDING", (0, 0), (-1, -1), 3),
          ("RIGHTPADDING", (0, 0), (-1, -1), 3), ("VALIGN", (0, 0), (-1, -1), "MIDDLE"), ("VALIGN", (0, 0), (-1, hdr_rows - 1), "BOTTOM"),
          ("TEXTCOLOR", (0, 0), (-1, -1), INK)]
    for i in range(hdr_rows, len(rows)):
        if (i - hdr_rows) % 2 == 1:
            st.append(("BACKGROUND", (0, i), (-1, i), ZEBRA))
    for i in highlight:
        st.append(("BACKGROUND", (0, i), (-1, i), HILITE))
    for i in bold_rows:
        st.append(("FONT", (0, i), (-1, i), "DV-B", fs))
    for ci, a in enumerate(align or []):
        if a in "RC":
            st.append(("ALIGN", (ci, hdr_rows), (ci, -1), "RIGHT" if a == "R" else "CENTER"))
    t.setStyle(TableStyle(st + (extra or [])))
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
    canvas.setFont("DV", 6.5)
    canvas.setFillColor(INK2)
    canvas.drawString(0.5 * inch, 0.3 * inch, "CORAL run 2026-10-09_004013 · cache-ext get_scan · evolved policies vs noop baseline · scored probes only")
    canvas.drawRightString(PAGE[0] - 0.5 * inch, 0.3 * inch, f"page {doc.page}")
    canvas.restoreState()


def contribs(t, io, rf, base):
    """Recompute the grader's score from raw values: z vs baseline, tanh, weighted mean."""
    z = [(t - base["tput"][0]) / base["tput"][1], (io - base["io"][0]) / base["io"][1], (rf - base["rf"][0]) / base["rf"][1]]
    c = [math.tanh(z[0]), math.tanh(-z[1]), math.tanh(-z[2])]
    return z, c, (W_T * c[0] + W_IO * c[1] + W_RF * c[2]) / (W_T + W_IO + W_RF)


def comp_header():
    top = ["#", "Commit", "Cls", "Throughput (ops/s)", "", "", "", "Bytes read (MB)", "", "", "", "Refaults (count)", "", "", "", "Score", "Description"]
    sub = ["", "", "", "value", "Δ%", "z", "contrib", "value", "Δ%", "z", "contrib", "value", "Δ%", "z", "contrib", "", ""]
    span = [("SPAN", (3, 0), (6, 0)), ("SPAN", (7, 0), (10, 0)), ("SPAN", (11, 0), (14, 0))]
    return [top, sub], span


W_COMP = [0.26, 0.6, 0.34, 0.58, 0.4, 0.36, 0.46, 0.5, 0.4, 0.36, 0.46, 0.52, 0.4, 0.36, 0.46, 0.52, 3.0]
AL_COMP = ["R", "L", "L"] + ["R"] * 13 + ["L"]


def comp_row(a):
    d = a["_d"]
    z = [a["tput"]["z"], a["io"]["z"], a["rf"]["z"]]
    c = [a["tput"]["contrib"], a["io"]["contrib"], a["rf"]["contrib"]]
    t = a["title"]
    return [a["n"], a["short"], a["cls"], f(a["t"], 1), sg(a["dt_pct"], 1), sg(z[0], 1), sg(c[0], 2), f(a["io_v"] / 1e6, 1), sg(a["dio_pct"], 1), sg(z[1], 1), sg(c[1], 2),
            f(a["rf_v"], 0), sg(a["drf_pct"], 1), sg(z[2], 1), sg(c[2], 2), f(a["score"], 4), (t[:100] + "…") if len(t) > 100 else t]


def main():
    d = an.load()
    A = d["attempts"]
    for a in A:
        a["_d"] = d
    G = an.groups(A)
    base = d["base"]
    bt, bts = base["tput"]
    bi, bis = base["io"]
    br, brs = base["rf"]
    # sanity: the displayed normalization reproduces every recorded score
    for a in A:
        _, _, s = contribs(a["t"], a["io_v"], a["rf_v"], base)
        assert abs(s - a["score"]) < 2e-3, (a["n"], s, a["score"])

    ref_keys = {a["key"] for a in A if a["ref"]}
    refs = [a for a in A if a["key"] in ref_keys]
    evolved = [a for a in A if a["key"] not in ref_keys]
    real_ev = [a for a in evolved if a["cls"] == "real"]
    best = max(real_ev, key=lambda a: a["score"])
    bg = next(g for g in G if g["key"] == best["key"])
    figs = fg.make_all(d, evolved, bg)

    # best policy source + diff vs reference s3fifo
    ag = os.path.join(REPO, "results", "cache-ext-get-scan", d["run"], "agents", "captain-nemo")
    src = subprocess.run(["git", "show", f"{best['hash']}:noop.c"], cwd=ag, capture_output=True, text=True).stdout
    open(os.path.join(an.HERE, "best_policy.c"), "w").write(src)
    ref_src = open(os.path.join(REPO, "seed", "reference", "s3fifo.c")).read()

    def split(s):
        i = s.find("// SECTION: USERSPACE LOADER")
        return (s[:i], s[i:]) if i >= 0 else (s, "")

    diffrows = []
    counts = {}
    for name, a_, b_ in (("kernel", split(ref_src)[0], split(src)[0]), ("loader", split(ref_src)[1], split(src)[1])):
        add = dele = 0
        for l in difflib.unified_diff(a_.splitlines(), b_.splitlines(), lineterm="", n=0):
            if l.startswith(("+++", "---", "@@")):
                continue
            body = l[1:].strip()
            if not body or body.startswith(("//", "/*", "*")):
                continue
            if l[0] == "+":
                add += 1
            else:
                dele += 1
            diffrows.append([name, "+" if l[0] == "+" else "−", body[:120]])
        counts[name] = (add, dele)

    story = []
    # ------------------------------------------------------------ 1: scoring parameters
    story += [Paragraph("Evolved policies vs baseline — CORAL run 2026-10-09_004013", H1), Paragraph("Parameters used in the score normalization", H2)]
    rows = [["Probe", "Weight", "Direction", "Baseline mean (noop, n=%d)" % base["n"], "Baseline sd", "CV %", "z", "Contribution"],
            ["Throughput (ops/s)", f(W_T, 2), "maximize", f(bt, 2), f(bts, 2), f(100 * bts / bt, 2), "(value − mean) / sd", "tanh(z)"],
            ["Bytes read (cgroup rbytes)", f(W_IO, 2), "minimize", f"{bi:,.0f}  ({f(bi/1e6,1)} MB)", f"{bis:,.0f}", f(100 * bis / bi, 2), "(value − mean) / sd", "tanh(−z)"],
            ["Refaults (cgroup memstat)", f(W_RF, 2), "minimize", f(br, 1), f(brs, 1), f(100 * brs / br, 2), "(value − mean) / sd", "tanh(−z)"]]
    story.append(tbl(rows, [2.0, 0.6, 0.8, 2.0, 1.1, 0.6, 1.4, 1.0], align=["L", "R", "L", "R", "R", "R", "L", "L"]))
    story.append(Paragraph("score = (2.0 × c_throughput + 0.5 × c_bytes + 0.25 × c_refaults) / 2.75, where c is the tanh-squashed contribution listed in the table above. Range [−1, 1]; 0 = same as the noop baseline. "
                           "Baseline = 8 consecutive noop evaluations. The displayed values reproduce all 28 recorded scores (max deviation &lt; 0.002).", NOTE))
    story.append(Paragraph("Run", H2))
    story.append(tbl([["Item", "Value"],
                      ["Attempts", f"{len(A)} total = {len(evolved)} evolved policies ({sum(a['cls']=='real' for a in evolved)} real, {sum(a['cls']=='tune' for a in evolved)} --tune) + {len(refs)} attempts running unmodified reference-policy code (context only)"],
                      ["Distinct evolved code versions", str(len({a['key'] for a in evolved}))],
                      ["Definition of 'evolved'", "an attempt whose code differs from every unmodified reference policy (fifo/mru/s3fifo/sampling/get_scan/mglru/lhd) the agent submitted as-is"],
                      ["Best evolved policy", f"#{best['n']} {best['short']} (score {best['score']:.4f}); details at the end of this report"]], [2.2, 7.8], align=["L", "L"]))

    # ------------------------------------------------------------ 3: reference context
    story.append(Paragraph("Unmodified reference policies — context only (not evolved)", H2))
    hdr, span = comp_header()
    story.append(tbl(hdr + [comp_row(a) for a in refs], W_COMP, fs=6.2, align=AL_COMP, hdr_rows=2, extra=span, wrap_from=40))
    story.append(Paragraph("Attempt #6 re-ran the unmodified reference s3fifo code (comment-only difference from #2).", NOTE))

    # ------------------------------------------------------------ 2: evolved vs baseline
    story += [PageBreak(), Paragraph("Evolved policies compared with the baseline", H1)]
    hdr, span = comp_header()
    rows = hdr + [comp_row(a) for a in evolved]
    hl = [2 + i for i, a in enumerate(evolved) if a["key"] == best["key"]]
    story.append(tbl(rows, W_COMP, fs=6.2, align=AL_COMP, hdr_rows=2, extra=span, highlight=hl, wrap_from=40))
    story.append(Paragraph(f"contrib = tanh(z) for throughput, tanh(−z) for bytes read and refaults. Baseline: throughput {f(bt,1)} ops/s, bytes read {f(bi/1e6,1)} MB, refaults {f(br,0)}. Δ% = (value − baseline mean) / baseline mean. Shaded rows = the best evolved policy's code (3 measurements).", NOTE))

    story += [PageBreak(), Paragraph("Aggregate over the evolved policies", H1)]
    def agg(label, key, pk, better_high):
        v = [a[pk] for a in evolved]
        zs = [(a[key] - base[{"t": "tput", "io_v": "io", "rf_v": "rf"}[key]][0]) / base[{"t": "tput", "io_v": "io", "rf_v": "rf"}[key]][1] for a in evolved]
        good = [(z > 0) if better_high else (z < 0) for z in zs]
        g1 = [(z > 1) if better_high else (z < -1) for z in zs]
        g2 = [(z > 2) if better_high else (z < -2) for z in zs]
        bi_ = max(range(len(v)), key=lambda i: v[i] if better_high else -v[i])
        wi_ = min(range(len(v)), key=lambda i: v[i] if better_high else -v[i])
        return [label, len(v), sg(an.mean(v), 2), sg(float(np.median(v)), 2), f"{sg(v[bi_],2)} (#{evolved[bi_]['n']})", f"{sg(v[wi_],2)} (#{evolved[wi_]['n']})", f"{sum(good)} / {len(v)}", f"{sum(g1)}", f"{sum(g2)}"]
    rows = [["Probe", "n", "Mean Δ%", "Median Δ%", "Best Δ% (attempt)", "Worst Δ% (attempt)", "Better than baseline", "Better by > 1σ", "Better by > 2σ"],
            agg("Throughput", "t", "dt_pct", True), agg("Bytes read", "io_v", "dio_pct", False), agg("Refaults", "rf_v", "drf_pct", False)]
    allgood = sum(1 for a in evolved if a["t"] > bt and a["io_v"] < bi and a["rf_v"] < br)
    allgood2 = sum(1 for a in evolved if a["t"] > bt + 2 * bts and a["io_v"] < bi - 2 * bis and a["rf_v"] < br - 2 * brs)
    story.append(tbl(rows, [1.4, 0.4, 0.9, 0.9, 1.6, 1.6, 1.3, 1.1, 1.1], align=["L"] + ["R"] * 8))
    story.append(Paragraph(f"Evolved policies better than baseline on all three probes at once: {allgood} of {len(evolved)}; by more than 2σ on all three: {allgood2} of {len(evolved)}.", NOTE))

    story += [Spacer(1, 6), Paragraph("Difference from baseline, per evolved attempt", H2), img(figs["vs"], AW, 5.2 * inch)]

    # ------------------------------------------------------------ 4: best evolved policy
    story += [PageBreak(), Paragraph(f"Best evolved policy — #{best['n']} {best['short']}", H1)]
    ms = bg["members"]
    first = ms[0]
    story.append(Paragraph("Selection", H2))
    story.append(tbl([["Item", "Value"],
                      ["Rule", "highest score among the real (non --tune) evolved attempts, i.e. the top of CORAL's leaderboard once unmodified reference code is excluded"],
                      ["Selected attempt", f"#{best['n']}  commit {best['hash']}  score {best['score']:.4f}"],
                      ["Identical code measured in", ", ".join(f"#{m['n']} {m['short']} ({m['cls']}, score {m['score']:.4f})" for m in ms)],
                      ["Description (first attempt of this code)", first["title"]],
                      ["Source", f"report/best_policy.c  (noop.c at commit {best['short']}; {len(src.splitlines())} lines)"]], [2.2, 7.8], align=["L", "L"]))

    story.append(Paragraph("Measurements of this policy vs baseline", H2))
    hdr = [["Measurement", "Throughput (ops/s)", "", "", "", "Bytes read (MB)", "", "", "", "Refaults", "", "", "", "Score"],
           ["", "value", "Δ%", "z", "contrib", "value", "Δ%", "z", "contrib", "value", "Δ%", "z", "contrib", ""]]
    span = [("SPAN", (1, 0), (4, 0)), ("SPAN", (5, 0), (8, 0)), ("SPAN", (9, 0), (12, 0))]
    rows = hdr + [["Baseline (noop mean ± sd)", f"{f(bt,1)} ± {f(bts,1)}", "", "", "", f"{f(bi/1e6,1)} ± {f(bis/1e6,2)}", "", "", "", f"{f(br,0)} ± {f(brs,0)}", "", "", "", ""]]
    for m in ms:
        z, c, s = contribs(m["t"], m["io_v"], m["rf_v"], base)
        rows.append([f"#{m['n']} {m['short']} ({m['cls']})", f(m["t"], 1), sg(m["dt_pct"], 2), sg(z[0], 2), sg(c[0], 3), f(m["io_v"] / 1e6, 1), sg(m["dio_pct"], 2), sg(z[1], 2), sg(c[1], 3),
                     f(m["rf_v"], 0), sg(m["drf_pct"], 2), sg(z[2], 2), sg(c[2], 3), f(m["score"], 4)])
    mt, mio, mrf = an.mean([m["t"] for m in ms]), an.mean([m["io_v"] for m in ms]), an.mean([m["rf_v"] for m in ms])
    z, c, s = contribs(mt, mio, mrf, base)
    rows.append([f"Mean of {len(ms)} measurements", f(mt, 1), sg(an.pct(mt, bt), 2), sg(z[0], 2), sg(c[0], 3), f(mio / 1e6, 1), sg(an.pct(mio, bi), 2), sg(z[1], 2), sg(c[1], 3),
                 f(mrf, 0), sg(an.pct(mrf, br), 2), sg(z[2], 2), sg(c[2], 3), f(s, 4)])
    rows.append([f"Sample sd of {len(ms)} measurements", f(an.sd([m["t"] for m in ms]), 1), "", "", "", f(an.sd([m["io_v"] for m in ms]) / 1e6, 2), "", "", "", f(an.sd([m["rf_v"] for m in ms]), 0), "", "", "", f(an.sd([m["score"] for m in ms]), 4)])
    n = len(rows)
    story.append(tbl(rows, [1.9, 0.9, 0.5, 0.45, 0.5, 0.8, 0.5, 0.45, 0.6, 0.7, 0.5, 0.45, 0.6, 0.6], fs=6.6, align=["L"] + ["R"] * 13, hdr_rows=2, extra=span, bold_rows=[n - 2]))
    story.append(Paragraph("The mean row applies the same normalization (z vs baseline, tanh, weights) to the mean of the measurements.", NOTE))

    # alternatives
    story.append(Paragraph("Alternatives considered (evolved policies)", H2))
    seen = set()
    alt = []
    for basis, lst in (("top-5 by score (real)", sorted(real_ev, key=lambda a: -a["score"])[:5]), ("top-3 by throughput (all)", sorted(evolved, key=lambda a: -a["t"])[:3])):
        for a in lst:
            g = next(x for x in G if x["key"] == a["key"])
            alt.append([basis if basis not in seen else "", f"#{a['n']} {a['short']}", a["cls"], f(a["score"], 4), f(a["t"], 1), sg(a["dt_pct"], 2), sg(a["dio_pct"], 1), sg(a["drf_pct"], 1), g["n"], f(g["mean"], 1), "★" if a["key"] == best["key"] else ""])
            seen.add(basis)
    story.append(tbl([["Basis", "Attempt", "Cls", "Score", "Throughput", "Δ% tput", "Δ% bytes", "Δ% refaults", "Identical measurements", "Mean tput of that code", "Best policy"]] + alt,
                     [1.7, 1.2, 0.4, 0.7, 0.8, 0.7, 0.7, 0.8, 1.2, 1.2, 0.7], fs=6.4, align=["L", "L", "L"] + ["R"] * 7 + ["C"]))
    story.append(Paragraph("The highest single throughput (#11 2d5d649a) is one measurement of a different code version; the repeat measurements of other versions show single-evaluation spread of several ops/s, so it is not separable from the selected policy.", NOTE))

    story += [PageBreak(), Paragraph("Best evolved policy — measurements and changes from the reference", H1), img(figs["best"], AW, 2.2 * inch), Spacer(1, 4)]
    story.append(Paragraph(f"Changes relative to the reference s3fifo.c it was derived from — kernel: +{counts['kernel'][0]} / −{counts['kernel'][1]} lines, loader: +{counts['loader'][0]} / −{counts['loader'][1]} lines (code lines only; comments and blank lines ignored)", H2))
    story.append(tbl([["Section", "±", "Changed line"]] + diffrows[:40], [0.9, 0.3, 8.8], fs=6.0, align=["L", "C", "L"], wrap_from=140))
    if len(diffrows) > 40:
        story.append(Paragraph(f"{len(diffrows) - 40} further changed lines omitted; the complete file is report/best_policy.c.", NOTE))

    doc = SimpleDocTemplate(os.path.join(an.HERE, "report_2026-10-09_1043_slim.pdf"), pagesize=PAGE, leftMargin=0.5 * inch, rightMargin=0.5 * inch, topMargin=0.45 * inch,
                            bottomMargin=0.5 * inch, title="Evolved policies vs baseline — CORAL run 2026-10-09_004013", author="coral-cache-evolution")
    doc.build(story, onFirstPage=footer, onLaterPages=footer)
    print("wrote", os.path.join(an.HERE, "report_2026-10-09_1043_slim.pdf"), "| evolved", len(evolved), "| best", best["short"], "| diff lines", counts)


if __name__ == "__main__":
    main()
