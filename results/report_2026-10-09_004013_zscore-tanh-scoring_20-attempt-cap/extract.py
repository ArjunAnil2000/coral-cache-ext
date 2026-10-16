#!/usr/bin/env python3
"""Extract every number worth reporting from one finished CORAL run into data.json."""
import glob, hashlib, json, os, re, subprocess, collections, datetime as dt

RUN = "/home/aanil/Desktop/ldos/arjua-forks/coral-cache-evolution/results/cache-ext-get-scan/2026-10-09_004013"
PUB = f"{RUN}/.coral/public"
AG = f"{RUN}/agents/captain-nemo"
OUT = os.path.dirname(os.path.abspath(__file__))
UTC = dt.timezone.utc


def git(*a, cwd=AG):
    r = subprocess.run(["git", *a], cwd=cwd, capture_output=True, text=True)
    return r.stdout if r.returncode == 0 else None


def parse_ts(s):
    return dt.datetime.fromisoformat(s.replace("Z", "+00:00")).astimezone(UTC)


def probe(fb, name):
    m = re.search(rf"- {name}: ([\d.e+]+) \S+ \| ([\d.e+]+) \+- ([\d.e+]+) \(n=(\d+)\) \| z=([+-][\d.]+) \| \S+ \| w=([\d.]+) \| contrib=([+-][\d.]+)", fb)
    if not m:
        return None
    v, mu, sd, n, z, w, c = m.groups()
    return dict(value=float(v), base_mean=float(mu), base_std=float(sd), base_n=int(n), z=float(z), weight=float(w), contrib=float(c))


def code_key(src):
    keep = [l.rstrip() for l in src.splitlines() if l.strip() and not l.strip().startswith("//")]
    return hashlib.sha1("\n".join(keep).encode()).hexdigest()[:10]


def sections(src):
    i = src.find("// SECTION: USERSPACE LOADER")
    return (src[:i], src[i:]) if i >= 0 else (src, "")


# ---------------------------------------------------------------- attempts
attempts = []
for f in glob.glob(f"{PUB}/attempts/*.json"):
    d = json.load(open(f))
    h = d["commit_hash"]
    fb = d.get("feedback") or ""
    submit = parse_ts(d["timestamp"])
    graded = dt.datetime.fromtimestamp(os.path.getmtime(f), tz=UTC)
    src = git("show", f"{h}:noop.c") or ""
    kern, load = sections(src)
    par = d.get("parent_hash")
    ns = git("diff", "--numstat", par, h, "--", "noop.c") if par else None
    add = dele = None
    if ns and ns.strip():
        a, b, _ = ns.split("\t")
        add, dele = int(a), int(b)
    wall = re.search(r"- wallclock \(not scored\): ([\d.]+)s", fb)
    a = dict(
        hash=h, short=h[:8], parent=(par or "")[:8], title=d["title"], status=d.get("status"),
        cls=(d.get("metadata") or {}).get("budget_class", "?"), score=d.get("score"),
        submit=submit.isoformat(), graded=graded.isoformat(), eval_latency_s=(graded - submit).total_seconds(),
        tput=probe(fb, "throughput"), io=probe(fb, "cgroup_iostat"), rf=probe(fb, "cgroup_memstat"),
        wallclock=float(wall.group(1)) if wall else None,
        code_lines=len(src.splitlines()), kernel_lines=len(kern.splitlines()), loader_lines=len(load.splitlines()),
        diff_add=add, diff_del=dele, key=code_key(src) if src else None,
    )
    attempts.append(a)
attempts.sort(key=lambda a: a["submit"])
for i, a in enumerate(attempts, 1):
    a["n"] = i

# ---------------------------------------------------------------- sessions (agent logs)
def tools_of(msg):
    out = []
    for c in (msg.get("content") if isinstance(msg, dict) and isinstance(msg.get("content"), list) else []):
        if isinstance(c, dict) and c.get("type") == "tool_use":
            out.append(c)
    return out

