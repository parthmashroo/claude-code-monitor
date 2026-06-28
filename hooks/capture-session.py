#!/usr/bin/env python3
"""
Claude Code Stop hook — captures session stats for the monitor widget.
Install: add to ~/.claude/settings.json under "Stop" hooks.
See README for setup instructions.
"""
import json, sys
from pathlib import Path
from datetime import datetime, timezone

OUT = Path.home() / ".claude" / "widgets" / "claude-code-monitor" / "session_data.json"

def read_stdin():
    try:
        if not sys.stdin.isatty():
            raw = sys.stdin.read().strip()
            if raw: return json.loads(raw)
    except: pass
    return {}

def parse_session(path_str):
    path = Path(path_str)
    if not path.exists(): return {}
    inp = out = cr = cw = msgs = 0
    model = ""; last_ts = None
    for raw in path.read_text(encoding="utf-8", errors="ignore").splitlines():
        raw = raw.strip()
        if not raw: continue
        try:
            e = json.loads(raw)
            if e.get("type") != "assistant": continue
            msg = e.get("message", {})
            u   = msg.get("usage", {})
            inp += u.get("input_tokens", 0)
            out += u.get("output_tokens", 0)
            cr  += u.get("cache_read_input_tokens", 0)
            cw  += u.get("cache_creation_input_tokens", 0)
            model = msg.get("model", model)
            ts_s = e.get("timestamp", "")
            if ts_s:
                ts = datetime.fromisoformat(ts_s.replace("Z", "+00:00"))
                if last_ts is None or ts > last_ts: last_ts = ts
            msgs += 1
        except: pass
    return dict(inp=inp, out=out, cr=cr, cw=cw, model=model,
                total=inp+out, msgs=msgs,
                last_ts=last_ts.isoformat() if last_ts else None)

hook = read_stdin()
session_stats = {}
if hook.get("transcript_path"):
    session_stats = parse_session(hook["transcript_path"])

OUT.parent.mkdir(parents=True, exist_ok=True)
OUT.write_text(json.dumps({
    "_written_at": datetime.now(tz=timezone.utc).isoformat(),
    "session_id":  hook.get("session_id", ""),
    "cwd":         hook.get("cwd", ""),
    "effort":      hook.get("effort", {}).get("level", ""),
    "session":     session_stats,
}, indent=2), encoding="utf-8")
