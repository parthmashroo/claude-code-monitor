#!/usr/bin/env python3
"""Claude Code monitor — single-row floating widget."""

import colorsys, ctypes, json, subprocess, sys, threading, time, urllib.error, urllib.request, winreg
from datetime import datetime, timedelta, timezone
from pathlib import Path
import tkinter as tk
from PIL import Image, ImageDraw, ImageTk

# 10 themes, 5 categories x 2 (dark, light, glassmorphism, claymorphism,
# gradient). Each theme carries a render STYLE (THEME_STYLE below) that
# changes how the surface itself draws, not just its colors -- ONLY the
# two "glassmorphism" themes get the glass treatment (translucency + blur
# backdrop + border stroke); dark/light are plain flat surfaces with zero
# glass effects. Dropped nord/twilight -- they were a 3rd/4th near-
# identical "dark + muted accent" variant on top of one-dark/graphite,
# indistinguishable at a glance; that slot went to a second gradient theme
# instead, since gradient/color is what was actually being asked for.
THEMES = {
    # -- dark: plain, moody, no glass --
    "one-dark":        dict(BG="#282c34", SEP="#3e4451", FG="#abb2bf", DIM="#636d83", MUT="#4b5263", OK="#98c379", WARN="#e5c07b", HOT="#e06c75", A1="#56b6c2"),
    "graphite":        dict(BG="#1c1e21", SEP="#3e4248", FG="#dadde1", DIM="#6b7178", MUT="#3e4248", OK="#78c8c0", WARN="#e8b260", HOT="#e87474", A1="#78c8c0"),
    # -- light / white --
    "linen":           dict(BG="#f5f0e8", SEP="#c0b49c", FG="#3c3732", DIM="#7a6e64", MUT="#b0a090", OK="#3d7a62", WARN="#a05a10", HOT="#a03030", A1="#2a6878"),
    "sakura":          dict(BG="#fdf0f3", SEP="#d8a0b0", FG="#4b3238", DIM="#9a6878", MUT="#c090a0", OK="#3a7850", WARN="#b06010", HOT="#c02848", A1="#2a6090"),
    # -- glassmorphism (only these two: translucency + blur + border stroke) --
    "lavender-mist":   dict(BG="#edeaf6", SEP="#d8d2ec", FG="#2d2a3d", DIM="#8b84a0", MUT="#c4bedc", OK="#3daa6e", WARN="#e08a3c", HOT="#e0526b", A1="#8b7fe8"),
    "midnight-fintech":dict(BG="#12141c", SEP="#232838", FG="#f4f6fb", DIM="#8890a6", MUT="#2a2f42", OK="#3ed598", WARN="#f0b860", HOT="#ff5c7a", A1="#4a7fff"),
    # -- claymorphism (soft embossed dual-shadow, puffy pastel) --
    "clay-peach":      dict(BG="#f2e4d8", SEP="#e0cab8", FG="#5c4433", DIM="#a68b73", MUT="#e8d5c4", OK="#6ba888", WARN="#e0a458", HOT="#d97a6c", A1="#e0916b"),
    "clay-lavender":   dict(BG="#e6e1f5", SEP="#d0c7ec", FG="#3d3358", DIM="#8b7fb0", MUT="#d8d0f0", OK="#6bb894", WARN="#e0a458", HOT="#e0708a", A1="#9b8de0"),
    # -- gradient: bold saturated surface, clean 3-stop sweeps (see THEME_GRAD) --
    "spectrum":        dict(BG="#0d0d0d", SEP="#242728", FG="#f4f4f6", DIM="#9c9c9d", MUT="#18191a", OK="#59d499", WARN="#ffc533", HOT="#ff6161", A1="#3987e5"),
    "sunrise":         dict(BG="#0d0d0d", SEP="#242728", FG="#f4f4f6", DIM="#9c9c9d", MUT="#18191a", OK="#59d499", WARN="#ffc533", HOT="#ff6161", A1="#d95926"),
}
THEME_NAMES = list(THEMES.keys())
THEME_STYLE = {
    "one-dark": "flat", "graphite": "flat",
    "linen": "flat", "sakura": "flat",
    "lavender-mist": "glass", "midnight-fintech": "glass",
    "clay-peach": "clay", "clay-lavender": "clay",
    "spectrum": "rainbow", "sunrise": "rainbow",
}
# Typography carries character too, not just color -- each style gets a
# distinct label/value face instead of every theme sharing one font.
#   flat: plain Segoe UI -- no attitude, just legible.
#   glass: a Light label face against Semibold values -- thin/airy label,
#     confident number, matches a translucent surface's delicacy.
#   clay: Semibold everywhere -- puffy/soft surfaces read as solid, rounded.
#   rainbow: Black-weight values -- the loud theme gets the loudest type.
STYLE_FONT = {
    "flat":    ("Segoe UI",       "Segoe UI Semibold"),
    "glass":   ("Segoe UI Light", "Segoe UI Semibold"),
    "clay":    ("Segoe UI Semibold", "Segoe UI Semibold"),
    "rainbow": ("Segoe UI Semibold", "Segoe UI Black"),
}
# Gradient stops for the two "rainbow" themes are pulled from a validated
# categorical palette (dataviz skill's reference instance) instead of
# hand-picked hex — each triple checked with scripts/validate_palette.js
# against this theme's own dark surface: OKLCH lightness band, chroma
# floor, CVD-safe separation (Machado-2009), and contrast, all PASS.
# spectrum: blue #3987e5 / aqua #199e70 / violet #9085e9 -- worst adjacent
#   CVD deltaE 61.6 (target >=12), all >=3:1 contrast on #15121e.
# sunrise: yellow #c98500 / orange #d95926 / red #e66767 -- worst adjacent
#   CVD deltaE 11.4 (legal floor band for a decorative, non-data surface),
#   all >=3:1 contrast on #1a1020.
THEME_GRAD = {
    "spectrum": ["#3987e5", "#199e70", "#9085e9"],
    "sunrise":  ["#c98500", "#d95926", "#e66767"],
}
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

