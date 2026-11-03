#!/usr/bin/env python3
"""Analyse raw/*.jsonl from run_compare.py: per host x policy statistics, host-speed index, policy gain per host
(with bootstrap CIs), run-order drift. Writes summary.json, figures/, report PDF."""
import glob, html, json, os, random

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

HERE = os.path.dirname(os.path.abspath(__file__))
HOSTS = ["pc252", "pc257", "pc258", "pc318"]
POL = ["best", "noop", "mglru"]
PNAME = {"best": "best evolved policy (7e6df4dc)", "noop": "unmodified no-op (kernel default)", "mglru": "unmodified MGLRU"}
T95 = {1: 12.706, 2: 4.303, 3: 3.182, 4: 2.776, 5: 2.571, 6: 2.447, 7: 2.365, 8: 2.306, 9: 2.262, 10: 2.228, 11: 2.201, 12: 2.179}
rng = np.random.default_rng(0)

raw = [json.loads(l) for h in HOSTS for l in open(f"{HERE}/raw/{h}.jsonl") if l.strip()]
ok = [r for r in raw if r["ok"]]
fails = [r for r in raw if not r["ok"]]
warm = {r["host"]: r["tput"] for r in ok if r["warmup"]}
data = {(h, p): np.array([r["tput"] for r in ok if r["host"] == h and r["policy"] == p and not r["warmup"]]) for h in HOSTS for p in POL}
side = {(h, p, k): np.array([r[k] for r in ok if r["host"] == h and r["policy"] == p and not r["warmup"]]) for h in HOSTS for p in POL for k in ("rbytes", "refault")}


def ci(x):
    n = len(x)
    return (np.std(x, ddof=1) / np.sqrt(n)) * T95.get(n - 1, 1.96) if n > 1 else float("nan")


def boot_ratio(a, b, n=5000):
    """95% bootstrap CI of mean(a)/mean(b) - 1."""
    ra = rng.choice(a, (n, len(a))).mean(1); rb = rng.choice(b, (n, len(b))).mean(1)
    q = np.percentile(ra / rb - 1, [2.5, 97.5])
    return float(a.mean() / b.mean() - 1), float(q[0]), float(q[1])


S = {"hosts": {}}
for h in HOSTS:
    S["hosts"][h] = {"warmup_best": warm.get(h)}
    for p in POL:
        x = data[(h, p)]
        S["hosts"][h][p] = dict(n=len(x), mean=float(x.mean()), sd=float(x.std(ddof=1)), ci95=float(ci(x)), min=float(x.min()), max=float(x.max()),
                                cv_pct=float(100 * x.std(ddof=1) / x.mean()), mean_rbytes_mib=float(side[(h, p, "rbytes")].mean() / 1048576),
                                mean_refault=float(side[(h, p, "refault")].mean()), values=[float(v) for v in x])
    for base in ("noop", "mglru"):
        g, lo, hi = boot_ratio(data[(h, "best")], data[(h, base)])
        S["hosts"][h][f"gain_vs_{base}"] = dict(gain_pct=100 * g, lo_pct=100 * lo, hi_pct=100 * hi)
ref_noop = float(np.mean([S["hosts"][h]["noop"]["mean"] for h in HOSTS]))
for h in HOSTS:
    S["hosts"][h]["speed_index_noop"] = S["hosts"][h]["noop"]["mean"] / ref_noop
    S["hosts"][h]["speed_index_best"] = S["hosts"][h]["best"]["mean"] / float(np.mean([S["hosts"][k]["best"]["mean"] for k in HOSTS]))
