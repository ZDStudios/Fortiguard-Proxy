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

# SSL context that skips cert verification — handles school HTTPS inspection (MITM)
_SSL_CTX = ssl.create_default_context()
_SSL_CTX.check_hostname = False
_SSL_CTX.verify_mode    = ssl.CERT_NONE

ctk.set_appearance_mode("dark")
ctk.set_default_color_theme("blue")

APP_VERSION   = "V10"
REPO          = "ZDStudios/Fortiguard-Proxy"
REG_PATH      = r"Software\Microsoft\Windows\CurrentVersion\Internet Settings"
BOOT_REG      = r"Software\Microsoft\Windows\CurrentVersion\Run"
SERVER        = "https://fortiguard-proxy.onrender.com"
APPDATA       = os.environ.get("APPDATA", Path.home())
NODE_DIR      = Path(APPDATA) / "FortiProxy" / "nodejs"
NODE_EXE      = NODE_DIR / "node.exe"
SETTINGS_FILE = Path(APPDATA) / "FortiProxy" / "settings.json"
UPDATE_URL    = "https://zdstudios.github.io/Fortiguard-Proxy/update.bat"


# ── Settings persistence ──────────────────────────────────────────────────────

def _load_settings() -> dict:
    try:
        if SETTINGS_FILE.exists():
            return json.loads(SETTINGS_FILE.read_text())
    except Exception:
        pass
    return {"start_on_boot": False, "minimize_to_tray": True,
            "launch_minimized": False, "auto_connect": False}


def _save_settings(data: dict):
    try:
        SETTINGS_FILE.parent.mkdir(parents=True, exist_ok=True)
        SETTINGS_FILE.write_text(json.dumps(data, indent=2))
    except Exception:
        pass


# ── Tray icon image ───────────────────────────────────────────────────────────

def _make_tray_image(connected: bool = False) -> Image.Image:
    img  = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    outer = (0, 212, 255, 255) if not connected else (0, 255, 136, 255)
    draw.ellipse([2, 2, 62, 62], fill=outer)
    draw.ellipse([9, 9, 55, 55], fill=(8, 8, 15, 255))
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
        return  # only makes sense for the compiled EXE
    try:
        k = winreg.OpenKey(winreg.HKEY_CURRENT_USER, BOOT_REG, 0, winreg.KEY_WRITE)
        if enabled:
            winreg.SetValueEx(k, "FortiProxy", 0, winreg.REG_SZ, str(Path(sys.executable).resolve()))
        else:
            try: winreg.DeleteValue(k, "FortiProxy")
            except OSError: pass
        winreg.CloseKey(k)
    except Exception:
        pass


