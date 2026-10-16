#!/usr/bin/env python3
"""FULL report (2026-10-09 10:27): numbers, tables and necessary graphs for one CORAL run."""
import collections
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
import figures_full as fg  # noqa: E402

OUT_PDF = os.path.join(an.HERE, "report_2026-10-09_1027_full.pdf")
FONTS = os.path.join(matplotlib.get_data_path(), "fonts", "ttf")
pdfmetrics.registerFont(TTFont("DV", os.path.join(FONTS, "DejaVuSans.ttf")))
pdfmetrics.registerFont(TTFont("DV-B", os.path.join(FONTS, "DejaVuSans-Bold.ttf")))
pdfmetrics.registerFontFamily("DV", normal="DV", bold="DV-B", italic="DV", boldItalic="DV-B")
INK, INK2 = colors.HexColor("#0b0b0b"), colors.HexColor("#52514e")
HDR, ZEBRA = colors.HexColor("#ecebe7"), colors.HexColor("#f6f5f2")
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


def tbl(rows, widths=None, fs=7, align=None, zebra=True, bold_last=False, hdr_rows=1, repeat=1):
    rows = [[Paragraph(str(c), HCELL) if i < hdr_rows else (Paragraph(str(c), CELL) if isinstance(c, str) and len(c) > 28 else c)
             for c in row] for i, row in enumerate(rows)]
    if widths:
        widths = [w * inch for w in widths]
        if sum(widths) > AW:
            widths = [w * AW / sum(widths) for w in widths]
    t = Table(rows, colWidths=widths, repeatRows=repeat, hAlign="LEFT")
    st = [("FONT", (0, 0), (-1, -1), "DV", fs), ("FONT", (0, 0), (-1, hdr_rows - 1), "DV-B", fs), ("VALIGN", (0, 0), (-1, hdr_rows - 1), "BOTTOM"),
          ("BACKGROUND", (0, 0), (-1, hdr_rows - 1), HDR), ("LINEBELOW", (0, hdr_rows - 1), (-1, hdr_rows - 1), 0.6, INK2),
          ("LINEBELOW", (0, -1), (-1, -1), 0.6, INK2), ("TOPPADDING", (0, 0), (-1, -1), 1.6), ("BOTTOMPADDING", (0, 0), (-1, -1), 1.6),
          ("LEFTPADDING", (0, 0), (-1, -1), 3), ("RIGHTPADDING", (0, 0), (-1, -1), 3), ("VALIGN", (0, hdr_rows), (-1, -1), "MIDDLE"),
          ("TEXTCOLOR", (0, 0), (-1, -1), INK)]
    if zebra:
        for i in range(hdr_rows, len(rows)):
            if (i - hdr_rows) % 2 == 1:
                st.append(("BACKGROUND", (0, i), (-1, i), ZEBRA))
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


def two(a, b):
    wa = AW / 2 - 4
    return Table([[img(a, wa), img(b, wa)]], colWidths=[AW / 2, AW / 2], hAlign="LEFT",
                 style=[("LEFTPADDING", (0, 0), (-1, -1), 0), ("RIGHTPADDING", (0, 0), (-1, -1), 2), ("VALIGN", (0, 0), (-1, -1), "TOP")])


def side_by_side(a, b):
    return Table([[a, b]], colWidths=[AW / 2, AW / 2], hAlign="LEFT", style=[("VALIGN", (0, 0), (-1, -1), "TOP"), ("LEFTPADDING", (0, 0), (-1, -1), 0)])


def footer(canvas, doc):
    canvas.saveState()
    canvas.setFont("DV", 6.5)
    canvas.setFillColor(INK2)
    canvas.drawString(0.5 * inch, 0.3 * inch, "CORAL run 2026-10-09_004013 · cache-ext get_scan · FULL report · all times local (CDT, UTC-5) unless marked")
    canvas.drawRightString(PAGE[0] - 0.5 * inch, 0.3 * inch, f"page {doc.page}")
    canvas.restoreState()


def shorten_path(p):
    p = re.sub(r"/home/aanil/Desktop/ldos/arjua-forks", "~/arjua-forks", p)
    return re.sub(r"coral-cache-evolution/results/cache-ext-get-scan/(\d{4}-\d{2}-\d{2}_\d{6})/agents/captain-nemo", r"…/\1/agents/captain-nemo", p)


