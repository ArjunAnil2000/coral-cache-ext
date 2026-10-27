#!/usr/bin/env python3
"""Report for a multi-host CORAL run (one agent per host; tanh or absolute-throughput scoring).

usage: multihost_report.py <run_dir> [out_parent]
Writes <out_parent>/multihost_<run>_<N>hosts/{report_*.pdf, data.json, README.md, figures/, best/}.
"""
import collections, datetime as dt, difflib, glob, hashlib, html, json, os, re, subprocess, sys

import matplotlib
import matplotlib.ticker as mt
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
RUN = os.path.abspath(sys.argv[1])
HERE = os.path.dirname(os.path.abspath(__file__))
OUTP = sys.argv[2] if len(sys.argv) > 2 else HERE
REPO = RUN.split("/results/")[0]
RID = os.path.basename(RUN)
PUB = f"{RUN}/.coral/public"
UTC, CDT = dt.timezone.utc, dt.timezone(dt.timedelta(hours=-5))
HOSTS = json.load(open(f"{REPO}/hosts.json"))
CLAIMS = json.load(open(f"{RUN}/.coral/private/host_claims.json"))
AGENT_HOST = {a: HOSTS["buckets"][i][0].split("@")[-1].split(".")[0] for a, i in CLAIMS.items()}
HOST_ORDER = sorted(AGENT_HOST.values())
BUDGET = HOSTS.get("per_host_budget")
OUT = f"{OUTP}/multihost_{RID}_{len(HOST_ORDER)}hosts"
os.makedirs(f"{OUT}/figures", exist_ok=True); os.makedirs(f"{OUT}/best", exist_ok=True)
PAL = ["#2a78d6", "#eb6834", "#1baf7a", "#8e5bd0", "#d4a017", "#c0392b"]
HCOL = {h: PAL[i % len(PAL)] for i, h in enumerate(HOST_ORDER)}


def ts(s): return dt.datetime.fromisoformat(s.replace("Z", "+00:00")).astimezone(UTC)
def key(src):
    keep = [l.rstrip() for l in src.splitlines() if l.strip() and not l.strip().startswith("//")]
    return hashlib.sha1("\n".join(keep).encode()).hexdigest()[:10]
def norm(src): return [l.rstrip() for l in src.splitlines()]


AGDIR = sorted(glob.glob(f"{RUN}/agents/*"))[0]
def git(*a):
    r = subprocess.run(["git", *a], cwd=AGDIR, capture_output=True, text=True); return r.stdout if r.returncode == 0 else ""


refs = {"noop": open(f"{REPO}/seed/noop.c").read()}
for f in sorted(glob.glob(f"{REPO}/seed/reference/*.c")): refs[os.path.basename(f)[:-2]] = open(f).read()
ref_keys = {n: key(s) for n, s in refs.items()}

RX = re.compile(r"- (cgroup_iostat|cgroup_memstat|throughput): ([\d.e+]+) \S+ \| ([\d.e+]+) \+- ([\d.e+]+) \(n=(\d+)\) \| z=([+-][\d.]+)")
A = []
for f in glob.glob(f"{PUB}/attempts/*.json"):
    d = json.load(open(f)); h, fb = d["commit_hash"], d.get("feedback") or ""
    src = git("show", f"{h}:noop.c")
    z = {k: (float(v), float(bm), float(bs), float(zz)) for k, v, bm, bs, n, zz in RX.findall(fb)}
    ma = re.search(r"score = throughput = ([\d.]+) ops/s", fb)            # absolute-throughput feedback
    mr = re.search(r"rbytes=([\d.]+)MiB", fb); mf = re.search(r"refault_file=(\d+)", fb)
    m = re.search(r"wall=([\d.]+)s", fb)
    a = dict(hash=h, short=h[:8], agent=d["agent_id"], host=AGENT_HOST.get(d["agent_id"], "?"), title=d["title"], status=d.get("status"),
             cls=(d.get("metadata") or {}).get("budget_class", "?"), score=d.get("score"), submit=ts(d["timestamp"]).isoformat(),
             crashed=d.get("score") is None, fail=(fb.strip().splitlines()[0][:200] if d.get("score") is None and fb.strip() else None),
             tput=(float(ma.group(1)) if ma else (z["throughput"][0] if "throughput" in z else None)),
             rbytes_mib=(float(mr.group(1)) if mr else (z["cgroup_iostat"][0] / 1048576 if "cgroup_iostat" in z else None)),
             refault=(float(mf.group(1)) if mf else (z["cgroup_memstat"][0] if "cgroup_memstat" in z else None)), z={k: v[3] for k, v in z.items()},
             base={k: v[1:3] for k, v in z.items()}, wall=float(m.group(1)) if m else None, src=src, key=key(src) if src else None, lines=len(src.splitlines()))
    a["ref"] = next((n for n, v in ref_keys.items() if v == a["key"]), None)
    A.append(a)
