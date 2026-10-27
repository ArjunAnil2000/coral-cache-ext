#!/usr/bin/env python3
"""Bytes read per operation for every scored attempt of a multi-host run (data.json from multihost_report.py).

usage: bytes_per_op_report.py <multihost_report_folder>
bytes/op = bytes read from disk in the measured phase / operations completed in it, with ops = throughput x 30 s
(BENCH_RUNTIME default; the measured phase length). Writes bytes_read_per_op.pdf and .csv into the folder.
"""
import csv, html, json, os, sys

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
from reportlab.platypus import Image, PageBreak, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

OUT = os.path.abspath(sys.argv[1])
D = json.load(open(f"{OUT}/data.json"))
RUNTIME = 30.0
HOSTS = D["hosts"]
AGENT = {h: next(a for a, hh in D["agent_host"].items() if hh == h) for h in HOSTS}
rows = []
for a in D["attempts"]:
    if a["crashed"] or a["tput"] is None or a["rbytes_mib"] is None:
        continue
    ops = a["tput"] * RUNTIME
    rows.append(dict(a, ops=ops, kb_op=a["rbytes_mib"] * 1024 / ops, byte_op=a["rbytes_mib"] * 1048576 / ops))
by = {h: sorted([r for r in rows if r["host"] == h], key=lambda r: r["submit"]) for h in HOSTS}
for h in HOSTS:
    for i, r in enumerate(by[h], 1): r["idx"] = i
crashed = {h: sum(1 for a in D["attempts"] if a["host"] == h and a["crashed"]) for h in HOSTS}
with open(f"{OUT}/bytes_read_per_op.csv", "w", newline="") as f:
    w = csv.writer(f); w.writerow(["host", "agent", "attempt_on_host", "commit", "unmodified_seed", "throughput_ops_s", "mib_read", "ops_in_window", "bytes_read_per_op", "kb_read_per_op", "title"])
    for h in HOSTS:
        for r in by[h]: w.writerow([h, r["agent"], r["idx"], r["short"], r["ref"] or "", f"{r['tput']:.2f}", f"{r['rbytes_mib']:.1f}", f"{r['ops']:.0f}", f"{r['byte_op']:.0f}", f"{r['kb_op']:.3f}", r["title"]])

INK, INK2, GRID, SURF = "#0b0b0b", "#52514e", "#dcdbd6", "#fcfcfb"
HC = dict(zip(HOSTS, ["#2a78d6", "#eb6834", "#1baf7a", "#8e5bd0"]))
plt.rcParams.update({"font.size": 8, "axes.edgecolor": GRID, "axes.labelcolor": INK2, "xtick.color": INK2, "ytick.color": INK2, "text.color": INK, "axes.facecolor": SURF, "figure.facecolor": SURF,
                     "axes.grid": True, "grid.color": GRID, "grid.linewidth": 0.5, "axes.spines.top": False, "axes.spines.right": False, "axes.titleweight": "bold", "axes.titlelocation": "left"})
os.makedirs(f"{OUT}/figures", exist_ok=True)
allkb = [r["kb_op"] for r in rows]; lo, hi = min(allkb) * 0.97, max(allkb) * 1.03
fig, axs = plt.subplots(2, 2, figsize=(10, 5.6))
for ax, h in zip(axs.flat, HOSTS):
    L = by[h]
    for r in L:
        if r["ref"]: ax.bar(r["idx"], r["kb_op"], facecolor=SURF, edgecolor=HC[h], hatch="////", lw=0.8, width=0.7)
        else: ax.bar(r["idx"], r["kb_op"], color=HC[h], width=0.7)
    ax.set_ylim(lo, hi); ax.xaxis.set_major_locator(matplotlib.ticker.MaxNLocator(integer=True))
    mu = np.mean([r["kb_op"] for r in L if not r["ref"]])
    ax.axhline(mu, color=INK2, lw=0.8, ls="--")
    ax.set_title(f"{h} ({AGENT[h]}): KB read per op, evolved mean {mu:.2f}", fontsize=8.5); ax.set_ylabel("KB / op"); ax.set_xlabel("scored attempt on that host, in order")
fig.text(0.5, -0.005, f"solid = evolved, hatched = unmodified seed/reference; dashed = mean of the evolved attempts; all panels share the y-axis, which starts at {lo:.1f} KB (not zero)", ha="center", fontsize=7.5, color=INK2)
fig.tight_layout(); F1 = f"{OUT}/figures/b1_kb_per_op.png"; fig.savefig(F1, dpi=200, bbox_inches="tight", facecolor=SURF); plt.close(fig)

fig, axs = plt.subplots(1, 2, figsize=(10, 3.6))
for h in HOSTS:
    L = by[h]
    axs[0].plot([r["tput"] for r in L], [r["kb_op"] for r in L], "o", ms=3.8, color=HC[h], alpha=0.85, label=h)
    axs[1].plot([r["tput"] for r in L], [r["rbytes_mib"] for r in L], "o", ms=3.8, color=HC[h], alpha=0.85, label=h)
axs[0].set_xlabel("throughput (ops/s)"); axs[0].set_ylabel("KB read per op"); axs[0].set_title("Bytes read per op vs throughput", fontsize=8.5)
axs[1].set_xlabel("throughput (ops/s)"); axs[1].set_ylabel("MiB read in the 30 s window"); axs[1].set_title("Total bytes read vs throughput", fontsize=8.5)
for ax in axs: ax.legend(frameon=False, fontsize=7)
fig.tight_layout(); F2 = f"{OUT}/figures/b2_vs_throughput.png"; fig.savefig(F2, dpi=200, bbox_inches="tight", facecolor=SURF); plt.close(fig)