sessions = []
tool_counts = collections.Counter()
coral_cmds = collections.Counter()
for f in sorted(glob.glob(f"{PUB}/logs/captain-nemo.*.log"), key=lambda p: int(p.rsplit(".", 2)[1])):
    idx = int(f.rsplit(".", 2)[1])
    res = None
    first = last = None
    n_assist = 0
    retries = 0
    stoks = collections.Counter()
    seen = {}
    s_tools = collections.Counter()
    for line in open(f):
        try:
            d = json.loads(line)
        except ValueError:
            continue
        ts = d.get("timestamp")
        if ts:
            t = parse_ts(ts)
            first = first or t
            last = t
        if d.get("type") == "assistant":
            m = d.get("message") or {}
            n_assist += 1
            for c in tools_of(m):
                tool_counts[c["name"]] += 1
                s_tools[c["name"]] += 1
                if c["name"] == "Bash":
                    cmd = (c.get("input") or {}).get("command", "")
                    for mm in re.finditer(r"\bcoral\s+(eval|log|show|wait|diff|checkout|revert|notes|skills|heartbeat|status)\b([^;&|\n]*)", cmd):
                        coral_cmds[mm.group(1) + (" --tune" if mm.group(1) == "eval" and "--tune" in mm.group(2) else "")] += 1
        if d.get("subtype") == "api_retry":
            retries += 1
        if d.get("type") == "result":
            res = d
    s = dict(idx=idx, start=first.isoformat() if first else None, end=last.isoformat() if last else None,
             assistant_msgs=n_assist, api_retries=retries, has_result=res is not None, tools=dict(s_tools))
    if res:
        u = res.get("usage") or {}
        s.update(duration_ms=res.get("duration_ms"), duration_api_ms=res.get("duration_api_ms"), num_turns=res.get("num_turns"),
                 cost_usd=res.get("total_cost_usd"), is_error=res.get("is_error"), subtype=res.get("subtype"),
                 in_tok=u.get("input_tokens", 0), cache_create=u.get("cache_creation_input_tokens", 0),
                 cache_read=u.get("cache_read_input_tokens", 0), out_tok=u.get("output_tokens", 0),
                 think_tok=(u.get("output_tokens_details") or {}).get("thinking_tokens", 0),
                 denials=len(res.get("permission_denials") or []), terminal_reason=res.get("terminal_reason"), stop_reason=res.get("stop_reason"))
    sessions.append(s)

# ---------------------------------------------------------------- gateway
rows = [json.loads(l) for l in open(f"{PUB}/gateway/requests.jsonl") if l.strip()]
gw = []
for r in rows:
    resp = r.get("response")
    err = None
    if r["status_code"] != 200:
        s = json.dumps(resp)
        if "thinking.type.disabled" in s: err = "thinking.type.disabled not supported for this model"
        elif "output_config" in s: err = "messages.N.output_config: extra inputs not permitted"
        elif "web_search" in s: err = "web_search tool type not supported"
        elif "Bedrock is unable to process" in s: err = "Bedrock unable to process request (503)"
        else: err = s[:80]
    u = resp.get("usage") if isinstance(resp, dict) else None
    gw.append(dict(ts=r["timestamp"], model=r["model"], status=r["status_code"], dur_ms=r["duration_ms"], session=r["session_id"],
                   err=err, in_tok=(u or {}).get("input_tokens"), out_tok=(u or {}).get("output_tokens")))
ctx = collections.Counter()
for r in rows:
    s = json.dumps(r["request"])
    for m in re.finditer(r"Contents of (/[^ ]+?\.md) \(", s):
        ctx[m.group(1)] += 1

# ---------------------------------------------------------------- misc
auto = json.load(open(f"{PUB}/auto_stop.json"))
notes = sorted(os.path.relpath(p, f"{PUB}/notes") for p in glob.glob(f"{PUB}/notes/**/*.md", recursive=True))
skills = sorted(os.listdir(f"{PUB}/skills"))
data = dict(run=os.path.basename(RUN), attempts=attempts, sessions=sessions, gateway=gw, gateway_total=len(rows),
            context_files=dict(ctx), tool_counts=dict(tool_counts), coral_cmds=dict(coral_cmds), auto_stop=auto, notes=notes,
            skills=skills, eval_count=int(open(f"{PUB}/eval_count").read().strip() or 0), n_requests=len(rows))
json.dump(data, open(f"{OUT}/data.json", "w"), indent=1)
print("attempts", len(attempts), "| sessions", len(sessions), "| gateway", len(gw), "| notes", len(notes), "| tools", sum(tool_counts.values()))
print("classes", collections.Counter(a["cls"] for a in attempts), "| statuses", collections.Counter(a["status"] for a in attempts))
print("sessions with result:", sum(s["has_result"] for s in sessions), "of", len(sessions))
print("coral cmds", dict(coral_cmds))
