#!/usr/bin/env python3
"""Extract every number worth reporting from CORAL run 2026-10-09_162748 (single seed: S3-FIFO) into data.json."""
import collections, datetime as dt, glob, hashlib, json, os, re, subprocess

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))
RUN = f"{REPO}/results/cache-ext-get-scan/2026-10-09_162748"
PUB, AG = f"{RUN}/.coral/public", f"{RUN}/agents/captain-nemo"
PREV = f"{REPO}/results/report_2026-10-09_004013_zscore-tanh-scoring_20-attempt-cap/data.json"
PREV2 = f"{REPO}/results/report_2026-10-09_102552_absolute-throughput-scoring_5-attempt-cap/data.json"
UTC = dt.timezone.utc


def git(*a, cwd=AG):
    r = subprocess.run(["git", *a], cwd=cwd, capture_output=True, text=True)
    return r.stdout if r.returncode == 0 else None


def ts(s):
    return dt.datetime.fromisoformat(s.replace("Z", "+00:00")).astimezone(UTC)


def key(src):
    keep = [l.rstrip() for l in src.splitlines() if l.strip() and not l.strip().startswith("//")]
    return hashlib.sha1("\n".join(keep).encode()).hexdigest()[:10]


def sections(src):
    i = src.find("// SECTION: USERSPACE LOADER")
    return (src[:i], src[i:]) if i >= 0 else (src, "")


SEED_KEY = key(open(f"{REPO}/seed/noop.c").read())   # the S3-FIFO seed (comment-only lines ignored)
ref_keys = {"s3fifo": SEED_KEY}

# ---------------------------------------------------------------- attempts
attempts = []
for f in glob.glob(f"{PUB}/attempts/*.json"):
    d = json.load(open(f))
    h, fb = d["commit_hash"], d.get("feedback") or ""
    submit, graded = ts(d["timestamp"]), dt.datetime.fromtimestamp(os.path.getmtime(f), tz=UTC)
    src = git("show", f"{h}:noop.c") or ""
    kern, load = sections(src)
    par = d.get("parent_hash")
    ns = git("diff", "--numstat", par, h, "--", "noop.c") if par else None
    add = dele = None
    if ns and ns.strip():
        a, b, _ = ns.split("\t"); add, dele = int(a), int(b)
    m1 = re.search(r"score = throughput = ([\d.]+) ops/s .*wall=([\d.]+)s", fb)
    m2 = re.search(r"rbytes=([\d.]+)MiB wbytes=([\d.]+)MiB rios=(\d+)", fb)
    m3 = re.search(r"refault_file=(\d+) pgmajfault=(\d+) pgactivate=(\d+) resident_file=(\d+)MiB", fb)
    m4 = re.search(r"- wallclock: ([\d.]+)s", fb)
    k = key(src) if src else None
    mc = re.search(r"- policy_counters: (.*)", fb)
    counters = {kk: int(vv) for kk, vv in re.findall(r"(\w+)=(\d+)", mc.group(1))} if mc else {}
    attempts.append(dict(
        hash=h, short=h[:8], parent=(par or "")[:8], title=d["title"], status=d.get("status"), cls=(d.get("metadata") or {}).get("budget_class", "?"),
        score=d.get("score"), crashed=m1 is None, fail_msg=(fb.strip().splitlines()[0][:160] if m1 is None else None), tput=float(m1.group(1)) if m1 else None, submit=submit.isoformat(), graded=graded.isoformat(), eval_latency_s=(graded - submit).total_seconds(),
        rbytes_mib=float(m2.group(1)) if m2 else None, wbytes_mib=float(m2.group(2)) if m2 else None, rios=int(m2.group(3)) if m2 else None,
        refault_file=int(m3.group(1)) if m3 else None, pgmajfault=int(m3.group(2)) if m3 else None, pgactivate=int(m3.group(3)) if m3 else None, resident_mib=int(m3.group(4)) if m3 else None,
        wallclock=(float(m1.group(2)) if m1 else (float(m4.group(1)) if m4 else None)), counters=counters, code_lines=len(src.splitlines()), kernel_lines=len(kern.splitlines()), loader_lines=len(load.splitlines()),
        diff_add=add, diff_del=dele, key=k, ref=next((n for n, v in ref_keys.items() if v == k), None)))
attempts.sort(key=lambda a: a["submit"])
for i, a in enumerate(attempts, 1):
    a["n"] = i

