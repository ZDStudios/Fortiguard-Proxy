import customtkinter as ctk
import subprocess
import threading
import winreg
import urllib.request
import ssl
import ctypes
import io
import json
import zipfile
import atexit
import os
import sys
import shutil
import time
import base64
import pystray
from datetime import datetime
from pathlib import Path
from PIL import Image, ImageDraw

_SSL_CTX = ssl.create_default_context()
_SSL_CTX.check_hostname = False
_SSL_CTX.verify_mode    = ssl.CERT_NONE

ctk.set_appearance_mode("dark")
ctk.set_default_color_theme("blue")

APP_VERSION   = "V22"
REPO          = "ZDStudios/Fortiguard-Proxy"
VERSION_URL   = "https://raw.githubusercontent.com/ZDStudios/Fortiguard-Proxy/main/docs/version.txt"
REG_PATH      = r"Software\Microsoft\Windows\CurrentVersion\Internet Settings"
BOOT_REG      = r"Software\Microsoft\Windows\CurrentVersion\Run"
SERVER        = "https://fortiguard-proxy.onrender.com"
SERVER_2      = "https://fortiguard-proxy.vercel.app"
APPDATA       = os.environ.get("APPDATA", Path.home())
NODE_DIR      = Path(APPDATA) / "FortiProxy" / "nodejs"
NODE_EXE      = NODE_DIR / "node.exe"
SETTINGS_FILE = Path(APPDATA) / "FortiProxy" / "settings.json"
UPDATE_URL    = "https://zdstudios.github.io/Fortiguard-Proxy/update.bat"

# ── Colour themes ─────────────────────────────────────────────────────────────

THEMES = {
    "Dark": {
        "accent":     "#4d9ef7",
        "bg":         "#1c1c1e",
        "bg_hdr":     "#2c2c2e",
        "bg_card":    "#2c2c2e",
        "bg_log":     "#1c1c1e",
        "bg_btn":     "#3a3a3c",
        "bg_btn_hov": "#48484a",
        "bg_stop":    "#2c2c2e",
        "text":       "#f2f2f7",
        "text_dim":   "#aeaeb2",
        "dim":        "#48484a",
        "dim2":       "#3a3a3c",
        "offline":    "#3a3a3c",
        "connected":  "#34c759",
        "conn_dim":   "#1a4a25",
        "start_fg":   "#1c4a28",
        "start_hov":  "#25623a",
        "stop_fg":    "#4a1c1c",
        "stop_hov":   "#622525",
        "warn":       "#ff9f0a",
        "error":      "#ff453a",
        "switch":     "#4d9ef7",
    },
    "Slate": {
        "accent":     "#818cf8",
        "bg":         "#0f172a",
        "bg_hdr":     "#1e293b",
        "bg_card":    "#1e293b",
        "bg_log":     "#0f172a",
        "bg_btn":     "#334155",
        "bg_btn_hov": "#475569",
        "bg_stop":    "#1e293b",
        "text":       "#f1f5f9",
        "text_dim":   "#94a3b8",
        "dim":        "#334155",
        "dim2":       "#1e293b",
        "offline":    "#1e293b",
        "connected":  "#4ade80",
        "conn_dim":   "#14532d",
        "start_fg":   "#14532d",
        "start_hov":  "#166534",
        "stop_fg":    "#7f1d1d",
        "stop_hov":   "#991b1b",
        "warn":       "#fbbf24",
        "error":      "#f87171",
        "switch":     "#818cf8",
    },
    "Forest": {
        "accent":     "#34d399",
        "bg":         "#111c16",
        "bg_hdr":     "#182a1e",
        "bg_card":    "#182a1e",
        "bg_log":     "#111c16",
        "bg_btn":     "#1f3828",
        "bg_btn_hov": "#284a34",
        "bg_stop":    "#182a1e",
        "text":       "#ecfdf5",
        "text_dim":   "#9ca3af",
        "dim":        "#284a34",
        "dim2":       "#1f3828",
        "offline":    "#1f3828",
        "connected":  "#34d399",
        "conn_dim":   "#065f46",
        "start_fg":   "#065f46",
        "start_hov":  "#047857",
        "stop_fg":    "#7f1d1d",
        "stop_hov":   "#991b1b",
        "warn":       "#f59e0b",
        "error":      "#f87171",
        "switch":     "#34d399",
    },
    "Burgundy": {
        "accent":     "#e07090",
        "bg":         "#1a1015",
        "bg_hdr":     "#261620",
        "bg_card":    "#261620",
        "bg_log":     "#1a1015",
        "bg_btn":     "#381e2c",
        "bg_btn_hov": "#4a2840",
        "bg_stop":    "#261620",
        "text":       "#fce7f3",
        "text_dim":   "#c4a0b0",
        "dim":        "#4a2840",
        "dim2":       "#381e2c",
        "offline":    "#381e2c",
        "connected":  "#4ade80",
        "conn_dim":   "#14532d",
        "start_fg":   "#14532d",
        "start_hov":  "#166534",
        "stop_fg":    "#7f1d1d",
        "stop_hov":   "#991b1b",
        "warn":       "#f59e0b",
        "error":      "#f87171",
        "switch":     "#e07090",
    },
    "Amber": {
        "accent":     "#f59e0b",
        "bg":         "#1c1810",
        "bg_hdr":     "#2a2418",
        "bg_card":    "#2a2418",
        "bg_log":     "#1c1810",
        "bg_btn":     "#3a3020",
        "bg_btn_hov": "#4a3e2c",
        "bg_stop":    "#2a2418",
        "text":       "#fffbeb",
        "text_dim":   "#a8a29e",
        "dim":        "#4a3e2c",
        "dim2":       "#3a3020",
        "offline":    "#3a3020",
        "connected":  "#4ade80",
        "conn_dim":   "#14532d",
        "start_fg":   "#14532d",
        "start_hov":  "#166534",
        "stop_fg":    "#7f1d1d",
        "stop_hov":   "#991b1b",
        "warn":       "#f59e0b",
        "error":      "#f87171",
        "switch":     "#f59e0b",
    },
    "Stone": {
        "accent":     "#a8a29e",
        "bg":         "#1c1917",
        "bg_hdr":     "#292524",
        "bg_card":    "#292524",
        "bg_log":     "#1c1917",
        "bg_btn":     "#3c3835",
        "bg_btn_hov": "#4e4a47",
        "bg_stop":    "#292524",
        "text":       "#fafaf9",
        "text_dim":   "#a8a29e",
        "dim":        "#4e4a47",
        "dim2":       "#3c3835",
        "offline":    "#3c3835",
        "connected":  "#4ade80",
        "conn_dim":   "#14532d",
        "start_fg":   "#14532d",
        "start_hov":  "#166534",
        "stop_fg":    "#7f1d1d",
        "stop_hov":   "#991b1b",
        "warn":       "#f59e0b",
        "error":      "#f87171",
        "switch":     "#a8a29e",
    },
}

