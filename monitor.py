#!/usr/bin/env python3
"""Claude Code monitor — single-row floating widget."""

import ctypes, json, subprocess, sys, threading, time, urllib.error, urllib.request, winreg
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
CFG = Path.home() / ".claude" / "widgets" / "claude-code-monitor" / "config.json"

def load_cfg():
    try: return json.loads(CFG.read_text())
    except: return {}

def save_cfg(**kw):
    c = load_cfg(); c.update(kw)
    CFG.parent.mkdir(parents=True, exist_ok=True)
    CFG.write_text(json.dumps(c))

_TIER_PRICE = {
    "opus":   (15.00, 75.00, 1.50, 18.75),
    "sonnet": ( 3.00, 15.00, 0.30,  3.75),
    "haiku":  ( 0.80,  4.00, 0.08,  1.00),
}
_EXACT_OVERRIDES = {
    "claude-haiku-3": (0.25, 1.25, 0.03, 0.30),  # only where a real price diverges from its tier
}

def _price(model_id):
    m = (model_id or "").lower()
    if m in _EXACT_OVERRIDES:
        return _EXACT_OVERRIDES[m], True
    for tier, price in _TIER_PRICE.items():
        if tier in m:
            return price, False
    return _TIER_PRICE["sonnet"], False

def _cost(i, o, cr, cw, model):
    (pi, po, pcr, pcw), confident = _price(model)
    return (i*pi + o*po + cr*pcr + cw*pcw) / 1_000_000, confident

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
    buckets = {}  # model -> [inp, out, cr, cw]
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
                        m   = msg.get("model") or "unknown"
                        b   = buckets.setdefault(m, [0, 0, 0, 0])
                        b[0] += u.get("input_tokens", 0)
                        b[1] += u.get("output_tokens", 0)
                        b[2] += u.get("cache_read_input_tokens", 0)
                        b[3] += u.get("cache_creation_input_tokens", 0)
                    except: pass
        except: pass

    inp = sum(b[0] for b in buckets.values())
    out = sum(b[1] for b in buckets.values())
    total = inp + out
    cost = 0.0; confident = True
    for m, b in buckets.items():
        c, ok = _cost(*b, model=m)
        cost += c; confident = confident and ok
    return dict(total=total, cost=cost, confident=confident, inp=inp, out=out)