A.sort(key=lambda a: a["submit"])
for i, a in enumerate(A, 1): a["n"] = i
ABS = any(a["score"] is not None and not a["z"] for a in A)
UNIT = "ops/s" if ABS else "score (tanh z)"
def fmt(v): return f"{v:.1f}" if ABS else f"{v:.3f}"
real = [a for a in A if a["cls"] == "real"]
scored = [a for a in real if not a["crashed"]]
by_host = {h: [a for a in A if a["host"] == h] for h in HOST_ORDER}
best_of = {h: max([a for a in scored if a["host"] == h], key=lambda a: a["score"], default=None) for h in HOST_ORDER}
overall = max(scored, key=lambda a: a["score"])
base_of = {}
for h in HOST_ORDER:
    b = next((a["base"].get("throughput") for a in by_host[h] if a["base"].get("throughput")), None)
    base_of[h] = b


def closest(src):
    L = norm(src)
    return sorted(((difflib.SequenceMatcher(None, norm(v), L, autojunk=False).ratio(), n) for n, v in refs.items()), reverse=True)


# sessions / cost / wall
sess = collections.defaultdict(list); t0 = t1 = None; tools = collections.Counter(); gw_status = collections.Counter()
for f in glob.glob(f"{PUB}/logs/*.log"):
    ag = os.path.basename(f).split(".")[0]
    for line in open(f):
        try: d = json.loads(line)
        except ValueError: continue
        if d.get("timestamp"):
            t = ts(d["timestamp"]); t0 = min(t0 or t, t); t1 = max(t1 or t, t)
        if d.get("type") == "result":
            u = d.get("usage") or {}
            sess[ag].append(dict(cost=d.get("total_cost_usd") or 0, out=u.get("output_tokens", 0), turns=d.get("num_turns") or 0))
if os.path.exists(f"{PUB}/gateway/requests.jsonl"):
    for l in open(f"{PUB}/gateway/requests.jsonl"):
        if l.strip(): gw_status[json.loads(l)["status_code"]] += 1
stop = json.load(open(f"{PUB}/auto_stop.json")) if os.path.exists(f"{PUB}/auto_stop.json") else {}
wall_h = (t1 - t0).total_seconds() / 3600 if t0 else None
cost = {ag: max(s["cost"] for s in v) for ag, v in sess.items()}   # total_cost_usd is cumulative per agent conversation: take the max, not the sum

# ---------------------------------------------------------------- figures
INK, INK2, GRID, SURF = "#0b0b0b", "#52514e", "#dcdbd6", "#fcfcfb"
plt.rcParams.update({"font.size": 8, "axes.edgecolor": GRID, "axes.labelcolor": INK2, "xtick.color": INK2, "ytick.color": INK2, "text.color": INK,
                     "axes.facecolor": SURF, "figure.facecolor": SURF, "axes.grid": True, "grid.color": GRID, "grid.linewidth": 0.5,
                     "axes.spines.top": False, "axes.spines.right": False, "axes.titleweight": "bold", "axes.titlelocation": "left"})
def save(fig, name):
    p = f"{OUT}/figures/{name}"; fig.savefig(p, dpi=200, bbox_inches="tight", facecolor=SURF); plt.close(fig); return p


nh = len(HOST_ORDER); cols = 2; rows_ = (nh + 1) // 2
fig, axs = plt.subplots(rows_, cols, figsize=(10, 2.9 * rows_), squeeze=False)
for ax, h in zip(axs.flat, HOST_ORDER):
    L = by_host[h]
    for i, a in enumerate(L, 1):
        if a["crashed"]: ax.plot(i, 0.02, "x", color="#c0392b", transform=ax.get_xaxis_transform(), clip_on=False); continue
        if a["cls"] != "real": ax.bar(i, a["score"], color="#c9c8c3", width=0.65)
        elif a["ref"]: ax.bar(i, a["score"], facecolor=SURF, edgecolor=HCOL[h], hatch="////", lw=0.8, width=0.65)
        else: ax.bar(i, a["score"], color=HCOL[h], width=0.65)
    sc = [a["score"] for a in L if not a["crashed"]] or [0]
    ax.set_ylim((min(sc) * 0.8) if ABS else min(sc + [0]) * 1.25, max(sc + [0.1]) * 1.1)
    ag = next(a for a, hh in AGENT_HOST.items() if hh == h)
    bb = best_of[h]; ax.set_title(f"{h} ({ag}) — best real {fmt(bb['score'])}" if bb else f"{h} ({ag})", fontsize=8.5); ax.set_ylabel(UNIT)
    ax.xaxis.set_major_locator(mt.MaxNLocator(integer=True))
