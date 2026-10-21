#!/usr/bin/env python3
"""Build a report folder for one CORAL run of the coral-cache-evolution task.

usage: runreport.py <worktree_dir> <tanh|abs> <all|one> <host> [outdir_parent]

Reads <worktree>/results/cache-ext-get-scan/<latest run>/ and writes
  report_<run>_<branch>_20-attempt-cap/{report_*.pdf, data.json, README.md, figures/, best/, best_evolved_policy.c}
Handles both feedback formats (tanh z-score and absolute throughput).
"""
import collections, datetime as dt, difflib, glob, hashlib, html, json, os, re, shutil, subprocess, sys

import matplotlib
import matplotlib.ticker
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
from reportlab.lib import colors
from reportlab.lib.enums import TA_LEFT
from reportlab.lib.pagesizes import landscape, letter
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import inch
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import (BaseDocTemplate, Frame, Image, NextPageTemplate, PageBreak, PageTemplate, Paragraph,
                                Spacer, Table, TableStyle, XPreformatted, KeepTogether)

WT, MODE, SEEDS, HOST = sys.argv[1:5]
OUTP = sys.argv[5] if len(sys.argv) > 5 else os.path.dirname(os.path.abspath(__file__))
BRANCH = subprocess.run(["git", "-C", WT, "branch", "--show-current"], capture_output=True, text=True).stdout.strip()
RUN = sorted(glob.glob(f"{WT}/results/cache-ext-get-scan/20*"))[-1]
RID = os.path.basename(RUN)
PUB, AG = f"{RUN}/.coral/public", f"{RUN}/agents/captain-nemo"
UTC, CDT = dt.timezone.utc, dt.timezone(dt.timedelta(hours=-5))
TANH = MODE == "tanh"
UNIT = "score (tanh z)" if TANH else "ops/s"
OUT = f"{OUTP}/report_{RID}_{BRANCH}_20-attempt-cap"
os.makedirs(f"{OUT}/figures", exist_ok=True)
os.makedirs(f"{OUT}/best", exist_ok=True)


def git(*a, cwd=AG):
    r = subprocess.run(["git", *a], cwd=cwd, capture_output=True, text=True)
    return r.stdout if r.returncode == 0 else None


def ts(s):
    return dt.datetime.fromisoformat(s.replace("Z", "+00:00")).astimezone(UTC)


def loc(iso):
    return dt.datetime.fromisoformat(iso).astimezone(CDT).strftime("%H:%M:%S")


def key(src):
    keep = [l.rstrip() for l in src.splitlines() if l.strip() and not l.strip().startswith("//")]
    return hashlib.sha1("\n".join(keep).encode()).hexdigest()[:10]


# ------------------------------------------------------------------ references available to the agent
refs = {"noop" if SEEDS == "all" else "s3fifo": open(f"{WT}/seed/noop.c").read()}
if SEEDS == "all":
    for f in sorted(glob.glob(f"{WT}/seed/reference/*.c")):
        refs[os.path.basename(f)[:-2]] = open(f).read()
ref_keys = {n: key(s) for n, s in refs.items()}
SEED_NAME = list(refs)[0]