def _hex_rgb(h):
    return int(h[1:3], 16), int(h[3:5], 16), int(h[5:7], 16)

def _hex_rgba(h, a=255):
    r, g, b = _hex_rgb(h)
    return (r, g, b, a)

def _mix(hex_a, hex_b, t):
    """Plain RGB lerp, t=0 -> hex_a, t=1 -> hex_b. Fine for blends toward a
    neutral (white/black/BG) but muddies transitions between unrelated
    hues — use _mix_hue for that."""
    ra, ga, ba = _hex_rgb(hex_a)
    rb, gb, bb = _hex_rgb(hex_b)
    return f"#{round(ra+(rb-ra)*t):02x}{round(ga+(gb-ga)*t):02x}{round(ba+(bb-ba)*t):02x}"

def _mix_hue(hex_a, hex_b, t):
    """Interpolate around the HSL hue wheel (shortest path) instead of
    straight-line RGB — RGB-lerping between distant hues (cyan->red etc.)
    crosses through desaturated brown/grey "mud"; going around the wheel
    keeps every intermediate color as vivid as its endpoints."""
    ra, ga, ba = _hex_rgb(hex_a)
    rb, gb, bb = _hex_rgb(hex_b)
    ha, la, sa = colorsys.rgb_to_hls(ra / 255, ga / 255, ba / 255)
    hb, lb, sb = colorsys.rgb_to_hls(rb / 255, gb / 255, bb / 255)
    dh = hb - ha
    if dh > 0.5: dh -= 1.0
    elif dh < -0.5: dh += 1.0
    h = (ha + dh * t) % 1.0
    l = la + (lb - la) * t
    s = sa + (sb - sa) * t
    r, g, b = colorsys.hls_to_rgb(h, l, s)
    return f"#{round(r*255):02x}{round(g*255):02x}{round(b*255):02x}"

def theme_gradient_stops(C):
    """A vivid spectral sweep grounded in this theme's own accent palette
    (its A1/OK/WARN/HOT hues, already curated), not a generic/universal
    rainbow — each theme keeps its own character. Blended 40% toward BG so
    it reads as tinted glass rather than a neon strip, without going muddy."""
    raw = [C["BG"], C["A1"], C["OK"], C["WARN"], C["HOT"], C["BG"]]
    return [_mix(s, C["BG"], 0.40) for s in raw]

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
    cr  = sum(b[2] for b in buckets.values())
    cw  = sum(b[3] for b in buckets.values())
    total = inp + out
    cost = 0.0; confident = True
    per_model = {}
    for m, b in buckets.items():
        c, ok = _cost(*b, model=m)
        cost += c; confident = confident and ok
        per_model[m] = dict(inp=b[0], out=b[1], cr=b[2], cw=b[3], cost=c)
    return dict(total=total, cost=cost, confident=confident, inp=inp, out=out,
                cr=cr, cw=cw, per_model=per_model)

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
#
# NOTE: true DWM blur-behind/acrylic is gated by the OS-wide "Transparency effects"
# setting (Settings > Personalization > Colors) — when that's off, Windows forces
# ALL apps' blur/acrylic to render flat, with no per-app override. The canvas-drawn
# gradient/highlight below is what carries the glass look when that's the case.
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

# DWMWCP_DONOTROUND=1, DWMWCP_ROUND=2, DWMWCP_ROUNDSMALL=3
_CORNER_PREF = {"glass": 2, "clay": 2, "rainbow": 2, "flat": 3}

def _dwm_round_corners(hwnd, pref_val):
    pref = ctypes.c_int(pref_val)
    return ctypes.windll.dwmapi.DwmSetWindowAttribute(hwnd, 33, ctypes.byref(pref), ctypes.sizeof(pref)) == 0