def main():
    d = an.load()
    A = d["attempts"]
    G = an.groups(A)
    figs = fg.make_all(d, G)
    bm, bs = d["base"]["tput"]
    bi, bis = d["base"]["io"]
    br, brs = d["base"]["rf"]
    S = d["sessions"]
    real = [a for a in A if a["cls"] == "real"]
    tune = [a for a in A if a["cls"] == "tune"]
    tput_all = [a["t"] for a in A]
    story = []

    # ---------------------------------------------------------------- 1 summary
    best_s = max(real, key=lambda a: a["score"])
    best_t = max(A, key=lambda a: a["t"])
    worst_t = min(A, key=lambda a: a["t"])
    start = an.dt.datetime.strptime(d["run"], "%Y-%m-%d_%H%M%S").replace(tzinfo=an.CDT)
    stop = an.local(d["auto_stop"]["timestamp"])
    story += [Paragraph("CORAL run 2026-10-09_004013 — results", H1), Paragraph("Run summary", H2)]
    meta = [["Item", "Value"],
            ["Task", "cache-ext-get-scan (LevelDB GET/SCAN, cache_ext eviction-policy search)"],
            ["Run start → stop (local)", f"{start:%H:%M:%S} → {stop:%H:%M:%S}  ({(stop-start).total_seconds()/60:.1f} min)"],
            ["Stop reason", f"{d['auto_stop']['reason']} (cap {d['auto_stop']['max_real_attempts']}, real attempts {d['auto_stop']['real_attempt_count']}); triggering attempt {d['auto_stop']['attempt_id'][:8]}, score {d['auto_stop']['score']:.4f}"],
            ["Agent", "1 agent (captain-nemo), runtime claude_code, model alias claude-opus-5-5 → Bedrock us.anthropic.claude-opus-5-5"],
            ["Attempts recorded", f"{len(A)} = {len(real)} real + {len(tune)} --tune;  coral eval invocations: {sum(v for k,v in d['coral_cmds'].items() if k.startswith('eval'))};  grader errors: 0"],
            ["Attempt status (CORAL)", ", ".join(f"{k}: {v}" for k, v in collections.Counter(a['status'] for a in A).items())],
            ["Agent sessions (claude -p)", f"{len(S)}; terminal reason: " + ", ".join(f"{k} {v}" for k, v in collections.Counter(x.get('terminal_reason') for x in S).most_common())],
            ["LLM usage (agent)", f"{sum(x.get('out_tok',0) for x in S):,} output tokens; {sum(x.get('cache_read',0) for x in S):,} cache-read + {sum(x.get('cache_create',0) for x in S):,} cache-write + {sum(x.get('in_tok',0) for x in S):,} input tokens; Claude Code cost estimate ${S[-1].get('cost_usd',0):.2f}; API time {S[-1].get('duration_api_ms',0)/1000:,.0f} s"],
            ["Notes / skills written", f"{len(d['notes'])} note files; skills present: {', '.join(d['skills'])}"],
            ["Distinct code versions", f"{len(G)} (identical code after stripping comment-only lines)"]]
    story.append(tbl(meta, [2.2, 7.8], align=["L", "L"]))
    story.append(Paragraph("Headline numbers", H2))
    above1 = sum(1 for t in tput_all if t > bm + bs)
    above2 = sum(1 for t in tput_all if t > bm + 2 * bs)
    above3 = sum(1 for t in tput_all if t > bm + 3 * bs)
    below = sum(1 for t in tput_all if t < bm)
    head = [["Metric", "Value", "Metric", "Value"],
            ["Noop baseline throughput (n=%d)" % d["base"]["n"], f"{f(bm)} ± {f(bs)} ops/s", "Attempts above baseline mean", f"{sum(1 for t in tput_all if t > bm)} / {len(A)}"],
            ["Best by score (real)", f"#{best_s['n']} {best_s['short']}: score {best_s['score']:.4f}, {f(best_s['t'])} ops/s", "Attempts > mean+1σ / +2σ / +3σ", f"{above1} / {above2} / {above3}"],
            ["Best by throughput (all)", f"#{best_t['n']} {best_t['short']} ({best_t['cls']}): {f(best_t['t'])} ops/s ({sg(best_t['dt_pct'],2)}%), score {best_t['score']:.4f}", "Attempts below baseline mean", f"{below} / {len(A)}"],
            ["Worst by throughput", f"#{worst_t['n']} {worst_t['short']}: {f(worst_t['t'])} ops/s ({sg(worst_t['dt_pct'],2)}%)", "Score range (min … max)", f"{min(a['score'] for a in A):.4f} … {max(a['score'] for a in A):.4f}"],
            ["Throughput, all attempts: mean ± sd", f"{f(an.mean(tput_all))} ± {f(an.sd(tput_all))} ops/s", "Throughput median (p10 … p90)", f"{f(an.pctile(tput_all,50))}  ({f(an.pctile(tput_all,10))} … {f(an.pctile(tput_all,90))})"],
            ["Throughput range (max − min)", f"{f(max(tput_all)-min(tput_all))} ops/s", "Final attempt (#%d)" % A[-1]["n"], f"{f(A[-1]['t'])} ops/s, score {A[-1]['score']:.4f}"],
            ["Bytes read, best (lowest)", f"{f(min(a['io_v'] for a in A)/1e6)} MB ({sg(min(a['dio_pct'] for a in A),1)}%)", "Refaults, best (lowest)", f"{f(min(a['rf_v'] for a in A),0)} ({sg(min(a['drf_pct'] for a in A),1)}%)"]]
    story.append(tbl(head, [2.0, 3.5, 2.2, 2.3], align=["L", "L", "L", "L"]))
    story.append(Paragraph("σ = baseline standard deviation of the 8 noop calibration runs. Δ% is relative to the baseline mean of the same probe. MB = 10^6 bytes.", NOTE))
    story.append(Paragraph("Summary by attempt class", H2))

    def crow(name, xs):
        t = [a["t"] for a in xs]
        return [name, len(xs), f(an.mean(t), 1), f(an.sd(t), 1), f(min(t), 1), f(max(t), 1), f(an.mean([a["score"] for a in xs]), 3), f(max(a["score"] for a in xs), 4),
                f(an.mean([a["io_v"] for a in xs]) / 1e6, 1), f(an.mean([a["rf_v"] for a in xs]), 0)]
    story.append(tbl([["Class", "n", "Mean tput", "sd", "Min", "Max", "Mean score", "Best score", "Mean bytes read MB", "Mean refaults"],
                      crow("real", real), crow("tune", tune), crow("all", A)], [1.0, 0.4, 0.9, 0.7, 0.8, 0.8, 0.9, 0.9, 1.3, 1.1], bold_last=True, align=["L"] + ["R"] * 9))

    # ---------------------------------------------------------------- 2 environment & workload
    story += [PageBreak(), Paragraph("Environment and workload", H1), Paragraph("Evaluation node (CloudLab, Wisconsin)", H2)]
    hw = [["Component", "Value", "Component", "Value"],
          ["Node type", "c220g1", "Kernel", "6.6.8-cache-ext+ (Ubuntu 22.04.2)"],
          ["CPU", "2 × Intel Xeon E5-2630 v3 @ 2.40 GHz", "Cores / threads", "16 cores / 32 threads (2 sockets, 2 NUMA nodes)"],
          ["CPU max / min MHz; governor", "3200 / 1200; schedutil", "Caches (L1d / L2 / L3)", "512 KiB / 4 MiB / 40 MiB (aggregate)"],
          ["Memory", "131,732,952 kB (125.6 GiB), no swap", "Disks", "2 × 1.1 TB SAS HDD (ST1200MM0007), 1 × 447 GB SSD (Intel SSDSC2BB480G4)"],
          ["Benchmark filesystem", "/mydata on /dev/sda3 (HDD), 63 GB, 25% used", "Cgroup", "cgroup v2; benchmark memory.max = 64 MB"],
          ["Compiler / tools", "clang 14.0.0-1ubuntu1.1, bpftool v7.3.0, libbpf (static)", "Eval isolation", "one eval at a time (flock); policy attached via BPF struct_ops to the cgroup"]]
    story.append(tbl(hw, [1.7, 3.3, 1.7, 3.3], align=["L"] * 4))
    story.append(Paragraph("Workload parameters (benchmark harness defaults, used for every attempt)", H2))
    wl = [["Parameter", "Value", "Parameter", "Value"],
          ["Benchmark", "My-YCSB (leveldb-scan branch), run_leveldb", "Request distribution / Zipfian constant", "zipfian / 0.99"],
          ["Operation mix", "95% GET (read), 5% SCAN", "Worker threads", "4 (exactly 1 dedicated scan thread)"],
          ["Scan length", "500 keys per SCAN", "Measured phase", "30 s"],
          ["Database entries", "500,000", "Warm-up phase", "10 s (same mix, probes not recording)"],
          ["Key / value size", "16 B / 200 B", "LevelDB block cache", "16 MiB (16,777,216 B)"],
          ["Cgroup memory limit (page cache)", "64 MB", "Page cache at start", "dropped before each run (echo 3 > drop_caches)"],
          ["Per-eval timeout", "180 s", "Observed eval wall time", f"{f(an.mean([a['wallclock'] for a in A]))} s mean ({f(min(a['wallclock'] for a in A))} … {f(max(a['wallclock'] for a in A))})"],
          ["Policy loader", "started detached; given -w <db dir> -s <cgroup bytes> -c <cgroup>", "scan_pids map", "pinned by harness; policies may read it (ground-truth scan-thread tids)"]]
    story.append(tbl(wl, [2.0, 3.0, 2.2, 2.8], align=["L"] * 4))
    story.append(Paragraph("Scoring and probes", H2))
    sc = [["Probe", "Source", "Direction", "Weight", "Baseline mean", "Baseline sd", "CV %", "n"],
          ["throughput (ops/s)", "results.json: throughput_ops_per_sec", "maximize", "2.0", f(bm, 2), f(bs, 2), f(100 * bs / bm, 2), d["base"]["n"]],
          ["bytes read (cgroup rbytes)", "cgroup io.stat (delta over measured phase)", "minimize", "0.5", f"{bi:,.0f}", f"{bis:,.0f}", f(100 * bis / bi, 2), d["base"]["n"]],
          ["refaults (cgroup memstat)", "cgroup memory.stat refault_file (delta)", "minimize", "0.25", f(br, 1), f(brs, 1), f(100 * brs / br, 2), d["base"]["n"]]]
    story.append(tbl(sc, [2.0, 3.1, 0.9, 0.7, 1.3, 1.1, 0.6, 0.4], align=["L", "L", "L", "R", "R", "R", "R", "R"]))
    story.append(Paragraph("score = Σ w·tanh(±z) / Σ w, where z = (value − baseline mean)/baseline sd, sign chosen so that an improvement is positive; range [−1, 1], 0 = same as noop. Weights sum to 2.75.", NOTE))

    # ---------------------------------------------------------------- 3 per-attempt
    story += [PageBreak(), Paragraph("Per-attempt results", H1)]
    hdr = ["#", "Local", "Commit", "Cls", "Parent", "Score", "Tput ops/s", "Δ%", "z", "Bytes read MB", "Δ%", "Refaults", "Δ%", "Wall s", "Eval s", "+/− lines", "Code lines"]
    rows = [hdr]
    for a in A:
        rows.append([a["n"], a["local"], a["short"], a["cls"], a["parent"], f(a["score"], 4), f(a["t"], 1), sg(a["dt_pct"], 1), sg(a["tz"], 1), f(a["io_v"] / 1e6, 1), sg(a["dio_pct"], 1),
                     f(a["rf_v"], 0), sg(a["drf_pct"], 1), f(a["wallclock"], 1), f(a["eval_latency_s"], 0),
                     f"+{a['diff_add']}/−{a['diff_del']}" if a["diff_add"] is not None else "-", a["code_lines"]])
    story.append(tbl(rows, [0.3, 0.6, 0.65, 0.4, 0.65, 0.6, 0.7, 0.5, 0.45, 0.75, 0.5, 0.65, 0.5, 0.5, 0.5, 0.8, 0.55], fs=6.4,
                     align=["R", "C", "L", "L", "L", "R", "R", "R", "R", "R", "R", "R", "R", "R", "R", "R", "R"]))
    story.append(Paragraph("Local = submit time. Eval s = submit → graded (attempt #1 includes the one-time 8-run noop calibration). +/− lines = diff of noop.c against the parent attempt. z = throughput z-score vs baseline.", NOTE))
    story += [PageBreak(), Paragraph("Score composition per attempt", H2)]
    rows = [["#", "Commit", "z tput", "contrib tput (w=2.0)", "z bytes", "contrib bytes (w=0.5)", "z refault", "contrib refault (w=0.25)", "weighted sum", "score"]]
    for a in A:
        ws = 2.0 * a["tput"]["contrib"] + 0.5 * a["io"]["contrib"] + 0.25 * a["rf"]["contrib"]
        rows.append([a["n"], a["short"], sg(a["tput"]["z"], 2), sg(a["tput"]["contrib"], 3), sg(a["io"]["z"], 2), sg(a["io"]["contrib"], 3), sg(a["rf"]["z"], 2), sg(a["rf"]["contrib"], 3), sg(ws, 3), f(a["score"], 4)])
    story.append(tbl(rows, [0.4, 0.8, 0.7, 1.3, 0.7, 1.4, 0.8, 1.5, 0.9, 0.7], fs=6.6, align=["R", "L"] + ["R"] * 8))
    story.append(Paragraph("weighted sum / 2.75 = score. Contributions are tanh-squashed, so |z| ≳ 2 gives ≈ ±0.96 or more.", NOTE))

    story += [PageBreak(), Paragraph("Derived per-operation metrics", H1)]
    rows = [["#", "Commit", "Cls", "Ops in measured phase (≈ tput × 30 s)", "Bytes read per op (KB)", "Refaults per 1k ops", "Read rate (MB/s)", "Refaults per MB read", "Wall s"]]
    for a in A + [None]:
        if a is None:
            ops = bm * 30
            rows.append(["noop", "(baseline)", "-", f(ops, 0), f(bi / ops / 1e3, 2), f(br / ops * 1e3, 2), f(bi / 30 / 1e6, 2), f(br / (bi / 1e6), 2), "-"])
            continue
        ops = a["t"] * 30
        rows.append([a["n"], a["short"], a["cls"], f(ops, 0), f(a["io_v"] / ops / 1e3, 2), f(a["rf_v"] / ops * 1e3, 2), f(a["io_v"] / 30 / 1e6, 2), f(a["rf_v"] / (a["io_v"] / 1e6), 2), f(a["wallclock"], 1)])
    story.append(tbl(rows, [0.5, 0.8, 0.45, 2.1, 1.4, 1.3, 1.1, 1.3, 0.6], fs=6.6, align=["R", "L", "L"] + ["R"] * 6))
    story.append(Paragraph("Assumes the probes cover exactly the 30 s measured phase (the harness wraps probes around that phase only), so operations = throughput × 30 and bytes/refaults are per measured phase. Refault = a page evicted earlier and read back in.", NOTE))
    story += [PageBreak(), Paragraph("Attempt descriptions (commit messages, verbatim)", H1)]
    rows = [["#", "Commit", "Cls", "Description"]] + [[a["n"], a["short"], a["cls"], a["title"]] for a in A]
    story.append(tbl(rows, [0.3, 0.7, 0.4, 8.6], fs=6.4, align=["R", "L", "L", "L"]))

    # ---------------------------------------------------------------- 4 figures
    story += [PageBreak(), Paragraph("Throughput over the run", H1), img(figs["timeline"], AW, 3.3 * inch), Spacer(1, 4), two(figs["score"], figs["tradeoff"])]
    story += [PageBreak(), Paragraph("Progress and distribution", H1), img(figs["best"], AW, 3.0 * inch), Spacer(1, 6), two(figs["hist"], figs["latency"])]

    # ---------------------------------------------------------------- 5 reference policies
    story += [PageBreak(), Paragraph("Reference policies run unmodified", H1)]
    rows = [["#", "Reference policy", "Cls", "Score", "Tput ops/s", "Δ% vs noop", "Bytes read MB", "Δ%", "Refaults", "Δ%"]]
    for a in A:
        if a["ref"]:
            rows.append([a["n"], a["ref"] + ".c", a["cls"], f(a["score"], 4), f(a["t"], 1), sg(a["dt_pct"], 2), f(a["io_v"] / 1e6, 1), sg(a["dio_pct"], 1), f(a["rf_v"], 0), sg(a["drf_pct"], 1)])
    story.append(tbl(rows, [0.3, 1.5, 0.5, 0.8, 0.9, 0.9, 1.0, 0.6, 0.8, 0.6], align=["R", "L", "L"] + ["R"] * 7))
    story.append(Paragraph("fifo.c and mru.c were not evaluated in this run (they were only smoke-tested before it).", NOTE))

    # ---------------------------------------------------------------- 6 noise / repeats
    pooled_sd, pdf_ = an.pooled(G)
    rsd, rdf, dropped = an.pooled_robust(G)
    story += [Paragraph("Repeat measurements of identical code", H1)]
    rows = [["Group", "First #", "Attempts (short hash, class r/t)", "n", "Mean", "sd", "Min", "Max", "Range %", "CV %", "Mean Δ% vs noop", "Mean bytes MB", "Mean refaults", "Mean score"]]
    for g in G:
        if g["n"] >= 2:
            mem = ", ".join(f"#{m['n']} {m['short']}{m['cls'][0]}" for m in g["members"])
            rows.append([g["gid"], g["first"], mem, g["n"], f(g["mean"], 1), f(g["sd"], 1), f(g["min"], 1), f(g["max"], 1), f(100 * (g["max"] - g["min"]) / g["mean"], 2),
                         f(100 * g["sd"] / g["mean"], 2), sg(an.pct(g["mean"], bm), 2), f(g["io"] / 1e6, 1), f(g["rf"], 0), f(g["score"], 3)])
    story.append(tbl(rows, [0.45, 0.45, 3.0, 0.3, 0.6, 0.45, 0.6, 0.6, 0.55, 0.45, 0.8, 0.8, 0.8, 0.6], fs=6.4, align=["L", "R", "L"] + ["R"] * 11))
    multi = [g for g in G if g["n"] >= 2]
    rows = [["Noise estimate", "Value"],
            ["Groups with ≥ 2 identical-code measurements", f"{len(multi)} groups, {sum(g['n'] for g in multi)} measurements"],
            ["Pooled within-group sd (throughput)", f"{f(pooled_sd, 2)} ops/s  (df = {pdf_}; CV {f(100*pooled_sd/bm,2)}%)"],
            ["Baseline sd (8 consecutive noop runs)", f"{f(bs, 2)} ops/s  (CV {f(100*bs/bm,2)}%)"],
            ["Ratio pooled / baseline sd", f(pooled_sd / bs, 2)],
            ["Pooled sd excluding the most deviant single measurement (#%d %s, %s ops/s)" % (dropped["n"], dropped["short"], f(dropped["t"], 1)), f"{f(rsd, 2)} ops/s  (df = {rdf}; CV {f(100*rsd/bm,2)}%; ratio to baseline sd {f(rsd/bs,2)})"],
            ["Largest within-group range", f"{f(max(100*(g['max']-g['min'])/g['mean'] for g in multi),2)} % of group mean"],
            ["Smallest 95% detectable difference between two means of 3 evals each (pooled sd, all data / excluding that outlier)",
             f"≈ {f(an.t95(pdf_)*pooled_sd*math.sqrt(2/3),1)} ops/s ({f(100*an.t95(pdf_)*pooled_sd*math.sqrt(2/3)/bm,2)}%)  /  ≈ {f(an.t95(rdf)*rsd*math.sqrt(2/3),1)} ops/s ({f(100*an.t95(rdf)*rsd*math.sqrt(2/3)/bm,2)}%)"]]
    story += [Spacer(1, 4), tbl(rows, [4.2, 5.8], align=["L", "L"]), Spacer(1, 6), img(figs["groups"], AW, 3.0 * inch)]

    story += [PageBreak(), Paragraph("Distinct code versions: ranking by mean throughput", H1)]
    rows = [["Rank", "Group", "First #", "n", "Mean tput", "sd", "Δ% vs noop", "Best single tput", "Mean bytes MB", "Mean refaults", "Mean score", "Best single score", "Ref", "Description (first attempt)"]]
    GS = sorted(G, key=lambda g: -g["mean"])
    for r_, g in enumerate(GS, 1):
        rows.append([r_, g["gid"], g["first"], g["n"], f(g["mean"], 1), f(g["sd"], 1) if g["n"] > 1 else "-", sg(an.pct(g["mean"], bm), 2), f(g["max"], 1), f(g["io"] / 1e6, 1),
                     f(g["rf"], 0), f(g["score"], 3), f(g["best_score"], 3), g["ref"] or "", g["title"]])
    story.append(tbl(rows, [0.35, 0.4, 0.4, 0.25, 0.65, 0.4, 0.6, 0.65, 0.6, 0.6, 0.55, 0.6, 0.55, 3.4], fs=6.0, align=["R", "L", "R", "R", "R", "R", "R", "R", "R", "R", "R", "R", "L", "L"]))
    story += [PageBreak(), Paragraph("Ranking by mean throughput (graphical)", H1), img(figs["rank"], AW, 6.6 * inch)]

    refg = next((g for g in G if g["ref"] == "s3fifo"), None)
    if refg:
        story += [PageBreak(), Paragraph("Each code version vs the unmodified reference s3fifo.c (pooled-sd Student t, 95% CI)", H1)]
        rows = [["Group", "First #", "n", "Mean tput", "Δ vs ref (ops/s)", "Δ vs ref (%)", "SE (pooled sd, all)", "95% CI low", "95% CI high", "excl. 0", "SE (outlier dropped)", "95% CI low", "95% CI high", "excl. 0"]]
        tc, tc2 = an.t95(pdf_), an.t95(rdf)

        def robust_mean_n(g):
            xs = [m["t"] for m in g["members"] if m is not dropped]
            return an.mean(xs), len(xs)
        for g in GS:
            if g is refg:
                continue
            dm = g["mean"] - refg["mean"]
            se = pooled_sd * math.sqrt(1 / g["n"] + 1 / refg["n"])
            lo, hi = dm - tc * se, dm + tc * se
            gm2, gn2 = robust_mean_n(g)
            rm2, rn2 = robust_mean_n(refg)
            dm2 = gm2 - rm2
            se2 = rsd * math.sqrt(1 / gn2 + 1 / rn2)
            lo2, hi2 = dm2 - tc2 * se2, dm2 + tc2 * se2
            rows.append([g["gid"], g["first"], g["n"], f(g["mean"], 1), sg(dm, 1), sg(100 * dm / refg["mean"], 2), f(se, 1), sg(lo, 1), sg(hi, 1), "yes" if (lo > 0 or hi < 0) else "no",
                         f(se2, 1), sg(lo2, 1), sg(hi2, 1), "yes" if (lo2 > 0 or hi2 < 0) else "no"])
        story.append(tbl(rows, [0.45, 0.45, 0.3, 0.7, 0.8, 0.7, 0.8, 0.75, 0.75, 0.5, 0.9, 0.75, 0.75, 0.5], fs=6.4, align=["L"] + ["R"] * 13))
        story.append(Paragraph(f"Reference s3fifo.c: n = {refg['n']}, mean {f(refg['mean'],1)} ops/s. SE = pooled sd × √(1/n + 1/n_ref). Left: pooled sd {f(pooled_sd,2)} ops/s (df {pdf_}, t = {tc}); right: pooled sd {f(rsd,2)} ops/s with the most deviant measurement dropped (df {rdf}, t = {tc2}). n = 1 groups use the same pooled sd. In the right-hand columns the dropped measurement (#{dropped['n']} {dropped['short']}) is also removed from its own group's mean, and the CIs are for the difference of the remaining means (the Δ columns on the left are the unadjusted means).", NOTE))

    # ---------------------------------------------------------------- 7 score analysis
    story += [Paragraph("Score analysis", H1), Paragraph("Correlations across the 28 attempts", H2)]
    cols = [("score", [a["score"] for a in A]), ("throughput", tput_all), ("bytes read", [a["io_v"] for a in A]), ("refaults", [a["rf_v"] for a in A]), ("wallclock", [a["wallclock"] for a in A])]
    rows = [["Pearson r"] + [c for c, _ in cols]] + [[c1] + [f(an.pearson(v1, v2), 3) for _, v2 in cols] for c1, v1 in cols]
    rows2 = [["Spearman ρ"] + [c for c, _ in cols]] + [[c1] + [f(an.spearman(v1, v2), 3) for _, v2 in cols] for c1, v1 in cols]
    story.append(side_by_side(tbl(rows, [1.0, 0.8, 0.8, 0.8, 0.8, 0.8], fs=6.8, align=["L"] + ["R"] * 5), tbl(rows2, [1.0, 0.8, 0.8, 0.8, 0.8, 0.8], fs=6.8, align=["L"] + ["R"] * 5)))
    sat = [a for a in A if a["score"] >= 0.95]
    story.append(Paragraph("Score saturation", H2))
    rows = [["Metric", "Value"],
            ["Attempts with score ≥ 0.95", f"{len(sat)} of {len(A)}"],
            ["Throughput span of those attempts", f"{f(min(a['t'] for a in sat))} … {f(max(a['t'] for a in sat))} ops/s  ({f(max(a['t'] for a in sat)-min(a['t'] for a in sat))} ops/s, {f(100*(max(a['t'] for a in sat)-min(a['t'] for a in sat))/bm,2)}% of baseline)"],
            ["Score span of those attempts", f"{min(a['score'] for a in sat):.4f} … {max(a['score'] for a in sat):.4f}  ({max(a['score'] for a in sat)-min(a['score'] for a in sat):.4f})"],
            ["Attempts with score ≤ −0.40", f"{sum(1 for a in A if a['score'] <= -0.4)} of {len(A)}  (throughput {f(min(a['t'] for a in A if a['score']<=-0.4))} … {f(max(a['t'] for a in A if a['score']<=-0.4))} ops/s)"],
            ["Attempts at the score floor (within 0.005 of −0.4545 = (−2 + 0.5 + 0.25)/2.75: throughput saturated at −1, I/O probes at +1)", str(sum(1 for a in A if abs(a['score'] + 0.4545) < 0.005))]]
    story.append(tbl(rows, [4.5, 5.5], align=["L", "L"]))

    # ---------------------------------------------------------------- 8 timing
    story += [PageBreak(), Paragraph("Timing", H1), Paragraph("Run phases (local time)", H2)]
    gw = d["gateway"]
    first_req = min(an.dt.datetime.fromisoformat(r["ts"]) for r in gw).astimezone(an.CDT)
    first_sub, first_graded = an.local(A[0]["submit"]), an.local(A[0]["graded"])
    lat = [a["eval_latency_s"] for a in A]
    ph = [["Event", "Time", "Elapsed since start (min)"],
          ["Run directory created / manager started", start.strftime("%H:%M:%S"), "0.0"],
          ["First model request at the gateway", first_req.strftime("%H:%M:%S"), f((first_req - start).total_seconds() / 60, 1)],
          ["First submission (attempt #1)", first_sub.strftime("%H:%M:%S"), f((first_sub - start).total_seconds() / 60, 1)],
          ["Attempt #1 graded (includes noop calibration)", first_graded.strftime("%H:%M:%S"), f((first_graded - start).total_seconds() / 60, 1)],
          ["Last submission (attempt #%d)" % A[-1]["n"], an.local(A[-1]["submit"]).strftime("%H:%M:%S"), f((an.local(A[-1]["submit"]) - start).total_seconds() / 60, 1)],
          ["Last attempt graded / auto-stop recorded", stop.strftime("%H:%M:%S"), f((stop - start).total_seconds() / 60, 1)]]
    story.append(tbl(ph, [4.5, 1.5, 2.0], align=["L", "R", "R"]))
    story.append(Paragraph("Evaluation latency (submit → graded)", H2))

    def lrow(name, v):
        return [name, len(v), f(an.mean(v), 1), f(an.pctile(v, 50), 1), f(an.pctile(v, 90), 1), f(min(v), 1), f(max(v), 1), f(sum(v), 0)]
    rows = [["Subset", "n", "Mean s", "Median s", "p90 s", "Min s", "Max s", "Total s"], lrow("all attempts", lat), lrow("all excluding #1 (calibration)", lat[1:]),
            lrow("real, excl. #1", [a["eval_latency_s"] for a in real[1:]]), lrow("tune", [a["eval_latency_s"] for a in tune])]
    story.append(tbl(rows, [3.0, 0.5, 0.8, 0.8, 0.8, 0.8, 0.8, 0.9], align=["L"] + ["R"] * 7))
    tot_eval, wall_total = sum(lat[1:]), (stop - start).total_seconds()
    story += [Spacer(1, 4), tbl([["Time budget", "Seconds", "% of run wall time"],
                                 ["Evaluation (attempts #2–#28, submit → graded)", f(tot_eval, 0), f(100 * tot_eval / wall_total, 1)],
                                 ["Attempt #1 incl. calibration", f(lat[0], 0), f(100 * lat[0] / wall_total, 1)],
                                 ["Everything else (agent reading, thinking, editing, note-writing)", f(wall_total - tot_eval - lat[0], 0), f(100 * (wall_total - tot_eval - lat[0]) / wall_total, 1)],
                                 ["Run wall time", f(wall_total, 0), "100.0"]], [5.0, 1.5, 1.5], align=["L", "R", "R"], bold_last=True)]

    # ---------------------------------------------------------------- 9 sessions
    story += [PageBreak(), Paragraph("Agent sessions and LLM usage", H1)]
    cum_cost = [x.get("cost_usd") or 0 for x in S]
    cum_api = [x.get("duration_api_ms") or 0 for x in S]
    inc_cost = [cum_cost[0]] + [b - a for a, b in zip(cum_cost, cum_cost[1:])]
    inc_api = [cum_api[0]] + [b - a for a, b in zip(cum_api, cum_api[1:])]
    rows = [["#", "Start", "Wall s", "API s (Δ)", "Turns", "Cost $ (Δ)", "Input tok", "Cache write tok", "Cache read tok", "Output tok", "Thinking tok", "API retries", "Denials", "Terminal reason"]]
    for i, s in enumerate(S):
        rows.append([s["idx"], an.hms(s["start"]), f((s.get("duration_ms") or 0) / 1000, 0), f(inc_api[i] / 1000, 0), s.get("num_turns", "-"), f(inc_cost[i], 3), f(s.get("in_tok", 0), 0),
                     f(s.get("cache_create", 0), 0), f(s.get("cache_read", 0), 0), f(s.get("out_tok", 0), 0), f(s.get("think_tok", 0), 0), s.get("api_retries", 0), s.get("denials", 0), s.get("terminal_reason") or "-"])
    tot = lambda k: sum((s.get(k) or 0) for s in S)
    rows.append(["Σ", "", f(tot("duration_ms") / 1000, 0), f(cum_api[-1] / 1000, 0), tot("num_turns"), f(cum_cost[-1], 2), f(tot("in_tok"), 0), f(tot("cache_create"), 0), f(tot("cache_read"), 0),
                 f(tot("out_tok"), 0), f(tot("think_tok"), 0), tot("api_retries"), tot("denials"), ""])
    story.append(tbl(rows, [0.3, 0.6, 0.5, 0.5, 0.4, 0.55, 0.65, 0.9, 1.0, 0.7, 0.75, 0.55, 0.5, 1.1], fs=6.2, align=["R", "C"] + ["R"] * 11 + ["L"], bold_last=True))
    story.append(Paragraph("Cost and API time: Claude Code reports total_cost_usd and duration_api_ms cumulatively across resumed sessions, so each row shows the increase over the previous session and Σ is the final cumulative value. Cost is Claude Code's own estimate, not an AWS bill. Wall s, turns and token counts are per session. Input tok = uncached input; cache write/read = prompt-cache creation/reads; output includes thinking. Terminal reason aborted_streaming = the session was cut off mid-response (consistent with CORAL interrupting and resuming the agent).", NOTE))
    story += [Spacer(1, 6), img(figs["sessions"], AW, 3.0 * inch), Paragraph("Agent actions", H2)]
    rows = [["Tool", "Calls"]] + [[k, v] for k, v in sorted(d["tool_counts"].items(), key=lambda kv: -kv[1])]
    rows2 = [["coral command", "Count"]] + [[k, v] for k, v in sorted(d["coral_cmds"].items(), key=lambda kv: -kv[1])]
    story.append(side_by_side(tbl(rows, [1.6, 0.7], fs=6.8, align=["L", "R"]), tbl(rows2, [1.6, 0.7], fs=6.8, align=["L", "R"])))
    story.append(Paragraph("Tool calls are those at the top level of the agent's transcript; the 'Bash' count includes every shell command, including file edits done via heredocs/sed. coral eval invocations (29) exceed recorded attempts (28) by one.", NOTE))

    # ---------------------------------------------------------------- 10 gateway
    by, err, latd = an.gateway_summary(d)
    story += [PageBreak(), Paragraph("LLM gateway (LiteLLM → Bedrock)", H1), Paragraph("Requests by model and HTTP status", H2)]
    models = sorted({m for m, _ in by})
    rows = [["Model alias", "200", "400", "503", "Total", "Success %"]]
    for m in models:
        tot_ = sum(by[(m, s)] for s in (200, 400, 503))
        rows.append([m, by[(m, 200)], by[(m, 400)], by[(m, 503)], tot_, f(100 * by[(m, 200)] / tot_, 1)])
    T_ = [sum(by[(m, s)] for m in models) for s in (200, 400, 503)]
    rows.append(["all", *T_, sum(T_), f(100 * T_[0] / sum(T_), 1)])
    story.append(tbl(rows, [2.2, 0.8, 0.8, 0.8, 0.8, 1.0], align=["L"] + ["R"] * 5, bold_last=True))
    story.append(Paragraph("Failure causes", H2))
    rows = [["HTTP", "Model alias", "Count", "Message (summarised from the gateway's error body)"]] + [[st, m, n, e] for (st, m, e), n in sorted(err.items(), key=lambda kv: -kv[1])]
    story.append(tbl(rows, [0.5, 1.4, 0.6, 7.5], align=["R", "L", "R", "L"]))
    story.append(Paragraph("Response time of successful (200) requests", H2))
    rows = [["Model alias", "n", "Mean s", "p50 s", "p90 s", "p99 s", "Max s", "Sum s"]]
    for m, x in latd.items():
        if x:
            rows.append([m, len(x), f(an.mean(x), 2), f(an.pctile(x, 50), 2), f(an.pctile(x, 90), 2), f(an.pctile(x, 99), 2), f(max(x), 2), f(sum(x), 0)])
    story.append(tbl(rows, [2.0, 0.5, 0.8, 0.8, 0.8, 0.8, 0.8, 0.8], align=["L"] + ["R"] * 7))
    out_t = sum(r["out_tok"] or 0 for r in gw if r["status"] == 200)
    in_t = sum(r["in_tok"] or 0 for r in gw if r["status"] == 200)
    sess = collections.Counter(r["session"] for r in gw)
    story.append(Paragraph("Totals over the gateway log", H2))
    rows = [["Metric", "Value"], ["Gateway requests logged", d["gateway_total"]], ["Distinct gateway sessions", len(sess)],
            ["Requests per gateway session (min / median / max)", f"{min(sess.values())} / {int(np.median(list(sess.values())))} / {max(sess.values())}"],
            ["Reported usage in 200 responses: input_tokens / output_tokens", f"{in_t:,} / {out_t:,}  (input excludes cached-prompt tokens)"],
            ["Requests during the Bedrock 503 episode", str(by[("claude-opus-5-5", 503)] + by[("claude-sonnet-5", 503)])]]
    story += [tbl(rows, [4.5, 5.5], align=["L", "L"]), Spacer(1, 6), img(figs["gateway"], AW, 3.0 * inch)]

    # ---------------------------------------------------------------- 11 context
    story += [PageBreak(), Paragraph("Context the agent received and artifacts it wrote", H1),
              Paragraph("Instruction files injected into the agent's prompts (Claude Code loads CLAUDE.md files up the directory tree)", H2)]
    rows = [["File", "Requests containing it", "of total"]] + [[shorten_path(k), v, d["gateway_total"]] for k, v in sorted(d["context_files"].items(), key=lambda kv: -kv[1])]
    story.append(tbl(rows, [7.0, 1.5, 1.0], align=["L", "R", "R"]))
    story.append(Paragraph("The first path is the arjua-forks repository's own project instructions (the previous throughput-profiling project), because the agent's worktree sits below that directory. The second is the task's CLAUDE.md written by CORAL.", NOTE))
    story.append(Paragraph("Notes written by the agent (.coral/public/notes)", H2))
    half = (len(d["notes"]) + 1) // 2
    left = [["File"]] + [[n] for n in d["notes"][:half]]
    right = [["File"]] + [[n] for n in d["notes"][half:]]
    story.append(side_by_side(tbl(left, [4.8], fs=6.6), tbl(right, [4.8], fs=6.6)))
    story.append(Paragraph("Measurements not available for this run", H2))
    rows = [["Quantity", "Status"],
            ["Per-operation latency (READ p99, SCAN p99), per-thread throughput", "Written by the benchmark to a per-eval scratch directory that is deleted after each eval; not retained"],
            ["Policy counters (promotions, list sizes, ghost hits)", "No policy exported a metrics file (policy_counters probe: 'no policy_metrics file')"],
            ["CPU utilisation / cycles / cache misses during evals", "Not collected"],
            ["Noop baseline individual runs", "Only the calibration mean and sd (n=8) were retained, not the 8 values"],
            ["Per-eval timestamps of grading", "Derived from attempt-file modification times (submit time = commit time)"]]
    story.append(tbl(rows, [4.0, 6.0], align=["L", "L"]))

    doc = SimpleDocTemplate(OUT_PDF, pagesize=PAGE, leftMargin=0.5 * inch, rightMargin=0.5 * inch, topMargin=0.45 * inch, bottomMargin=0.5 * inch,
                            title="CORAL run 2026-10-09_004013 — results (full)", author="coral-cache-evolution")
    doc.build(story, onFirstPage=footer, onLaterPages=footer)
    print("wrote", OUT_PDF)


if __name__ == "__main__":
    main()