# ------------------------------------------------------------------ attempts
RX_T = re.compile(r"- (cgroup_iostat|cgroup_memstat|throughput): ([\d.e+]+) \S+ \| ([\d.e+]+) \+- ([\d.e+]+) \(n=(\d+)\) \| z=([+-][\d.]+)")
A = []
for f in glob.glob(f"{PUB}/attempts/*.json"):
    d = json.load(open(f))
    h, fb = d["commit_hash"], d.get("feedback") or ""
    src = git("show", f"{h}:noop.c") or ""
    r = dict(hash=h, short=h[:8], parent=(d.get("parent_hash") or "")[:8], title=d["title"], status=d.get("status"),
             cls=(d.get("metadata") or {}).get("budget_class", "?"), score=d.get("score"), submit=ts(d["timestamp"]).isoformat(),
             key=key(src) if src else None, lines=len(src.splitlines()), src=src)
    r["crashed"] = d.get("score") is None
    r["fail"] = fb.strip().splitlines()[0][:200] if r["crashed"] and fb.strip() else None
    m = re.search(r"wall=([\d.]+)s", fb)
    r["wall"] = float(m.group(1)) if m else None
    if TANH:
        z = {k: (float(v), float(bm), float(bs), int(n), float(zz)) for k, v, bm, bs, n, zz in RX_T.findall(fb)}
        r["tput"] = z["throughput"][0] if "throughput" in z else None
        r["rbytes_mib"] = z["cgroup_iostat"][0] / 1048576 if "cgroup_iostat" in z else None
        r["refault"] = z["cgroup_memstat"][0] if "cgroup_memstat" in z else None
        r["z"] = {k: v[4] for k, v in z.items()}
        r["base"] = {k: v[1:4] for k, v in z.items()}
    else:
        m1 = re.search(r"score = throughput = ([\d.]+) ops/s", fb)
        m2 = re.search(r"rbytes=([\d.]+)MiB wbytes=([\d.]+)MiB rios=(\d+)", fb)
        m3 = re.search(r"refault_file=(\d+) pgmajfault=(\d+) pgactivate=(\d+) resident_file=(\d+)MiB", fb)
        r["tput"] = float(m1.group(1)) if m1 else None
        r["rbytes_mib"], r["wbytes_mib"], r["rios"] = (float(m2.group(1)), float(m2.group(2)), int(m2.group(3))) if m2 else (None,) * 3
        r["refault"] = int(m3.group(1)) if m3 else None
        r["pgmajfault"], r["pgactivate"], r["resident_mib"] = (int(m3.group(2)), int(m3.group(3)), int(m3.group(4))) if m3 else (None,) * 3
    r["ref"] = next((n for n, v in ref_keys.items() if v == r["key"]), None)
    A.append(r)
A.sort(key=lambda a: a["submit"])
for i, a in enumerate(A, 1):
    a["n"] = i
real = [a for a in A if a["cls"] == "real"]
scored = [a for a in real if not a["crashed"]]
best = max(scored, key=lambda a: a["score"])
evolved = [a for a in scored if not a["ref"]]
best_ev = max(evolved, key=lambda a: a["score"]) if evolved else None
seed_runs = [a for a in scored if a["ref"] == SEED_NAME]
BASE = None
if TANH:
    b0 = next((a for a in A if a.get("base")), None)
    BASE = b0["base"] if b0 else None


def closest(src):
    L = [l.rstrip() for l in src.splitlines()]
    out = []
    for n, s in refs.items():
        sm = difflib.SequenceMatcher(None, [l.rstrip() for l in s.splitlines()], L, autojunk=False)
        out.append((sm.ratio(), n))
    return sorted(out, reverse=True)


# ------------------------------------------------------------------ sessions / gateway
sess, tool = [], collections.Counter()
t_first = t_last = None
for f in sorted(glob.glob(f"{PUB}/logs/captain-nemo.*.log")):
    res = None
    for line in open(f):
        try: d = json.loads(line)
        except ValueError: continue
        if d.get("timestamp"):
            t = ts(d["timestamp"]); t_first = min(t_first or t, t); t_last = max(t_last or t, t)
        if d.get("type") == "assistant":
            m = d.get("message") or {}
            for c in (m.get("content") if isinstance(m, dict) and isinstance(m.get("content"), list) else []):
                if isinstance(c, dict) and c.get("type") == "tool_use": tool[c["name"]] += 1
        if d.get("type") == "result": res = d
    if res:
        u = res.get("usage") or {}
        sess.append(dict(cost=res.get("total_cost_usd") or 0, dur=(res.get("duration_ms") or 0) / 1000, turns=res.get("num_turns") or 0,
                         inp=u.get("input_tokens", 0), cc=u.get("cache_creation_input_tokens", 0), cr=u.get("cache_read_input_tokens", 0),
                         out=u.get("output_tokens", 0), denials=len(res.get("permission_denials") or [])))
