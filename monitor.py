#!/usr/bin/env python3
"""Claude Code monitor — single-row floating widget."""

import json, subprocess, sys, threading, time, urllib.request, winreg
from datetime import datetime, timedelta, timezone
from pathlib import Path
import tkinter as tk

THEMES = {
    "one-dark":        dict(BG="#282c34", SEP="#3e4451", FG="#abb2bf", DIM="#636d83", MUT="#4b5263", OK="#98c379", WARN="#e5c07b", HOT="#e06c75", A1="#56b6c2"),
    "catppuccin-mocha":dict(BG="#1e1e2e", SEP="#313244", FG="#cdd6f4", DIM="#6c7086", MUT="#45475a", OK="#a6e3a1", WARN="#fab387", HOT="#f38ba8", A1="#94e2d5"),
    "tokyo-night":     dict(BG="#1a1b26", SEP="#292e42", FG="#c0caf5", DIM="#565f89", MUT="#3b4261", OK="#9ece6a", WARN="#e0af68", HOT="#f7768e", A1="#73daca"),
    "dracula":         dict(BG="#282a36", SEP="#44475a", FG="#f8f8f2", DIM="#6272a4", MUT="#44475a", OK="#50fa7b", WARN="#f1fa8c", HOT="#ff5555", A1="#8be9fd"),
    "nord":            dict(BG="#2e3440", SEP="#4c566a", FG="#d8dee9", DIM="#616e88", MUT="#4c566a", OK="#a3be8c", WARN="#ebcb8b", HOT="#bf616a", A1="#88c0d0"),
    "graphite":        dict(BG="#1c1e21", SEP="#3e4248", FG="#dadde1", DIM="#6b7178", MUT="#3e4248", OK="#78c8c0", WARN="#e8b260", HOT="#e87474", A1="#78c8c0"),
    "mono":            dict(BG="#1a1a1a", SEP="#3a3a3a", FG="#e4e4e4", DIM="#808080", MUT="#464646", OK="#c8c8c8", WARN="#e0e0e0", HOT="#ffffff", A1="#b0b0b0"),
    "twilight":        dict(BG="#1a1625", SEP="#3d3550", FG="#e8e1f0", DIM="#7a6e8a", MUT="#554b69", OK="#a0d2b4", WARN="#e8a05a", HOT="#e4648c", A1="#96b4cc"),
    "linen":           dict(BG="#f5f0e8", SEP="#c0b49c", FG="#3c3732", DIM="#7a6e64", MUT="#b0a090", OK="#3d7a62", WARN="#a05a10", HOT="#a03030", A1="#2a6878"),
    "sakura":          dict(BG="#fdf0f3", SEP="#d8a0b0", FG="#4b3238", DIM="#9a6878", MUT="#c090a0", OK="#3a7850", WARN="#b06010", HOT="#c02848", A1="#2a6090"),
}
THEME_NAMES = list(THEMES.keys())
CFG = Path.home() / ".claude" / "widgets" / "claude-monitor" / "config.json"

def load_cfg():
    try: return json.loads(CFG.read_text())
    except: return {}

def save_cfg(**kw):
    c = load_cfg(); c.update(kw)
    CFG.parent.mkdir(parents=True, exist_ok=True)
    CFG.write_text(json.dumps(c))

_P = {
    "claude-opus-4":   (15.00, 75.00, 1.50, 18.75),
    "claude-sonnet-4": ( 3.00, 15.00, 0.30,  3.75),
    "claude-haiku-4":  ( 0.80,  4.00, 0.08,  1.00),
    "claude-opus-3":   (15.00, 75.00, 1.50, 18.75),
    "claude-sonnet-3": ( 3.00, 15.00, 0.30,  3.75),
    "claude-haiku-3":  ( 0.25,  1.25, 0.03,  0.30),
}
def _price(m):
    m = (m or "").lower()
    for k, v in _P.items():
        if k in m: return v
    return (3.00, 15.00, 0.30, 3.75)

