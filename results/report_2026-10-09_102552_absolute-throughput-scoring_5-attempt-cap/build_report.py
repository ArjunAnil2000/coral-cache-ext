#!/usr/bin/env python3
"""Report for CORAL run 2026-10-09_102552: absolute-throughput scoring (score = measured ops/s), 5-attempt cap."""
import collections
import datetime as dt
import json
import math
import os
import re
import sys

import matplotlib
import numpy as np
from reportlab.lib import colors
from reportlab.lib.enums import TA_LEFT
from reportlab.lib.pagesizes import landscape, letter
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import inch
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import Image, PageBreak, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import analysis as an  # noqa: E402
import figures as fg  # noqa: E402

HERE = an.HERE
REPO = os.path.dirname(os.path.dirname(HERE))
PREV_DATA = f"{REPO}/results/report_2026-10-09_004013_zscore-tanh-scoring_20-attempt-cap/data.json"
STAMP = dt.datetime.now(an.CDT).strftime("%Y-%m-%d_%H%M")
OUT_PDF = os.path.join(HERE, f"report_{STAMP}.pdf")
FONTS = os.path.join(matplotlib.get_data_path(), "fonts", "ttf")
pdfmetrics.registerFont(TTFont("DV", os.path.join(FONTS, "DejaVuSans.ttf")))
pdfmetrics.registerFont(TTFont("DV-B", os.path.join(FONTS, "DejaVuSans-Bold.ttf")))
pdfmetrics.registerFontFamily("DV", normal="DV", bold="DV-B", italic="DV", boldItalic="DV-B")
INK, INK2 = colors.HexColor("#0b0b0b"), colors.HexColor("#52514e")
HDR, ZEBRA, HILITE = colors.HexColor("#ecebe7"), colors.HexColor("#f6f5f2"), colors.HexColor("#dff3ea")
PAGE = landscape(letter)
AW = PAGE[0] - 1.0 * inch
H1 = ParagraphStyle("h1", fontName="DV-B", fontSize=14, leading=17, textColor=INK, spaceBefore=2, spaceAfter=5)
H2 = ParagraphStyle("h2", fontName="DV-B", fontSize=9.5, leading=12, textColor=INK, spaceBefore=7, spaceAfter=3)
NOTE = ParagraphStyle("note", fontName="DV", fontSize=6.8, leading=8.6, textColor=INK2, spaceBefore=1, spaceAfter=2)
HCELL = ParagraphStyle("hcell", fontName="DV-B", fontSize=6.4, leading=7.6, textColor=INK)
CELL = ParagraphStyle("cell", fontName="DV", fontSize=6.6, leading=8, textColor=INK, alignment=TA_LEFT)


def f(x, n=1):
    return "-" if x is None or (isinstance(x, float) and math.isnan(x)) else f"{x:,.{n}f}"


def sg(x, n=1):
    return "-" if x is None or (isinstance(x, float) and math.isnan(x)) else f"{x:+,.{n}f}"


def tbl(rows, widths=None, fs=7, align=None, bold_last=False, hdr_rows=1, highlight=()):
    rows = [[Paragraph(str(c), HCELL) if i < hdr_rows else (Paragraph(str(c), CELL) if isinstance(c, str) and len(c) > 28 else c) for c in row] for i, row in enumerate(rows)]
    if widths:
        widths = [w * inch for w in widths]
        if sum(widths) > AW:
            widths = [w * AW / sum(widths) for w in widths]
    t = Table(rows, colWidths=widths, repeatRows=1, hAlign="LEFT")
    st = [("FONT", (0, 0), (-1, -1), "DV", fs), ("FONT", (0, 0), (-1, hdr_rows - 1), "DV-B", fs), ("VALIGN", (0, 0), (-1, hdr_rows - 1), "BOTTOM"),
          ("BACKGROUND", (0, 0), (-1, hdr_rows - 1), HDR), ("LINEBELOW", (0, hdr_rows - 1), (-1, hdr_rows - 1), 0.6, INK2), ("LINEBELOW", (0, -1), (-1, -1), 0.6, INK2),
          ("TOPPADDING", (0, 0), (-1, -1), 1.8), ("BOTTOMPADDING", (0, 0), (-1, -1), 1.8), ("LEFTPADDING", (0, 0), (-1, -1), 3), ("RIGHTPADDING", (0, 0), (-1, -1), 3),
          ("VALIGN", (0, hdr_rows), (-1, -1), "MIDDLE"), ("TEXTCOLOR", (0, 0), (-1, -1), INK)]
    for i in range(hdr_rows, len(rows)):
        if (i - hdr_rows) % 2 == 1:
            st.append(("BACKGROUND", (0, i), (-1, i), ZEBRA))
    for i in highlight:
        st.append(("BACKGROUND", (0, i), (-1, i), HILITE))
    for ci, a in enumerate(align or []):
        if a == "R":
            st.append(("ALIGN", (ci, 0), (ci, -1), "RIGHT"))
        elif a == "C":
            st.append(("ALIGN", (ci, 0), (ci, -1), "CENTER"))
    if bold_last:
        st.append(("FONT", (0, -1), (-1, -1), "DV-B", fs))
    t.setStyle(TableStyle(st))
    return t