fig.text(0.5, -0.005, "x = attempt order on that host. solid = evolved, hatched = unmodified seed/reference, grey = tune, red x = crashed.", ha="center", fontsize=7.5, color=INK2)
fig.tight_layout(); F1 = save(fig, "m1_scores_by_host.png")

fig, axs = plt.subplots(1, 2, figsize=(10, 3.4))
for h in HOST_ORDER:
    L = [a for a in scored if a["host"] == h]
    xs = range(1, len(L) + 1)
    axs[0].step(xs, np.maximum.accumulate([a["score"] for a in L]), where="post", color=HCOL[h], lw=1.5, label=f"{h}")
    axs[1].plot(xs, [a["tput"] for a in L], "-o", ms=2.6, lw=0.8, color=HCOL[h], label=f"{h} (baseline {base_of[h][0]:.0f} ± {base_of[h][1]:.0f})" if base_of[h] else h)
axs[0].set_title("Best score so far, per host", fontsize=8.5); axs[0].set_xlabel("scored real attempt on that host"); axs[0].set_ylabel(UNIT)
axs[1].set_title("Throughput of every scored real attempt (ops/s)", fontsize=8.5); axs[1].set_xlabel("scored real attempt on that host"); axs[1].set_ylabel("ops/s")
for ax in axs: ax.xaxis.set_major_locator(mt.MaxNLocator(integer=True)); ax.legend(fontsize=6.5, frameon=False)
fig.tight_layout(); F2 = save(fig, "m2_progress.png")

# ---------------------------------------------------------------- exports
for h in HOST_ORDER:
    b = best_of[h]
    if b: open(f"{OUT}/best/{h}_best_{b['short']}_{fmt(b['score'])}.c", "w").write(b["src"])
open(f"{OUT}/best/best_overall_{overall['host']}_{overall['short']}_{fmt(overall['score'])}.c", "w").write(overall["src"])
json.dump({k: v for k, v in overall.items() if k != "src"}, open(f"{OUT}/best/best_overall.json", "w"), indent=1, default=str)
json.dump(dict(run=RID, hosts=HOST_ORDER, agent_host=AGENT_HOST, budget=BUDGET, auto_stop=stop, wall_hours=wall_h, cost=cost, gateway=dict(gw_status),
               baselines=base_of, attempts=[{k: v for k, v in a.items() if k != "src"} for a in A]), open(f"{OUT}/data.json", "w"), indent=1, default=str)

# ---------------------------------------------------------------- PDF
ttf = os.path.join(os.path.dirname(matplotlib.__file__), "mpl-data/fonts/ttf")
for n, f in (("DV", "DejaVuSans.ttf"), ("DVB", "DejaVuSans-Bold.ttf"), ("DVM", "DejaVuSansMono.ttf")): pdfmetrics.registerFont(TTFont(n, os.path.join(ttf, f)))
H1 = ParagraphStyle("h1", fontName="DVB", fontSize=15, leading=19, spaceAfter=6)
H2 = ParagraphStyle("h2", fontName="DVB", fontSize=10.5, leading=14, spaceBefore=8, spaceAfter=4)
P = ParagraphStyle("p", fontName="DV", fontSize=8.2, leading=11.2, spaceAfter=3)
S = ParagraphStyle("s", fontName="DV", fontSize=6.8, leading=8.6)
CODE = ParagraphStyle("c", fontName="DVM", fontSize=5.2, leading=6.1)
PW, PH = landscape(letter); M = 0.5 * inch
doc = BaseDocTemplate(f"{OUT}/report_{RID}.pdf", pagesize=landscape(letter), leftMargin=M, rightMargin=M, topMargin=M, bottomMargin=M, title=f"Multi-host CORAL run {RID}")
gap = 0.2 * inch; fw = (PW - 2 * M - gap) / 2
doc.addPageTemplates([PageTemplate("main", [Frame(M, M, PW - 2 * M, PH - 2 * M, id="m")]),
                      PageTemplate("code", [Frame(M, M, fw, PH - 2 * M, id="l", leftPadding=2, rightPadding=2), Frame(M + fw + gap, M, fw, PH - 2 * M, id="r", leftPadding=2, rightPadding=2)])])