gw = [json.loads(l) for l in open(f"{PUB}/gateway/requests.jsonl") if l.strip()] if os.path.exists(f"{PUB}/gateway/requests.jsonl") else []
gw_status = collections.Counter(r["status_code"] for r in gw)
stop = json.load(open(f"{PUB}/auto_stop.json")) if os.path.exists(f"{PUB}/auto_stop.json") else {}
wall_h = ((t_last - t_first).total_seconds() / 3600) if t_first else None

# ------------------------------------------------------------------ figures
INK, INK2, GRID, SURF = "#0b0b0b", "#52514e", "#dcdbd6", "#fcfcfb"
BLUE, ORANGE, AQUA, GREY = "#2a78d6", "#eb6834", "#1baf7a", "#a9a8a3"
plt.rcParams.update({"font.size": 8, "axes.edgecolor": GRID, "axes.labelcolor": INK2, "xtick.color": INK2, "ytick.color": INK2, "text.color": INK,
                     "axes.facecolor": SURF, "figure.facecolor": SURF, "axes.grid": True, "grid.color": GRID, "grid.linewidth": 0.5,
                     "axes.spines.top": False, "axes.spines.right": False, "axes.titleweight": "bold", "axes.titlelocation": "left"})


def save(fig, name):
    p = f"{OUT}/figures/{name}"
    fig.savefig(p, dpi=200, bbox_inches="tight", facecolor=SURF); plt.close(fig); return p


fig, ax = plt.subplots(figsize=(10, 3.4))
for a in A:
    if a["crashed"]:
        ax.plot(a["n"], 0.02, "x", color="#c0392b", transform=ax.get_xaxis_transform(), clip_on=False); continue
    col = GREY if a["cls"] != "real" else (AQUA if a["ref"] else BLUE)
    ax.bar(a["n"], a["score"], color=col, width=0.62)
    ax.annotate(f"{a['score']:.3g}" if TANH else f"{a['score']:.0f}", (a["n"], a["score"]), xytext=(0, 2), textcoords="offset points", ha="center", fontsize=6)
ax.set_xticks([a["n"] for a in A]); ax.set_xticklabels([f"#{a['n']}" for a in A], fontsize=6)
lo = min([a["score"] for a in A if not a["crashed"]] + [0]); hi = max(a["score"] for a in A if not a["crashed"])
ax.set_ylim(lo * 1.1 if lo < 0 else 0 if TANH else min(a["score"] for a in A if not a["crashed"]) * 0.8, hi * 1.08)
ax.set_ylabel(UNIT)
ax.set_title(f"Score per attempt, submission order ({BRANCH})")
ax.set_xlabel("blue = evolved, teal = unmodified seed/reference, grey = tune attempt (not counted), red x = crashed")
F1 = save(fig, "f1_scores.png")

fig, axs = plt.subplots(1, 2, figsize=(10, 3.2))
bs, cur = [], -1e9
rs = [a for a in real if not a["crashed"]]
for i, a in enumerate(rs, 1):
    cur = max(cur, a["score"]); bs.append(cur)
axs[0].step(range(1, len(rs) + 1), bs, where="post", color=BLUE, lw=1.4)
axs[0].plot(range(1, len(rs) + 1), [a["score"] for a in rs], "o", color=GREY, ms=3)
axs[0].xaxis.set_major_locator(matplotlib.ticker.MaxNLocator(integer=True)); axs[0].set_xlabel("scored real attempt"); axs[0].set_ylabel(UNIT); axs[0].set_title("Best so far (grey dots: each attempt)")
pts = [a for a in scored if a["rbytes_mib"] is not None and a["tput"] is not None]
axs[1].plot([a["rbytes_mib"] for a in pts], [a["tput"] for a in pts], "o", color=BLUE, ms=4)
axs[1].set_xlabel("bytes read during measured phase (MiB)"); axs[1].set_ylabel("throughput (ops/s)")
r_ = np.corrcoef([a["rbytes_mib"] for a in pts], [a["tput"] for a in pts])[0, 1] if len(pts) > 2 else float("nan")
axs[1].set_title(f"Throughput vs bytes read (r = {r_:+.2f}, n = {len(pts)})")
F2 = save(fig, "f2_progress.png")