def img(path, width=AW, maxh=None):
    from PIL import Image as PI
    w, h = PI.open(path).size
    ht = width * h / w
    if maxh and ht > maxh:
        ht, width = maxh, maxh * w / h
    return Image(path, width=width, height=ht, hAlign="LEFT")


def side(a, b):
    return Table([[a, b]], colWidths=[AW / 2, AW / 2], hAlign="LEFT", style=[("VALIGN", (0, 0), (-1, -1), "TOP"), ("LEFTPADDING", (0, 0), (-1, -1), 0)])


def footer(canvas, doc):
    canvas.saveState()
    canvas.setFont("DV", 6.5)
    canvas.setFillColor(INK2)
    canvas.drawString(0.5 * inch, 0.3 * inch, "CORAL run 2026-10-09_102552 · cache-ext get_scan · absolute-throughput scoring · 5-attempt cap · times local (CDT, UTC-5)")
    canvas.drawRightString(PAGE[0] - 0.5 * inch, 0.3 * inch, f"page {doc.page}")
    canvas.restoreState()


def shorten(p):
    p = re.sub(r"/home/aanil/Desktop/ldos/arjua-forks", "~/arjua-forks", p)
    return re.sub(r"coral-cache-evolution/results/cache-ext-get-scan/(\d{4}-\d{2}-\d{2}_\d{6})/agents/captain-nemo", r"…/\1/agents/captain-nemo", p)


def prev_noise():
    """Within-code spread of the first run (identical code measured more than once), for context."""
    pv = json.load(open(PREV_DATA))
    g = collections.OrderedDict()
    for a in pv["attempts"]:
        g.setdefault(a["key"], []).append(a["tput"]["value"])
    multi = [x for x in g.values() if len(x) > 1]
    num = sum((len(x) - 1) * np.var(x, ddof=1) for x in multi)
    df = sum(len(x) - 1 for x in multi)
    worst = max(((abs(v - float(np.median(x))), i, j) for i, x in enumerate(multi) for j, v in enumerate(x)))
    num2, df2 = 0.0, 0
    for i, x in enumerate(multi):
        y = [v for j, v in enumerate(x) if not (i == worst[1] and j == worst[2])]
        if len(y) > 1:
            num2 += (len(y) - 1) * np.var(y, ddof=1)
            df2 += len(y) - 1
    return dict(sd_all=math.sqrt(num / df), df_all=df, sd_rob=math.sqrt(num2 / df2), df_rob=df2, n_groups=len(multi), n_meas=sum(len(x) for x in multi),
                max_range=max(100 * (max(x) - min(x)) / np.mean(x) for x in multi))