def _cost(i, o, cr, cw, model):
    pi, po, pcr, pcw = _price(model)
    return (i*pi + o*po + cr*pcr + cw*pcw) / 1_000_000

def _k(n):
    if n >= 1_000_000: return f"{n/1_000_000:.1f}M"
    if n >= 1_000:     return f"{n/1_000:.0f}k"
    return str(n)

def _fc(v): return f"${v:.2f}" if v < 100 else f"${v:.0f}"

def _bar(pct, w=6):
    filled = round(min(pct, 100) / 100 * w)
    return "█" * filled + "░" * (w - filled)

def _rl_color(pct, C):
    return C["OK"] if pct < 50 else C["WARN"] if pct < 80 else C["HOT"]

def _countdown(ts_str):
    try:
        ts   = datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
        diff = (ts - datetime.now(tz=timezone.utc)).total_seconds()
        if diff <= 0: return "free"
        m = int(diff // 60)
        if m < 60: return f"{m}m"
        h, rm = divmod(m, 60)
        if h < 24: return f"{h}h{rm:02d}m"
        d, rh = divmod(h, 24)
        return f"{d}d{rh}h"
    except: return ""

# ── data loaders ─────────────────────────────────────────────────────────────

def load_today():
    now   = datetime.now(tz=timezone.utc)
    today = now.astimezone().date()
    inp = out = cr = cw = 0
    model = "unknown"; total = 0
    for f in (Path.home() / ".claude" / "projects").rglob("*.jsonl"):
        try:
            with open(f, encoding="utf-8", errors="ignore") as fh:
                for raw in fh:
                    raw = raw.strip()
                    if not raw: continue
                    try:
                        e = json.loads(raw)
                        if e.get("type") != "assistant": continue
                        ts_s = e.get("timestamp", "")
                        if not ts_s: continue
                        ts = datetime.fromisoformat(ts_s.replace("Z", "+00:00"))
                        if ts.astimezone().date() != today: continue
                        msg = e.get("message", {})
                        u   = msg.get("usage", {})
                        i, o   = u.get("input_tokens", 0), u.get("output_tokens", 0)
                        c_r, c_w = u.get("cache_read_input_tokens", 0), u.get("cache_creation_input_tokens", 0)
                        inp += i; out += o; cr += c_r; cw += c_w
                        model = msg.get("model", model)
                    except: pass
        except: pass
    total = inp + out
    cost  = _cost(inp, out, cr, cw, model)
    return dict(total=total, cost=cost)

def load_sess():
    try:
        s = json.loads(
            (Path.home() / ".claude" / "widgets" / "claude-monitor" / "session_data.json")
            .read_text(encoding="utf-8")
        ).get("session", {})
        return s.get("total", 0), s.get("msgs", 0)
    except:
        return 0, 0

def fetch_limits():
    try:
        creds = json.loads(
            (Path.home() / ".claude" / ".credentials.json").read_text(encoding="utf-8")
        )
        token = creds["claudeAiOauth"]["accessToken"]
        req   = urllib.request.Request(
            "https://api.anthropic.com/api/oauth/usage",
            headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
        )
        with urllib.request.urlopen(req, timeout=8) as r:
            data = json.loads(r.read())
        fh = data.get("five_hour") or {}
        sd = data.get("seven_day")  or {}
        return dict(
            fh_pct      = fh.get("utilization"),
            fh_resets_at = fh.get("resets_at", ""),
            sd_pct      = sd.get("utilization"),
            sd_resets_at = sd.get("resets_at", ""),
        )
    except:
        return None

# ── startup registration ──────────────────────────────────────────────────────

def register_startup():
    try:
        script = str(Path(__file__).resolve())
        exe    = str(Path(sys.executable).parent / "pythonw.exe")
        if not Path(exe).exists():
            exe = sys.executable
        val = f'"{exe}" "{script}"'
        key = winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            r"Software\Microsoft\Windows\CurrentVersion\Run",
            0, winreg.KEY_SET_VALUE
        )
        winreg.SetValueEx(key, "ClaudeMonitor", 0, winreg.REG_SZ, val)
        winreg.CloseKey(key)
    except Exception as e:
        pass  # non-fatal