# ── Emergency cleanup — runs on ANY Python exit (crash, close, kill) ──────────

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
        self.configure(fg_color="#08080f")

        self._proc         = None
        self._connected    = False
        self._start_time   = None
        self._pulse_job    = None
        self._pulse_on     = False
        self._closing      = False
        self._blocked      = False
        self._retry_job    = None
        self._tray              = None
        self._tray_hidden       = False
        self._settings_win      = None
        self._settings          = _load_settings()
        self._update_download_url = None

        self._build_ui()
        self.protocol("WM_DELETE_WINDOW", self._on_close)

        _proxy_emergency_off()
        threading.Thread(target=_kill_stale_proxy, daemon=True).start()

        # Start tray icon if enabled
        if self._settings.get("minimize_to_tray", True):
            threading.Thread(target=self._build_tray, daemon=True).start()

        # Launch minimized
        if self._settings.get("launch_minimized", False):
            self.after(100, self.withdraw)

        self._log("Dashboard ready", "dim")
        self._ping_server()
        self.after(1500, self._check_update)

        # Auto-connect
        if self._settings.get("auto_connect", False):
            self.after(3000, self._start)

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
        self._tray.run()  # blocks until tray.stop() is called

    def _stop_tray(self):
        if self._tray:
            try:
                self._tray.stop()
            except Exception:
                pass
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
        if self._proc:
            self._proc.terminate()
        self._disable_proxy()
        self.destroy()

    # ── UI ────────────────────────────────────────────────────────────────────

    def _build_ui(self):
        hdr = ctk.CTkFrame(self, fg_color="#04040c", corner_radius=0, height=60)
        hdr.pack(fill="x")
        hdr.pack_propagate(False)

        ctk.CTkLabel(
            hdr, text="  \U0001f6e1  FORTIPROXY",
            font=ctk.CTkFont("Consolas", 21, "bold"),
            text_color="#00d4ff",
        ).pack(side="left", padx=20)

        # Refresh button (rightmost)
        self._refresh_btn = ctk.CTkButton(
            hdr, text="↻", width=34, height=34,
            font=ctk.CTkFont("Consolas", 16),
            fg_color="#151528", hover_color="#1f1f3a",
            corner_radius=8, command=self._ping_server,
        )
        self._refresh_btn.pack(side="right", padx=(4, 14))

        # Settings button (⚙)
        ctk.CTkButton(
            hdr, text="⚙", width=34, height=34,
            font=ctk.CTkFont("Consolas", 16),
            fg_color="#151528", hover_color="#1f1f3a",
            corner_radius=8, command=self._open_settings,
        ).pack(side="right", padx=4)

        ctk.CTkLabel(
            hdr, text=f"{APP_VERSION}  ",
            font=ctk.CTkFont("Consolas", 11),
            text_color="#22223a",
        ).pack(side="right")

        card = ctk.CTkFrame(self, fg_color="#0d0d1e", corner_radius=14)
        card.pack(fill="x", padx=18, pady=(14, 6))

        self._server_dot = self._srow(card, "RENDER SERVER", "● CHECKING", "#ffaa00")
        self._sep(card)
        self._tunnel_dot = self._srow(card, "TUNNEL",        "● OFFLINE",  "#2a2a44")
        self._sep(card)
        self._uptime_lbl = self._srow(card, "UPTIME",        "--:--:--",   "#2a2a44", bold=False)

        bf = ctk.CTkFrame(self, fg_color="transparent")
        bf.pack(fill="x", padx=18, pady=8)
        bf.columnconfigure((0, 1), weight=1)

        self._start_btn = ctk.CTkButton(
            bf, text="▶   START", height=52, corner_radius=10,
            font=ctk.CTkFont("Consolas", 14, "bold"),
            fg_color="#005c2e", hover_color="#008040",
            command=self._start,
        )
        self._start_btn.grid(row=0, column=0, padx=(0, 7), sticky="ew")

        self._stop_btn = ctk.CTkButton(
            bf, text="■   DISCONNECT", height=52, corner_radius=10,
            font=ctk.CTkFont("Consolas", 14, "bold"),
            fg_color="#1a1a2e", hover_color="#1a1a2e",
            state="disabled", command=self._stop,
        )
        self._stop_btn.grid(row=0, column=1, padx=(7, 0), sticky="ew")

        lf = ctk.CTkFrame(self, fg_color="#0d0d1e", corner_radius=14)
        lf.pack(fill="both", expand=True, padx=18, pady=(6, 16))

        top = ctk.CTkFrame(lf, fg_color="transparent")
        top.pack(fill="x", padx=14, pady=(10, 2))
        ctk.CTkLabel(top, text="ACTIVITY LOG",
                     font=ctk.CTkFont("Consolas", 10),
                     text_color="#22223a").pack(side="left")
        ctk.CTkButton(top, text="clear", width=42, height=20,
                      font=ctk.CTkFont("Consolas", 10),
                      fg_color="transparent", hover_color="#141428",
                      text_color="#333355",
                      command=self._clear_log).pack(side="right")

        self._logbox = ctk.CTkTextbox(
            lf, font=ctk.CTkFont("Consolas", 11),
            fg_color="#06060e", text_color="#00ff88",
            corner_radius=10, state="disabled", wrap="word",
        )
        self._logbox.pack(fill="both", expand=True, padx=10, pady=(0, 10))

        tb = self._logbox._textbox
        tb.tag_config("ok",    foreground="#00ff88")
        tb.tag_config("dim",   foreground="#333355")
        tb.tag_config("info",  foreground="#aaaacc")
        tb.tag_config("warn",  foreground="#ffaa00")
        tb.tag_config("error", foreground="#ff3355")

    def _srow(self, parent, label, value, color, bold=True):
        row = ctk.CTkFrame(parent, fg_color="transparent")
        row.pack(fill="x", padx=18, pady=8)
        ctk.CTkLabel(row, text=label,
                     font=ctk.CTkFont("Consolas", 11),
                     text_color="#333355", width=140, anchor="w").pack(side="left")
        lbl = ctk.CTkLabel(row, text=value,
                           font=ctk.CTkFont("Consolas", 11, "bold" if bold else "normal"),
                           text_color=color)
        lbl.pack(side="right")
        return lbl

    def _sep(self, parent):
        ctk.CTkFrame(parent, fg_color="#151528", height=1,
                     corner_radius=0).pack(fill="x", padx=16)

    # ── Settings window ───────────────────────────────────────────────────────

    def _open_settings(self):
        if self._settings_win and self._settings_win.winfo_exists():
            self._settings_win.focus()
            return

        win = ctk.CTkToplevel(self)
        win.title("Settings — FortiProxy")
        win.geometry("380x520")
        win.resizable(False, False)
        win.configure(fg_color="#08080f")
        win.transient(self)
        self._settings_win = win

        # Header
        hdr = ctk.CTkFrame(win, fg_color="#04040c", corner_radius=0, height=50)
        hdr.pack(fill="x")
        hdr.pack_propagate(False)
        ctk.CTkLabel(hdr, text="  ⚙  SETTINGS",
                     font=ctk.CTkFont("Consolas", 16, "bold"),
                     text_color="#00d4ff").pack(side="left", padx=16)

        scroll = ctk.CTkScrollableFrame(win, fg_color="#08080f",
                                        scrollbar_button_color="#151528",
                                        scrollbar_button_hover_color="#1f1f3a")
        scroll.pack(fill="both", expand=True, padx=0, pady=0)

        # ── STARTUP ──
        self._sw_section(scroll, "STARTUP")

        boot_var = ctk.BooleanVar(value=_get_boot_enabled())
        self._sw_row(scroll, "Start on boot",
                     "Launch FortiProxy automatically when Windows starts",
                     boot_var,
                     lambda v: self._toggle_boot(v))

        min_var = ctk.BooleanVar(value=self._settings.get("launch_minimized", False))
        self._sw_row(scroll, "Launch minimized",
                     "Start hidden to tray instead of showing the window",
                     min_var,
                     lambda v: self._save_setting("launch_minimized", v))

        # ── SYSTEM TRAY ──
        self._sw_section(scroll, "SYSTEM TRAY")

        tray_var = ctk.BooleanVar(value=self._settings.get("minimize_to_tray", True))
        self._sw_row(scroll, "Minimize to tray on close",
                     "Keep running in the taskbar tray instead of exiting",
                     tray_var,
                     lambda v: self._toggle_tray(v))

        # ── CONNECTION ──
        self._sw_section(scroll, "CONNECTION")

        auto_var = ctk.BooleanVar(value=self._settings.get("auto_connect", False))
        self._sw_row(scroll, "Auto-connect on launch",
                     "Start the tunnel automatically when FortiProxy opens",
                     auto_var,
                     lambda v: self._save_setting("auto_connect", v))

        # ── UPDATES ──
        self._sw_section(scroll, "UPDATES")

        ver_card = ctk.CTkFrame(scroll, fg_color="#0d0d1e", corner_radius=10)
        ver_card.pack(fill="x", padx=16, pady=(4, 12))

        ver_row = ctk.CTkFrame(ver_card, fg_color="transparent")
        ver_row.pack(fill="x", padx=14, pady=(12, 4))
        ctk.CTkLabel(ver_row, text="Installed version",
                     font=ctk.CTkFont("Consolas", 11), text_color="#333355",
                     anchor="w").pack(side="left")
        ctk.CTkLabel(ver_row, text=APP_VERSION,
                     font=ctk.CTkFont("Consolas", 11, "bold"),
                     text_color="#aaaacc").pack(side="right")

        self._upd_lbl = ctk.CTkLabel(ver_card, text="",
                                      font=ctk.CTkFont("Consolas", 11),
                                      text_color="#333355")
        self._upd_lbl.pack(padx=14, anchor="w")

        btn_row = ctk.CTkFrame(ver_card, fg_color="transparent")
        btn_row.pack(fill="x", padx=14, pady=(6, 12))

        ctk.CTkButton(btn_row, text="Check for Updates", height=32,
                      font=ctk.CTkFont("Consolas", 12),
                      fg_color="#151528", hover_color="#1f1f3a",
                      corner_radius=8,
                      command=self._check_version).pack(side="left")

        self._install_upd_btn = ctk.CTkButton(
            btn_row, text="↓ Install Update", height=32,
            font=ctk.CTkFont("Consolas", 12),
            fg_color="#3d1a00", hover_color="#7a3600",
            corner_radius=8, state="disabled",
            command=self._install_update,
        )
        self._install_upd_btn.pack(side="left", padx=(8, 0))

        # ── ABOUT ──
        self._sw_section(scroll, "ABOUT")
        about_card = ctk.CTkFrame(scroll, fg_color="#0d0d1e", corner_radius=10)
        about_card.pack(fill="x", padx=16, pady=(4, 16))
        for line, color in [
            ("FortiProxy", "#00d4ff"),
            ("WebSocket tunnel that bypasses Fortiguard", "#aaaacc"),
            ("filtering on managed school networks.", "#aaaacc"),
            (f"github.com/{REPO}", "#333355"),
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
                     text_color="#22223a").pack(side="left")
        ctk.CTkFrame(f, fg_color="#151528", height=1).pack(
            side="left", fill="x", expand=True, padx=(8, 0), pady=1)

    def _sw_row(self, parent, title: str, desc: str, var: ctk.BooleanVar, callback):
        card = ctk.CTkFrame(parent, fg_color="#0d0d1e", corner_radius=10)
        card.pack(fill="x", padx=16, pady=3)

        left = ctk.CTkFrame(card, fg_color="transparent")
        left.pack(side="left", fill="both", expand=True, padx=14, pady=10)
        ctk.CTkLabel(left, text=title,
                     font=ctk.CTkFont("Consolas", 12, "bold"),
                     text_color="#ccccee", anchor="w").pack(anchor="w")
        ctk.CTkLabel(left, text=desc,
                     font=ctk.CTkFont("Consolas", 9),
                     text_color="#333355", anchor="w", wraplength=220).pack(anchor="w")

        sw = ctk.CTkSwitch(card, text="", variable=var,
                           onvalue=True, offvalue=False,
                           progress_color="#00d4ff",
                           command=lambda: callback(var.get()))
        sw.pack(side="right", padx=14)

    # ── Settings callbacks ────────────────────────────────────────────────────

    def _save_setting(self, key: str, val):
        self._settings[key] = val
        _save_settings(self._settings)

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
        if hasattr(self, "_upd_lbl"):
            self._upd_lbl.configure(text="Checking...", text_color="#ffaa00")

        def _run():
            try:
                url = f"https://api.github.com/repos/{REPO}/releases/latest"
                req = urllib.request.Request(
                    url, headers={"User-Agent": "FortiProxy/2.0",
                                  "Accept": "application/vnd.github+json"})
                with urllib.request.urlopen(req, timeout=10, context=_SSL_CTX) as r:
                    data = json.loads(r.read())
                latest = data.get("tag_name", "").strip()
                if not latest:
                    raise RuntimeError("No release tag found")

                # Compare V-numbers numerically (V9 → 9, V10 → 10)
                def vnum(s):
                    try: return int(s.lstrip("Vv"))
                    except ValueError: return 0

                if vnum(latest) > vnum(APP_VERSION):
                    asset = next(
                        (a for a in data.get("assets", [])
                         if a.get("name", "").endswith(".zip")),
                        None,
                    )
                    self._update_download_url = (
                        asset["browser_download_url"] if asset else None
                    )
                    msg = f"● {latest} available!"
                    color = "#ffaa00"
                    self._tlog(f"Update available: {latest} (you have {APP_VERSION})", "warn")
                    if hasattr(self, "_install_upd_btn") and self._install_upd_btn.winfo_exists():
                        self.after(0, lambda: self._install_upd_btn.configure(state="normal"))
                else:
                    self._update_download_url = None
                    msg = f"● Up to date ({APP_VERSION})"
                    color = "#00ff88"
                    if hasattr(self, "_install_upd_btn") and self._install_upd_btn.winfo_exists():
                        self.after(0, lambda: self._install_upd_btn.configure(state="disabled"))

                if hasattr(self, "_upd_lbl") and self._upd_lbl.winfo_exists():
                    self.after(0, lambda: self._upd_lbl.configure(text=msg, text_color=color))
            except Exception as e:
                if hasattr(self, "_upd_lbl") and self._upd_lbl.winfo_exists():
                    self.after(0, lambda: self._upd_lbl.configure(
                        text=f"Check failed ({e})", text_color="#ff3355"))

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
                    headers={"User-Agent": "FortiProxy/2.0"},
                )
                with urllib.request.urlopen(req, timeout=300, context=_SSL_CTX) as r:
                    total    = int(r.headers.get("Content-Length", 0))
                    data     = bytearray()
                    last_pct = -1
                    while True:
                        chunk = r.read(131072)
                        if not chunk:
                            break
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

                subprocess.Popen(
                    ["cmd", "/c", str(bat)],
                    cwd=str(tmp),
                    creationflags=0x00000010,  # CREATE_NEW_CONSOLE — shows install window
                )
                self._tlog("Installer launched — FortiProxy will restart", "ok")
                self.after(2000, self._full_quit)

            except Exception as e:
                self._tlog(f"Update failed: {e}", "error")
                if hasattr(self, "_install_upd_btn") and self._install_upd_btn.winfo_exists():
                    self.after(0, lambda: self._install_upd_btn.configure(
                        state="normal", text="↓ Install Update"))

        threading.Thread(target=_run, daemon=True).start()

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
                req = urllib.request.Request(UPDATE_URL, headers={"User-Agent": "FortiProxy/2.0"})
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
                subprocess.Popen(
                    ["cmd", "/c", str(tmp)],
                    cwd=exe_dir,
                    stdin=subprocess.DEVNULL,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    creationflags=0x00000010,
                )
            except Exception:
                pass
        threading.Thread(target=_run, daemon=True).start()

    def _ping_server(self):
        if self._retry_job:
            self.after_cancel(self._retry_job)
            self._retry_job = None
        self._server_dot.configure(text="● CHECKING", text_color="#ffaa00")
        self._refresh_btn.configure(state="disabled")
        self._tlog("Pinging Render server...", "dim")

        def _check():
            try:
                urllib.request.urlopen(
                    urllib.request.Request(SERVER, headers={"User-Agent": "FortiProxy/2.0"}),
                    timeout=12, context=_SSL_CTX,
                )
                self.after(0, lambda: self._server_dot.configure(
                    text="● ONLINE", text_color="#00ff88"))
                self._tlog("Render server is online", "ok")
            except Exception as e:
                self.after(0, lambda: self._server_dot.configure(
                    text="● OFFLINE", text_color="#ff3355"))
                self._tlog(f"Server unreachable ({e}) — retrying in 15s", "warn")
                self._retry_job = self.after(15000, self._ping_server)
            finally:
                self.after(0, lambda: self._refresh_btn.configure(state="normal"))

        threading.Thread(target=_check, daemon=True).start()

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
            req = urllib.request.Request(
                "https://nodejs.org/dist/index.json",
                headers={"User-Agent": "FortiProxy/2.0"},
            )
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
                    if not chunk:
                        break
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
        self._tunnel_dot.configure(text="● CONNECTING", text_color="#ffaa00")

        def _run():
            self._tlog("Checking server...", "dim")
            try:
                urllib.request.urlopen(
                    urllib.request.Request(SERVER, headers={"User-Agent": "FortiProxy/2.0"}),
                    timeout=12, context=_SSL_CTX,
                )
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
                    text=True, bufsize=1, cwd=str(BASE_DIR),
                    **extra,
                )
                self.after(0, self._on_connected)
                for line in self._proc.stdout:
                    line = line.strip()
                    if not line:
                        continue
                    if line.startswith("FORTIPROXY_CMD:"):
                        cmd = line.split(":", 1)[1]
                        self.after(0, lambda c=cmd: self._handle_server_cmd(c))
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
        self._tunnel_dot.configure(text="● CONNECTED", text_color="#00ff88")
        self._stop_btn.configure(state="normal",
                                  fg_color="#5c0000", hover_color="#880000")
        self._log("Tunnel active — traffic routed through Render", "ok")
        self._tick_uptime()
        self._pulse()
        # Update tray icon to green
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
            self._tunnel_dot.configure(text="● BLOCKED", text_color="#ff3355")
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
            self._tunnel_dot.configure(text="● OFFLINE", text_color="#2a2a44")
            self._log("Disconnected — proxy disabled", "warn")
        self._uptime_lbl.configure(text="--:--:--", text_color="#2a2a44")
        self._blocked = False
        self._reset_ui()
        # Update tray icon back to cyan
        if self._tray:
            try: self._tray.icon = _make_tray_image(connected=False)
            except Exception: pass

    def report_callback_exception(self, exc, val, tb):
        try:
            self._disable_proxy()
            if self._proc:
                self._proc.terminate()
            self._tlog(f"Unexpected error: {val}", "error")
        except Exception:
            pass

    def _reset_ui(self):
        self._start_btn.configure(state="normal", text="▶   START")
        self._stop_btn.configure(state="disabled",
                                  fg_color="#1a1a2e", hover_color="#1a1a2e")

    def _tick_uptime(self):
        if not self._connected:
            return
        s = int(time.time() - self._start_time)
        self._uptime_lbl.configure(
            text=f"{s//3600:02d}:{(s%3600)//60:02d}:{s%60:02d}",
            text_color="#00d4ff",
        )
        self.after(1000, self._tick_uptime)

    def _pulse(self):
        if not self._connected:
            return
        self._pulse_on = not self._pulse_on
        self._tunnel_dot.configure(
            text_color="#00ff88" if self._pulse_on else "#006633")
        self._pulse_job = self.after(900, self._pulse)

    def _on_close(self):
        # Minimize to tray instead of quitting (if enabled)
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
    threading.Thread(target=_install_start_menu, daemon=True).start()
    App().mainloop()