def main():
    d = json.load(open(os.path.join(HERE, "data.json")))
    A, S = d["attempts"], d["sessions"]
    bm, bs = d["prev"]["base"]["tput"]
    bio, bios = d["prev"]["base"]["io"]
    bio_mib = bio / 1048576.0
    brf, brfs = d["prev"]["base"]["rf"]
    noise = prev_noise()
    for a in A:
        a["policy"] = (a["ref"] + ".c (unmodified)") if a["ref"] else "evolved v1"
        a["dt_pct"] = an.pct(a["tput"], bm)
        a["local"] = an.hms(a["submit"])
        a["ops"] = a["tput"] * 30
    evolved = [a for a in A if not a["ref"]]
    best = max(A, key=lambda a: a["tput"])
    best_ev = max(evolved, key=lambda a: a["tput"]) if evolved else None
    tp = [a["tput"] for a in A]
    start = dt.datetime.strptime(d["run"], "%Y-%m-%d_%H%M%S").replace(tzinfo=an.CDT)
    stop = an.local(d["auto_stop"]["timestamp"])
    figs = fg.make_all(d)
    story = []

    # ------------------------------------------------------------ 1 summary
    story += [Paragraph("CORAL run 2026-10-09_102552 — results (absolute-throughput scoring)", H1), Paragraph("Run summary", H2)]
    meta = [["Item", "Value"],
            ["Task", "cache-ext-get-scan (LevelDB GET/SCAN, cache_ext eviction-policy search)"],
            ["Scoring in this run", "score = measured throughput in ops/s (absolute; higher is better). No baseline calibration, z-score, tanh or weights; branch absolute-throughput-score (commit e31539d)."],
            ["Run start → stop (local)", f"{start:%H:%M:%S} → {stop:%H:%M:%S}  ({(stop-start).total_seconds()/60:.1f} min)"],
            ["Stop reason", f"{d['auto_stop']['reason']} (cap {d['auto_stop']['max_real_attempts']}, real attempts {d['auto_stop']['real_attempt_count']}); triggering attempt {d['auto_stop']['attempt_id'][:8]}, score {d['auto_stop']['score']:.2f}"],
            ["Agent", "1 agent (captain-nemo), runtime claude_code, model alias claude-opus-5-5 → Bedrock us.anthropic.claude-opus-5-5"],
            ["Attempts recorded", f"{len(A)} = {sum(a['cls']=='real' for a in A)} real + {sum(a['cls']=='tune' for a in A)} --tune; coral eval invocations: {sum(v for k,v in d['coral_cmds'].items() if k.startswith('eval'))}; grader errors: 0 (one more eval invocation than recorded attempts)"],
            ["Attempts by code", f"{len(A) - len(evolved)} ran unmodified reference policies ({', '.join(a['ref'] + '.c' for a in A if a['ref'])}); {len(evolved)} agent-evolved design"],
            ["Attempt status (CORAL)", ", ".join(f"{k}: {v}" for k, v in collections.Counter(a['status'] for a in A).items()) + "  (relative to the agent's own previous best)"],
            ["Agent sessions (claude -p)", f"{len(S)}; terminal reason: " + ", ".join(f"{k} {v}" for k, v in collections.Counter(x.get('terminal_reason') for x in S).most_common())],
            ["LLM usage (agent)", f"{sum(x.get('out_tok',0) for x in S):,} output tokens; {sum(x.get('cache_read',0) for x in S):,} cache-read + {sum(x.get('cache_create',0) for x in S):,} cache-write + {sum(x.get('in_tok',0) for x in S):,} input tokens; Claude Code cost estimate ${S[-1].get('cost_usd',0):.2f}; API time {S[-1].get('duration_api_ms',0)/1000:,.0f} s"],
            ["Notes / skills written", f"{len(d['notes'])} notes ({len(d['denials'])} write attempts were denied by the permission layer); skills present: {', '.join(d['skills'])}"]]
    story.append(tbl(meta, [2.2, 7.8], align=["L", "L"]))
    story.append(Paragraph("Headline numbers", H2))
    head = [["Metric", "Value", "Metric", "Value"],
            ["Best score (= throughput)", f"#{best['n']} {best['short']} {best['policy']}: {f(best['tput'],2)} ops/s", "Throughput, mean ± sd of 5", f"{f(an.mean(tp),1)} ± {f(an.sd(tp),1)} ops/s"],
            ["Best agent-evolved attempt", f"#{best_ev['n']} {best_ev['short']}: {f(best_ev['tput'],2)} ops/s" if best_ev else "-", "Throughput range (max − min)", f"{f(max(tp)-min(tp),1)} ops/s ({f(100*(max(tp)-min(tp))/an.mean(tp),2)}% of mean)"],
            ["Worst score", f"#{min(A, key=lambda a: a['tput'])['n']} {min(A, key=lambda a: a['tput'])['policy']}: {f(min(tp),2)} ops/s", "Final attempt (#%d)" % A[-1]["n"], f"{A[-1]['policy']}: {f(A[-1]['tput'],2)} ops/s"],
            ["Reference: run-1 noop baseline (external)", f"{f(bm,1)} ± {f(bs,1)} ops/s (n={d['prev']['base']['n']}, run 2026-10-09_004013)", "Attempts above that reference mean", f"{sum(1 for t in tp if t > bm)} / {len(A)}"]]
    story.append(tbl(head, [2.2, 3.5, 2.0, 2.3], align=["L"] * 4))
    story.append(Paragraph("This run contains no noop evaluation (the new scoring needs no baseline). Where a baseline is shown it is the 8-run noop calibration from the first run on the same node and workload (z-score scoring, 2026-10-09_004013) and is marked 'external'.", NOTE))
    story.append(Paragraph("Scoring and recorded probes", H2))
    sc = [["Probe", "Source", "Role in this run", "Unit"],
          ["throughput", "results.json: throughput_ops_per_sec", "THE SCORE (maximized)", "ops/s"],
          ["rbytes", "cgroup io.stat (delta over measured phase)", "diagnostic only", "MiB"],
          ["wbytes, rios", "cgroup io.stat", "diagnostic only", "MiB, count"],
          ["refault_file, pgmajfault, pgactivate, resident_file", "cgroup memory.stat", "diagnostic only", "count, count, count, MiB"],
          ["wallclock", "benchmark wall time (setup + warm-up + measured)", "diagnostic only", "s"]]
    story.append(tbl(sc, [3.2, 3.6, 2.0, 1.2], align=["L"] * 4))

    # ------------------------------------------------------------ 2 environment & workload
    story += [PageBreak(), Paragraph("Environment and workload", H1), Paragraph("Evaluation node (CloudLab, Wisconsin)", H2)]
    hw = [["Component", "Value", "Component", "Value"],
          ["Node type", "c220g1", "Kernel", "6.6.8-cache-ext+ (Ubuntu 22.04.2)"],
          ["CPU", "2 × Intel Xeon E5-2630 v3 @ 2.40 GHz", "Cores / threads", "16 cores / 32 threads (2 sockets, 2 NUMA nodes)"],
          ["Memory", "131,732,952 kB (125.6 GiB), no swap", "Disks", "2 × 1.1 TB SAS HDD, 1 × 447 GB SSD"],
          ["Benchmark filesystem", "/mydata on /dev/sda3 (HDD), 63 GB", "Cgroup", "cgroup v2; benchmark memory.max = 64 MB"],
          ["Compiler / tools", "clang 14.0.0-1ubuntu1.1, bpftool v7.3.0", "Eval isolation", "one eval at a time (flock); policy attached via BPF struct_ops"]]
    story.append(tbl(hw, [1.7, 3.3, 1.7, 3.3], align=["L"] * 4))
    story.append(Paragraph("Workload parameters (benchmark harness defaults, every attempt)", H2))
    wl = [["Parameter", "Value", "Parameter", "Value"],
          ["Benchmark", "My-YCSB (leveldb-scan branch), run_leveldb", "Request distribution / Zipfian constant", "zipfian / 0.99"],
          ["Operation mix", "95% GET (read), 5% SCAN", "Worker threads", "4 (exactly 1 dedicated scan thread)"],
          ["Scan length", "500 keys per SCAN", "Measured phase", "30 s"],
          ["Database entries", "500,000", "Warm-up phase", "10 s (same mix, probes not recording)"],
          ["Key / value size", "16 B / 200 B", "LevelDB block cache", "16 MiB"],
          ["Cgroup memory limit (page cache)", "64 MB", "Page cache at start", "dropped before each run"],
          ["Per-eval timeout", "180 s", "Observed eval wall time", f"{f(an.mean([a['wallclock'] for a in A]),1)} s mean ({f(min(a['wallclock'] for a in A),1)} … {f(max(a['wallclock'] for a in A),1)})"]]
    story.append(tbl(wl, [2.0, 3.0, 2.2, 2.8], align=["L"] * 4))

    # ------------------------------------------------------------ 3 per-attempt
    story += [PageBreak(), Paragraph("Per-attempt results", H1)]
    rows = [["#", "Local", "Commit", "Parent", "Policy", "Status", "SCORE = throughput (ops/s)", "Δ ops/s vs ext. ref", "Δ%", "Wall s", "Eval s", "+/− lines", "Code lines"]]
    for a in A:
        rows.append([a["n"], a["local"], a["short"], a["parent"], a["policy"], a["status"], f(a["tput"], 2), sg(a["tput"] - bm, 1), sg(a["dt_pct"], 2), f(a["wallclock"], 1), f(a["eval_latency_s"], 0),
                     f"+{a['diff_add']}/−{a['diff_del']}" if a["diff_add"] is not None else "-", a["code_lines"]])
    hl = [1 + i for i, a in enumerate(A) if a is best]
    story.append(tbl(rows, [0.3, 0.65, 0.7, 0.7, 1.6, 0.7, 1.1, 0.9, 0.55, 0.5, 0.5, 0.8, 0.6], fs=6.8, align=["R", "C", "L", "L", "L", "L", "R", "R", "R", "R", "R", "R", "R"], highlight=hl))
    story.append(Paragraph(f"Shaded = highest score. Δ columns compare with the external run-1 noop mean ({f(bm,1)} ops/s). Eval s = submit → graded; with no calibration step every attempt takes one evaluation. Status is CORAL's comparison with the agent's own previous best, not with a baseline.", NOTE))
    story.append(Paragraph("Diagnostic probes and derived per-operation metrics", H2))
    rows = [["#", "Commit", "Policy", "Bytes read MiB", "Δ% vs ext. ref", "Bytes written MiB", "Read I/Os", "Refaults", "Δ% vs ext. ref", "pgmajfault", "pgactivate", "Resident file MiB",
             "Ops in phase (≈ tput × 30)", "Read KB / op", "Refaults / 1k ops", "Read I/Os / 1k ops", "Read MB/s"]]
    for a in A:
        rows.append([a["n"], a["short"], a["policy"], f(a["rbytes_mib"], 1), sg(an.pct(a["rbytes_mib"], bio_mib), 1), f(a["wbytes_mib"], 1), f(a["rios"], 0), f(a["refault_file"], 0), sg(an.pct(a["refault_file"], brf), 1),
                     a["pgmajfault"], f(a["pgactivate"], 0), a["resident_mib"], f(a["ops"], 0), f(a["rbytes_mib"] * 1048.576 / a["ops"], 2), f(a["refault_file"] / a["ops"] * 1e3, 1), f(a["rios"] / a["ops"] * 1e3, 1), f(a["rbytes_mib"] * 1.048576 / 30, 2)])
    story.append(tbl(rows, [0.25, 0.62, 1.3, 0.5, 0.5, 0.5, 0.5, 0.55, 0.5, 0.68, 0.7, 0.62, 0.65, 0.5, 0.55, 0.55, 0.5], fs=6.0, align=["R", "L", "L"] + ["R"] * 14))
    story.append(Paragraph(f"External run-1 noop reference for these probes: bytes read {f(bio_mib,1)} MiB, refaults {f(brf,0)}. Assumes the probes cover exactly the 30 s measured phase, so operations = throughput × 30.", NOTE))
    story += [Paragraph("Attempt descriptions (commit messages, verbatim)", H2)]
    rows = [["#", "Commit", "Policy", "Description"]] + [[a["n"], a["short"], a["policy"], a["title"]] for a in A]
    story.append(tbl(rows, [0.3, 0.7, 1.5, 7.5], fs=6.8, align=["R", "L", "L", "L"]))

    # ------------------------------------------------------------ 4 figures
    story += [PageBreak(), Paragraph("Score per attempt", H1), img(figs["tput"], AW, 3.4 * inch), Spacer(1, 6), img(figs["io"], AW, 3.1 * inch)]

    # ------------------------------------------------------------ 5 cross-run
    story += [PageBreak(), Paragraph("Same code, two runs", H1)]
    refs = d["prev"]["refs"]
    names = ["get_scan", "s3fifo", "mglru", "sampling", "lhd", "mru"]
    rows = [["Policy (unmodified reference code)", "Run 1 attempts (class: ops/s)", "Run 1 mean", "Run 2 (attempt: ops/s)", "Δ ops/s (run 2 − run 1 mean)", "Δ%", "Δ in robust within-code sd", "Run 1 bytes read MiB", "Run 2 bytes read MiB", "Run 1 refaults", "Run 2 refaults"]]
    for n in names:
        r1 = [p for p in refs if p["ref"] == n]
        r2 = [a for a in A if a["ref"] == n]
        m1 = an.mean([p["tput"] for p in r1]) if r1 else float("nan")
        m2 = an.mean([a["tput"] for a in r2]) if r2 else float("nan")
        dd = m2 - m1
        rows.append([n + ".c", ", ".join(f"{p['cls']} #{p['n']}: {f(p['tput'],1)}" for p in r1) or "not run", f(m1, 1), ", ".join(f"#{a['n']}: {f(a['tput'],2)}" for a in r2) or "not run", sg(dd, 1), sg(100 * dd / m1, 1) if not math.isnan(dd) else "-",
                     sg(dd / noise["sd_rob"], 1) if not math.isnan(dd) else "-", f(an.mean([p["io_bytes"] for p in r1]) / 1048576, 1) if r1 else "-", f(an.mean([a["rbytes_mib"] for a in r2]), 1) if r2 else "-",
                     f(an.mean([p["rf"] for p in r1]), 0) if r1 else "-", f(an.mean([a["refault_file"] for a in r2]), 0) if r2 else "-"])
    story.append(tbl(rows, [1.5, 2.3, 0.6, 1.2, 0.9, 0.5, 0.8, 0.8, 0.8, 0.7, 0.7], fs=6.6, align=["L", "L", "R", "L", "R", "R", "R", "R", "R", "R", "R"]))
    story.append(Paragraph("Run 1 = 2026-10-09_004013 (z-score scoring, 20-attempt cap); run 2 = this run. The attempts compared run byte-identical policy code (comment-only lines ignored): the agent copied each reference file over noop.c unchanged in both runs. mglru.c and lhd.c were run only in run 1, mru.c only in run 2.", NOTE))
    story.append(Paragraph("Run-1 within-code spread (context for the size of the differences)", H2))
    rows = [["Quantity (from run 1: identical code measured more than once)", "Value"],
            ["Groups / measurements", f"{noise['n_groups']} groups, {noise['n_meas']} measurements"],
            ["Pooled within-code sd of throughput (all data)", f"{f(noise['sd_all'],2)} ops/s (df {noise['df_all']})"],
            ["Pooled within-code sd excluding the most deviant single measurement ('robust')", f"{f(noise['sd_rob'],2)} ops/s (df {noise['df_rob']})"],
            ["Largest within-code range in run 1", f"{f(noise['max_range'],2)} % of the group mean"],
            ["Run-1 noop baseline sd (8 consecutive evals)", f"{f(bs,2)} ops/s"]]
    story.append(tbl(rows, [6.0, 4.0], align=["L", "L"]))
    story += [Spacer(1, 6), img(figs["cross"], AW, 3.1 * inch)]

    # ------------------------------------------------------------ 6 best
    story += [PageBreak(), Paragraph("Best attempt and best agent-evolved design", H1)]
    rows = [["Item", "Highest score (overall)", "Best agent-evolved design"],
            ["Attempt", f"#{best['n']}  {best['hash']}", f"#{best_ev['n']}  {best_ev['hash']}" if best_ev else "-"],
            ["Policy", best["policy"], "evolved v1 (agent's own design; no reference code)" if best_ev else "-"],
            ["Score (= throughput, ops/s)", f(best["tput"], 2), f(best_ev["tput"], 2) if best_ev else "-"],
            ["vs external run-1 noop mean", f"{sg(best['tput']-bm,1)} ops/s ({sg(best['dt_pct'],2)}%)", f"{sg(best_ev['tput']-bm,1)} ops/s ({sg(best_ev['dt_pct'],2)}%)" if best_ev else "-"],
            ["Bytes read (MiB) / refaults", f"{f(best['rbytes_mib'],1)} / {f(best['refault_file'],0)}", f"{f(best_ev['rbytes_mib'],1)} / {f(best_ev['refault_file'],0)}" if best_ev else "-"],
            ["Code size", f"{best['code_lines']} lines (kernel {best['kernel_lines']}, loader {best['loader_lines']})", f"{best_ev['code_lines']} lines (kernel {best_ev['kernel_lines']}, loader {best_ev['loader_lines']})" if best_ev else "-"],
            ["Description", best["title"], best_ev["title"] if best_ev else "-"]]
    story.append(tbl(rows, [1.6, 3.8, 4.6], align=["L", "L", "L"]))
    story.append(Paragraph("Ranking of all attempts by score", H2))
    rows = [["Rank", "#", "Commit", "Policy", "Score (ops/s)", "Δ vs best (ops/s)", "Δ vs best (%)"]]
    for r_, a in enumerate(sorted(A, key=lambda a: -a["tput"]), 1):
        rows.append([r_, a["n"], a["short"], a["policy"], f(a["tput"], 2), sg(a["tput"] - best["tput"], 1), sg(an.pct(a["tput"], best["tput"]), 2)])
    story.append(tbl(rows, [0.5, 0.4, 0.9, 2.2, 1.2, 1.3, 1.2], align=["R", "R", "L", "L", "R", "R", "R"]))
    story.append(Paragraph(f"Each attempt is a single measurement; identical code varied by up to {f(noise['max_range'],1)}% in run 1, so adjacent ranks (differences under about 1–2%) are not distinguishable. The agent-evolved design's source is saved as best_evolved_policy.c.", NOTE))

    # ------------------------------------------------------------ 7 timing
    story += [Spacer(1, 8), Paragraph("Timing", H1)]
    gw = d["gateway"]
    first_req = min(dt.datetime.fromisoformat(r["ts"]) for r in gw).astimezone(an.CDT)
    lat = [a["eval_latency_s"] for a in A]
    ph = [["Event", "Time", "Elapsed since start (min)"],
          ["Run directory created / manager started", start.strftime("%H:%M:%S"), "0.0"],
          ["First model request at the gateway", first_req.strftime("%H:%M:%S"), f((first_req - start).total_seconds() / 60, 1)],
          ["First submission (attempt #1)", an.local(A[0]["submit"]).strftime("%H:%M:%S"), f((an.local(A[0]["submit"]) - start).total_seconds() / 60, 1)],
          ["Last submission (attempt #%d)" % A[-1]["n"], an.local(A[-1]["submit"]).strftime("%H:%M:%S"), f((an.local(A[-1]["submit"]) - start).total_seconds() / 60, 1)],
          ["Last attempt graded / auto-stop recorded", stop.strftime("%H:%M:%S"), f((stop - start).total_seconds() / 60, 1)]]
    story.append(tbl(ph, [4.5, 1.5, 2.0], align=["L", "R", "R"]))
    wall = (stop - start).total_seconds()
    story += [Spacer(1, 4), tbl([["Time budget", "Seconds", "% of run wall time"], ["Evaluation (all 5 attempts, submit → graded)", f(sum(lat), 0), f(100 * sum(lat) / wall, 1)],
                                 ["Everything else (agent reading, thinking, editing)", f(wall - sum(lat), 0), f(100 * (wall - sum(lat)) / wall, 1)], ["Run wall time", f(wall, 0), "100.0"]],
                                [5.0, 1.5, 1.5], align=["L", "R", "R"], bold_last=True),
              Paragraph(f"Eval latency per attempt: min {f(min(lat),1)} s, median {f(float(np.median(lat)),1)} s, max {f(max(lat),1)} s.", NOTE)]

    # ------------------------------------------------------------ 8 sessions & gateway
    story += [PageBreak(), Paragraph("Agent sessions and LLM usage", H1)]
    cum_c = [x.get("cost_usd") or 0 for x in S]
    cum_a = [x.get("duration_api_ms") or 0 for x in S]
    inc_c = [cum_c[0]] + [b - a for a, b in zip(cum_c, cum_c[1:])]
    inc_a = [cum_a[0]] + [b - a for a, b in zip(cum_a, cum_a[1:])]
    rows = [["#", "Start", "Wall s", "API s (Δ)", "Turns", "Cost $ (Δ)", "Input tok", "Cache write tok", "Cache read tok", "Output tok", "Thinking tok", "API retries", "Denials", "Terminal reason"]]
    for i, s in enumerate(S):
        rows.append([s["idx"], an.hms(s["start"]), f((s.get("duration_ms") or 0) / 1000, 0), f(inc_a[i] / 1000, 0), s.get("num_turns", "-"), f(inc_c[i], 3), f(s.get("in_tok", 0), 0), f(s.get("cache_create", 0), 0),
                     f(s.get("cache_read", 0), 0), f(s.get("out_tok", 0), 0), f(s.get("think_tok", 0), 0), s.get("api_retries", 0), s.get("denials", 0), s.get("terminal_reason") or "-"])
    tot = lambda k: sum((s.get(k) or 0) for s in S)
    rows.append(["Σ", "", f(tot("duration_ms") / 1000, 0), f(cum_a[-1] / 1000, 0), tot("num_turns"), f(cum_c[-1], 2), f(tot("in_tok"), 0), f(tot("cache_create"), 0), f(tot("cache_read"), 0), f(tot("out_tok"), 0), f(tot("think_tok"), 0), tot("api_retries"), tot("denials"), ""])
    story.append(tbl(rows, [0.3, 0.6, 0.5, 0.6, 0.4, 0.6, 0.65, 0.9, 1.0, 0.7, 0.75, 0.55, 0.5, 1.1], fs=6.6, align=["R", "C"] + ["R"] * 11 + ["L"], bold_last=True))
    story.append(Paragraph("Cost and API time are cumulative in Claude Code's result records, so rows show the increase over the previous session and Σ the final value; cost is Claude Code's estimate, not an AWS bill. Wall s, turns and tokens are per session. aborted_streaming = the session was cut off mid-response (consistent with CORAL interrupting and resuming the agent).", NOTE))
    story.append(Paragraph("Agent actions", H2))
    rows = [["Tool", "Calls"]] + [[k, v] for k, v in sorted(d["tool_counts"].items(), key=lambda kv: -kv[1])]
    rows2 = [["coral command", "Count"]] + [[k, v] for k, v in sorted(d["coral_cmds"].items(), key=lambda kv: -kv[1])]
    story.append(side(tbl(rows, [1.6, 0.7], fs=6.8, align=["L", "R"]), tbl(rows2, [1.6, 0.7], fs=6.8, align=["L", "R"])))
    story.append(Paragraph("Permission denials (actions the permission layer refused)", H2))
    rows = [["Session", "Tool", "Target (truncated)"]] + [[x["session"], x["tool"], x["target"]] for x in d["denials"]] if d["denials"] else [["Session", "Tool", "Target"], ["-", "-", "none"]]
    story.append(tbl(rows, [0.6, 0.8, 8.6], fs=6.4, align=["R", "L", "L"]))

    by = collections.Counter((r["model"], r["status"]) for r in gw)
    err = collections.Counter((r["status"], r["model"], r["err"]) for r in gw if r["status"] != 200)
    story += [PageBreak(), Paragraph("LLM gateway (LiteLLM → Bedrock)", H1), Paragraph("Requests by model and HTTP status", H2)]
    models = sorted({m for m, _ in by})
    codes = sorted({s for _, s in by})
    rows = [["Model alias"] + [str(c) for c in codes] + ["Total", "Success %"]]
    for m in models:
        tot_ = sum(by[(m, c)] for c in codes)
        rows.append([m] + [by[(m, c)] for c in codes] + [tot_, f(100 * by[(m, 200)] / tot_, 1)])
    T_ = [sum(by[(m, c)] for m in models) for c in codes]
    rows.append(["all"] + T_ + [sum(T_), f(100 * T_[codes.index(200)] / sum(T_), 1)])
    story.append(tbl(rows, [2.2] + [0.8] * len(codes) + [0.8, 1.0], align=["L"] + ["R"] * (len(codes) + 2), bold_last=True))
    story.append(Paragraph("Failure causes", H2))
    rows = [["HTTP", "Model alias", "Count", "Message (summarised from the gateway's error body)"]] + [[st, m, n, e] for (st, m, e), n in sorted(err.items(), key=lambda kv: -kv[1])]
    story.append(tbl(rows, [0.5, 1.4, 0.6, 7.5], align=["R", "L", "R", "L"]))
    x = [r["dur_ms"] / 1000 for r in gw if r["status"] == 200]
    story.append(Paragraph("Response time of successful (200) requests", H2))
    story.append(tbl([["n", "Mean s", "p50 s", "p90 s", "p99 s", "Max s", "Sum s"], [len(x), f(an.mean(x), 2), f(an.pctile(x, 50), 2), f(an.pctile(x, 90), 2), f(an.pctile(x, 99), 2), f(max(x), 2), f(sum(x), 0)]],
                     [0.6, 0.9, 0.9, 0.9, 0.9, 0.9, 0.9], align=["R"] * 7))
    sess = collections.Counter(r["session"] for r in gw)
    story.append(Paragraph("Context the agent received", H2))
    rows = [["Instruction file injected into the agent's prompts", "Requests containing it", "of total"]] + [[shorten(k), v, d["gateway_total"]] for k, v in sorted(d["context_files"].items(), key=lambda kv: -kv[1])]
    story.append(tbl(rows, [7.0, 1.5, 1.0], align=["L", "R", "R"]))
    story.append(Paragraph(f"Gateway: {d['gateway_total']} requests in {len(sess)} gateway sessions. The first file is the arjua-forks repository's own project instructions (the earlier throughput-profiling project), loaded because the agent's worktree sits below that directory; the second is the task's CLAUDE.md written by CORAL.", NOTE))
    story.append(Paragraph("Measurements not available for this run", H2))
    rows = [["Quantity", "Status"],
            ["Noop baseline in this run", "None evaluated; the agent's own comparison point was the figure given in the task description (≈ 1210–1225 ops/s). The run-1 calibration is used as an external reference."],
            ["Per-operation latency (READ p99, SCAN p99), per-thread throughput", "Written to a per-eval scratch directory that is deleted after each eval; not retained"],
            ["Policy counters", "No policy exported a metrics file"],
            ["Agent notes", f"{len(d['notes'])} written; the agent's attempts to create the notes directory and files were denied (see permission denials)"],
            ["CPU utilisation / cycles during evals", "Not collected"]]
    story.append(tbl(rows, [3.5, 6.5], align=["L", "L"]))

    doc = SimpleDocTemplate(OUT_PDF, pagesize=PAGE, leftMargin=0.5 * inch, rightMargin=0.5 * inch, topMargin=0.45 * inch, bottomMargin=0.5 * inch,
                            title="CORAL run 2026-10-09_102552 — results (absolute-throughput scoring)", author="coral-cache-evolution")
    doc.build(story, onFirstPage=footer, onLaterPages=footer)
    # best evolved policy source
    import subprocess
    if best_ev:
        ag = f"{REPO}/results/cache-ext-get-scan/{d['run']}/agents/captain-nemo"
        open(os.path.join(HERE, "best_evolved_policy.c"), "w").write(subprocess.run(["git", "show", f"{best_ev['hash']}:noop.c"], cwd=ag, capture_output=True, text=True).stdout)
    print("wrote", OUT_PDF)


if __name__ == "__main__":
    main()