# do hosts differ in the policy's gain? pairwise bootstrap of difference in log-gain
pair = []
for i, a in enumerate(HOSTS):
    for b in HOSTS[i + 1:]:
        n = 5000
        ga = np.log(rng.choice(data[(a, "best")], (n, len(data[(a, "best")]))).mean(1) / rng.choice(data[(a, "noop")], (n, len(data[(a, "noop")]))).mean(1))
        gb = np.log(rng.choice(data[(b, "best")], (n, len(data[(b, "best")]))).mean(1) / rng.choice(data[(b, "noop")], (n, len(data[(b, "noop")]))).mean(1))
        d = ga - gb; lo, hi = np.percentile(d, [2.5, 97.5])
        pair.append(dict(a=a, b=b, diff_pct=float(100 * (np.log(data[(a, "best")].mean() / data[(a, "noop")].mean()) - np.log(data[(b, "best")].mean() / data[(b, "noop")].mean()))),
                         lo_pct=float(100 * lo), hi_pct=float(100 * hi), differs=bool(lo > 0 or hi < 0)))
S["gain_pairwise"] = pair
# run-order drift (linear slope of throughput vs eval order, whole experiment, per host, all policies detrended by policy mean)
drift = {}
for h in HOSTS:
    xs, ys = [], []
    for r in sorted([r for r in ok if r["host"] == h and not r["warmup"]], key=lambda r: r["seq"]):
        xs.append(r["seq"]); ys.append(r["tput"] / S["hosts"][h][r["policy"]]["mean"])
    sl = float(np.polyfit(xs, ys, 1)[0]); drift[h] = dict(pct_over_experiment=100 * sl * (max(xs) - min(xs)))
S["drift"] = drift; S["failures"] = [{k: r[k] for k in ("host", "policy", "round", "error")} for r in fails]
json.dump(S, open(f"{HERE}/summary.json", "w"), indent=1)

# ---------------------------------------------------------------- figures
INK, INK2, GRID, SURF = "#0b0b0b", "#52514e", "#dcdbd6", "#fcfcfb"
PC = {"best": "#2a78d6", "noop": "#a9a8a3", "mglru": "#eb6834"}
plt.rcParams.update({"font.size": 8, "axes.edgecolor": GRID, "axes.labelcolor": INK2, "xtick.color": INK2, "ytick.color": INK2, "text.color": INK, "axes.facecolor": SURF,
                     "figure.facecolor": SURF, "axes.grid": True, "grid.color": GRID, "grid.linewidth": 0.5, "axes.spines.top": False, "axes.spines.right": False,
                     "axes.titleweight": "bold", "axes.titlelocation": "left"})
fig, ax = plt.subplots(figsize=(10, 3.8))
for i, h in enumerate(HOSTS):
    for j, p in enumerate(POL):
        x0 = i + (j - 1) * 0.26; v = data[(h, p)]
        ax.plot(x0 + (np.arange(len(v)) - (len(v) - 1) / 2) * 0.018, v, "o", ms=3.5, color=PC[p], alpha=0.85, label=PNAME[p] if i == 0 else None)
        ax.hlines(v.mean(), x0 - 0.1, x0 + 0.1, color=INK, lw=1.4)
    if h in warm: ax.plot(i, warm[h], "x", color="#c0392b", ms=6, label="first eval on host (warm-up, not in means)" if i == 0 else None)
ax.set_xticks(range(len(HOSTS))); ax.set_xticklabels(HOSTS); ax.set_ylabel("throughput (ops/s)")
ax.set_title("Same three policies on each host (dots: individual evals, bar: mean)"); ax.legend(frameon=False, fontsize=7, loc="lower left")
F1 = f"{HERE}/figures/f1_by_host.png"; os.makedirs(f"{HERE}/figures", exist_ok=True); fig.savefig(F1, dpi=200, bbox_inches="tight", facecolor=SURF); plt.close(fig)

fig, axs = plt.subplots(1, 2, figsize=(10, 3.2))
for ax, base in zip(axs, ("noop", "mglru")):
    g = [S["hosts"][h][f"gain_vs_{base}"] for h in HOSTS]
    ax.bar(range(4), [x["gain_pct"] for x in g], color=PC["best"], width=0.55, yerr=[[x["gain_pct"] - x["lo_pct"] for x in g], [x["hi_pct"] - x["gain_pct"] for x in g]], ecolor=INK2, capsize=3)
    ax.set_xticks(range(4)); ax.set_xticklabels(HOSTS); ax.set_ylabel("% throughput gain"); ax.set_title(f"Best policy vs unmodified {base} (same host, 95% bootstrap CI)", fontsize=8.5)