def pc(t): return Paragraph(t, S)
def tbl(rows, widths, fs=6.8):
    rows = [[Paragraph(f"<b>{c}</b>", ParagraphStyle("hd", fontName="DVB", fontSize=fs, leading=fs + 1.6)) if i == 0 and isinstance(c, str) else c for c in r] for i, r in enumerate(rows)]
    t = Table(rows, colWidths=widths, repeatRows=1)
    t.setStyle(TableStyle([("FONT", (0, 0), (-1, -1), "DV", fs), ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#ecebe6")), ("VALIGN", (0, 0), (-1, -1), "TOP"),
                           ("GRID", (0, 0), (-1, -1), 0.25, colors.HexColor(GRID)), ("TOPPADDING", (0, 0), (-1, -1), 2), ("BOTTOMPADDING", (0, 0), (-1, -1), 2)]))
    return t


st = [Paragraph(f"Multi-host CORAL evolution — run {RID}", H1)]
_sc = ("score = absolute measured throughput (ops/s)" if ABS else "tanh scoring: weighted mean of tanh(z-score vs that host's own no-op baseline) over throughput (w 2.0), bytes read (0.5) and refaults (0.25)")
st.append(Paragraph(f"{len(HOST_ORDER)} agents, one per CloudLab host (each agent evaluated only on its own host, in parallel); {_sc}. "
                    f"Budget {BUDGET} real evaluations per host; all attempts are in one shared leaderboard.", P))
n_t = sum(a["cls"] != "real" for a in A)
rows = [["host", "agent", "real / tune / crashed", "best score", "its tput (ops/s)", "max tput (ops/s)", "host no-op baseline (ops/s, n=8; tanh only)", "LLM cost"]]
for h in HOST_ORDER:
    L = by_host[h]; r_ = [a for a in L if a["cls"] == "real"]; sc_ = [a for a in r_ if not a["crashed"]]
    ag = next(a for a, hh in AGENT_HOST.items() if hh == h); b = best_of[h]; mx = max(sc_, key=lambda a: a["tput"], default=None)
    rows.append([f"<b>{h}</b>", ag, f"{len(r_)} / {sum(a['cls'] != 'real' for a in L)} / {sum(a['crashed'] for a in r_)}",
                 pc(f"#{b['n']} {b['short']} <b>{fmt(b['score'])}</b>") if b else "-", f"{b['tput']:.1f}" if b else "-", f"{mx['tput']:.1f}" if mx else "-",
                 f"{base_of[h][0]:.1f} ± {base_of[h][1]:.1f}" if base_of[h] else "-", f"${cost.get(ag, 0):.0f}"])
rows[1:] = [[pc(c) if isinstance(c, str) and c.startswith("<b>") else c for c in r] for r in rows[1:]]
st.append(tbl(rows, [0.6 * inch, 1.0 * inch, 1.2 * inch, 1.7 * inch, 1.0 * inch, 1.0 * inch, 1.9 * inch, PW - 2 * M - 8.4 * inch]))
st.append(Spacer(1, 4))
for t in (f"Overall best: <b>{overall['host']}</b> ({overall['agent']}), #{overall['n']} {overall['short']}, score {fmt(overall['score'])}, {overall['tput']:.1f} ops/s — "
          f"{'unmodified ' + overall['ref'] + '.c' if overall['ref'] else 'agent-evolved'}.",
          f"Run stop: {html.escape(str(stop.get('reason') or stop)[:140]) if stop else 'stopped manually before reaching the attempt cap'}; wall time {wall_h:.2f} h; total LLM cost ${sum(cost.values()):.0f}; gateway requests {dict(gw_status)}." if wall_h else "",
          ("Hosts differ in speed, so raw throughput is not comparable across hosts: compare changes within a host, not levels across hosts." if ABS else
           "Hosts differ in speed; tanh scores are relative to each host's own baseline. The baselines are tight (a few ops/s), so a policy a few percent above the no-op can already have a large z-score and a tanh close to 1.")):
    if t: st.append(Paragraph("• " + t, P))