ttf = os.path.join(os.path.dirname(matplotlib.__file__), "mpl-data/fonts/ttf")
for n, f in (("DV", "DejaVuSans.ttf"), ("DVB", "DejaVuSans-Bold.ttf")): pdfmetrics.registerFont(TTFont(n, os.path.join(ttf, f)))
H1 = ParagraphStyle("h1", fontName="DVB", fontSize=15, leading=19, spaceAfter=6)
H2 = ParagraphStyle("h2", fontName="DVB", fontSize=10.5, leading=14, spaceBefore=8, spaceAfter=4)
P = ParagraphStyle("p", fontName="DV", fontSize=8.2, leading=11.2, spaceAfter=3)
SM = ParagraphStyle("s", fontName="DV", fontSize=6.6, leading=8.2)
def pc(t): return Paragraph(t, SM)
def tbl(rr, widths, fs=6.8):
    rr = [[Paragraph(f"<b>{c}</b>", ParagraphStyle("hd", fontName="DVB", fontSize=fs, leading=fs + 1.6)) if i == 0 and isinstance(c, str) else c for c in r] for i, r in enumerate(rr)]
    t = Table(rr, colWidths=widths, repeatRows=1)
    t.setStyle(TableStyle([("FONT", (0, 0), (-1, -1), "DV", fs), ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#ecebe6")), ("VALIGN", (0, 0), (-1, -1), "TOP"),
                           ("GRID", (0, 0), (-1, -1), 0.25, colors.HexColor(GRID)), ("TOPPADDING", (0, 0), (-1, -1), 1.5), ("BOTTOMPADDING", (0, 0), (-1, -1), 1.5)]))
    return t
PW, PH = landscape(letter); M = 0.5 * inch
doc = SimpleDocTemplate(f"{OUT}/bytes_read_per_op.pdf", pagesize=landscape(letter), leftMargin=M, rightMargin=M, topMargin=M, bottomMargin=M, title="Bytes read per operation")
st = [Paragraph(f"Bytes read per operation — multi-host run {D['run']}", H1)]
st.append(Paragraph(f"For every scored attempt ({len(rows)} of {len(D['attempts'])}; {sum(crashed.values())} crashed attempts have no measurement): <b>bytes read per op = bytes read from disk in the measured phase ÷ operations completed in it</b>, with operations = throughput × {RUNTIME:.0f} s "
                    "(the benchmark's measured window). Lower means each operation needed less disk I/O. One scored attempt = one evaluation on that agent's own host; hosts differ in speed, so compare within a host first.", P))
hd = ["host (agent)", "scored", "KB/op: best by lowest", "KB/op median", "KB/op min – max", "mean MiB read", "unmodified seeds (KB/op)", "best-throughput attempt: KB/op"]
rr = [hd]
for h in HOSTS:
    L = by[h]; k = np.array([r["kb_op"] for r in L]); lowest = min(L, key=lambda r: r["kb_op"]); bt = max(L, key=lambda r: r["tput"])
    seeds = ", ".join(f"{r['ref']} {r['kb_op']:.2f}" for r in L if r["ref"])
    rr.append([pc(f"<b>{h}</b> ({AGENT[h]})"), len(L), pc(f"{lowest['kb_op']:.2f} (#{lowest['idx']} {lowest['short']}, {lowest['tput']:.0f} ops/s)"), f"{np.median(k):.2f}", f"{k.min():.2f} – {k.max():.2f}",
               f"{np.mean([r['rbytes_mib'] for r in L]):.0f}", pc(seeds or "-"), pc(f"{bt['kb_op']:.2f} ({bt['short']}, {bt['tput']:.0f} ops/s)")])
st.append(tbl(rr, [1.3 * inch, 0.5 * inch, 1.9 * inch, 0.8 * inch, 1.0 * inch, 0.8 * inch, 2.0 * inch, 1.7 * inch]))
c = np.corrcoef([r["tput"] for r in rows], [r["kb_op"] for r in rows])[0, 1]
c_h = {h: np.corrcoef([r["tput"] for r in by[h]], [r["kb_op"] for r in by[h]])[0, 1] for h in HOSTS}
st.append(Spacer(1, 4))
st.append(Paragraph(f"Correlation of KB/op with throughput: {c:+.2f} over all attempts; per host " + ", ".join(f"{h} {v:+.2f}" for h, v in c_h.items()) + ". "
                    "Note KB/op moves with the policy but is not what the run optimised: the score was throughput, and the best policy does not have the lowest KB/op.", P))
st.append(Image(F1, width=7.3 * inch, height=7.3 * inch * 0.56))
st.append(PageBreak()); st.append(Image(F2, width=9.4 * inch, height=9.4 * inch * 0.36))
st.append(Paragraph("Every scored attempt", H2))
body = [["host", "#", "commit", "tput ops/s", "MiB read", "ops in 30 s", "bytes/op", "KB/op", "design / title"]]
for h in HOSTS:
    for r in by[h]:
        body.append([h, r["idx"], r["short"] + (f" ={r['ref']}" if r["ref"] else ""), f"{r['tput']:.1f}", f"{r['rbytes_mib']:.1f}", f"{r['ops']:.0f}", f"{r['byte_op']:.0f}", f"{r['kb_op']:.2f}", pc(html.escape(r["title"][:115]))])
st.append(tbl(body, [0.4 * inch, 0.3 * inch, 1.2 * inch, 0.6 * inch, 0.6 * inch, 0.7 * inch, 0.6 * inch, 0.5 * inch, PW - 2 * M - 4.9 * inch], fs=6.3))
doc.build(st)
print("rows", len(rows), "| overall KB/op min/median/max", round(min(allkb), 2), round(float(np.median(allkb)), 2), round(max(allkb), 2), "| corr", round(c, 2))