def apply_glass(hwnd, bg_hex, style="flat"):
    hwnd = ctypes.windll.user32.GetAncestor(hwnd, 2) or hwnd  # GA_ROOT — DWM APIs need the real top-level HWND, not Tk's inner child
    r, g, b = int(bg_hex[1:3], 16), int(bg_hex[3:5], 16), int(bg_hex[5:7], 16)
    dark = (0.299 * r + 0.587 * g + 0.114 * b) < 128
    is_win11 = False
    try:
        is_win11 = sys.getwindowsversion().build >= 22000
    except Exception:
        pass
    if is_win11:
        try: _dwm_round_corners(hwnd, _CORNER_PREF.get(style, 3))
        except Exception: pass
    if style != "glass":
        return  # only dedicated glassmorphism themes get the acrylic backdrop
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
# Rendered on a single Canvas rather than a row of Label/Frame widgets: each
# Label has its own flat solid background, so a row of them tiles into a
# seamed "brick" — there's no way to paint one continuous gradient across
# widget boundaries. A Canvas is one drawing surface, so the gradient,
# specular highlight, and shadow edge all read as one continuous material,
# with text drawn on top of it.

class Monitor(tk.Tk):
    H = 34
    HIDE_AFTER = 3  # consecutive misses before hiding a rate-limit segment
    BAR_W = 58; BAR_H = 12
    PAD_L = 12; PAD_R = 24

    def __init__(self):
        super().__init__()
        cfg          = load_cfg()
        # falls back to one-dark if the saved theme name no longer exists
        # (e.g. a since-removed/renamed theme in an older config.json) --
        # a curated theme list must never crash startup for an existing user.
        self._tname  = cfg.get("theme", "one-dark")
        if self._tname not in THEMES:
            self._tname = "one-dark"
        self.C       = THEMES[self._tname]
        self._style  = THEME_STYLE.get(self._tname, "glass")
        self._grad   = theme_gradient_stops(self.C)
        self._dx = self._dy = 0
        self._stop = threading.Event()
        self._fh_misses = self._sd_misses = 0
        self._fh_visible = self._sd_visible = True
        self._fh_user_hidden = self._sd_user_hidden = False  # manual right-click toggle, independent of auto-hide
        self._hover_enabled = True   # right-click toggle for the hover breakdown panel
        self._spark_enabled = True   # right-click toggle for the sparkline
        self._fh_shown = self._sd_shown = False  # has ever had real data
        self._cur_w = 560

        # cached display state — _layout() redraws entirely from this, so a
        # relayout (hide/show, tick update) never needs the caller to know
        # what's already on screen.
        self._d = dict(
            tok_in="--", tok_out="--", cost="", cost_col=self.C["WARN"],
            sess="--", msgs="",
            fh_pct_txt="", fh_cd="", fh_col=self.C["OK"],
            sd_pct_txt="", sd_cd="", sd_col=self.C["OK"],
            burn_txt="",
        )
        self._history = []       # [(epoch_seconds, cost), ...] sampled through today, for the sparkline
        self._history_day = None
        self._last_today = {}    # full load_today() dict, for the hover breakdown panel
        self._hover_win = None
        self._hover_hide_job = None
        self._hover_zone = None  # (x0, y0, x1, y1) in canvas coords, updated each _layout()

        self.overrideredirect(True)
        self.attributes("-topmost", True)
        # -alpha is whole-window (no way to fade only the background while
        # keeping text opaque -- 0.80 for everyone was a regression, fixed).
        # Real translucency is glassmorphism's own defining trait, so only
        # "glass" style themes get a slightly reduced alpha; flat/clay are
        # explicitly matte/physical materials and stay fully opaque.
        self.attributes("-alpha", 0.92 if self._style == "glass" else 1.0)
        self.configure(bg=self.C["BG"])
        x = cfg.get("x", 40); y = cfg.get("y", 40)
        x = max(0, min(x, self.winfo_screenwidth()  - self._cur_w))
        y = max(0, min(y, self.winfo_screenheight() - self.H))

        # DPI-aware sizing: every pixel constant (H, padding, bar size) was a
        # fixed number, so the same window was physically smaller on a
        # high-DPI laptop panel (e.g. 150% scaling) and larger on a 100%
        # external monitor -- Windows never rescales an overrideredirect
        # Tk window for you. Placeholder-position first so the window lands
        # on its real target monitor, then read that monitor's actual DPI
        # and scale from there, before building anything pixel-sized.
        self.geometry(f"1x1+{x}+{y}")
        self.update_idletasks()
        scale = 1.0
        if sys.platform == "win32":
            try:
                hwnd = ctypes.windll.user32.GetAncestor(self.winfo_id(), 2)  # GA_ROOT
                dpi = ctypes.windll.user32.GetDpiForWindow(hwnd)
                scale = dpi / 96.0
                self.tk.call("tk", "scaling", dpi / 72.0)  # sync Tk's own point->pixel conversion
            except Exception:
                scale = 1.0
        self._scale = scale
        self.H      = round(34 * scale)
        self.PAD_L  = round(12 * scale)
        self.PAD_R  = round(24 * scale)
        self.BAR_W  = round(58 * scale)
        self.BAR_H  = round(12 * scale)
        self._cur_w = round(self._cur_w * scale)
        y = max(0, min(y, self.winfo_screenheight() - self.H))
        self.geometry(f"{self._cur_w}x{self.H}+{x}+{y}")

        self.canvas = tk.Canvas(self, width=self._cur_w, height=self.H,
                                bg=self.C["BG"], highlightthickness=0)
        self.canvas.pack(fill="both", expand=True)
        self.canvas.bind("<ButtonPress-1>", self._press)
        self.canvas.bind("<B1-Motion>",     self._drag)
        self.canvas.bind("<Button-3>",      self._open_theme_menu)
        self.canvas.bind("<Motion>",        self._on_hover_motion)
        # <Motion> alone only fires while the pointer is over the canvas --
        # once it leaves entirely (moves to the taskbar, another window),
        # no more Motion events arrive, so the hover-zone check in
        # _on_hover_motion never runs again and the panel was staying stuck
        # open. <Leave> catches exactly that case.
        self.canvas.bind("<Leave>",         lambda e: self._hide_hover())

        self._build_close()
        self._layout()

        self.update_idletasks()
        if sys.platform == "win32":
            apply_glass(self.winfo_id(), self.C["BG"], style=self._style)
        self._start()

    # ── background: calm neutral surface + thin gradient accent + shadow edge ──
    # The reference designs put color on the page backdrop and in accent
    # elements (a chart line, a progress fill, a thin edge) — the content
    # surface itself stays clean and neutral so text has consistent contrast.
    # Painting the full multi-hue gradient behind every label was the actual
    # "jQuery2 kind of design" tell: it competed with the text instead of
    # framing it. Reserve the theme's gradient for a thin top accent stripe.
    def _redraw_background(self, w, h):
        cv = self.canvas
        cv.delete("bg")
        {"glass": self._bg_glass, "flat": self._bg_flat, "clay": self._bg_clay,
         "rainbow": self._bg_rainbow}[self._style](w, h)
        cv.tag_lower("bg")

    # dedicated glassmorphism: accent stripe + soft sheen + a visible border
    # stroke outlining the whole card — every one of the supplied glass
    # reference images has this stroke; it's the single strongest visual
    # cue that reads as "glass edge" rather than "flat rectangle."
    def _bg_glass(self, w, h):
        cv = self.canvas
        cv.create_rectangle(0, 0, w, h, fill=self.C["BG"], outline="", tags=("bg",))
        stops = self._grad
        n = len(stops) - 1
        step = 2
        accent_h = 3
        for xx in range(0, w, step):
            t = xx / max(w - 1, 1)
            seg = min(int(t * n), n - 1)
            color = _mix_hue(stops[seg], stops[seg + 1], (t * n) - seg)
            cv.create_rectangle(xx, 0, xx + step, accent_h, fill=color, outline="", tags=("bg",))
        hl = _mix("#ffffff", self.C["BG"], 0.62)
        cv.create_rectangle(0, accent_h, w, accent_h + 3, fill=hl, outline="", tags=("bg",))
        shadow = _mix("#000000", self.C["BG"], 0.7)
        cv.create_line(0, h - 1, w, h - 1, fill=shadow, tags=("bg",))
        border = _mix("#ffffff", self.C["BG"], 0.45)
        cv.create_rectangle(0, 0, w - 1, h - 1, outline=border, fill="", tags=("bg",))

    # plain flat / solid surface: no gradient, no stripe, no border — for
    # themes explicitly meant to have zero glass effect.
    def _bg_flat(self, w, h):
        cv = self.canvas
        cv.create_rectangle(0, 0, w, h, fill=self.C["BG"], outline="", tags=("bg",))
        shadow = _mix("#000000", self.C["BG"], 0.85)
        cv.create_line(0, h - 1, w, h - 1, fill=shadow, tags=("bg",))

    # claymorphism: soft embossed dual-shadow (light catch on the top-left
    # edge, soft shadow on the bottom-right) on a matte pastel surface —
    # simulates a puffy pressed/extruded surface instead of glass or flat.
    # Pushed to a much stronger light/dark contrast and thicker lines than
    # the first pass, which was too subtle to read as "embossed" at 34px.
    def _bg_clay(self, w, h):
        cv = self.canvas
        cv.create_rectangle(0, 0, w, h, fill=self.C["BG"], outline="", tags=("bg",))
        light = _mix("#ffffff", self.C["BG"], 0.70)
        dark  = _mix("#000000", self.C["BG"], 0.55)
        cv.create_line(2, 2, w - 2, 2, fill=light, width=4, tags=("bg",))
        cv.create_line(2, 2, 2, h - 2, fill=light, width=4, tags=("bg",))
        cv.create_line(2, h - 3, w - 2, h - 3, fill=dark, width=4, tags=("bg",))
        cv.create_line(w - 3, 2, w - 3, h - 2, fill=dark, width=4, tags=("bg",))

    # gradient: covering the text row in gradient (previous pass, 66% height)
    # was a structural contrast failure, not a tuning issue -- measured with
    # the validator's own contrast() function: white text against that
    # pastel gradient hit ~1.7-1.9:1 (need >=4.5:1). A pastel/mid-lightness
    # background is bad for ANY text color sitting on it — no recolor fixes
    # that, because the problem is the background's own lightness, not the
    # text. Structural fix: the gradient never sits behind text. It frames
    # the bar as a thin band top AND bottom; the text row in between sits on
    # the plain, calm, full-contrast surface — same guarantee as "flat".
    def _bg_rainbow(self, w, h):
        cv = self.canvas
        cv.create_rectangle(0, 0, w, h, fill=self.C["BG"], outline="", tags=("bg",))
        stops = THEME_GRAD[self._tname]
        n = len(stops) - 1
        band_h = max(4, round(h * 0.16))
        step = 2
        for xx in range(0, w, step):
            t = xx / max(w - 1, 1)
            seg = min(int(t * n), n - 1)
            color = _mix_hue(stops[seg], stops[seg + 1], (t * n) - seg)
            cv.create_rectangle(xx, 0, xx + step, band_h, fill=color, outline="", tags=("bg",))
            cv.create_rectangle(xx, h - band_h, xx + step, h, fill=color, outline="", tags=("bg",))
        cv.create_rectangle(0, 0, w - 1, h - 1, outline=self.C["SEP"], fill="", tags=("bg",))

    def _build_close(self):
        # Drawn as two crossing lines rather than a "x" text glyph -- the
        # multiplication-sign glyph doesn't vertically center itself the
        # same way regular text does in this font, no matter what y-anchor
        # is used. Explicit line geometry centers exactly on `mid`, always.
        C, cv = self.C, self.canvas
        r = max(3, round(4 * self._scale))
        self._close_items = (
            cv.create_line(0, 0, 0, 0, fill=C["MUT"], width=max(1, round(1.4 * self._scale)), tags=("close",)),
            cv.create_line(0, 0, 0, 0, fill=C["MUT"], width=max(1, round(1.4 * self._scale)), tags=("close",)),
        )
        self._close_r = r
        cv.tag_bind("close", "<Button-1>", lambda e: self._close())
        cv.tag_bind("close", "<Enter>", lambda e: (cv.itemconfig("close", fill=C["HOT"]),
                                                    cv.config(cursor="hand2")))
        cv.tag_bind("close", "<Leave>", lambda e: (cv.itemconfig("close", fill=C["MUT"]),
                                                    cv.config(cursor="")))

    # ── layout: manual flex-row over Canvas items, since Canvas has no
    # geometry manager of its own. Rebuilt from self._d on every data tick
    # and every visibility change — cheap (~20 text items), and the
    # background/window only actually redraw/resize if the total width
    # changed, so a steady-state tick doesn't repaint the gradient.
    def _layout(self):
        C, cv, d = self.C, self.canvas, self._d
        cv.delete("content")
        mid = self.H // 2
        label_face, value_face = STYLE_FONT.get(self._style, STYLE_FONT["flat"])
        FL, FV, FVS, FS = (label_face, 9), (value_face, 11), (value_face, 10), (label_face, 10)
        x = self.PAD_L

        def put(text, color, font=FV, before=0, after=4):
            # No style needs a text-shadow trick anymore: the gradient
            # frames the bar top/bottom now (see _bg_rainbow) and never
            # sits behind the text row, so every style gets the same plain-
            # surface contrast guarantee.
            nonlocal x
            x += before
            item = cv.create_text(x, mid, text=text, fill=color, font=font, anchor="w", tags=("content",))
            bbox = cv.bbox(item)
            x += (bbox[2] - bbox[0] if bbox else 0) + after
            return item

        def sep():
            put("│", C["MUT"], FS, before=2, after=8)

        hover_x0 = x
        put("tdy", C["DIM"], FL, after=4)
        put("↑", C["DIM"], FS, after=1)
        put(d["tok_in"], C["A1"], FV, after=4)
        put("↓", C["DIM"], FS, after=1)
        put(d["tok_out"], C["A1"], FV, after=4)
        put(d["cost"], d["cost_col"], FVS, after=4)
        put(d["burn_txt"], C["DIM"], FL, after=6)
        if self._spark_enabled and len(self._history) >= 2:
            # only reserve the sparkline's space once there's an actual line
            # to draw -- with <2 points it was a near-invisible flat dash
            # that just read as a big unexplained gap before "sess".
            x = self._place_sparkline(x, mid)
        self._hover_zone = (hover_x0, 0, x, self.H)

        sep()
        put("sess", C["DIM"], FL, after=4)
        put(d["sess"], C["FG"], FV, after=4)
        put(d["msgs"], C["DIM"], FL, after=0)

        if self._fh_visible and not self._fh_user_hidden:
            sep()
            put("5h", C["DIM"], FL, after=6)
            x = self._place_bar(x, mid, d["fh_pct_txt"], d["fh_col"], "fh")
            put(d["fh_pct_txt"], d["fh_col"], FVS, after=4)
            put(d["fh_cd"], C["DIM"], FL, after=0)

        if self._sd_visible and not self._sd_user_hidden:
            sep()
            put("7d", C["DIM"], FL, after=6)
            x = self._place_bar(x, mid, d["sd_pct_txt"], d["sd_col"], "sd")
            put(d["sd_pct_txt"], d["sd_col"], FVS, after=4)
            put(d["sd_cd"], C["DIM"], FL, after=0)

        total_w = max(x + self.PAD_R, 120)
        cx = total_w - round(14 * self._scale)
        r = self._close_r
        cv.coords(self._close_items[0], cx - r, mid - r, cx + r, mid + r)
        cv.coords(self._close_items[1], cx - r, mid + r, cx + r, mid - r)
        if total_w != self._cur_w:
            self._cur_w = total_w
            cv.config(width=total_w)
            self.geometry(f"{total_w}x{self.H}")
            self._redraw_background(total_w, self.H)
        cv.tag_raise("content")
        cv.tag_raise("close")

    # Tkinter's Canvas has no anti-aliasing -- every oval/rounded edge drawn
    # with create_oval/create_rectangle comes out stair-stepped ("Windows
    # XP pixelated"), no matter how carefully the geometry is tuned. Real
    # smooth edges need supersampling: render the pill at 4x resolution
    # with PIL (which itself doesn't anti-alias primitives either), then
    # downsample with LANCZOS, which is what actually produces the smooth
    # curve -- the same technique browsers' compositors do automatically.
    BAR_SS = 4

    def _render_bar_image(self, bw, bh, pct, color):
        C = self.C
        SS = self.BAR_SS
        W, H = bw * SS, bh * SS
        img = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        draw = ImageDraw.Draw(img)
        track_col  = _mix(C["MUT"], C["BG"], 0.2)
        border_col = _mix(C["FG"], C["BG"], 0.6)
        draw.rounded_rectangle([0, 0, W - 1, H - 1], radius=H // 2,
                               fill=_hex_rgba(track_col), outline=_hex_rgba(border_col), width=SS)
        if pct > 0:
            fw = max(bh, round(min(pct, 100) / 100 * bw))
            FW = fw * SS
            light = _mix(color, "#ffffff", 0.35)
            fill_img = Image.new("RGBA", (FW, H), (0, 0, 0, 0))
            fdraw = ImageDraw.Draw(fill_img)
            for xx in range(FW):
                t = xx / max(FW - 1, 1)
                fdraw.line([(xx, 0), (xx, H)], fill=_hex_rgba(_mix(color, light, t)))
            inset = round(1.5 * SS)
            mask = Image.new("L", (FW, H), 0)
            ImageDraw.Draw(mask).rounded_rectangle(
                [inset, inset, FW - 1 - inset, H - 1 - inset],
                radius=max(1, (H - 2 * inset) // 2), fill=255)
            fill_img.putalpha(mask)
            img.alpha_composite(fill_img, (0, 0))
        return ImageTk.PhotoImage(img.resize((bw, bh), Image.LANCZOS))

    def _place_bar(self, x, mid, pct_txt, color, which):
        cv = self.canvas
        bw, bh = self.BAR_W, self.BAR_H
        pct = int(pct_txt.rstrip("%")) if pct_txt else 0
        photo = self._render_bar_image(bw, bh, pct, color)
        setattr(self, f"_{which}_bar_photo", photo)  # Tkinter drops the image if nothing keeps a reference
        cv.create_image(x, mid, image=photo, anchor="w", tags=("content",))
        return x + bw + 6

    # today's cost sampled roughly every 3 minutes into self._history --
    # drawn as a small polyline, min-max normalized to the box. Only called
    # once 2+ points exist (see _layout) -- with fewer, reserving the space
    # for a barely-visible flat dash just read as an unexplained gap before
    # "sess", so the slot doesn't exist at all until there's a real line.
    SPARK_W = 30; SPARK_H = 13

    def _place_sparkline(self, x, mid):
        cv, C = self.canvas, self.C
        w = round(self.SPARK_W * self._scale)
        h = round(self.SPARK_H * self._scale)
        y0 = mid - h / 2
        hist = self._history
        costs = [c for _, c in hist]
        lo, hi = min(costs), max(costs)
        span = max(hi - lo, 0.01)
        n = len(hist)
        pts = []
        for i, (_, c) in enumerate(hist):
            pts.append(x + (i / (n - 1)) * w)
            pts.append(y0 + h - ((c - lo) / span) * h)
        cv.create_line(*pts, fill=C["A1"], width=max(1, round(1.3 * self._scale)),
                       smooth=True, tags=("content",))
        return x + w

    # ── hover breakdown panel ────────────────────────────────────────────────
    # Motion-based rather than per-item <Enter>/<Leave>: the content items get
    # deleted and rebuilt every _layout() call (every 5s tick), and canvas
    # item enter/leave tracking can go stale across that churn if the pointer
    # sits still while the underlying item is swapped out. A stored bounding
    # box compared against live pointer position on every <Motion> event
    # sidesteps that entirely.
    def _on_hover_motion(self, e):
        if not self._hover_enabled:
            return
        z = self._hover_zone
        if z and z[0] <= e.x <= z[2] and z[1] <= e.y <= z[3]:
            self._show_hover(e)
        else:
            self._hide_hover()

    def _show_hover(self, e):
        if self._hover_hide_job:
            self.after_cancel(self._hover_hide_job)
            self._hover_hide_job = None
        if self._hover_win:
            return
        C = self.C
        info = self._last_today
        label_face = STYLE_FONT.get(self._style, STYLE_FONT["flat"])[0]

        win = tk.Toplevel(self)
        win.overrideredirect(True)
        win.attributes("-topmost", True)
        win.configure(bg=C["SEP"])
        frame = tk.Frame(win, bg=C["BG"], padx=10, pady=8)
        frame.pack(padx=1, pady=1)

        def line(txt, color=C["FG"], bold=False):
            tk.Label(frame, text=txt, fg=color, bg=C["BG"], anchor="w", justify="left",
                     font=(label_face, 9, "bold" if bold else "normal")).pack(fill="x")

        line("Today's usage", C["DIM"], bold=True)
        line(f"Input:        {_k(info.get('inp', 0))} tok")
        line(f"Output:       {_k(info.get('out', 0))} tok")
        line(f"Cache read:   {_k(info.get('cr', 0))} tok")
        line(f"Cache write:  {_k(info.get('cw', 0))} tok")
        prefix = "" if info.get("confident", True) else "~"
        line(f"Cost: {prefix}{_fc(info.get('cost', 0))}", C["WARN"], bold=True)
        per_model = info.get("per_model", {})
        if len(per_model) > 1:
            line("per model", C["MUT"])
            for m, b in per_model.items():
                line(f"  {m}: {_fc(b['cost'])}", C["DIM"])

        win.update_idletasks()
        gap = round(4 * self._scale)
        x = self.winfo_rootx()
        wy = self.winfo_rooty()
        panel_h = win.winfo_reqheight()
        below_y = wy + self.H + gap
        # the widget is often docked near the bottom of the screen -- always
        # dropping the panel downward let it run off-screen there. Flip to
        # above the widget when there isn't room below.
        if below_y + panel_h > self.winfo_screenheight():
            y = wy - panel_h - gap
        else:
            y = below_y
        win.geometry(f"+{x}+{max(0, y)}")
        self._hover_win = win

    def _hide_hover(self):
        if self._hover_hide_job:
            return
        def do_hide():
            if self._hover_win:
                self._hover_win.destroy()
                self._hover_win = None
            self._hover_hide_job = None
        self._hover_hide_job = self.after(120, do_hide)

    def _hide_hover_now(self):
        if self._hover_hide_job:
            self.after_cancel(self._hover_hide_job)
            self._hover_hide_job = None
        if self._hover_win:
            self._hover_win.destroy()
            self._hover_win = None

    # ── theme ─────────────────────────────────────────────────────────────────
    def _open_theme_menu(self, e):
        C    = self.C
        menu = tk.Menu(self, tearoff=0, bg=C["BG"], fg=C["FG"],
                       activebackground=C["SEP"], activeforeground=C["FG"],
                       bd=0, relief="flat")

        fh_var = tk.BooleanVar(value=not self._fh_user_hidden)
        sd_var = tk.BooleanVar(value=not self._sd_user_hidden)
        hover_var = tk.BooleanVar(value=self._hover_enabled)
        spark_var = tk.BooleanVar(value=self._spark_enabled)
        def toggle_fh():
            self._fh_user_hidden = not fh_var.get()
            self._layout()
        def toggle_sd():
            self._sd_user_hidden = not sd_var.get()
            self._layout()
        def toggle_hover():
            self._hover_enabled = hover_var.get()
            if not self._hover_enabled:
                self._hide_hover_now()
        def toggle_spark():
            self._spark_enabled = spark_var.get()
            self._layout()
        menu.add_checkbutton(label="Show 5h", variable=fh_var, command=toggle_fh, font=("Segoe UI", 9))
        menu.add_checkbutton(label="Show 7d", variable=sd_var, command=toggle_sd, font=("Segoe UI", 9))
        menu.add_checkbutton(label="Hover panel", variable=hover_var, command=toggle_hover, font=("Segoe UI", 9))
        menu.add_checkbutton(label="Sparkline", variable=spark_var, command=toggle_spark, font=("Segoe UI", 9))
        menu.add_separator()

        for name in THEME_NAMES:
            label = f"* {name}" if name == self._tname else f"  {name}"
            menu.add_command(label=label, font=("Segoe UI", 9),
                             command=lambda n=name: self._switch_theme(n))
        menu.post(e.x_root, e.y_root)

    def _switch_theme(self, name):
        save_cfg(theme=name, x=self.winfo_x(), y=self.winfo_y())
        subprocess.Popen([sys.executable, str(Path(__file__).resolve())])
        self._close()

    def _close(self):
        self._stop.set()
        self.destroy()

    # ── drag ─────────────────────────────────────────────────────────────────
    def _press(self, e):
        item = self.canvas.find_closest(e.x, e.y)
        if item and "close" in self.canvas.gettags(item[0]):
            return  # let the close binding handle it, don't start a drag
        self._dx = e.x_root - self.winfo_x()
        self._dy = e.y_root - self.winfo_y()

    def _drag(self, e):
        x = e.x_root - self._dx; y = e.y_root - self._dy
        self.geometry(f"+{x}+{y}")
        save_cfg(x=x, y=y)

    # ── data refresh ─────────────────────────────────────────────────────────
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
                        self.after(0, self._apply_limits, lim)
                except Exception: pass
                self._stop.wait(60)

        threading.Thread(target=run_local, daemon=True).start()
        threading.Thread(target=run_api,   daemon=True).start()

    def _apply_local(self, t, st, msgs):
        # Only redraws from cached state -- must NOT re-run rate-limit miss
        # counting here. This fires every 5s; _apply_limits' miss counter is
        # meant to track real 60s API polls. Re-processing the same cached
        # self._limits on every 5s tick was incrementing misses 12x faster
        # than intended, hiding a segment in ~15s instead of the real 3min
        # HIDE_AFTER window -- that was the actual cause of the reported
        # rapid show/hide flicker, not a cosmetic issue.
        C, d = self.C, self._d
        cost_c = C["HOT"] if t["cost"] > 10 else C["WARN"] if t["cost"] > 3 else C["OK"]
        prefix = "" if t.get("confident", True) else "~"
        d["tok_in"] = _k(t["inp"]); d["tok_out"] = _k(t["out"])
        d["cost"] = prefix + _fc(t["cost"]); d["cost_col"] = cost_c
        d["sess"] = _k(st) if st else "--"
        d["msgs"] = f"{msgs}msg" if msgs else ""

        now_local = datetime.now()
        midnight  = now_local.replace(hour=0, minute=0, second=0, microsecond=0)
        hours     = max((now_local - midnight).total_seconds() / 3600, 1 / 60)
        d["burn_txt"] = f"{_fc(t['cost'] / hours)}/hr"

        self._last_today = t
        today_str = now_local.date().isoformat()
        if self._history_day != today_str:
            self._history = []
            self._history_day = today_str
        now_epoch = time.time()
        if not self._history or now_epoch - self._history[-1][0] >= 180:
            self._history.append((now_epoch, t["cost"]))
            if len(self._history) > 200:
                self._history.pop(0)

        self._layout()

    def _apply_limits(self, lim):
        # Once a segment has shown real data, a later transient miss (a
        # single dropped fetch, a rate-limited API call) freezes it on its
        # last-known values instead of hiding it — hiding/showing on every
        # 60s poll was the actual complaint, not the auto-hide concept
        # itself. Only a segment that has *never* had data hides after
        # repeated misses, since there's nothing meaningful to freeze on.
        C, d = self.C, self._d
        fh_pct = lim.get("fh_pct")
        sd_pct = lim.get("sd_pct")
        if fh_pct is None:
            self._fh_misses += 1
            if not self._fh_shown and self._fh_misses == self.HIDE_AFTER:
                self._fh_visible = False
        else:
            self._fh_misses = 0
            self._fh_visible = True
            self._fh_shown = True
            pct = int(fh_pct)
            col = _rl_color(pct, C)
            d["fh_pct_txt"] = f"{pct}%"; d["fh_col"] = col
            d["fh_cd"] = _countdown(lim.get("fh_resets_at", ""))
        if sd_pct is None:
            self._sd_misses += 1
            if not self._sd_shown and self._sd_misses == self.HIDE_AFTER:
                self._sd_visible = False
        else:
            self._sd_misses = 0
            self._sd_visible = True
            self._sd_shown = True
            pct = int(sd_pct)
            col = _rl_color(pct, C)
            d["sd_pct_txt"] = f"{pct}%"; d["sd_col"] = col
            d["sd_cd"] = _countdown(lim.get("sd_resets_at", ""))
        self._layout()


def _make_dpi_aware():
    # Must run before any Tk window is created, or Windows bitmap-stretches
    # the whole rendered window to match display scaling — the classic
    # blurry-text look on any HiDPI/scaled monitor.
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)  # PROCESS_PER_MONITOR_DPI_AWARE
    except Exception:
        try:
            ctypes.windll.user32.SetProcessDPIAware()  # pre-8.1 fallback
        except Exception:
            pass

if __name__ == "__main__":
    if sys.platform == "win32":
        _make_dpi_aware()
    register_startup()
    Monitor().mainloop()