st.append(Image(F1, width=8.6 * inch, height=8.6 * inch * 0.29 * rows_))
st.append(PageBreak()); st.append(Image(F2, width=9.2 * inch, height=9.2 * inch * 0.34))
st.append(Paragraph("Top 10 attempts across all hosts (real, scored)", H2))
top = sorted(scored, key=lambda a: -a["score"])[:10]
body = [["#", "host", "agent", "attempt", "commit", "score", "tput", "MiB read", "refaults", "design / title"]]
for i, a in enumerate(top, 1):
    body.append([i, a["host"], a["agent"], a["n"], a["short"], fmt(a['score']), f"{a['tput']:.1f}", f"{a['rbytes_mib']:.0f}", f"{a['refault']:.0f}", pc(html.escape(a["title"][:130]))])
st.append(tbl(body, [0.3 * inch, 0.45 * inch, 0.9 * inch, 0.5 * inch, 0.65 * inch, 0.5 * inch, 0.5 * inch, 0.6 * inch, 0.65 * inch, PW - 2 * M - 5.05 * inch]))
st.append(PageBreak())
for h in HOST_ORDER:
    st.append(Paragraph(f"All attempts on {h} ({next(a for a, hh in AGENT_HOST.items() if hh == h)})", H2))
    body = [["#", "commit", "class", "score", "tput", "read MiB", "refaults", "wall s", "design / title"]]
    for i, a in enumerate(by_host[h], 1):
        body.append([i, a["short"], a["cls"] + (" ✗" if a["crashed"] else "") + (f" ={a['ref']}" if a["ref"] else ""), "crash" if a["crashed"] else fmt(a["score"]),
                     "-" if a["tput"] is None else f"{a['tput']:.1f}", "-" if a["rbytes_mib"] is None else f"{a['rbytes_mib']:.0f}", "-" if a["refault"] is None else f"{a['refault']:.0f}",
                     "-" if a["wall"] is None else f"{a['wall']:.0f}", pc(html.escape((a["fail"] if a["crashed"] and a["fail"] else a["title"])[:140]))])
    st.append(tbl(body, [0.3 * inch, 0.65 * inch, 0.8 * inch, 0.5 * inch, 0.5 * inch, 0.55 * inch, 0.55 * inch, 0.4 * inch, PW - 2 * M - 4.25 * inch], fs=6.3))
    st.append(PageBreak())

# best policies: overall first, then each other host's best (skip duplicates)
seen = set(); picks = [overall] + [best_of[h] for h in HOST_ORDER if best_of[h]]
for b in picks:
    if b["hash"] in seen: continue
    seen.add(b["hash"])
    cl = closest(b["src"]); anc = cl[0][1]
    st.append(NextPageTemplate("code")); st.append(PageBreak())
    tag = " — overall best" if b["hash"] == overall["hash"] else ""
    st.append(Paragraph(f"{b['host']} ({b['agent']}): best policy #{b['n']} {b['short']} — score {fmt(b['score'])}, {b['tput']:.1f} ops/s{tag}", H2))
    st.append(Paragraph(f"Agent's title: <i>{html.escape(b['title'][:500])}</i>", P))
    st.append(Paragraph(f"Closest seed by line similarity: {', '.join(f'{n} {r:.0%}' for r, n in cl[:3])}. Lines that differ from <b>{anc}</b> are highlighted.", P))
    ref = set(norm(refs[anc])); out = []
    for l in b["src"].splitlines():
        e = html.escape(l.rstrip().expandtabs(4)) or " "
        out.append(f'<span backColor="#fff1b8">{e}</span>' if l.rstrip() not in ref and l.strip() else e)
    for i in range(0, len(out), 120): st.append(XPreformatted("\n".join(out[i:i + 120]), CODE))
    st.append(NextPageTemplate("main"))
doc.build(st)
open(f"{OUT}/README.md", "w").write(f"""# Multi-host CORAL run {RID}

{len(HOST_ORDER)} agents, one per host ({', '.join(HOST_ORDER)}), {'absolute-throughput' if ABS else 'tanh'} scoring, {BUDGET} real evals per host. Overall best: {overall['host']} #{overall['n']} `{overall['short']}` score {fmt(overall['score'])}.

| File | What it is |
|---|---|
| `report_{RID}.pdf` | Per-host summary, progress figures, top attempts, all attempts per host, best policies with code. |
| `data.json` | Attempts, per-host baselines, cost and run info. |
| `best/best_overall_*.c`, `best/best_overall.json` | Highest-scoring real attempt across hosts. |
| `best/<host>_best_*.c` | Highest-scoring real attempt on each host. |

Rebuild: `python3 results/pc3000/multihost_report.py {RUN}`
""")
print(OUT)