def load_sess():
    try:
        s = json.loads(
            (Path.home() / ".claude" / "widgets" / "claude-code-monitor" / "session_data.json")
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
    except FileNotFoundError:
        return dict(error="no-credentials-file")
    except Exception:
        return dict(error="credentials-file-unreadable")

    try:
        token = creds["claudeAiOauth"]["accessToken"]
    except KeyError:
        return dict(error="no-oauth-token")  # e.g. Enterprise/SSO/gateway login, or API-key auth

    try:
        req = urllib.request.Request(
            "https://api.anthropic.com/api/oauth/usage",
            headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
        )
        with urllib.request.urlopen(req, timeout=8) as r:
            data = json.loads(r.read())
    except urllib.error.HTTPError as e:
        return dict(error=f"http-{e.code}")  # e.g. 401/403 — invalid token or endpoint not entitled
    except Exception:
        return dict(error="network-error")

    fh = data.get("five_hour") or {}
    sd = data.get("seven_day")  or {}
    if fh.get("utilization") is None and sd.get("utilization") is None:
        return dict(error="empty-response")  # reached the API, no usable fields — e.g. Enterprise plan

    return dict(
        fh_pct       = fh.get("utilization"),
        fh_resets_at = fh.get("resets_at", ""),
        sd_pct       = sd.get("utilization"),
        sd_resets_at = sd.get("resets_at", ""),
    )

# ── glassmorphism ─────────────────────────────────────────────────────────────
# Tier 1: DWM Acrylic backdrop (Win11 22000+) — native, flyout-style blur.
# Tier 2: SetWindowCompositionAttribute acrylic blur-behind (Win10 1803+, undocumented
#         but stable and widely relied upon — no official replacement exists pre-Win11).
# Tier 3: flat alpha transparency (already the default, no action needed).
#
# Corner rounding is done via DWMWA_WINDOW_CORNER_PREFERENCE (Win11+), not GDI
# SetWindowRgn: region-clipping a layered (-alpha) window that also has an acrylic
# backdrop is a known bad combination — the clipped-off corners paint solid black
# instead of transparent, because SetWindowRgn's hard clip doesn't carry an alpha
# channel through DWM's composition. Asking DWM to round the corners itself avoids
# the conflict entirely. No GDI fallback for pre-Win11 — square corners beat broken
# black-triangle corners.
GLASS_ALPHA = 0xCC  # tint opacity 0-255; lower = more blur showing through

class _ACCENT_POLICY(ctypes.Structure):
    _fields_ = [("AccentState", ctypes.c_int), ("AccentFlags", ctypes.c_int),
                ("GradientColor", ctypes.c_uint), ("AnimationId", ctypes.c_int)]

class _WINCOMPATTRDATA(ctypes.Structure):
    _fields_ = [("Attribute", ctypes.c_int), ("Data", ctypes.c_void_p), ("SizeOfData", ctypes.c_size_t)]

def _dwm_acrylic(hwnd, r, g, b, dark):
    dwm = ctypes.windll.dwmapi
    flag = ctypes.c_int(1 if dark else 0)
    dwm.DwmSetWindowAttribute(hwnd, 20, ctypes.byref(flag), ctypes.sizeof(flag))  # immersive dark mode
    backdrop = ctypes.c_int(3)  # DWMSBT_TRANSIENTWINDOW — flyout/acrylic, fits a floating toolbar
    return dwm.DwmSetWindowAttribute(hwnd, 38, ctypes.byref(backdrop), ctypes.sizeof(backdrop)) == 0

def _legacy_acrylic(hwnd, r, g, b):
    accent = _ACCENT_POLICY()
    accent.AccentState   = 4  # ACCENT_ENABLE_ACRYLICBLURBEHIND
    accent.GradientColor = (GLASS_ALPHA << 24) | (b << 16) | (g << 8) | r  # ABGR
    data = _WINCOMPATTRDATA()
    data.Attribute   = 19  # WCA_ACCENT_POLICY
    data.SizeOfData  = ctypes.sizeof(accent)
    data.Data        = ctypes.cast(ctypes.pointer(accent), ctypes.c_void_p)
    return bool(ctypes.windll.user32.SetWindowCompositionAttribute(hwnd, ctypes.byref(data)))

def _dwm_round_corners(hwnd):
    pref = ctypes.c_int(3)  # DWMWCP_ROUNDSMALL — MS guidance for small/flyout windows
    return ctypes.windll.dwmapi.DwmSetWindowAttribute(hwnd, 33, ctypes.byref(pref), ctypes.sizeof(pref)) == 0

def apply_glass(hwnd, bg_hex):
    hwnd = ctypes.windll.user32.GetAncestor(hwnd, 2) or hwnd  # GA_ROOT — DWM APIs need the real top-level HWND, not Tk's inner child
    r, g, b = int(bg_hex[1:3], 16), int(bg_hex[3:5], 16), int(bg_hex[5:7], 16)
    dark = (0.299 * r + 0.587 * g + 0.114 * b) < 128
    is_win11 = False
    try:
        is_win11 = sys.getwindowsversion().build >= 22000
    except Exception:
        pass
    if is_win11:
        try: _dwm_round_corners(hwnd)
        except Exception: pass
    try:
        if is_win11 and _dwm_acrylic(hwnd, r, g, b, dark):
            return
    except Exception:
        pass
    try:
        _legacy_acrylic(hwnd, r, g, b)
    except Exception:
        pass  # Tier 3: falls back to the existing flat -alpha transparency

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
    HIDE_AFTER = 3  # consecutive misses before hiding a rate-limit segment

    def __init__(self):
        super().__init__()
        cfg         = load_cfg()
        self._tname = cfg.get("theme", "one-dark")
        self.C      = THEMES[self._tname]
        self._limits = {}
        self._dx = self._dy = 0
        self._stop = threading.Event()
        self._fh_misses = self._sd_misses = 0

        self.overrideredirect(True)
        self.attributes("-topmost", True)
        self.attributes("-alpha", 0.95)
        self.configure(bg=self.C["SEP"])
        x = cfg.get("x", 40); y = cfg.get("y", 40)
        x = max(0, min(x, self.winfo_screenwidth()  - self.W))
        y = max(0, min(y, self.winfo_screenheight() - self.H))
        self.geometry(f"{self.W}x{self.H}+{x}+{y}")
        self._build()
        self.update_idletasks()
        if sys.platform == "win32":
            apply_glass(self.winfo_id(), self.C["BG"])
        self._start()

    # ── build ─────────────────────────────────────────────────────────────────
    def _lbl(self, parent, text="", color="FG", font=("Consolas", 9)):
        return tk.Label(parent, text=text, fg=self.C[color],
                        bg=parent["bg"], font=font)

    def _build(self):
        C   = self.C
        row = tk.Frame(self, bg=C["BG"])
        row.pack(fill="both", expand=True, padx=1, pady=1)
        self._row = row

        # close button FIRST so tkinter reserves right-side space before left items fill in
        close_btn = tk.Label(row, text=" × ", fg=C["MUT"], bg=C["BG"],
                             font=("Consolas", 9, "bold"), cursor="hand2")
        close_btn.pack(side="right", padx=(0, 2))
        close_btn.bind("<Button-1>", lambda _: self._close())
        close_btn.bind("<Enter>",    lambda e: close_btn.config(fg=C["HOT"]))
        close_btn.bind("<Leave>",    lambda e: close_btn.config(fg=C["MUT"]))

        # drag handle
        drag = tk.Frame(row, bg=C["BG"], width=6)
        drag.pack(side="left")
        drag.bind("<ButtonPress-1>", self._press)
        drag.bind("<B1-Motion>",     self._drag)

        # today tokens (input / output split, ↑ = sent to model, ↓ = received back)
        self._lbl(row, "tdy", "DIM", ("Consolas", 8)).pack(side="left")
        self._lbl(row, "↑", "DIM", ("Consolas", 9)).pack(side="left", padx=(4, 0))
        self._tok_in  = self._lbl(row, "--", "A1", ("Consolas", 9, "bold"))
        self._tok_in.pack(side="left", padx=(1, 0))
        self._lbl(row, "↓", "DIM", ("Consolas", 9)).pack(side="left", padx=(4, 0))
        self._tok_out = self._lbl(row, "--", "A1", ("Consolas", 9, "bold"))
        self._tok_out.pack(side="left", padx=(1, 0))
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
        self._fh_label = self._lbl(row, "5h", "DIM", ("Consolas", 8))
        self._fh_label.pack(side="left")
        self._fhbar, self._fh_fill = self._make_bar(row)
        self._fhpct = self._lbl(row, "",       "A1",  ("Consolas", 8, "bold"))
        self._fhpct.pack(side="left", padx=(4, 0))
        self._fhcd  = self._lbl(row, "",       "DIM", ("Consolas", 8))
        self._fhcd.pack(side="left", padx=(3, 0))

        self._sep3 = self._lbl(row, " | ", "MUT", ("Consolas", 9))
        self._sep3.pack(side="left")

        # 7d bar
        self._sd_label = self._lbl(row, "7d", "DIM", ("Consolas", 8))
        self._sd_label.pack(side="left")
        self._sdbar, self._sd_fill = self._make_bar(row)
        self._sdpct = self._lbl(row, "",       "A1",  ("Consolas", 8, "bold"))
        self._sdpct.pack(side="left", padx=(4, 0))
        self._sdcd  = self._lbl(row, "",       "DIM", ("Consolas", 8))
        self._sdcd.pack(side="left", padx=(3, 0))

        # make full row draggable + right-click for theme
        for w in [row, self._tok_in, self._tok_out, self._cost, self._sess, self._msgs,
                  self._fhbar, self._fhpct, self._fhcd, self._fh_label,
                  self._sdbar, self._sdpct, self._sdcd, self._sd_label,
                  self._sep1, self._sep2, self._sep3]:
            w.bind("<ButtonPress-1>", self._press)
            w.bind("<B1-Motion>",     self._drag)
            w.bind("<Button-3>",      self._open_theme_menu)

    BAR_W = 44; BAR_H = 8

    def _make_bar(self, parent):
        C = self.C
        canvas = tk.Canvas(parent, width=self.BAR_W, height=self.BAR_H,
                           bg=parent["bg"], highlightthickness=0)
        canvas.pack(side="left", padx=(4, 0))
        canvas.create_rectangle(0, 0, self.BAR_W, self.BAR_H, fill=C["MUT"], outline="")
        fill_id = canvas.create_rectangle(0, 0, 0, self.BAR_H, fill=C["OK"], outline="")
        return canvas, fill_id

    def _set_bar(self, canvas, fill_id, pct, color):
        w = round(min(pct, 100) / 100 * self.BAR_W)
        canvas.coords(fill_id, 0, 0, w, self.BAR_H)
        canvas.itemconfig(fill_id, fill=color)

    def _resize_to_fit(self):
        self.update_idletasks()
        req_w = max(self._row.winfo_reqwidth() + 2, 120)
        if req_w != self.winfo_width():
            self.geometry(f"{req_w}x{self.H}")

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
        self._close()

    def _close(self):
        self._stop.set()
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
            while not self._stop.is_set():
                try:
                    t = load_today(); st, msgs = load_sess()
                    if not self._stop.is_set():
                        self.after(0, self._apply_local, t, st, msgs)
                except Exception: pass
                self._stop.wait(5)

        def run_api():
            while not self._stop.is_set():
                try:
                    lim = fetch_limits()
                    if lim and not self._stop.is_set():
                        self._limits = lim
                        self.after(0, self._apply_limits, lim)
                except Exception: pass
                self._stop.wait(60)

        threading.Thread(target=run_local, daemon=True).start()
        threading.Thread(target=run_api,   daemon=True).start()

    def _apply_local(self, t, st, msgs):
        C = self.C
        cost_c = C["HOT"] if t["cost"] > 10 else C["WARN"] if t["cost"] > 3 else C["OK"]
        prefix = "" if t.get("confident", True) else "~"
        self._tok_in.config(text=_k(t["inp"]))
        self._tok_out.config(text=_k(t["out"]))
        self._cost.config(text=prefix + _fc(t["cost"]), fg=cost_c)
        self._sess.config(text=_k(st) if st else "--")
        self._msgs.config(text=f"{msgs}msg" if msgs else "")
        if self._limits:
            self._apply_limits(self._limits)

    def _apply_limits(self, lim):
        C = self.C
        fh_pct = lim.get("fh_pct")
        sd_pct = lim.get("sd_pct")
        resized = False
        if fh_pct is None:
            self._fh_misses += 1
            if self._fh_misses == self.HIDE_AFTER:
                self._fh_label.pack_forget(); self._fhbar.pack_forget()
                self._fhpct.pack_forget(); self._fhcd.pack_forget(); self._sep2.pack_forget()
                resized = True
        else:
            self._fh_misses = 0
            pct = int(fh_pct)
            col = _rl_color(pct, C)
            self._set_bar(self._fhbar, self._fh_fill, pct, col)
            self._fhpct.config(text=f"{pct}%", fg=col)
            self._fhcd.config(text=_countdown(lim.get("fh_resets_at", "")))
        if sd_pct is None:
            self._sd_misses += 1
            if self._sd_misses == self.HIDE_AFTER:
                self._sd_label.pack_forget(); self._sdbar.pack_forget()
                self._sdpct.pack_forget(); self._sdcd.pack_forget(); self._sep3.pack_forget()
                resized = True
        else:
            self._sd_misses = 0
            pct = int(sd_pct)
            col = _rl_color(pct, C)
            self._set_bar(self._sdbar, self._sd_fill, pct, col)
            self._sdpct.config(text=f"{pct}%", fg=col)
            self._sdcd.config(text=_countdown(lim.get("sd_resets_at", "")))
        if resized:
            self._resize_to_fit()


if __name__ == "__main__":
    register_startup()
    Monitor().mainloop()