# ------------------------------------------------------------------ exports
os.makedirs(f"{OUT}/best", exist_ok=True)
open(f"{OUT}/best/best_policy.c", "w").write(best["src"])
json.dump({k: v for k, v in best.items() if k != "src"}, open(f"{OUT}/best/best_policy.json", "w"), indent=1, default=str)
if best_ev and best_ev["hash"] != best["hash"]:
    open(f"{OUT}/best_evolved_policy.c", "w").write(best_ev["src"])
data = dict(run=RID, branch=BRANCH, host=HOST, mode=MODE, seeds=SEEDS, auto_stop=stop, wall_hours=wall_h, gateway_status=dict(gw_status),
            attempts=[{k: v for k, v in a.items() if k != "src"} for a in A], sessions=sess, tools=dict(tool), baseline=BASE)
json.dump(data, open(f"{OUT}/data.json", "w"), indent=1, default=str)

# ------------------------------------------------------------------ PDF
ttf = os.path.join(os.path.dirname(matplotlib.__file__), "mpl-data/fonts/ttf")
for n, f in (("DV", "DejaVuSans.ttf"), ("DVB", "DejaVuSans-Bold.ttf"), ("DVM", "DejaVuSansMono.ttf")):
    pdfmetrics.registerFont(TTFont(n, os.path.join(ttf, f)))
H1 = ParagraphStyle("h1", fontName="DVB", fontSize=15, leading=19, spaceAfter=6)
H2 = ParagraphStyle("h2", fontName="DVB", fontSize=10.5, leading=14, spaceBefore=8, spaceAfter=4)
P = ParagraphStyle("p", fontName="DV", fontSize=8.2, leading=11.2, spaceAfter=3, alignment=TA_LEFT)
S = ParagraphStyle("s", fontName="DV", fontSize=6.6, leading=8.2)
CODE = ParagraphStyle("c", fontName="DVM", fontSize=5.2, leading=6.1)
PW, PH = landscape(letter)
M = 0.5 * inch
doc = BaseDocTemplate(f"{OUT}/report_{RID}.pdf", pagesize=landscape(letter), leftMargin=M, rightMargin=M, topMargin=M, bottomMargin=M,
                      title=f"CORAL run {RID} ({BRANCH})")
gap = 0.2 * inch
fw = (PW - 2 * M - gap) / 2
doc.addPageTemplates([PageTemplate("main", [Frame(M, M, PW - 2 * M, PH - 2 * M, id="m")]),
                      PageTemplate("code", [Frame(M, M, fw, PH - 2 * M, id="l", leftPadding=2, rightPadding=2),
                                            Frame(M + fw + gap, M, fw, PH - 2 * M, id="r", leftPadding=2, rightPadding=2)])])