# ── Settings persistence ──────────────────────────────────────────────────────

def _load_settings() -> dict:
    try:
        if SETTINGS_FILE.exists():
            return json.loads(SETTINGS_FILE.read_text())
    except Exception:
        pass
    return {"start_on_boot": False, "minimize_to_tray": True,
            "launch_minimized": False, "auto_connect": False,
            "auto_update": True, "theme": "Dark"}


def _save_settings(data: dict):
    try:
        SETTINGS_FILE.parent.mkdir(parents=True, exist_ok=True)
        SETTINGS_FILE.write_text(json.dumps(data, indent=2))
    except Exception:
        pass


def _get_theme(settings: dict | None = None) -> dict:
    s = settings or _load_settings()
    return THEMES.get(s.get("theme", "Dark"), THEMES["Dark"])


# Active theme palette — loaded once at startup, used everywhere
_T = _get_theme()


def _hex_rgb(h: str) -> tuple:
    h = h.lstrip("#")
    return tuple(int(h[i:i+2], 16) for i in (0, 2, 4))


# ── Tray icon image ───────────────────────────────────────────────────────────

def _make_tray_image(connected: bool = False) -> Image.Image:
    img  = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    outer = (*_hex_rgb(_T["connected"] if connected else _T["accent"]), 255)
    bg    = (*_hex_rgb(_T["bg"]), 255)
    draw.ellipse([2, 2, 62, 62], fill=outer)
    draw.ellipse([9, 9, 55, 55], fill=bg)
    draw.ellipse([24, 24, 40, 40], fill=outer)
    return img


# ── Boot registry ─────────────────────────────────────────────────────────────

def _get_boot_enabled() -> bool:
    try:
        k = winreg.OpenKey(winreg.HKEY_CURRENT_USER, BOOT_REG, 0, winreg.KEY_READ)
        winreg.QueryValueEx(k, "FortiProxy")
        winreg.CloseKey(k)
        return True
    except OSError:
        return False


def _set_boot_enabled(enabled: bool):
    if not getattr(sys, "frozen", False):
        return
    try:
        k = winreg.OpenKey(winreg.HKEY_CURRENT_USER, BOOT_REG, 0, winreg.KEY_WRITE)
        if enabled:
            winreg.SetValueEx(k, "FortiProxy", 0, winreg.REG_SZ,
                              str(Path(sys.executable).resolve()))
        else:
            try: winreg.DeleteValue(k, "FortiProxy")
            except OSError: pass
        winreg.CloseKey(k)
    except Exception:
        pass


# ── Single instance lock ──────────────────────────────────────────────────────

_INSTANCE_MUTEX = None
QUIT_SIGNAL     = Path(APPDATA) / "FortiProxy" / ".quit_signal"


def _ensure_single_instance() -> bool:
    """Create a named Windows mutex. Returns False if another instance is already running."""
    global _INSTANCE_MUTEX
    _INSTANCE_MUTEX = ctypes.windll.kernel32.CreateMutexW(None, False,
                                                           "Local\\FortiProxy_SingleInstance")
    return ctypes.windll.kernel32.GetLastError() != 183  # 183 = ERROR_ALREADY_EXISTS


# ── Emergency cleanup ─────────────────────────────────────────────────────────

@atexit.register
def _proxy_emergency_off():
    try:
        k = winreg.OpenKey(winreg.HKEY_CURRENT_USER, REG_PATH, 0, winreg.KEY_WRITE)
        winreg.SetValueEx(k, "ProxyEnable", 0, winreg.REG_DWORD, 0)
        for v in ("ProxyServer", "AutoConfigURL", "ProxyOverride"):
            try: winreg.DeleteValue(k, v)
            except OSError: pass
        winreg.CloseKey(k)
        ctypes.windll.Wininet.InternetSetOptionW(0, 39, 0, 0)
        ctypes.windll.Wininet.InternetSetOptionW(0, 37, 0, 0)
    except Exception:
        pass


def _kill_stale_proxy():
    try:
        r = subprocess.run(
            ["powershell", "-Command",
             "(Get-NetTCPConnection -LocalPort 8080 -LocalAddress 127.0.0.1"
             " -ErrorAction SilentlyContinue).OwningProcess"],
            capture_output=True, text=True, creationflags=0x08000000, timeout=6,
        )
        pid = r.stdout.strip()
        if pid and pid.isdigit():
            subprocess.run(["taskkill", "/PID", pid, "/F"],
                           capture_output=True, creationflags=0x08000000, timeout=4)
    except Exception:
        pass


def _install_start_menu():
    if not getattr(sys, "frozen", False):
        return
    lnk  = (Path(APPDATA)
            / "Microsoft" / "Windows" / "Start Menu" / "Programs" / "FortiProxy.lnk")
    exe  = str(Path(sys.executable).resolve())
    wdir = str(Path(sys.executable).parent.resolve())
    ps = (
        f'$s=New-Object -ComObject WScript.Shell;'
        f'$l=$s.CreateShortcut("{lnk}");'
        f'$l.TargetPath="{exe}";'
        f'$l.IconLocation="{exe},0";'
        f'$l.WorkingDirectory="{wdir}";'
        f'$l.Description="FortiProxy";'
        f'$l.Save()'
    )
    enc = base64.b64encode(ps.encode("utf-16-le")).decode("ascii")
    subprocess.run(
        ["powershell", "-WindowStyle", "Hidden", "-EncodedCommand", enc],
        capture_output=True, creationflags=0x08000000,
    )


def _get_base_dir() -> Path:
    if getattr(sys, "frozen", False):
        work = Path(APPDATA) / "FortiProxy"
        work.mkdir(exist_ok=True)
        src = Path(sys._MEIPASS)
        for fname in ("client.js", "proxy.pac", "package.json"):
            s = src / fname
            if s.exists():
                shutil.copy2(s, work / fname)
        src_ws = src / "node_modules" / "ws"
        dst_ws = work / "node_modules" / "ws"
        if src_ws.exists() and not dst_ws.exists():
            shutil.copytree(src_ws, dst_ws)
        return work
    else:
        client_dir = Path(__file__).parent.parent / "client"
        return client_dir if client_dir.exists() else Path(__file__).parent