# ── widget ────────────────────────────────────────────────────────────────────

class Monitor(tk.Tk):
    W = 560; H = 30

    def __init__(self):
        super().__init__()
        cfg         = load_cfg()
        self._tname = cfg.get("theme", "one-dark")
        self.C      = THEMES[self._tname]
        self._limits = {}
        self._dx = self._dy = 0

        self.overrideredirect(True)
        self.attributes("-topmost", True)
        self.attributes("-alpha", 0.95)
        self.configure(bg=self.C["SEP"])
        x = cfg.get("x", 40); y = cfg.get("y", 40)
        self.geometry(f"{self.W}x{self.H}+{x}+{y}")
        self._build()
        self._start()

    # ── build ─────────────────────────────────────────────────────────────────
    def _lbl(self, parent, text="", color="FG", font=("Consolas", 9)):
        return tk.Label(parent, text=text, fg=self.C[color],
                        bg=parent["bg"], font=font)

    def _build(self):
        C   = self.C
        row = tk.Frame(self, bg=C["BG"])
        row.pack(fill="both", expand=True, padx=1, pady=1)

        # close button FIRST so tkinter reserves right-side space before left items fill in
        close_btn = tk.Label(row, text=" × ", fg=C["MUT"], bg=C["BG"],
                             font=("Consolas", 9, "bold"), cursor="hand2")
        close_btn.pack(side="right", padx=(0, 2))
        close_btn.bind("<Button-1>", lambda _: self.destroy())
        close_btn.bind("<Enter>",    lambda e: close_btn.config(fg=C["HOT"]))
        close_btn.bind("<Leave>",    lambda e: close_btn.config(fg=C["MUT"]))

        # drag handle
        drag = tk.Frame(row, bg=C["BG"], width=6)
        drag.pack(side="left")
        drag.bind("<ButtonPress-1>", self._press)
        drag.bind("<B1-Motion>",     self._drag)

        # today tokens
        self._tok  = self._lbl(row, "--",  "A1",   ("Consolas", 9, "bold"))
        self._tok.pack(side="left", padx=(0, 0))
        self._cost = self._lbl(row, "",    "WARN",  ("Consolas", 9))
        self._cost.pack(side="left", padx=(4, 0))

        self._sep1 = self._lbl(row, " | ", "MUT", ("Consolas", 9))
        self._sep1.pack(side="left")

        # session
        self._lbl(row, "sess", "DIM", ("Consolas", 8)).pack(side="left")
        self._sess = self._lbl(row, "--",  "FG",  ("Consolas", 9, "bold"))
        self._sess.pack(side="left", padx=(3, 0))
        self._msgs = self._lbl(row, "",    "DIM", ("Consolas", 8))
        self._msgs.pack(side="left", padx=(3, 0))

        self._sep2 = self._lbl(row, " | ", "MUT", ("Consolas", 9))
        self._sep2.pack(side="left")

        # 5h bar
        self._lbl(row, "5h", "DIM", ("Consolas", 8)).pack(side="left")
        self._fhbar = self._lbl(row, "░░░░░░", "MUT", ("Consolas", 8))
        self._fhbar.pack(side="left", padx=(3, 0))
        self._fhpct = self._lbl(row, "",       "A1",  ("Consolas", 8, "bold"))
        self._fhpct.pack(side="left", padx=(3, 0))
        self._fhcd  = self._lbl(row, "",       "DIM", ("Consolas", 8))
        self._fhcd.pack(side="left", padx=(3, 0))

        self._sep3 = self._lbl(row, " | ", "MUT", ("Consolas", 9))
        self._sep3.pack(side="left")

        # 7d bar
        self._lbl(row, "7d", "DIM", ("Consolas", 8)).pack(side="left")
        self._sdbar = self._lbl(row, "░░░░░░", "MUT", ("Consolas", 8))
        self._sdbar.pack(side="left", padx=(3, 0))
        self._sdpct = self._lbl(row, "",       "A1",  ("Consolas", 8, "bold"))
        self._sdpct.pack(side="left", padx=(3, 0))
        self._sdcd  = self._lbl(row, "",       "DIM", ("Consolas", 8))
        self._sdcd.pack(side="left", padx=(3, 0))

        # make full row draggable + right-click for theme
        for w in [row, self._tok, self._cost, self._sess, self._msgs,
                  self._fhbar, self._fhpct, self._fhcd,
                  self._sdbar, self._sdpct, self._sdcd,
                  self._sep1, self._sep2, self._sep3]:
            w.bind("<ButtonPress-1>", self._press)
            w.bind("<B1-Motion>",     self._drag)
            w.bind("<Button-3>",      self._open_theme_menu)

    # ── theme ─────────────────────────────────────────────────────────────────
    def _open_theme_menu(self, e):
        C    = self.C
        menu = tk.Menu(self, tearoff=0, bg=C["BG"], fg=C["FG"],
                       activebackground=C["SEP"], activeforeground=C["FG"],
                       bd=0, relief="flat")
        for name in THEME_NAMES:
            label = f"* {name}" if name == self._tname else f"  {name}"
            menu.add_command(label=label, font=("Consolas", 9),
                             command=lambda n=name: self._switch_theme(n))
        menu.post(e.x_root, e.y_root)

    def _switch_theme(self, name):
        save_cfg(theme=name, x=self.winfo_x(), y=self.winfo_y())
        subprocess.Popen([sys.executable, str(Path(__file__).resolve())])
        self.destroy()

    # ── drag ──────────────────────────────────────────────────────────────────
    def _press(self, e):
        self._dx = e.x_root - self.winfo_x()
        self._dy = e.y_root - self.winfo_y()

    def _drag(self, e):
        x = e.x_root - self._dx; y = e.y_root - self._dy
        self.geometry(f"+{x}+{y}")
        save_cfg(x=x, y=y)

    # ── data refresh ──────────────────────────────────────────────────────────
    def _start(self):
        def run_local():
            while True:
                try:
                    t = load_today(); st, msgs = load_sess()
                    self.after(0, self._apply_local, t, st, msgs)
                except Exception: pass
                time.sleep(5)

        def run_api():
            while True:
                try:
                    lim = fetch_limits()
                    if lim:
                        self._limits = lim
                        self.after(0, self._apply_limits, lim)
                except Exception: pass
                time.sleep(60)

        threading.Thread(target=run_local, daemon=True).start()
        threading.Thread(target=run_api,   daemon=True).start()

    def _apply_local(self, t, st, msgs):
        C = self.C
        cost_c = C["HOT"] if t["cost"] > 10 else C["WARN"] if t["cost"] > 3 else C["OK"]
        self._tok.config(text=_k(t["total"]))
        self._cost.config(text=_fc(t["cost"]), fg=cost_c)
        self._sess.config(text=_k(st) if st else "--")
        self._msgs.config(text=f"{msgs}msg" if msgs else "")
        if self._limits:
            self._apply_limits(self._limits)

    def _apply_limits(self, lim):
        C = self.C
        fh_pct = lim.get("fh_pct")
        sd_pct = lim.get("sd_pct")
        if fh_pct is not None:
            pct = int(fh_pct)
            col = _rl_color(pct, C)
            self._fhbar.config(text=_bar(pct), fg=col)
            self._fhpct.config(text=f"{pct}%", fg=col)
        self._fhcd.config(text=_countdown(lim.get("fh_resets_at", "")))
        if sd_pct is not None:
            pct = int(sd_pct)
            col = _rl_color(pct, C)
            self._sdbar.config(text=_bar(pct), fg=col)
            self._sdpct.config(text=f"{pct}%", fg=col)
        self._sdcd.config(text=_countdown(lim.get("sd_resets_at", "")))


if __name__ == "__main__":
    register_startup()
    Monitor().mainloop()
