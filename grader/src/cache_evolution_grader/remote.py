"""SSH client for the node-side evaluator (remote/eval_remote.py).

The grader runs on the CORAL host; compile + BPF attach + benchmark happen on
the CloudLab node. One call = one ssh session = one request/response JSON pair.
The node serializes calls with its own flock, so concurrent grader subprocesses
here simply queue there.
"""

from __future__ import annotations

import json
import subprocess
from types import SimpleNamespace
from typing import Any, Dict, List, Optional


class RemoteError(Exception):
    """Transport/protocol failure (ssh down, bad JSON, remote crash)."""


class RemoteBusy(Exception):
    """Node's eval lock was not acquired within lock_wait."""


def ssh_argv(cfg: Dict[str, Any]) -> List[str]:
    argv = [
        "ssh",
        "-o", "BatchMode=yes",
        "-o", f"ConnectTimeout={int(cfg['ssh_connect_timeout'])}",
        "-o", "ServerAliveInterval=15",
        "-o", "ServerAliveCountMax=4",
    ]
    if cfg.get("ssh_key"):
        argv += ["-i", cfg["ssh_key"], "-o", "IdentitiesOnly=yes"]
    argv += list(cfg.get("ssh_options") or [])
    argv.append(cfg["ssh_target"])
    # With a forced-command key this string is ignored by sshd.
    argv.append(cfg["remote_command"])
    return argv


def build_request(cfg: Dict[str, Any], policy_src: str, runs: int) -> Dict[str, Any]:
    return {
        "policy_src": policy_src,
        "runs": runs,
        "benchmark": cfg["benchmark"],
        "probes": cfg["probes"],
        "weights": cfg["weights"],
        "eval_timeout": cfg["eval_timeout"],
        "lock_wait": cfg["lock_wait"],
    }


def total_timeout(cfg: Dict[str, Any], runs: int) -> int:
    """lock wait + compile headroom + runs evals + slack."""
    return int(cfg["lock_wait"]) + 300 + runs * int(cfg["eval_timeout"]) + 60


def _call_once(cfg, req, timeout) -> Dict[str, Any]:
    try:
        proc = subprocess.run(
            ssh_argv(cfg),
            input=json.dumps(req),
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired:
        raise RemoteError(f"ssh to {cfg['ssh_target']} timed out after {timeout}s")
    except OSError as e:
        raise RemoteError(f"cannot launch ssh: {e}")
    out = (proc.stdout or "").strip()
    if proc.returncode == 255 and not out:
        raise _Transient(f"ssh connection to {cfg['ssh_target']} failed: {(proc.stderr or '').strip()[-300:]}")
    if not out:
        raise RemoteError(
            f"remote evaluator exited {proc.returncode} with no response; stderr tail:\n{(proc.stderr or '')[-800:]}"
        )
    try:
        # Response is the last non-empty stdout line (login banners etc. may precede it).
        return json.loads(out.splitlines()[-1])
    except ValueError:
        raise RemoteError(f"unparseable remote response: {out[-300:]!r}; stderr tail:\n{(proc.stderr or '')[-500:]}")


class _Transient(RemoteError):
    pass


def run_remote(cfg: Dict[str, Any], policy_src: str, runs: int = 1, _call=_call_once):
    """Compile `policy_src` on the node and evaluate it `runs` times.

    Returns (compile_info, results) where compile_info has .ok/.error/.stderr_tail
    and each result mimics evaluator.EvaluationResult (.ok/.error/.probes/
    .wallclock_sec/.feedback_text()). Raises RemoteBusy / RemoteError.
    """
    req = build_request(cfg, policy_src, runs)
    timeout = total_timeout(cfg, runs)
    try:
        resp = _call(cfg, req, timeout)
    except _Transient:
        # Connection failed (or dropped): the node's flock guarantees a
        # half-finished earlier attempt is gone or finishing before a retry runs.
        resp = _call(cfg, req, timeout)

    status = resp.get("status")
    if status == "busy":
        raise RemoteBusy(resp.get("error", "node busy"))
    if status != "ok":
        raise RemoteError(f"remote evaluator error: {resp.get('error', resp)}")
    c = resp["compile"]
    compile_info = SimpleNamespace(ok=c["ok"], error=c.get("error", ""), stderr_tail=c.get("stderr_tail", ""))
    return compile_info, [_result(r) for r in resp["results"]]


def _result(d: Dict[str, Any]):
    r = SimpleNamespace(**d)

    def feedback_text(r=r) -> str:
        head = f"[{'OK' if r.ok else 'FAIL'}] wall={r.wallclock_sec:.2f}s"
        if not r.ok and r.error:
            head += f"  error={r.error}"
        lines = [head] + [f"  - {n}: {r.probes[n]['summary']}" for n in sorted(r.probes)]
        if not r.ok and r.stderr_tail:
            lines += ["stderr tail:", r.stderr_tail[-800:]]
        return "\n".join(lines)

    r.feedback_text = feedback_text
    return r