def tbl(rows, widths, hdr=True, fs=6.6):
    t = Table(rows, colWidths=widths, repeatRows=1 if hdr else 0)
    st = [("FONT", (0, 0), (-1, -1), "DV", fs), ("VALIGN", (0, 0), (-1, -1), "TOP"), ("GRID", (0, 0), (-1, -1), 0.25, colors.HexColor(GRID)),
          ("TOPPADDING", (0, 0), (-1, -1), 1.5), ("BOTTOMPADDING", (0, 0), (-1, -1), 1.5)]
    if hdr: st += [("FONT", (0, 0), (-1, 0), "DVB", fs), ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#ecebe6"))]
    t.setStyle(TableStyle(st)); return t


def pc(t): return Paragraph(html.escape(str(t)), S)


fmt = (lambda v: f"{v:.3f}") if TANH else (lambda v: f"{v:.1f}")
st = []
st.append(Paragraph(f"CORAL run {RID} — {BRANCH}", H1))
desc = ("all seven reference policies available" if SEEDS == "all" else "S3-FIFO is the only seed") + "; " + \
       ("score = tanh-squashed weighted z-score vs the vanilla-kernel no-op baseline (throughput w=2.0, bytes read 0.5, refaults 0.25)"
        if TANH else "score = absolute measured throughput (ops/s)")
st.append(Paragraph(f"{html.escape(desc)}. Evaluated on CloudLab host <b>{HOST}.emulab.net</b> (2-core, ~2 GB Xeon; absolute throughput is not comparable with the earlier c220g1 runs or with the other hosts).", P))
n_t, n_c = sum(a["cls"] != "real" for a in A), sum(a["crashed"] for a in real)
rows = [["real attempts", f"{len(real)} (cap 20)   |   scored {len(scored)}, crashed {n_c}   |   tune {n_t}"],
        ["stop reason", html.escape(str(stop.get("reason") or stop)[:160])],
        ["wall time (agent logs)", f"{wall_h:.2f} h" if wall_h else "-"],
        ["best attempt", f"#{best['n']} <b>{best['short']}</b>  score {fmt(best['score'])}"
         + (f"  (throughput {best['tput']:.1f} ops/s)" if TANH and best['tput'] else "") + f" — {'unmodified ' + best['ref'] + '.c' if best['ref'] else 'agent-evolved'}"],
        ["best evolved", (f"#{best_ev['n']} <b>{best_ev['short']}</b>  score {fmt(best_ev['score'])}" + (f"  (throughput {best_ev['tput']:.1f} ops/s)" if TANH and best_ev['tput'] else "")) if best_ev else "-"],
        ["unmodified seed (" + SEED_NAME + ")", ", ".join(f"#{a['n']}: {fmt(a['score'])}" for a in seed_runs) or "not submitted unmodified"],
        ["LLM usage", f"{sum(s['cost'] for s in sess):.2f} USD, {sum(s['out'] for s in sess)/1e3:.0f}k output tokens, {sum(s['turns'] for s in sess)} turns in {len(sess)} sessions; gateway requests {len(gw)} {dict(gw_status)}"]]
if BASE:
    tb = BASE.get("throughput")
    rows.append(["tanh baseline (no-op, n=8)", f"throughput {tb[0]:.1f} ± {tb[1]:.1f} ops/s on this host" if tb else "-"])
st.append(tbl([[Paragraph(f"<b>{k}</b>", S), Paragraph(v, S)] for k, v in rows], [1.7 * inch, PW - 2 * M - 1.7 * inch], hdr=False))
st.append(Spacer(1, 6))
st.append(Image(F1, width=7.4 * inch, height=7.4 * inch * 0.34))
st.append(Image(F2, width=7.4 * inch, height=7.4 * inch * 0.32))
st.append(PageBreak())
st.append(Paragraph("All attempts (submission order)", H2))
hd = ["#", "commit", "class", "score", "tput ops/s", "read MiB", "refaults", "wall s", "design / title"]
body = [hd]
for a in A:
    body.append([a["n"], a["short"], a["cls"] + (" ✗" if a["crashed"] else "") + (f" ={a['ref']}" if a["ref"] else ""),
                 "crash" if a["crashed"] else fmt(a["score"]), "-" if a["tput"] is None else f"{a['tput']:.1f}",
                 "-" if a["rbytes_mib"] is None else f"{a['rbytes_mib']:.0f}", "-" if a["refault"] is None else f"{a['refault']:.0f}",
                 "-" if a["wall"] is None else f"{a['wall']:.0f}", pc(a["title"][:150] if not a["crashed"] else (a["fail"] or a["title"])[:150])])
st.append(tbl(body, [0.3 * inch, 0.7 * inch, 0.8 * inch, 0.5 * inch, 0.6 * inch, 0.55 * inch, 0.6 * inch, 0.45 * inch, PW - 2 * M - 4.5 * inch]))
if any(a["crashed"] for a in A):
    st.append(Paragraph("Crashed attempts (no score; real ones still count toward the cap)", H2))
    for a in A:
        if a["crashed"]: st.append(Paragraph(f"#{a['n']} {a['short']} ({a['cls']}): {html.escape(a['fail'] or '(no feedback)')}", P))

# best policy
st.append(NextPageTemplate("code")); st.append(PageBreak())
cl = closest(best_ev["src"] if best_ev else best["src"])
tgt = best_ev or best
st.append(Paragraph(f"Best evolved policy: #{tgt['n']} {tgt['short']} — score {fmt(tgt['score'])}", H2))
st.append(Paragraph(f"Title: {html.escape(tgt['title'][:600])}", P))
st.append(Paragraph("Closest available seed by line similarity: " + ", ".join(f"{n} {r:.0%}" for r, n in cl[:3]) +
                    f". Lines that differ from <b>{cl[0][1]}</b> are highlighted below.", P))
ref_lines = set(l.rstrip() for l in refs[cl[0][1]].splitlines())
out = []
for l in tgt["src"].splitlines():
    e = html.escape(l.rstrip().expandtabs(4)) or " "
    out.append(f'<span backColor="#fff1b8">{e}</span>' if l.rstrip() not in ref_lines and l.strip() else e)
for i in range(0, len(out), 120):
    st.append(XPreformatted("\n".join(out[i:i + 120]), CODE))
st.append(NextPageTemplate("main")); st.append(PageBreak())
# caveats
st.append(Paragraph("Notes and caveats", H2))
for t in (f"Hardware: {HOST}.emulab.net is a 2-core ~2 GB node; absolute numbers differ from other hosts and from the earlier c220g1 runs.",
          "Repeated evaluations of identical code vary by a few percent; differences of a few ops/s (or a few hundredths of tanh score) between attempts are within noise.",
          f"{n_t} tune attempt(s) were graded but do not count toward the 20-attempt cap." if n_t else "No tune attempts were used.",
          "Best-by-score is a single measurement; re-measure before drawing conclusions about small gaps." if True else ""):
    st.append(Paragraph("• " + html.escape(t), P))
doc.build(st)

open(f"{OUT}/README.md", "w").write(f"""# Report for CORAL run {RID} — {BRANCH}

{desc}. Host: {HOST}.emulab.net. {len(real)} real attempts ({len(scored)} scored, {n_c} crashed), {n_t} tune.

| File | What it is |
|---|---|
| `report_{RID}.pdf` | Summary, score figures, all attempts, best evolved policy with code (changed lines highlighted vs the closest seed), caveats. |
| `data.json` | Extracted attempt, session and gateway data. |
| `best/best_policy.c`, `best/best_policy.json` | Highest-scoring real attempt (#{best['n']} `{best['short']}`, {fmt(best['score'])}{' — unmodified ' + best['ref'] + '.c' if best['ref'] else ''}). |
| `best_evolved_policy.c` | Best agent-evolved attempt{f" (#{best_ev['n']} `{best_ev['short']}`, {fmt(best_ev['score'])})" if best_ev else ''}; written only if it differs from the best policy. |
| `figures/` | Figures used in the PDF. |

Rebuild: `python3 results/runreport.py <worktree> {MODE} {SEEDS} {HOST}` (needs the gitignored run directory `{RUN}`).
""")
print(OUT, "| best", best["short"], fmt(best["score"]), "| best evolved", best_ev and (best_ev["short"], fmt(best_ev["score"])), "| pages built")