# ---------------------------------------------------------------- sessions
sessions, tool_counts, coral_cmds, denials = [], collections.Counter(), collections.Counter(), []
for f in sorted(glob.glob(f"{PUB}/logs/captain-nemo.*.log"), key=lambda p: int(p.rsplit(".", 2)[1])):
    idx = int(f.rsplit(".", 2)[1])
    res, first, last, retries, n_assist = None, None, None, 0, 0
    for line in open(f):
        try: d = json.loads(line)
        except ValueError: continue
        if d.get("timestamp"):
            t = ts(d["timestamp"]); first = first or t; last = t
        if d.get("type") == "assistant":
            n_assist += 1
            m = d.get("message") or {}
            for c in (m.get("content") if isinstance(m, dict) and isinstance(m.get("content"), list) else []):
                if isinstance(c, dict) and c.get("type") == "tool_use":
                    tool_counts[c["name"]] += 1
                    if c["name"] == "Bash":
                        cmd = (c.get("input") or {}).get("command", "")
                        for mm in re.finditer(r"\bcoral\s+(eval|log|show|wait|diff|checkout|revert|notes|skills|heartbeat|status)\b([^;&|\n]*)", cmd):
                            coral_cmds[mm.group(1) + (" --tune" if mm.group(1) == "eval" and "--tune" in mm.group(2) else "")] += 1
        if d.get("subtype") == "api_retry": retries += 1
        if d.get("type") == "result": res = d
    s = dict(idx=idx, start=first.isoformat() if first else None, end=last.isoformat() if last else None, assistant_msgs=n_assist, api_retries=retries, has_result=res is not None)
    if res:
        u = res.get("usage") or {}
        pd = res.get("permission_denials") or []
        for p in pd:
            denials.append(dict(session=idx, tool=p.get("tool_name"), target=json.dumps(p.get("tool_input"))[:160]))
        s.update(duration_ms=res.get("duration_ms"), duration_api_ms=res.get("duration_api_ms"), num_turns=res.get("num_turns"), cost_usd=res.get("total_cost_usd"),
                 subtype=res.get("subtype"), terminal_reason=res.get("terminal_reason"), in_tok=u.get("input_tokens", 0), cache_create=u.get("cache_creation_input_tokens", 0),
                 cache_read=u.get("cache_read_input_tokens", 0), out_tok=u.get("output_tokens", 0), think_tok=(u.get("output_tokens_details") or {}).get("thinking_tokens", 0), denials=len(pd))
    sessions.append(s)

# ---------------------------------------------------------------- gateway
rows = [json.loads(l) for l in open(f"{PUB}/gateway/requests.jsonl") if l.strip()]
gw = []
for r in rows:
    resp, err = r.get("response"), None
    if r["status_code"] != 200:
        s = json.dumps(resp)
        if "thinking.type.disabled" in s: err = "thinking.type.disabled not supported for this model"
        elif "output_config" in s: err = "messages.N.output_config: extra inputs not permitted"
        elif "web_search" in s: err = "web_search tool type not supported"
        elif "Bedrock is unable to process" in s: err = "Bedrock unable to process request (503)"
        else: err = s[:80]
    u = resp.get("usage") if isinstance(resp, dict) else None
    gw.append(dict(ts=r["timestamp"], model=r["model"], status=r["status_code"], dur_ms=r["duration_ms"], session=r["session_id"], err=err, in_tok=(u or {}).get("input_tokens"), out_tok=(u or {}).get("output_tokens")))
ctx = collections.Counter()
for r in rows:
    for m in re.finditer(r"Contents of (/[^ ]+?\.md) \(", json.dumps(r["request"])): ctx[m.group(1)] += 1

prev = json.load(open(PREV))
prev2 = json.load(open(PREV2))
# earlier runs' attempts that ran the same S3-FIFO code unmodified (identical normalized key)
prev_refs = [dict(run="run 1 (z-score, 004013)", short=a["short"], cls=a["cls"], tput=a["tput"]["value"], io_bytes=a["io"]["value"], rf=a["rf"]["value"], n=a["n"], ref="s3fifo")
             for a in prev["attempts"] if a.get("key") == SEED_KEY]
prev_refs += [dict(run="run 2 (absolute, 102552)", short=a["short"], cls=a["cls"], tput=a["tput"], io_bytes=a["rbytes_mib"] * 1048576, rf=a["refault_file"], n=a["n"], ref="s3fifo")
              for a in prev2["attempts"] if a.get("key") == SEED_KEY]
data = dict(run=os.path.basename(RUN), attempts=attempts, sessions=sessions, gateway=gw, gateway_total=len(rows), context_files=dict(ctx), tool_counts=dict(tool_counts),
            coral_cmds=dict(coral_cmds), denials=denials, auto_stop=json.load(open(f"{PUB}/auto_stop.json")), notes=sorted(os.path.relpath(p, f"{PUB}/notes") for p in glob.glob(f"{PUB}/notes/**/*.md", recursive=True)),
            skills=sorted(os.listdir(f"{PUB}/skills")), seed_key=SEED_KEY, eval_count=int(open(f"{PUB}/eval_count").read().strip() or 0), ref_keys=ref_keys,
            prev=dict(run=prev["run"], base=prev["attempts"][0] and dict(tput=[prev["attempts"][0]["tput"]["base_mean"], prev["attempts"][0]["tput"]["base_std"]],
                                                                        io=[prev["attempts"][0]["io"]["base_mean"], prev["attempts"][0]["io"]["base_std"]],
                                                                        rf=[prev["attempts"][0]["rf"]["base_mean"], prev["attempts"][0]["rf"]["base_std"]], n=prev["attempts"][0]["tput"]["base_n"]),
                      refs=prev_refs))
json.dump(data, open(f"{HERE}/data.json", "w"), indent=1)
print("attempts", len(attempts), "| sessions", len(sessions), "| gateway", len(gw), "| denials", len(denials), "| prev refs", [(p["ref"], round(p["tput"], 1)) for p in prev_refs])
for a in attempts: print(a["n"], a["short"], a["ref"], a["tput"], a["rbytes_mib"], a["refault_file"], a["status"])
print("denials:", denials[:6])