BASE_DIR = _get_base_dir()


class App(ctk.CTk):
    def __init__(self):
        super().__init__()
        self.title("FortiProxy")
        self.geometry("580x580")
        self.resizable(False, False)
        self.configure(fg_color=_T["bg"])

        self._proc              = None
        self._connected         = False
        self._start_time        = None
        self._pulse_job         = None
        self._pulse_on          = False
        self._closing           = False
        self._blocked           = False
        self._retry_job         = None
        self._retry2_job        = None
        self._tray              = None
        self._tray_hidden       = False
        self._settings_win      = None
        self._settings          = _load_settings()
        self._update_download_url = None

        self._build_ui()
        self.protocol("WM_DELETE_WINDOW", self._on_close)

        _proxy_emergency_off()
        threading.Thread(target=_kill_stale_proxy, daemon=True).start()

        if self._settings.get("minimize_to_tray", True):
            threading.Thread(target=self._build_tray, daemon=True).start()

        if self._settings.get("launch_minimized", False):
            self.after(100, self.withdraw)

        # Clear any stale quit signal from a previous crash
        try: QUIT_SIGNAL.unlink(missing_ok=True)
        except Exception: pass

        self._log("Dashboard ready", "dim")
        self._ping_server()
        self.after(1500, self._check_update)
        self.after(3000, self._auto_check_update)
        self.after(1000, self._check_quit_signal)

        if self._settings.get("auto_connect", False):
            self.after(5000, self._start)

    # ── Tray ──────────────────────────────────────────────────────────────────

    def _build_tray(self):
        menu = pystray.Menu(
            pystray.MenuItem("Open FortiProxy", self._show_window, default=True),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("Disconnect", self._tray_disconnect,
                             enabled=lambda item: self._connected),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("Quit", self._quit_app),
        )
        self._tray = pystray.Icon("FortiProxy", _make_tray_image(), "FortiProxy", menu)
        self._tray.run()

    def _stop_tray(self):
        if self._tray:
            try: self._tray.stop()
            except Exception: pass
            self._tray = None

    def _show_window(self, icon=None, item=None):
        self._tray_hidden = False
        self.after(0, self.deiconify)
        self.after(0, self.lift)
        self.after(0, self.focus_force)

    def _tray_disconnect(self, icon=None, item=None):
        self.after(0, self._stop)

    def _quit_app(self, icon=None, item=None):
        self._closing = True
        self._stop_tray()
        self.after(0, self._full_quit)

    def _full_quit(self):
        self._connected = False
        if self._pulse_job:
            self.after_cancel(self._pulse_job)
        if self._retry_job:
            self.after_cancel(self._retry_job)
        if self._retry2_job:
            self.after_cancel(self._retry2_job)
        if self._proc:
            self._proc.terminate()
        self._disable_proxy()
        self.destroy()

    # ── UI ────────────────────────────────────────────────────────────────────

    def _build_ui(self):
        hdr = ctk.CTkFrame(self, fg_color=_T["bg_hdr"], corner_radius=0, height=60)
        hdr.pack(fill="x")
        hdr.pack_propagate(False)

        ctk.CTkLabel(
            hdr, text="  \U0001f6e1  FORTIPROXY",
            font=ctk.CTkFont("Consolas", 21, "bold"),
            text_color=_T["accent"],
        ).pack(side="left", padx=20)

        self._refresh_btn = ctk.CTkButton(
            hdr, text="↻", width=34, height=34,
            font=ctk.CTkFont("Consolas", 16),
            fg_color=_T["bg_btn"], hover_color=_T["bg_btn_hov"],
            corner_radius=8, command=self._ping_server,
        )
        self._refresh_btn.pack(side="right", padx=(4, 14))

        ctk.CTkButton(
            hdr, text="⚙", width=34, height=34,
            font=ctk.CTkFont("Consolas", 16),
            fg_color=_T["bg_btn"], hover_color=_T["bg_btn_hov"],
            corner_radius=8, command=self._open_settings,
        ).pack(side="right", padx=4)

        ctk.CTkLabel(
            hdr, text=f"{APP_VERSION}  ",
            font=ctk.CTkFont("Consolas", 11),
            text_color=_T["dim2"],
        ).pack(side="right")

        card = ctk.CTkFrame(self, fg_color=_T["bg_card"], corner_radius=14)
        card.pack(fill="x", padx=18, pady=(14, 6))

        self._server_dot  = self._srow(card, "RENDER",  "● CHECKING", _T["warn"])
        self._sep(card)
        self._server2_dot = self._srow(card, "VERCEL",  "● --",       _T["offline"])
        self._sep(card)
        self._tunnel_dot  = self._srow(card, "TUNNEL",  "● OFFLINE",  _T["offline"])
        self._sep(card)
        self._uptime_lbl  = self._srow(card, "UPTIME",  "--:--:--",   _T["offline"],
                                       bold=False)

        bf = ctk.CTkFrame(self, fg_color="transparent")
        bf.pack(fill="x", padx=18, pady=8)
        bf.columnconfigure((0, 1), weight=1)

        self._start_btn = ctk.CTkButton(
            bf, text="▶   START", height=52, corner_radius=10,
            font=ctk.CTkFont("Consolas", 14, "bold"),
            fg_color=_T["start_fg"], hover_color=_T["start_hov"],
            command=self._start,
        )
        self._start_btn.grid(row=0, column=0, padx=(0, 7), sticky="ew")

        self._stop_btn = ctk.CTkButton(
            bf, text="■   DISCONNECT", height=52, corner_radius=10,
            font=ctk.CTkFont("Consolas", 14, "bold"),
            fg_color=_T["bg_stop"], hover_color=_T["bg_stop"],
            state="disabled", command=self._stop,
        )
        self._stop_btn.grid(row=0, column=1, padx=(7, 0), sticky="ew")

        lf = ctk.CTkFrame(self, fg_color=_T["bg_card"], corner_radius=14)
        lf.pack(fill="both", expand=True, padx=18, pady=(6, 16))

        top = ctk.CTkFrame(lf, fg_color="transparent")
        top.pack(fill="x", padx=14, pady=(10, 2))
        ctk.CTkLabel(top, text="ACTIVITY LOG",
                     font=ctk.CTkFont("Consolas", 10),
                     text_color=_T["dim2"]).pack(side="left")
        ctk.CTkButton(top, text="clear", width=42, height=20,
                      font=ctk.CTkFont("Consolas", 10),
                      fg_color="transparent", hover_color=_T["bg_btn"],
                      text_color=_T["dim"],
                      command=self._clear_log).pack(side="right")

        self._logbox = ctk.CTkTextbox(
            lf, font=ctk.CTkFont("Consolas", 11),
            fg_color=_T["bg_log"], text_color=_T["connected"],
            corner_radius=10, state="disabled", wrap="word",
        )
        self._logbox.pack(fill="both", expand=True, padx=10, pady=(0, 10))

        tb = self._logbox._textbox
        tb.tag_config("ok",    foreground=_T["connected"])
        tb.tag_config("dim",   foreground=_T["dim"])
        tb.tag_config("info",  foreground=_T["text_dim"])
        tb.tag_config("warn",  foreground=_T["warn"])
        tb.tag_config("error", foreground=_T["error"])

    def _srow(self, parent, label, value, color, bold=True):
        row = ctk.CTkFrame(parent, fg_color="transparent")
        row.pack(fill="x", padx=18, pady=8)
        ctk.CTkLabel(row, text=label,
                     font=ctk.CTkFont("Consolas", 11),
                     text_color=_T["dim"], width=140, anchor="w").pack(side="left")
        lbl = ctk.CTkLabel(row, text=value,
                           font=ctk.CTkFont("Consolas", 11, "bold" if bold else "normal"),
                           text_color=color)
        lbl.pack(side="right")
        return lbl

    def _sep(self, parent):
        ctk.CTkFrame(parent, fg_color=_T["bg_btn"], height=1,
                     corner_radius=0).pack(fill="x", padx=16)

    # ── Settings window ───────────────────────────────────────────────────────

    def _open_settings(self):
        if self._settings_win and self._settings_win.winfo_exists():
            self._settings_win.focus()
            return

        win = ctk.CTkToplevel(self)
        win.title("Settings — FortiProxy")
        win.geometry("400x600")
        win.resizable(False, False)
        win.configure(fg_color=_T["bg"])
        win.transient(self)
        self._settings_win = win

        hdr = ctk.CTkFrame(win, fg_color=_T["bg_hdr"], corner_radius=0, height=50)
        hdr.pack(fill="x")
        hdr.pack_propagate(False)
        ctk.CTkLabel(hdr, text="  ⚙  SETTINGS",
                     font=ctk.CTkFont("Consolas", 16, "bold"),
                     text_color=_T["accent"]).pack(side="left", padx=16)

        scroll = ctk.CTkScrollableFrame(win, fg_color=_T["bg"],
                                        scrollbar_button_color=_T["bg_btn"],
                                        scrollbar_button_hover_color=_T["bg_btn_hov"])
        scroll.pack(fill="both", expand=True)

        # ── APPEARANCE ──
        self._sw_section(scroll, "APPEARANCE")

        theme_card = ctk.CTkFrame(scroll, fg_color=_T["bg_card"], corner_radius=10)
        theme_card.pack(fill="x", padx=16, pady=(4, 8))

        # Dropdown row
        th_row = ctk.CTkFrame(theme_card, fg_color="transparent")
        th_row.pack(fill="x", padx=14, pady=(12, 6))
        ctk.CTkLabel(th_row, text="Colour scheme",
                     font=ctk.CTkFont("Consolas", 12, "bold"),
                     text_color=_T["text"], anchor="w").pack(side="left")

        current_theme = self._settings.get("theme", "Dark")
        theme_menu = ctk.CTkOptionMenu(
            th_row,
            values=list(THEMES.keys()),
            fg_color=_T["bg_btn"],
            button_color=_T["accent"],
            button_hover_color=_T["bg_btn_hov"],
            dropdown_fg_color=_T["bg_card"],
            text_color=_T["text"],
            font=ctk.CTkFont("Consolas", 11),
            command=self._change_theme,
            width=170,
        )
        theme_menu.set(current_theme)
        theme_menu.pack(side="right")

        # Colour swatches
        sw_row = ctk.CTkFrame(theme_card, fg_color="transparent")
        sw_row.pack(fill="x", padx=14, pady=(2, 8))
        ctk.CTkLabel(sw_row, text="Quick pick  ",
                     font=ctk.CTkFont("Consolas", 9),
                     text_color=_T["dim"]).pack(side="left")
        for name, palette in THEMES.items():
            tip = name
            btn = ctk.CTkButton(
                sw_row, text="", width=26, height=26,
                corner_radius=13,
                fg_color=palette["accent"],
                hover_color=palette["connected"],
                border_width=2 if name == current_theme else 0,
                border_color="#ffffff",
                command=lambda n=name, m=theme_menu: (self._change_theme(n), m.set(n)),
            )
            btn.pack(side="left", padx=3)

        self._theme_note = ctk.CTkLabel(
            theme_card, text="Choose a scheme above, then restart to apply",
            font=ctk.CTkFont("Consolas", 9),
            text_color=_T["dim"])
        self._theme_note.pack(padx=14, pady=(0, 10), anchor="w")

        # ── STARTUP ──
        self._sw_section(scroll, "STARTUP")

        boot_var = ctk.BooleanVar(value=_get_boot_enabled())
        self._sw_row(scroll, "Start on boot",
                     "Launch FortiProxy automatically when Windows starts",
                     boot_var, lambda v: self._toggle_boot(v))

        min_var = ctk.BooleanVar(value=self._settings.get("launch_minimized", False))
        self._sw_row(scroll, "Launch minimized",
                     "Start hidden to tray instead of showing the window",
                     min_var, lambda v: self._save_setting("launch_minimized", v))

        # ── SYSTEM TRAY ──
        self._sw_section(scroll, "SYSTEM TRAY")

        tray_var = ctk.BooleanVar(value=self._settings.get("minimize_to_tray", True))
        self._sw_row(scroll, "Minimize to tray on close",
                     "Keep running in the taskbar tray instead of exiting",
                     tray_var, lambda v: self._toggle_tray(v))

        # ── CONNECTION ──
        self._sw_section(scroll, "CONNECTION")

        auto_var = ctk.BooleanVar(value=self._settings.get("auto_connect", False))
        self._sw_row(scroll, "Auto-connect on launch",
                     "Start the tunnel automatically when FortiProxy opens",
                     auto_var, lambda v: self._save_setting("auto_connect", v))

        # ── UPDATES ──
        self._sw_section(scroll, "UPDATES")

        auto_upd_var = ctk.BooleanVar(value=self._settings.get("auto_update", True))
        self._sw_row(scroll, "Auto-update check",
                     "Check for new versions automatically each time FortiProxy opens",
                     auto_upd_var, lambda v: self._save_setting("auto_update", v))

        ver_card = ctk.CTkFrame(scroll, fg_color=_T["bg_card"], corner_radius=10)
        ver_card.pack(fill="x", padx=16, pady=(4, 12))

        ver_row = ctk.CTkFrame(ver_card, fg_color="transparent")
        ver_row.pack(fill="x", padx=14, pady=(12, 4))
        ctk.CTkLabel(ver_row, text="Installed version",
                     font=ctk.CTkFont("Consolas", 11),
                     text_color=_T["dim"], anchor="w").pack(side="left")
        ctk.CTkLabel(ver_row, text=APP_VERSION,
                     font=ctk.CTkFont("Consolas", 11, "bold"),
                     text_color=_T["text_dim"]).pack(side="right")

        self._upd_lbl = ctk.CTkLabel(ver_card, text="",
                                      font=ctk.CTkFont("Consolas", 11),
                                      text_color=_T["dim"])
        self._upd_lbl.pack(padx=14, anchor="w")

        btn_row = ctk.CTkFrame(ver_card, fg_color="transparent")
        btn_row.pack(fill="x", padx=14, pady=(6, 12))

        ctk.CTkButton(btn_row, text="Check for Updates", height=32,
                      font=ctk.CTkFont("Consolas", 12),
                      fg_color=_T["bg_btn"], hover_color=_T["bg_btn_hov"],
                      corner_radius=8,
                      command=self._check_version).pack(side="left")

        self._install_upd_btn = ctk.CTkButton(
            btn_row, text="↓ Install Update", height=32,
            font=ctk.CTkFont("Consolas", 12),
            fg_color=_T["stop_fg"], hover_color=_T["stop_hov"],
            corner_radius=8, state="disabled",
            command=self._install_update,
        )
        self._install_upd_btn.pack(side="left", padx=(8, 0))

        # ── ABOUT ──
        self._sw_section(scroll, "ABOUT")
        about_card = ctk.CTkFrame(scroll, fg_color=_T["bg_card"], corner_radius=10)
        about_card.pack(fill="x", padx=16, pady=(4, 16))
        for line, color in [
            ("FortiProxy",                              _T["accent"]),
            ("WebSocket tunnel that bypasses Fortiguard", _T["text_dim"]),
            ("filtering on managed school networks.",   _T["text_dim"]),
            (f"github.com/{REPO}",                     _T["dim"]),
        ]:
            ctk.CTkLabel(about_card, text=line,
                         font=ctk.CTkFont("Consolas", 10),
                         text_color=color, anchor="w").pack(padx=14, pady=1, anchor="w")
        ctk.CTkFrame(about_card, fg_color="transparent", height=8).pack()

    def _sw_section(self, parent, title: str):
        f = ctk.CTkFrame(parent, fg_color="transparent")
        f.pack(fill="x", padx=16, pady=(14, 4))
        ctk.CTkLabel(f, text=title,
                     font=ctk.CTkFont("Consolas", 10, "bold"),
                     text_color=_T["dim2"]).pack(side="left")
        ctk.CTkFrame(f, fg_color=_T["bg_btn"], height=1).pack(
            side="left", fill="x", expand=True, padx=(8, 0), pady=1)

    def _sw_row(self, parent, title: str, desc: str, var: ctk.BooleanVar, callback):
        card = ctk.CTkFrame(parent, fg_color=_T["bg_card"], corner_radius=10)
        card.pack(fill="x", padx=16, pady=3)
        left = ctk.CTkFrame(card, fg_color="transparent")
        left.pack(side="left", fill="both", expand=True, padx=14, pady=10)
        ctk.CTkLabel(left, text=title,
                     font=ctk.CTkFont("Consolas", 12, "bold"),
                     text_color=_T["text"], anchor="w").pack(anchor="w")
        ctk.CTkLabel(left, text=desc,
                     font=ctk.CTkFont("Consolas", 9),
                     text_color=_T["dim"], anchor="w", wraplength=220).pack(anchor="w")
        sw = ctk.CTkSwitch(card, text="", variable=var,
                           onvalue=True, offvalue=False,
                           progress_color=_T["switch"],
                           command=lambda: callback(var.get()))
        sw.pack(side="right", padx=14)

    # ── Settings callbacks ────────────────────────────────────────────────────

    def _save_setting(self, key: str, val):
        self._settings[key] = val
        _save_settings(self._settings)

    def _change_theme(self, name: str):
        if name not in THEMES:
            return
        self._save_setting("theme", name)
        if hasattr(self, "_theme_note") and self._theme_note.winfo_exists():
            self._theme_note.configure(
                text=f"'{name}' saved — restart FortiProxy to apply",
                text_color=_T["warn"])
        self._tlog(f"Theme set to {name} — restart FortiProxy to apply", "warn")

    def _toggle_boot(self, enabled: bool):
        self._save_setting("start_on_boot", enabled)
        _set_boot_enabled(enabled)
        if not getattr(sys, "frozen", False):
            self._tlog("Boot setting only works in the installed EXE (not script mode)", "warn")
        else:
            self._tlog(f"Start on boot {'enabled' if enabled else 'disabled'}", "ok")

    def _toggle_tray(self, enabled: bool):
        self._save_setting("minimize_to_tray", enabled)
        if enabled and self._tray is None:
            threading.Thread(target=self._build_tray, daemon=True).start()
            self._tlog("System tray icon enabled", "ok")
        elif not enabled and self._tray is not None:
            self._stop_tray()
            self._tlog("System tray icon disabled", "ok")

    def _check_version(self):
        if hasattr(self, "_upd_lbl") and self._upd_lbl.winfo_exists():
            self._upd_lbl.configure(text="Checking...", text_color=_T["warn"])

        def _run():
            try:
                req = urllib.request.Request(
                    VERSION_URL, headers={"User-Agent": "FortiProxy/2.0"})
                with urllib.request.urlopen(req, timeout=10, context=_SSL_CTX) as r:
                    latest = r.read().decode().strip().splitlines()[0].strip()
                if not latest:
                    raise RuntimeError("Empty version file")

                def vnum(s):
                    try: return int(s.lstrip("Vv"))
                    except ValueError: return 0

                if vnum(latest) > vnum(APP_VERSION):
                    self._update_download_url = (
                        f"https://raw.githubusercontent.com/{REPO}/main/FortiProxy-{latest}.zip")
                    msg   = f"● {latest} available!"
                    color = _T["warn"]
                    self._tlog(f"Update available: {latest} (you have {APP_VERSION})", "warn")
                    if hasattr(self, "_install_upd_btn") and self._install_upd_btn.winfo_exists():
                        self.after(0, lambda: self._install_upd_btn.configure(state="normal"))
                else:
                    self._update_download_url = None
                    msg   = f"● Up to date ({APP_VERSION})"
                    color = _T["connected"]
                    if hasattr(self, "_install_upd_btn") and self._install_upd_btn.winfo_exists():
                        self.after(0, lambda: self._install_upd_btn.configure(state="disabled"))

                if hasattr(self, "_upd_lbl") and self._upd_lbl.winfo_exists():
                    self.after(0, lambda: self._upd_lbl.configure(text=msg, text_color=color))
            except Exception as e:
                err_msg = str(e)
                if hasattr(self, "_upd_lbl") and self._upd_lbl.winfo_exists():
                    self.after(0, lambda m=err_msg: self._upd_lbl.configure(
                        text=f"● {m}", text_color=_T["error"]))

        threading.Thread(target=_run, daemon=True).start()

    def _install_update(self):
        if not self._update_download_url:
            self._tlog("No update URL — click Check for Updates first", "warn")
            return
        if hasattr(self, "_install_upd_btn") and self._install_upd_btn.winfo_exists():
            self._install_upd_btn.configure(state="disabled", text="Downloading...")

        def _run():
            import tempfile
            try:
                self._tlog("Downloading update...", "info")
                req = urllib.request.Request(
                    self._update_download_url,
                    headers={"User-Agent": "FortiProxy/2.0"})
                with urllib.request.urlopen(req, timeout=300, context=_SSL_CTX) as r:
                    total    = int(r.headers.get("Content-Length", 0))
                    data     = bytearray()
                    last_pct = -1
                    while True:
                        chunk = r.read(131072)
                        if not chunk: break
                        data.extend(chunk)
                        if total:
                            pct = (len(data) * 100 // total) // 10 * 10
                            if pct != last_pct:
                                self._tlog(f"Downloading... {pct}%", "dim")
                                last_pct = pct

                self._tlog("Extracting...", "dim")
                tmp = Path(tempfile.mkdtemp(prefix="FortiProxy_upd_"))
                with zipfile.ZipFile(io.BytesIO(bytes(data))) as zf:
                    zf.extractall(tmp)

                bat = tmp / "install.bat"
                if not bat.exists():
                    raise RuntimeError("install.bat not found in update package")

                subprocess.Popen(["cmd", "/c", str(bat)], cwd=str(tmp),
                                 creationflags=0x00000010)
                # Do NOT delete the temp folder via atexit — the bat needs to
                # copy FortiProxy.exe from it AFTER Python exits.
                # install.bat schedules its own cleanup.
                self._tlog("Installer launched — FortiProxy will restart", "ok")
                self.after(2000, self._full_quit)

            except Exception as e:
                self._tlog(f"Update failed: {e}", "error")
                if hasattr(self, "_install_upd_btn") and self._install_upd_btn.winfo_exists():
                    self.after(0, lambda: self._install_upd_btn.configure(
                        state="normal", text="↓ Install Update"))

        threading.Thread(target=_run, daemon=True).start()

    def _auto_check_update(self):
        if not self._settings.get("auto_update", True):
            return

        def _run():
            try:
                req = urllib.request.Request(
                    VERSION_URL, headers={"User-Agent": "FortiProxy/2.0"})
                with urllib.request.urlopen(req, timeout=10, context=_SSL_CTX) as r:
                    latest = r.read().decode().strip().splitlines()[0].strip()
                if not latest:
                    return

                def vnum(s):
                    try: return int(s.lstrip("Vv"))
                    except ValueError: return 0

                if vnum(latest) > vnum(APP_VERSION):
                    self._update_download_url = (
                        f"https://raw.githubusercontent.com/{REPO}/main/FortiProxy-{latest}.zip")
                    self.after(0, lambda: self._show_update_prompt(latest))
            except Exception:
                pass

        threading.Thread(target=_run, daemon=True).start()

    def _show_update_prompt(self, version: str):
        if self._closing:
            return
        dialog = ctk.CTkToplevel(self)
        dialog.title("Update Available")
        dialog.geometry("360x170")
        dialog.resizable(False, False)
        dialog.configure(fg_color=_T["bg"])
        dialog.transient(self)
        dialog.grab_set()
        dialog.lift()
        dialog.focus_force()

        ctk.CTkLabel(dialog, text="Update Available",
                     font=ctk.CTkFont("Consolas", 15, "bold"),
                     text_color=_T["accent"]).pack(pady=(22, 6))
        ctk.CTkLabel(dialog,
                     text=f"Version {version} is available.\nWould you like to update now?",
                     font=ctk.CTkFont("Consolas", 11),
                     text_color=_T["text_dim"]).pack(pady=(0, 18))

        btn_row = ctk.CTkFrame(dialog, fg_color="transparent")
        btn_row.pack()

        def _do_update():
            dialog.destroy()
            self._install_update()

        ctk.CTkButton(btn_row, text="Update Now", width=130, height=36,
                      font=ctk.CTkFont("Consolas", 12, "bold"),
                      fg_color=_T["start_fg"], hover_color=_T["start_hov"],
                      command=_do_update).pack(side="left", padx=(0, 8))
        ctk.CTkButton(btn_row, text="Later", width=80, height=36,
                      font=ctk.CTkFont("Consolas", 12),
                      fg_color=_T["bg_btn"], hover_color=_T["bg_btn_hov"],
                      command=dialog.destroy).pack(side="left")

    # ── Logging ───────────────────────────────────────────────────────────────

    def _log(self, msg, style="ok"):
        ts = datetime.now().strftime("%H:%M:%S")
        self._logbox.configure(state="normal")
        tb = self._logbox._textbox
        tb.insert("end", f"[{ts}]  ", "dim")
        tb.insert("end", f"{msg}\n", style)
        tb.see("end")
        self._logbox.configure(state="disabled")

    def _tlog(self, msg, style="ok"):
        if not self._closing:
            self.after(0, lambda: self._log(msg, style))

    def _clear_log(self):
        self._logbox.configure(state="normal")
        self._logbox.delete("1.0", "end")
        self._logbox.configure(state="disabled")

    # ── Server ping ───────────────────────────────────────────────────────────

    def _check_update(self):
        def _run():
            import tempfile
            try:
                req = urllib.request.Request(UPDATE_URL,
                                             headers={"User-Agent": "FortiProxy/2.0"})
                with urllib.request.urlopen(req, timeout=10) as resp:
                    content = resp.read().decode("utf-8", errors="replace")
                runnable = [ln for ln in content.splitlines()
                            if ln.strip() and not ln.strip().startswith("::")]
                if not runnable:
                    return
                tmp = Path(tempfile.gettempdir()) / "fp_update.bat"
                tmp.write_text(content, encoding="utf-8")
                exe_dir = (str(Path(sys.executable).parent) if getattr(sys, "frozen", False)
                           else str(Path(__file__).parent.parent))
                subprocess.Popen(["cmd", "/c", str(tmp)], cwd=exe_dir,
                                 stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                                 stderr=subprocess.DEVNULL, creationflags=0x00000010)
            except Exception:
                pass
        threading.Thread(target=_run, daemon=True).start()

    def _ping_server(self):
        for job_attr in ("_retry_job", "_retry2_job"):
            j = getattr(self, job_attr, None)
            if j:
                self.after_cancel(j)
                setattr(self, job_attr, None)

        self._server_dot.configure(text="● CHECKING", text_color=_T["warn"])
        self._refresh_btn.configure(state="disabled")
        self._tlog("Pinging servers...", "dim")

        def _check_one(url, dot_attr, label, retry_attr):
            try:
                urllib.request.urlopen(
                    urllib.request.Request(url, headers={"User-Agent": "FortiProxy/2.0"}),
                    timeout=12, context=_SSL_CTX)
                self.after(0, lambda: getattr(self, dot_attr).configure(
                    text="● ONLINE", text_color=_T["connected"]))
                self._tlog(f"{label} is online", "ok")
            except Exception as e:
                self.after(0, lambda: getattr(self, dot_attr).configure(
                    text="● OFFLINE", text_color=_T["error"]))
                self._tlog(f"{label} unreachable — retrying in 30s", "warn")
                setattr(self, retry_attr, self.after(30000, self._ping_server))
            finally:
                self.after(0, lambda: self._refresh_btn.configure(state="normal"))

        def _run():
            _check_one(SERVER, "_server_dot", "Render", "_retry_job")
            if SERVER_2:
                _check_one(SERVER_2, "_server2_dot", "Vercel", "_retry2_job")
            else:
                self.after(0, lambda: self._server2_dot.configure(
                    text="● NOT SET", text_color=_T["dim"]))

        threading.Thread(target=_run, daemon=True).start()

    # ── Proxy ─────────────────────────────────────────────────────────────────

    def _refresh_proxy(self):
        try:
            _wininet = ctypes.windll.Wininet
            _wininet.InternetSetOptionW(0, 39, 0, 0)
            _wininet.InternetSetOptionW(0, 37, 0, 0)
        except Exception:
            pass

    def _enable_proxy(self):
        try:
            k = winreg.OpenKey(winreg.HKEY_CURRENT_USER, REG_PATH, 0, winreg.KEY_WRITE)
            winreg.SetValueEx(k, "ProxyServer",   0, winreg.REG_SZ,    "127.0.0.1:8080")
            winreg.SetValueEx(k, "ProxyEnable",   0, winreg.REG_DWORD, 1)
            winreg.SetValueEx(k, "ProxyOverride", 0, winreg.REG_SZ,
                              "localhost;127.*;10.*;172.16.*;192.168.*;<local>")
            try: winreg.DeleteValue(k, "AutoConfigURL")
            except OSError: pass
            winreg.CloseKey(k)
            self._refresh_proxy()
            return True
        except PermissionError:
            self._tlog("Registry blocked — right-click FortiProxy → Run as administrator", "error")
            return False
        except Exception as e:
            self._tlog(f"Failed to set proxy ({e})", "error")
            return False

    def _disable_proxy(self):
        try:
            k = winreg.OpenKey(winreg.HKEY_CURRENT_USER, REG_PATH, 0, winreg.KEY_WRITE)
            winreg.SetValueEx(k, "ProxyEnable", 0, winreg.REG_DWORD, 0)
            for val in ("ProxyServer", "AutoConfigURL", "ProxyOverride"):
                try: winreg.DeleteValue(k, val)
                except OSError: pass
            winreg.CloseKey(k)
            self._refresh_proxy()
        except Exception as e:
            self._tlog(f"Failed to disable proxy: {e}", "error")

    # ── Tunnel ────────────────────────────────────────────────────────────────

    def _ensure_node(self) -> str:
        if NODE_EXE.exists():
            return str(NODE_EXE)
        found = shutil.which("node")
        if found:
            return found
        self._tlog("Node.js not found — downloading portable version (~28 MB)...", "warn")
        try:
            req = urllib.request.Request("https://nodejs.org/dist/index.json",
                                         headers={"User-Agent": "FortiProxy/2.0"})
            with urllib.request.urlopen(req, timeout=15, context=_SSL_CTX) as r:
                releases = json.loads(r.read())
            lts = next((rel for rel in releases if rel.get("lts")), None)
            if not lts:
                raise RuntimeError("No LTS release found in Node.js index")
            version = lts["version"]
            url = f"https://nodejs.org/dist/{version}/node-{version}-win-x64.zip"
            self._tlog(f"Downloading Node.js {version}...", "info")
            req = urllib.request.Request(url, headers={"User-Agent": "FortiProxy/2.0"})
            with urllib.request.urlopen(req, timeout=300, context=_SSL_CTX) as r:
                total    = int(r.headers.get("Content-Length", 0))
                data     = bytearray()
                last_pct = -1
                while True:
                    chunk = r.read(131072)
                    if not chunk: break
                    data.extend(chunk)
                    if total:
                        pct = (len(data) * 100 // total) // 10 * 10
                        if pct != last_pct:
                            self._tlog(f"Downloading... {pct}%", "dim")
                            last_pct = pct
            NODE_DIR.mkdir(parents=True, exist_ok=True)
            with zipfile.ZipFile(io.BytesIO(bytes(data))) as zf:
                entry = next(n for n in zf.namelist() if n.endswith("/node.exe"))
                NODE_EXE.write_bytes(zf.read(entry))
            self._tlog(f"Node.js {version} ready", "ok")
            return str(NODE_EXE)
        except Exception as e:
            raise RuntimeError(f"Could not install Node.js: {e}")

    def _start(self):
        self._start_btn.configure(state="disabled", text="  CONNECTING...")
        self._tunnel_dot.configure(text="● CONNECTING", text_color=_T["warn"])

        def _run():
            self._tlog("Checking server...", "dim")
            try:
                urllib.request.urlopen(
                    urllib.request.Request(SERVER, headers={"User-Agent": "FortiProxy/2.0"}),
                    timeout=12, context=_SSL_CTX)
                self._tlog("Server online", "ok")
            except Exception as e:
                self._tlog(f"Server unreachable ({e}) — trying anyway", "warn")

            ws_pkg = BASE_DIR / "node_modules" / "ws" / "package.json"
            if not ws_pkg.exists():
                if getattr(sys, "frozen", False):
                    self._tlog("ws module missing from bundle — please rebuild EXE", "error")
                    self.after(0, self._reset_ui)
                    return
                self._tlog("Installing dependencies (one-time)...", "info")
                r = subprocess.run("npm install", cwd=str(BASE_DIR),
                                   shell=True, capture_output=True, text=True)
                if r.returncode != 0:
                    self._tlog(f"npm install failed: {r.stderr.strip()}", "error")
                    self.after(0, self._reset_ui)
                    return
                self._tlog("Dependencies installed", "ok")

            try:
                node = self._ensure_node()
            except RuntimeError as e:
                self._tlog(str(e), "error")
                self.after(0, self._reset_ui)
                return

            if not self._enable_proxy():
                self.after(0, self._reset_ui)
                return
            self._tlog("System proxy set to 127.0.0.1:8080", "ok")

            try:
                extra = {"creationflags": 0x08000000} if sys.platform == "win32" else {}
                self._proc = subprocess.Popen(
                    [node, str(BASE_DIR / "client.js")],
                    stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                    text=True, bufsize=1, cwd=str(BASE_DIR), **extra)
                self.after(0, self._on_connected)
                for line in self._proc.stdout:
                    line = line.strip()
                    if not line: continue
                    if line.startswith("FORTIPROXY_CMD:"):
                        cmd = line.split(":", 1)[1]
                        self.after(0, lambda c=cmd: self._handle_server_cmd(c))
                    elif "closed before the connection was established" in line:
                        pass  # normal browser cleanup noise, suppress
                    else:
                        self._tlog(line, "info")
                self._proc.wait()
            except Exception as e:
                self._tlog(f"Error starting proxy: {e}", "error")
            finally:
                self.after(0, self._on_disconnected)

        threading.Thread(target=_run, daemon=True).start()

    def _stop(self):
        self._tlog("Disconnecting...", "warn")
        self._stop_btn.configure(state="disabled")
        if self._proc:
            self._proc.terminate()

    def _on_connected(self):
        self._connected  = True
        self._start_time = time.time()
        self._tunnel_dot.configure(text="● CONNECTED", text_color=_T["connected"])
        self._stop_btn.configure(state="normal",
                                  fg_color=_T["stop_fg"], hover_color=_T["stop_hov"])
        self._log("Tunnel active — traffic routed through Render", "ok")
        self._tick_uptime()
        self._pulse()
        if self._tray:
            try: self._tray.icon = _make_tray_image(connected=True)
            except Exception: pass

    def _handle_server_cmd(self, cmd):
        if cmd == "block":
            self._blocked   = True
            self._connected = False
            if self._pulse_job:
                self.after_cancel(self._pulse_job)
                self._pulse_job = None
            self._disable_proxy()
            self._tunnel_dot.configure(text="● BLOCKED", text_color=_T["error"])
            self._log("Blocked by server admin — proxy disabled", "error")
        elif cmd == "unblock":
            self._blocked = False
            self._log("Unblocked by server admin", "ok")

    def _on_disconnected(self):
        self._connected = False
        if self._pulse_job:
            self.after_cancel(self._pulse_job)
            self._pulse_job = None
        self._disable_proxy()
        if not self._blocked:
            self._tunnel_dot.configure(text="● OFFLINE", text_color=_T["offline"])
            self._log("Disconnected — proxy disabled", "warn")
        self._uptime_lbl.configure(text="--:--:--", text_color=_T["offline"])
        self._blocked = False
        self._reset_ui()
        if self._tray:
            try: self._tray.icon = _make_tray_image(connected=False)
            except Exception: pass

    def report_callback_exception(self, exc, val, tb):
        # Log UI errors but never kill the proxy — they're almost always
        # harmless (stale widget refs, closed settings window, etc.)
        try:
            self._tlog(f"UI error (non-fatal): {val}", "warn")
        except Exception:
            pass

    def _reset_ui(self):
        self._start_btn.configure(state="normal", text="▶   START")
        self._stop_btn.configure(state="disabled",
                                  fg_color=_T["bg_stop"], hover_color=_T["bg_stop"])

    def _tick_uptime(self):
        if not self._connected:
            return
        s = int(time.time() - self._start_time)
        self._uptime_lbl.configure(
            text=f"{s//3600:02d}:{(s%3600)//60:02d}:{s%60:02d}",
            text_color=_T["accent"])
        self.after(1000, self._tick_uptime)

    def _pulse(self):
        if not self._connected:
            return
        self._pulse_on = not self._pulse_on
        self._tunnel_dot.configure(
            text_color=_T["connected"] if self._pulse_on else _T["conn_dim"])
        self._pulse_job = self.after(900, self._pulse)

    def _check_quit_signal(self):
        """Polls for a .quit_signal file written by install.bat for graceful shutdown."""
        if self._closing:
            return
        if QUIT_SIGNAL.exists():
            try: QUIT_SIGNAL.unlink(missing_ok=True)
            except Exception: pass
            self._closing = True
            self._stop_tray()
            self.after(0, self._full_quit)
            return
        self.after(1000, self._check_quit_signal)

    def _on_close(self):
        if self._settings.get("minimize_to_tray", True) and not self._closing:
            self.withdraw()
            self._tray_hidden = True
            return
        self._closing   = True
        self._connected = False
        if self._pulse_job:
            self.after_cancel(self._pulse_job)
        if self._retry_job:
            self.after_cancel(self._retry_job)
        if self._proc:
            self._proc.terminate()
        self._stop_tray()
        self._disable_proxy()
        self.destroy()


if __name__ == "__main__":
    if not _ensure_single_instance():
        # Find and raise the already-running instance's window
        hwnd = ctypes.windll.user32.FindWindowW(None, "FortiProxy")
        if hwnd:
            ctypes.windll.user32.ShowWindow(hwnd, 9)          # SW_RESTORE
            ctypes.windll.user32.SetForegroundWindow(hwnd)
        sys.exit(0)
    threading.Thread(target=_install_start_menu, daemon=True).start()
    App().mainloop()