F2 = f"{HERE}/figures/f2_gain.png"; fig.savefig(F2, dpi=200, bbox_inches="tight", facecolor=SURF); plt.close(fig)

fig, ax = plt.subplots(figsize=(10, 3.2))
hc = {"pc252": "#2a78d6", "pc257": "#eb6834", "pc258": "#1baf7a", "pc318": "#8e5bd0"}
for h in HOSTS:
    rs = sorted([r for r in ok if r["host"] == h], key=lambda r: r["seq"])
    ax.plot([r["seq"] + 1 for r in rs], [r["tput"] for r in rs], "-o", ms=3, lw=0.7, color=hc[h], label=h)
ax.set_xlabel("eval order on that host (1 = warm-up)"); ax.set_ylabel("throughput (ops/s)"); ax.set_title("Run-order view (checks for drift or warm-up effects; policies interleaved)")
ax.legend(frameon=False, fontsize=7, ncol=4)
F3 = f"{HERE}/figures/f3_order.png"; fig.savefig(F3, dpi=200, bbox_inches="tight", facecolor=SURF); plt.close(fig)

# ---------------------------------------------------------------- PDF
ttf = os.path.join(os.path.dirname(matplotlib.__file__), "mpl-data/fonts/ttf")
for n, f in (("DV", "DejaVuSans.ttf"), ("DVB", "DejaVuSans-Bold.ttf")): pdfmetrics.registerFont(TTFont(n, os.path.join(ttf, f)))
H1 = ParagraphStyle("h1", fontName="DVB", fontSize=15, leading=19, spaceAfter=6)
H2 = ParagraphStyle("h2", fontName="DVB", fontSize=10.5, leading=14, spaceBefore=8, spaceAfter=4)
P = ParagraphStyle("p", fontName="DV", fontSize=8.2, leading=11.2, spaceAfter=3)
SM = ParagraphStyle("s", fontName="DV", fontSize=7, leading=8.8)
def pc(t): return Paragraph(t, SM)
def tbl(rows, widths, fs=7):
    rows = [[Paragraph(f"<b>{c}</b>", ParagraphStyle("hd", fontName="DVB", fontSize=fs, leading=fs + 1.6)) if i == 0 and isinstance(c, str) else c for c in r] for i, r in enumerate(rows)]
    t = Table(rows, colWidths=widths, repeatRows=1)
    t.setStyle(TableStyle([("FONT", (0, 0), (-1, -1), "DV", fs), ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#ecebe6")), ("VALIGN", (0, 0), (-1, -1), "TOP"),
                           ("GRID", (0, 0), (-1, -1), 0.25, colors.HexColor(GRID)), ("TOPPADDING", (0, 0), (-1, -1), 2), ("BOTTOMPADDING", (0, 0), (-1, -1), 2)]))
    return t
PW, PH = landscape(letter); M = 0.5 * inch
doc = SimpleDocTemplate(f"{HERE}/compare-new-hosts.pdf", pagesize=landscape(letter), leftMargin=M, rightMargin=M, topMargin=M, bottomMargin=M, title="Best policy on the new hosts")
st = [Paragraph("Does the 712 ops/s policy hold up on the four new hosts?", H1)]
n_per = S["hosts"][HOSTS[0]]["best"]["n"]
st.append(Paragraph(f"The best policy from the earlier 4-host run (<b>7e6df4dc</b>, region-CLOCK, 712.2 ops/s on pc309, evolved on a different set of hosts: pc306, pc309, pc319, pc320) was run unchanged on the four current hosts (pc252, pc257, pc258, pc318), interleaved with two unmodified controls (the no-op kernel default and MGLRU) "
                    f"so that host speed can be separated from policy effect. {n_per} evaluations per policy per host, order rotated each round, one warm-up eval per host (not in the means). Hosts ran in parallel, one eval at a time each.", P))
