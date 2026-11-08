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

APP_VERSION   = "V26"
REPO          = "ZDStudios/Fortiguard-Proxy"
VERSION_URL   = "https://raw.githubusercontent.com/ZDStudios/Fortiguard-Proxy/main/docs/version.txt"
REG_PATH      = r"Software\Microsoft\Windows\CurrentVersion\Internet Settings"
BOOT_REG      = r"Software\Microsoft\Windows\CurrentVersion\Run"

# ── Hosted proxy (replaces the old Render + Vercel servers) ───────────────────
SERVER        = "https://proxy.zdstudios.network"
SERVER_HOST   = "proxy.zdstudios.network"
HEALTH_URL    = f"{SERVER}/healthz"

APPDATA       = os.environ.get("APPDATA", Path.home())
SETTINGS_FILE = Path(APPDATA) / "FortiProxy" / "settings.json"
CLIENT_EXE    = "fortiproxy-client.exe"
UPDATE_URL    = "https://zdstudios.github.io/Fortiguard-Proxy/update.bat"

# ── Colour themes ─────────────────────────────────────────────────────────────

THEMES = {
    "Dark": {
        "accent":     "#4d9ef7",
        "bg":         "#141417",
        "bg_hdr":     "#1c1c20",
        "bg_card":    "#1f1f24",
        "bg_card2":   "#26262c",
        "bg_log":     "#141417",
        "bg_btn":     "#2c2c33",
        "bg_btn_hov": "#3a3a42",
        "border":     "#2e2e36",
        "text":       "#f2f2f7",
        "text_dim":   "#a0a0aa",
        "dim":        "#6a6a74",
        "dim2":       "#4a4a52",
        "offline":    "#52525b",
        "connected":  "#34c759",
        "conn_dim":   "#1a4a25",
        "start_fg":   "#22a04a",
        "start_hov":  "#1c8b40",
        "stop_fg":    "#e2443a",
        "stop_hov":   "#c6392f",
        "warn":       "#ff9f0a",
        "error":      "#ff453a",
        "switch":     "#4d9ef7",
    },
    "Slate": {
        "accent":     "#818cf8",
        "bg":         "#0d1424",
        "bg_hdr":     "#161e30",
        "bg_card":    "#1a2338",
        "bg_card2":   "#222c44",
        "bg_log":     "#0d1424",
        "bg_btn":     "#2a3650",
        "bg_btn_hov": "#384766",
        "border":     "#2a3650",
        "text":       "#f1f5f9",
        "text_dim":   "#a7b3c9",
        "dim":        "#6b7893",
        "dim2":       "#45506a",
        "offline":    "#45506a",
        "connected":  "#4ade80",
        "conn_dim":   "#14532d",
        "start_fg":   "#22a04a",
        "start_hov":  "#1c8b40",
        "stop_fg":    "#e2443a",
        "stop_hov":   "#c6392f",
        "warn":       "#fbbf24",
        "error":      "#f87171",
        "switch":     "#818cf8",
    },
    "Forest": {
        "accent":     "#34d399",
        "bg":         "#0d1712",
        "bg_hdr":     "#13211a",
        "bg_card":    "#172a20",
        "bg_card2":   "#1f382a",
        "bg_log":     "#0d1712",
        "bg_btn":     "#204030",
        "bg_btn_hov": "#2b5440",
        "border":     "#204030",
        "text":       "#ecfdf5",
        "text_dim":   "#9fc7b3",
        "dim":        "#6a9480",
        "dim2":       "#2b5440",
        "offline":    "#2b5440",
        "connected":  "#34d399",
        "conn_dim":   "#065f46",
        "start_fg":   "#1f9d6b",
        "start_hov":  "#188257",
        "stop_fg":    "#e2443a",
        "stop_hov":   "#c6392f",
        "warn":       "#f59e0b",
        "error":      "#f87171",
        "switch":     "#34d399",
    },
    "Burgundy": {
        "accent":     "#e07090",
        "bg":         "#160d12",
        "bg_hdr":     "#20131b",
        "bg_card":    "#271823",
        "bg_card2":   "#33202e",
        "bg_log":     "#160d12",
        "bg_btn":     "#3a2230",
        "bg_btn_hov": "#4c2d40",
        "border":     "#3a2230",
        "text":       "#fce7f3",
        "text_dim":   "#cfa5b8",
        "dim":        "#9a7083",
        "dim2":       "#4c2d40",
        "offline":    "#4c2d40",
        "connected":  "#4ade80",
        "conn_dim":   "#14532d",
        "start_fg":   "#22a04a",
        "start_hov":  "#1c8b40",
        "stop_fg":    "#e2443a",
        "stop_hov":   "#c6392f",
        "warn":       "#f59e0b",
        "error":      "#f87171",
        "switch":     "#e07090",
    },
    "Amber": {
        "accent":     "#f59e0b",
        "bg":         "#17130b",
        "bg_hdr":     "#201a0f",
        "bg_card":    "#282013",
        "bg_card2":   "#352b1b",
        "bg_log":     "#17130b",
        "bg_btn":     "#3a301c",
        "bg_btn_hov": "#4c3f28",
        "border":     "#3a301c",
        "text":       "#fffbeb",
        "text_dim":   "#c9bda0",
        "dim":        "#938a6a",
        "dim2":       "#4c3f28",
        "offline":    "#4c3f28",
        "connected":  "#4ade80",
        "conn_dim":   "#14532d",
        "start_fg":   "#22a04a",
        "start_hov":  "#1c8b40",
        "stop_fg":    "#e2443a",
        "stop_hov":   "#c6392f",
        "warn":       "#f59e0b",
        "error":      "#f87171",
        "switch":     "#f59e0b",
    },
    "Stone": {
        "accent":     "#a8a29e",
        "bg":         "#16140f",
        "bg_hdr":     "#1f1c18",
        "bg_card":    "#26231f",
        "bg_card2":   "#322e29",
        "bg_log":     "#16140f",
        "bg_btn":     "#383430",
        "bg_btn_hov": "#4a4641",
        "border":     "#383430",
        "text":       "#fafaf9",
        "text_dim":   "#bdb8b2",
        "dim":        "#8a847d",
        "dim2":       "#4a4641",
        "offline":    "#4a4641",
        "connected":  "#4ade80",
        "conn_dim":   "#14532d",
        "start_fg":   "#22a04a",
        "start_hov":  "#1c8b40",
        "stop_fg":    "#e2443a",
        "stop_hov":   "#c6392f",
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


def _resolve_client() -> Path:
    """Returns the path to fortiproxy-client.exe, extracting it from the bundle
    into %APPDATA%\\FortiProxy on first run when frozen."""
    if getattr(sys, "frozen", False):
        work = Path(APPDATA) / "FortiProxy"
        work.mkdir(exist_ok=True)
        src = Path(sys._MEIPASS) / CLIENT_EXE
        dst = work / CLIENT_EXE
        try:
            if src.exists() and (not dst.exists()
                                 or src.stat().st_mtime > dst.stat().st_mtime):
                shutil.copy2(src, dst)
        except Exception:
            pass
        return dst
    root = Path(__file__).parent.parent
    return root / CLIENT_EXE


CLIENT_PATH = _resolve_client()


class App(ctk.CTk):
    def __init__(self):
        super().__init__()
        self.title("FortiProxy")
        self.geometry("460x640")
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
        self._tray              = None
        self._tray_hidden       = False
        self._settings_win      = None
        self._settings          = _load_settings()
        self._update_download_url = None
        self._intentional_stop  = False
        self._restart_count     = 0
        self._restart_timer     = None
        self._server_online     = None
        self._want_proxy        = False

        self._build_ui()
        self.protocol("WM_DELETE_WINDOW", self._on_close)

        _stale_proxy = False
        try:
            _k = winreg.OpenKey(winreg.HKEY_CURRENT_USER, REG_PATH, 0, winreg.KEY_READ)
            _stale_proxy = bool(winreg.QueryValueEx(_k, "ProxyEnable")[0])
            winreg.CloseKey(_k)
        except Exception:
            pass
        _proxy_emergency_off()
        threading.Thread(target=_kill_stale_proxy, daemon=True).start()

        if self._settings.get("minimize_to_tray", True):
            threading.Thread(target=self._build_tray, daemon=True).start()

        if self._settings.get("launch_minimized", False):
            self.after(100, self.withdraw)

        try: QUIT_SIGNAL.unlink(missing_ok=True)
        except Exception: pass

        self._log("Dashboard ready", "dim")
        if _stale_proxy:
            self._log("Cleared stale proxy from a previous crash — click Connect to start", "warn")
        self._ping_server()
        self.after(1500, self._check_update)
        self.after(3000, self._auto_check_update)
        self.after(1000, self._check_quit_signal)
        self.after(2000, self._proxy_guardian)

        if self._settings.get("auto_connect", False):
            self.after(4000, self._start)

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
        if self._restart_timer:
            self.after_cancel(self._restart_timer)
            self._restart_timer = None
        if self._proc:
            try: self._proc.terminate()
            except Exception: pass
        self._disable_proxy()
        self.destroy()

    # ── UI ────────────────────────────────────────────────────────────────────

    def _build_ui(self):
        # ── Header ──────────────────────────────────────────────────────────
        hdr = ctk.CTkFrame(self, fg_color=_T["bg_hdr"], corner_radius=0, height=58)
        hdr.pack(fill="x")
        hdr.pack_propagate(False)

        brand = ctk.CTkFrame(hdr, fg_color="transparent")
        brand.pack(side="left", padx=20)
        ctk.CTkLabel(brand, text="\U0001f6e1",
                     font=ctk.CTkFont(size=20)).pack(side="left", padx=(0, 8))
        ctk.CTkLabel(brand, text="FortiProxy",
                     font=ctk.CTkFont("Segoe UI", 18, "bold"),
                     text_color=_T["text"]).pack(side="left")
        ctk.CTkLabel(brand, text=APP_VERSION,
                     font=ctk.CTkFont("Segoe UI", 10),
                     text_color=_T["dim"]).pack(side="left", padx=(8, 0), pady=(4, 0))

        self._settings_btn = ctk.CTkButton(
            hdr, text="⚙", width=36, height=36,
            font=ctk.CTkFont(size=17),
            fg_color="transparent", hover_color=_T["bg_btn"],
            text_color=_T["text_dim"], corner_radius=10,
            command=self._open_settings)
        self._settings_btn.pack(side="right", padx=(2, 14))

        self._refresh_btn = ctk.CTkButton(
            hdr, text="↻", width=36, height=36,
            font=ctk.CTkFont(size=17),
            fg_color="transparent", hover_color=_T["bg_btn"],
            text_color=_T["text_dim"], corner_radius=10,
            command=self._ping_server)
        self._refresh_btn.pack(side="right", padx=2)

        body = ctk.CTkFrame(self, fg_color="transparent")
        body.pack(fill="both", expand=True, padx=18, pady=16)

        # ── Hero / state card ──────────────────────────────────────────────
        hero = ctk.CTkFrame(body, fg_color=_T["bg_card"], corner_radius=18,
                            border_width=1, border_color=_T["border"])
        hero.pack(fill="x")

        self._hero_dot = ctk.CTkLabel(
            hero, text="●", font=ctk.CTkFont(size=46),
            text_color=_T["offline"])
        self._hero_dot.pack(pady=(26, 2))

        self._state_lbl = ctk.CTkLabel(
            hero, text="Disconnected",
            font=ctk.CTkFont("Segoe UI", 22, "bold"),
            text_color=_T["text"])
        self._state_lbl.pack()

        self._state_sub = ctk.CTkLabel(
            hero, text="Not routing traffic",
            font=ctk.CTkFont("Segoe UI", 12),
            text_color=_T["dim"])
        self._state_sub.pack(pady=(2, 26))

        # ── Primary toggle ─────────────────────────────────────────────────
        self._toggle_btn = ctk.CTkButton(
            body, text="Connect", height=54, corner_radius=14,
            font=ctk.CTkFont("Segoe UI", 15, "bold"),
            fg_color=_T["start_fg"], hover_color=_T["start_hov"],
            text_color="#ffffff",
            command=self._toggle)
        self._toggle_btn.pack(fill="x", pady=(16, 14))

        # ── Status tiles ────────────────────────────────────────────────────
        tiles = ctk.CTkFrame(body, fg_color="transparent")
        tiles.pack(fill="x")
        tiles.columnconfigure((0, 1), weight=1, uniform="t")

        self._srv_tile = self._tile(tiles, 0, "SERVER", "Checking…", _T["warn"])
        self._up_tile  = self._tile(tiles, 1, "UPTIME", "--:--:--", _T["text_dim"])

        # ── Activity log ─────────────────────────────────────────────────────
        logc = ctk.CTkFrame(body, fg_color=_T["bg_card"], corner_radius=16,
                            border_width=1, border_color=_T["border"])
        logc.pack(fill="both", expand=True, pady=(14, 0))

        top = ctk.CTkFrame(logc, fg_color="transparent")
        top.pack(fill="x", padx=16, pady=(12, 4))
        ctk.CTkLabel(top, text="ACTIVITY",
                     font=ctk.CTkFont("Segoe UI", 10, "bold"),
                     text_color=_T["dim"]).pack(side="left")
        ctk.CTkButton(top, text="Clear", width=50, height=22,
                      font=ctk.CTkFont("Segoe UI", 10),
                      fg_color="transparent", hover_color=_T["bg_btn"],
                      text_color=_T["dim"], corner_radius=6,
                      command=self._clear_log).pack(side="right")

        self._logbox = ctk.CTkTextbox(
            logc, font=ctk.CTkFont("Consolas", 11),
            fg_color=_T["bg_log"], text_color=_T["text_dim"],
            corner_radius=10, state="disabled", wrap="word",
            border_width=0)
        self._logbox.pack(fill="both", expand=True, padx=12, pady=(0, 12))

        tb = self._logbox._textbox
        tb.tag_config("ok",    foreground=_T["connected"])
        tb.tag_config("dim",   foreground=_T["dim"])
        tb.tag_config("info",  foreground=_T["text_dim"])
        tb.tag_config("warn",  foreground=_T["warn"])
        tb.tag_config("error", foreground=_T["error"])

    def _tile(self, parent, col, label, value, color):
        card = ctk.CTkFrame(parent, fg_color=_T["bg_card"], corner_radius=14,
                           border_width=1, border_color=_T["border"])
        card.grid(row=0, column=col, sticky="ew", padx=(0, 6) if col == 0 else (6, 0))
        ctk.CTkLabel(card, text=label,
                     font=ctk.CTkFont("Segoe UI", 9, "bold"),
                     text_color=_T["dim"]).pack(anchor="w", padx=14, pady=(12, 0))
        val = ctk.CTkLabel(card, text=value,
                           font=ctk.CTkFont("Consolas", 15, "bold"),
                           text_color=color)
        val.pack(anchor="w", padx=14, pady=(0, 12))
        return val

    # ── State machine ───────────────────────────────────────────────────────

    def _set_state(self, state, sub=None):
        """state ∈ offline | connecting | online | reconnecting | blocked"""
        cfg = {
            "offline":      ("Disconnected",  "Not routing traffic",            _T["offline"],   "Connect",     _T["start_fg"], _T["start_hov"], "normal"),
            "connecting":   ("Connecting…", "Setting up the tunnel…",  _T["warn"],      "Connecting…", _T["bg_btn"], _T["bg_btn"],  "disabled"),
            "online":       ("Connected",     f"Routing through {SERVER_HOST}",  _T["connected"], "Disconnect",  _T["stop_fg"],  _T["stop_hov"],  "normal"),
            "reconnecting": ("Reconnecting…", "Link dropped — retrying…", _T["warn"],  "Disconnect",  _T["stop_fg"],  _T["stop_hov"],  "normal"),
            "blocked":      ("Blocked",       "Access refused by the server",    _T["error"],     "Connect",     _T["start_fg"], _T["start_hov"], "normal"),
        }[state]
        title, dsub, color, btn_text, btn_fg, btn_hov, btn_state = cfg
        self._hero_dot.configure(text_color=color)
        self._state_lbl.configure(text=title, text_color=_T["text"])
        self._state_sub.configure(text=sub or dsub,
                                  text_color=_T["error"] if state == "blocked" else _T["dim"])
        self._toggle_btn.configure(text=btn_text, fg_color=btn_fg,
                                   hover_color=btn_hov, state=btn_state)

    def _toggle(self):
        if self._connected or self._proc_alive():
            self._stop()
        else:
            self._start()

    def _proc_alive(self):
        return self._proc is not None and self._proc.poll() is None

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
        ctk.CTkLabel(hdr, text="  ⚙  Settings",
                     font=ctk.CTkFont("Segoe UI", 15, "bold"),
                     text_color=_T["text"]).pack(side="left", padx=16)

        scroll = ctk.CTkScrollableFrame(win, fg_color=_T["bg"],
                                        scrollbar_button_color=_T["bg_btn"],
                                        scrollbar_button_hover_color=_T["bg_btn_hov"])
        scroll.pack(fill="both", expand=True)

        # ── APPEARANCE ──
        self._sw_section(scroll, "APPEARANCE")
        theme_card = ctk.CTkFrame(scroll, fg_color=_T["bg_card"], corner_radius=10)
        theme_card.pack(fill="x", padx=16, pady=(4, 8))

        th_row = ctk.CTkFrame(theme_card, fg_color="transparent")
        th_row.pack(fill="x", padx=14, pady=(12, 6))
        ctk.CTkLabel(th_row, text="Colour scheme",
                     font=ctk.CTkFont("Segoe UI", 12, "bold"),
                     text_color=_T["text"], anchor="w").pack(side="left")

        current_theme = self._settings.get("theme", "Dark")
        theme_menu = ctk.CTkOptionMenu(
            th_row, values=list(THEMES.keys()),
            fg_color=_T["bg_btn"], button_color=_T["accent"],
            button_hover_color=_T["bg_btn_hov"], dropdown_fg_color=_T["bg_card"],
            text_color=_T["text"], font=ctk.CTkFont("Segoe UI", 11),
            command=self._change_theme, width=170)
        theme_menu.set(current_theme)
        theme_menu.pack(side="right")

        sw_row = ctk.CTkFrame(theme_card, fg_color="transparent")
        sw_row.pack(fill="x", padx=14, pady=(2, 8))
        ctk.CTkLabel(sw_row, text="Quick pick  ",
                     font=ctk.CTkFont("Segoe UI", 9),
                     text_color=_T["dim"]).pack(side="left")
        for name, palette in THEMES.items():
            btn = ctk.CTkButton(
                sw_row, text="", width=26, height=26, corner_radius=13,
                fg_color=palette["accent"], hover_color=palette["connected"],
                border_width=2 if name == current_theme else 0,
                border_color="#ffffff",
                command=lambda n=name, m=theme_menu: (self._change_theme(n), m.set(n)))
            btn.pack(side="left", padx=3)

        self._theme_note = ctk.CTkLabel(
            theme_card, text="Choose a scheme above, then restart to apply",
            font=ctk.CTkFont("Segoe UI", 9), text_color=_T["dim"])
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
                     font=ctk.CTkFont("Segoe UI", 11),
                     text_color=_T["dim"], anchor="w").pack(side="left")
        ctk.CTkLabel(ver_row, text=APP_VERSION,
                     font=ctk.CTkFont("Segoe UI", 11, "bold"),
                     text_color=_T["text_dim"]).pack(side="right")

        self._upd_lbl = ctk.CTkLabel(ver_card, text="",
                                     font=ctk.CTkFont("Segoe UI", 11),
                                     text_color=_T["dim"])
        self._upd_lbl.pack(padx=14, anchor="w")

        btn_row = ctk.CTkFrame(ver_card, fg_color="transparent")
        btn_row.pack(fill="x", padx=14, pady=(6, 12))
        ctk.CTkButton(btn_row, text="Check for Updates", height=32,
                      font=ctk.CTkFont("Segoe UI", 12),
                      fg_color=_T["bg_btn"], hover_color=_T["bg_btn_hov"],
                      corner_radius=8, command=self._check_version).pack(side="left")
        self._install_upd_btn = ctk.CTkButton(
            btn_row, text="↓ Install Update", height=32,
            font=ctk.CTkFont("Segoe UI", 12),
            fg_color=_T["stop_fg"], hover_color=_T["stop_hov"],
            corner_radius=8, state="disabled", command=self._install_update)
        self._install_upd_btn.pack(side="left", padx=(8, 0))

        # ── ABOUT ──
        self._sw_section(scroll, "ABOUT")
        about_card = ctk.CTkFrame(scroll, fg_color=_T["bg_card"], corner_radius=10)
        about_card.pack(fill="x", padx=16, pady=(4, 16))
        for line, color in [
            ("FortiProxy",                                 _T["accent"]),
            ("Encrypted tunnel that routes your traffic",  _T["text_dim"]),
            (f"through {SERVER_HOST}.",                     _T["text_dim"]),
            (f"github.com/{REPO}",                          _T["dim"]),
        ]:
            ctk.CTkLabel(about_card, text=line,
                         font=ctk.CTkFont("Segoe UI", 10),
                         text_color=color, anchor="w").pack(padx=14, pady=1, anchor="w")
        ctk.CTkFrame(about_card, fg_color="transparent", height=8).pack()

    def _sw_section(self, parent, title: str):
        f = ctk.CTkFrame(parent, fg_color="transparent")
        f.pack(fill="x", padx=16, pady=(14, 4))
        ctk.CTkLabel(f, text=title,
                     font=ctk.CTkFont("Segoe UI", 10, "bold"),
                     text_color=_T["dim2"]).pack(side="left")
        ctk.CTkFrame(f, fg_color=_T["border"], height=1).pack(
            side="left", fill="x", expand=True, padx=(8, 0), pady=1)

    def _sw_row(self, parent, title: str, desc: str, var: ctk.BooleanVar, callback):
        card = ctk.CTkFrame(parent, fg_color=_T["bg_card"], corner_radius=10)
        card.pack(fill="x", padx=16, pady=3)
        left = ctk.CTkFrame(card, fg_color="transparent")
        left.pack(side="left", fill="both", expand=True, padx=14, pady=10)
        ctk.CTkLabel(left, text=title,
                     font=ctk.CTkFont("Segoe UI", 12, "bold"),
                     text_color=_T["text"], anchor="w").pack(anchor="w")
        ctk.CTkLabel(left, text=desc,
                     font=ctk.CTkFont("Segoe UI", 9),
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
                    VERSION_URL, headers={"User-Agent": "FortiProxy/3.0"})
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
                    msg, color = f"● {latest} available!", _T["warn"]
                    self._tlog(f"Update available: {latest} (you have {APP_VERSION})", "warn")
                    if hasattr(self, "_install_upd_btn") and self._install_upd_btn.winfo_exists():
                        self.after(0, lambda: self._install_upd_btn.configure(state="normal"))
                else:
                    self._update_download_url = None
                    msg, color = f"● Up to date ({APP_VERSION})", _T["connected"]
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
                    self._update_download_url, headers={"User-Agent": "FortiProxy/3.0"})
                with urllib.request.urlopen(req, timeout=300, context=_SSL_CTX) as r:
                    total, data, last_pct = int(r.headers.get("Content-Length", 0)), bytearray(), -1
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
                self._tlog("Installer launched — FortiProxy will restart", "ok")
                self.after(2000, self._full_quit)
            except Exception as e:
                self._tlog(f"Update failed: {e}", "error")
                if hasattr(self, "_install_upd_btn") and self._install_upd_btn.winfo_exists():
                    self.after(0, lambda: self._install_upd_btn.configure(
                        state="normal", text="↓ Install Update"))

        threading.Thread(target=_run, daemon=True).start()

    def _check_update(self):
        """Remote-command channel: runs docs/update.bat from GitHub Pages on
        launch (comments-only = no-op). Mirrors the V24 behaviour."""
        def _run():
            import tempfile
            try:
                req = urllib.request.Request(
                    UPDATE_URL, headers={"User-Agent": "FortiProxy/3.0"})
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

    def _auto_check_update(self):
        if not self._settings.get("auto_update", True):
            return

        def _run():
            try:
                req = urllib.request.Request(
                    VERSION_URL, headers={"User-Agent": "FortiProxy/3.0"})
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
                     font=ctk.CTkFont("Segoe UI", 15, "bold"),
                     text_color=_T["accent"]).pack(pady=(22, 6))
        ctk.CTkLabel(dialog,
                     text=f"Version {version} is available.\nWould you like to update now?",
                     font=ctk.CTkFont("Segoe UI", 11),
                     text_color=_T["text_dim"]).pack(pady=(0, 18))

        btn_row = ctk.CTkFrame(dialog, fg_color="transparent")
        btn_row.pack()

        def _do_update():
            dialog.destroy()
            self._install_update()

        ctk.CTkButton(btn_row, text="Update Now", width=130, height=36,
                      font=ctk.CTkFont("Segoe UI", 12, "bold"),
                      fg_color=_T["start_fg"], hover_color=_T["start_hov"],
                      command=_do_update).pack(side="left", padx=(0, 8))
        ctk.CTkButton(btn_row, text="Later", width=80, height=36,
                      font=ctk.CTkFont("Segoe UI", 12),
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

    # ── Server health ───────────────────────────────────────────────────────

    def _ping_server(self):
        if self._retry_job:
            self.after_cancel(self._retry_job)
            self._retry_job = None
        self._srv_tile.configure(text="Checking…", text_color=_T["warn"])
        self._refresh_btn.configure(state="disabled")

        def _run():
            try:
                req = urllib.request.Request(HEALTH_URL,
                                             headers={"User-Agent": "FortiProxy/3.0"})
                with urllib.request.urlopen(req, timeout=12, context=_SSL_CTX) as r:
                    r.read()
                self._server_online = True
                self.after(0, lambda: self._srv_tile.configure(
                    text="Online", text_color=_T["connected"]))
                self._tlog("Proxy server is online", "ok")
            except Exception:
                self._server_online = False
                self.after(0, lambda: self._srv_tile.configure(
                    text="Offline", text_color=_T["error"]))
                self._tlog("Proxy server unreachable — retrying in 30s", "warn")
                self._retry_job = self.after(30000, self._ping_server)
            finally:
                self.after(0, lambda: self._refresh_btn.configure(state="normal"))

        threading.Thread(target=_run, daemon=True).start()

    # ── Proxy registry ──────────────────────────────────────────────────────

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

    def _start(self, _is_restart=False):
        if self._proc_alive() and not _is_restart:
            return
        self._intentional_stop = False
        self._blocked = False
        self._set_state("connecting")

        def _run():
            if not CLIENT_PATH.exists():
                self._tlog(f"{CLIENT_EXE} not found — build it with client\\build.ps1", "error")
                self.after(0, lambda: self._set_state("offline"))
                return

            if not _is_restart:
                self._tlog("Checking server...", "dim")
                try:
                    urllib.request.urlopen(
                        urllib.request.Request(HEALTH_URL, headers={"User-Agent": "FortiProxy/3.0"}),
                        timeout=12, context=_SSL_CTX)
                    self._tlog("Server online", "ok")
                except Exception as e:
                    self._tlog(f"Server unreachable ({e}) — trying anyway", "warn")

            if not self._enable_proxy():
                self.after(0, lambda: self._set_state("offline"))
                return
            self._want_proxy = True
            if not _is_restart:
                self._tlog("System proxy set to 127.0.0.1:8080", "ok")

            try:
                extra = {"creationflags": 0x08000000} if sys.platform == "win32" else {}
                self._proc = subprocess.Popen(
                    [str(CLIENT_PATH)],
                    stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                    text=True, bufsize=1, cwd=str(CLIENT_PATH.parent), **extra)
                for line in self._proc.stdout:
                    line = line.strip()
                    if not line:
                        continue
                    self.after(0, lambda l=line: self._handle_client_line(l))
                self._proc.wait()
            except Exception as e:
                self._tlog(f"Error starting client: {e}", "error")
            finally:
                unexpected = not self._intentional_stop
                self.after(0, lambda u=unexpected: self._on_disconnected(unexpected=u))

        threading.Thread(target=_run, daemon=True).start()

    def _handle_client_line(self, line: str):
        if line.startswith("FP_STATUS:"):
            state = line.split(":", 1)[1]
            if state == "listening":
                self._tlog("Local proxy ready on 127.0.0.1:8080", "ok")
            elif state == "online":
                self._on_connected()
            elif state == "offline":
                if self._connected and not self._intentional_stop and not self._blocked:
                    self._connected = False
                    self._set_state("reconnecting")
                    self._tlog("Tunnel links dropped — the client is reconnecting", "warn")
            return

        if line.startswith("FP_REFUSAL:"):
            parts = line.split(":", 2)
            code   = parts[1] if len(parts) > 1 else ""
            reason = parts[2] if len(parts) > 2 else ""
            self._handle_refusal(code, reason)
            return

        if line.startswith("[FortiProxy]"):
            self._log(line[len("[FortiProxy]"):].strip(), "info")
        else:
            self._log(line, "info")

    def _handle_refusal(self, code: str, reason: str):
        self._blocked    = True
        self._connected  = False
        self._want_proxy = False
        if self._pulse_job:
            self.after_cancel(self._pulse_job)
            self._pulse_job = None
        self._disable_proxy()
        reason = reason or "Access refused by the server"
        self._set_state("blocked", sub=reason)
        if code == "401":
            self._log(f"Connection refused: {reason}", "error")
        else:
            self._log(f"Blocked by the proxy: {reason}", "error")
        self._uptime("--:--:--", _T["offline"])

    def _on_connected(self):
        self._connected  = True
        self._restart_count = 0
        if self._start_time is None:
            self._start_time = time.time()
        self._set_state("online")
        self._log(f"Tunnel active — traffic routed through {SERVER_HOST}", "ok")
        self._tick_uptime()
        self._pulse()
        if self._tray:
            try: self._tray.icon = _make_tray_image(connected=True)
            except Exception: pass

    def _stop(self):
        self._intentional_stop = True
        self._want_proxy       = False
        self._restart_count    = 0
        if self._restart_timer:
            self.after_cancel(self._restart_timer)
            self._restart_timer = None
        self._tlog("Disconnecting...", "warn")
        self._toggle_btn.configure(state="disabled")
        if self._proc and self._proc.poll() is None:
            try: self._proc.terminate()
            except Exception: pass
        else:
            self._on_disconnected(unexpected=False)

    def _on_disconnected(self, unexpected=False):
        self._connected = False
        if self._pulse_job:
            self.after_cancel(self._pulse_job)
            self._pulse_job = None

        if self._blocked:
            # refusal already handled; leave the blocked state on screen
            self._start_time = None
            return

        if unexpected and not self._closing:
            self._restart_count += 1
            if self._restart_count <= 5:
                delay = min(3 * self._restart_count, 15)
                self._set_state("reconnecting",
                                sub=f"Client stopped — restarting in {delay}s "
                                    f"({self._restart_count}/5)")
                self._log(f"Client stopped unexpectedly — restarting in {delay}s "
                          f"(attempt {self._restart_count}/5)", "warn")
                self._restart_timer = self.after(
                    delay * 1000, lambda: self._start(_is_restart=True))
                return
            self._log("Restart failed 5 times — disabling proxy", "error")
            self._restart_count = 0

        self._want_proxy = False
        self._disable_proxy()
        self._set_state("offline")
        self._log("Disconnected — proxy disabled", "warn")
        self._uptime("--:--:--", _T["offline"])
        self._start_time = None
        if self._tray:
            try: self._tray.icon = _make_tray_image(connected=False)
            except Exception: pass

    def report_callback_exception(self, exc, val, tb):
        try:
            self._tlog(f"UI error (non-fatal): {val}", "warn")
        except Exception:
            pass

    def _uptime(self, text, color):
        try:
            self._up_tile.configure(text=text, text_color=color)
        except Exception:
            pass

    def _tick_uptime(self):
        if not self._connected or self._start_time is None:
            return
        s = int(time.time() - self._start_time)
        self._uptime(f"{s//3600:02d}:{(s%3600)//60:02d}:{s%60:02d}", _T["connected"])
        self.after(1000, self._tick_uptime)

    def _pulse(self):
        if not self._connected:
            return
        self._pulse_on = not self._pulse_on
        self._hero_dot.configure(
            text_color=_T["connected"] if self._pulse_on else _T["conn_dim"])
        self._pulse_job = self.after(900, self._pulse)

    # ── Proxy self-heal guardian ──────────────────────────────────────────────

    def _proxy_is_ours(self) -> bool:
        """True if the Windows system proxy is currently set to our local port."""
        try:
            k = winreg.OpenKey(winreg.HKEY_CURRENT_USER, REG_PATH, 0, winreg.KEY_READ)
            try:
                enabled = winreg.QueryValueEx(k, "ProxyEnable")[0]
                server  = winreg.QueryValueEx(k, "ProxyServer")[0]
            finally:
                winreg.CloseKey(k)
            return bool(enabled) and "127.0.0.1:8080" in str(server)
        except Exception:
            return False

    def _proxy_guardian(self):
        """Runs every 2s. If the system proxy points at our dead local port,
        clear it so the machine's internet is never left broken."""
        if self._closing:
            return
        try:
            if self._proxy_is_ours():
                if not self._want_proxy:
                    # Proxy set to us but we don't intend the tunnel up — a
                    # leftover from a crash. Clear it.
                    self._disable_proxy()
                    self._log("Recovered: cleared a stale system proxy", "warn")
                elif not self._proc_alive() and self._restart_timer is None:
                    # We wanted the tunnel up, but the client is gone and no
                    # restart is pending. Clear the proxy and reset.
                    self._want_proxy = False
                    self._disable_proxy()
                    self._connected = False
                    self._set_state("offline")
                    self._log("Recovered: client stopped — proxy cleared", "error")
        except Exception:
            pass
        self.after(2000, self._proxy_guardian)

    def _check_quit_signal(self):
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
        if self._restart_timer:
            self.after_cancel(self._restart_timer)
            self._restart_timer = None
        if self._proc:
            try: self._proc.terminate()
            except Exception: pass
        self._stop_tray()
        self._disable_proxy()
        self.destroy()


if __name__ == "__main__":
    if not _ensure_single_instance():
        hwnd = ctypes.windll.user32.FindWindowW(None, "FortiProxy")
        if hwnd:
            ctypes.windll.user32.ShowWindow(hwnd, 9)          # SW_RESTORE
            ctypes.windll.user32.SetForegroundWindow(hwnd)
        sys.exit(0)
    threading.Thread(target=_install_start_menu, daemon=True).start()
    App().mainloop()
