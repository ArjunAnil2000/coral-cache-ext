"""Derived statistics for the report. Pure functions over data.json (no plotting, no PDF)."""
import collections
import datetime as dt
import json
import math
import os

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
CDT = dt.timezone(dt.timedelta(hours=-5))

# two-sided 95% Student t critical values, df = 1..30
T95 = [12.706, 4.303, 3.182, 2.776, 2.571, 2.447, 2.365, 2.306, 2.262, 2.228, 2.201, 2.179, 2.160, 2.145, 2.131,
       2.120, 2.110, 2.101, 2.093, 2.086, 2.080, 2.074, 2.069, 2.064, 2.060, 2.056, 2.052, 2.048, 2.045, 2.042]


def t95(df):
    df = int(df)
    return T95[df - 1] if 1 <= df <= 30 else (1.96 if df > 30 else float("nan"))


def local(iso):
    return dt.datetime.fromisoformat(iso).astimezone(CDT)


def hms(iso):
    return local(iso).strftime("%H:%M:%S") if iso else "-"


def mean(x):
    return float(np.mean(x)) if len(x) else float("nan")


def sd(x):
    return float(np.std(x, ddof=1)) if len(x) > 1 else float("nan")


def pct(v, base):
    return 100.0 * (v / base - 1.0)


def pctile(x, p):
    return float(np.percentile(x, p)) if len(x) else float("nan")


def ranks(x):
    x = np.asarray(x, float)
    order = np.argsort(x, kind="mergesort")
    r = np.empty(len(x))
    i = 0
    while i < len(x):
        j = i
        while j + 1 < len(x) and x[order[j + 1]] == x[order[i]]:
            j += 1
        r[order[i:j + 1]] = (i + j) / 2.0 + 1
        i = j + 1
    return r


def pearson(a, b):
    a, b = np.asarray(a, float), np.asarray(b, float)
    if a.std() == 0 or b.std() == 0:
        return float("nan")
    return float(np.corrcoef(a, b)[0, 1])


def spearman(a, b):
    return pearson(ranks(a), ranks(b))


def load():
    d = json.load(open(os.path.join(HERE, "data.json")))
    A = d["attempts"]
    b = A[0]
    d["base"] = dict(tput=(b["tput"]["base_mean"], b["tput"]["base_std"]),
                     io=(b["io"]["base_mean"], b["io"]["base_std"]),
                     rf=(b["rf"]["base_mean"], b["rf"]["base_std"]), n=b["tput"]["base_n"])
    bt, bi, br = d["base"]["tput"][0], d["base"]["io"][0], d["base"]["rf"][0]
    for a in A:
        a["t"] = a["tput"]["value"]
        a["io_v"] = a["io"]["value"]
        a["rf_v"] = a["rf"]["value"]
        a["dt_pct"] = pct(a["t"], bt)
        a["dio_pct"] = pct(a["io_v"], bi)
        a["drf_pct"] = pct(a["rf_v"], br)
        a["tz"] = a["tput"]["z"]
        a["local"] = hms(a["submit"])
        a["ref"] = None
    import re
    for a in A:
        m = re.search(r"reference (\w+)\.c unchanged", a["title"])
        if m:
            a["ref"] = m.group(1)
    return d


def groups(A):
    g = collections.OrderedDict()
    for a in A:
        g.setdefault(a["key"], []).append(a)
    out = []
    for i, (k, ms) in enumerate(g.items(), 1):
        t = [m["t"] for m in ms]
        out.append(dict(gid=f"C{i}", key=k, members=ms, n=len(ms), t=t, mean=mean(t), sd=sd(t), min=min(t), max=max(t),
                        io=mean([m["io_v"] for m in ms]), rf=mean([m["rf_v"] for m in ms]),
                        score=mean([m["score"] for m in ms]), best_score=max(m["score"] for m in ms),
                        ref=next((m["ref"] for m in ms if m["ref"]), None), title=ms[0]["title"], first=ms[0]["n"]))
    return out


def pooled(G):
    num = sum((g["n"] - 1) * g["sd"] ** 2 for g in G if g["n"] > 1)
    df = sum(g["n"] - 1 for g in G if g["n"] > 1)
    return (math.sqrt(num / df) if df else float("nan")), df


def gateway_summary(d):
    gw = d["gateway"]
    by = collections.Counter((r["model"], r["status"]) for r in gw)
    err = collections.Counter((r["status"], r["model"], r["err"]) for r in gw if r["status"] != 200)
    lat = {}
    for m in sorted({r["model"] for r in gw}):
        x = [r["dur_ms"] / 1000.0 for r in gw if r["model"] == m and r["status"] == 200]
        lat[m] = x
    return by, err, lat


def pooled_robust(G):
    """Pooled within-group sd after dropping the single measurement that deviates most from its
    group median (among groups with n >= 2). Returns (sd, df, dropped_member_or_None)."""
    worst = None
    for g in G:
        if g["n"] >= 2:
            med = float(np.median(g["t"]))
            for m in g["members"]:
                dev = abs(m["t"] - med)
                if worst is None or dev > worst[0]:
                    worst = (dev, g["gid"], m)
    if worst is None:
        return float("nan"), 0, None
    num, df = 0.0, 0
    for g in G:
        x = [m["t"] for m in g["members"] if not (g["gid"] == worst[1] and m is worst[2])]
        if len(x) > 1:
            num += (len(x) - 1) * float(np.var(x, ddof=1))
            df += len(x) - 1
    return (math.sqrt(num / df) if df else float("nan")), df, worst[2]