rows = [["host", "best policy mean ± CI95 (sd, cv)", "no-op mean ± CI95", "MGLRU mean ± CI95", "warm-up eval", "speed index (no-op)", "gain vs no-op [95% CI]", "gain vs MGLRU [95% CI]"]]
for h in HOSTS:
    d = S["hosts"][h]
    def cell(p): return f"{d[p]['mean']:.1f} ± {d[p]['ci95']:.1f}"
    gn, gm = d["gain_vs_noop"], d["gain_vs_mglru"]
    rows.append([f"<b>{h}</b>", f"{cell('best')} (sd {d['best']['sd']:.1f}, cv {d['best']['cv_pct']:.1f}%)", cell("noop"), cell("mglru"), f"{d['warmup_best']:.1f}" if d["warmup_best"] else "-",
                 f"{d['speed_index_noop']:.3f}", f"{gn['gain_pct']:+.1f}% [{gn['lo_pct']:+.1f}, {gn['hi_pct']:+.1f}]", f"{gm['gain_pct']:+.1f}% [{gm['lo_pct']:+.1f}, {gm['hi_pct']:+.1f}]"])
rows = [rows[0]] + [[pc(r[0])] + r[1:] for r in rows[1:]]
st.append(tbl(rows, [0.6 * inch, 2.0 * inch, 1.2 * inch, 1.2 * inch, 0.8 * inch, 1.0 * inch, 1.6 * inch, 1.6 * inch]))
st.append(Spacer(1, 4))
ps = S["gain_pairwise"]
st.append(Paragraph("<b>Do hosts differ in how much the policy helps?</b> Pairwise difference in the best-vs-no-op gain (log-ratio, % points) with 95% bootstrap CI: " +
                    "; ".join(f"{p['a']} vs {p['b']}: {p['diff_pct']:+.1f} [{p['lo_pct']:+.1f}, {p['hi_pct']:+.1f}]{' *' if p['differs'] else ''}" for p in ps) + ". * = CI excludes 0.", P))
st.append(Paragraph("<b>Drift over the experiment</b> (change in normalised throughput from first to last eval, linear fit): " + ", ".join(f"{h} {d['pct_over_experiment']:+.1f}%" for h, d in drift.items()) + ".", P))
if fails: st.append(Paragraph(f"<b>{len(fails)} eval(s) failed</b> and are excluded: " + html.escape("; ".join(f"{f['host']} {f['policy']} r{f['round']}: {f['error'][:80]}" for f in S['failures'])), P))
st.append(PageBreak()); st.append(Image(F1, width=9.4 * inch, height=9.4 * inch * 0.38)); st.append(Image(F2, width=9.4 * inch, height=9.4 * inch * 0.32))
st.append(PageBreak()); st.append(Image(F3, width=9.4 * inch, height=9.4 * inch * 0.32))
rows = [["host", "policy", "n", "mean", "sd", "min", "max", "MiB read (mean)", "refaults (mean)"]]
for h in HOSTS:
    for p in POL:
        d = S["hosts"][h][p]; rows.append([h, p, d["n"], f"{d['mean']:.1f}", f"{d['sd']:.1f}", f"{d['min']:.1f}", f"{d['max']:.1f}", f"{d['mean_rbytes_mib']:.0f}", f"{d['mean_refault']:.0f}"])
st.append(Paragraph("Per host and policy", H2)); st.append(tbl(rows, [0.7 * inch, 0.7 * inch, 0.4 * inch, 0.8 * inch, 0.6 * inch, 0.7 * inch, 0.7 * inch, 1.2 * inch, 1.2 * inch]))
doc.build(st)
print(json.dumps({h: {p: round(S["hosts"][h][p]["mean"], 1) for p in POL} | {"gain_noop": round(S["hosts"][h]["gain_vs_noop"]["gain_pct"], 1), "warm": S["hosts"][h]["warmup_best"]} for h in HOSTS}, indent=1))
