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
import os
import sys
import shutil
import time
import base64
from datetime import datetime
from pathlib import Path

# SSL context that skips cert verification — handles school HTTPS inspection (MITM)
_SSL_CTX = ssl.create_default_context()
_SSL_CTX.check_hostname = False
_SSL_CTX.verify_mode    = ssl.CERT_NONE

ctk.set_appearance_mode("dark")
ctk.set_default_color_theme("blue")

REG_PATH  = r"Software\Microsoft\Windows\CurrentVersion\Internet Settings"
SERVER    = "https://fortiguard-proxy.onrender.com"
NODE_DIR  = Path(os.environ.get("APPDATA", Path.home())) / "FortiProxy" / "nodejs"
NODE_EXE  = NODE_DIR / "node.exe"


UPDATE_URL = "https://zdstudios.github.io/Fortiguard-Proxy/update.bat"


def _install_start_menu():

    """Always rewrite the Start Menu shortcut to the current EXE path.
    This self-heals if the EXE is moved to a new folder."""
    if not getattr(sys, "frozen", False):
        return
    lnk  = (Path(os.environ.get("APPDATA", Path.home()))
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
    """Return directory containing client.js, proxy.pac, package.json."""
    if getattr(sys, "frozen", False):
        # Compiled EXE: extract bundled files to %APPDATA%\FortiProxy
        work = Path(os.environ.get("APPDATA", Path.home())) / "FortiProxy"
        work.mkdir(exist_ok=True)
        src = Path(sys._MEIPASS)

        # Copy flat files (always refresh so updates apply)
        for fname in ("client.js", "proxy.pac", "package.json"):
            s = src / fname
            if s.exists():
                shutil.copy2(s, work / fname)

        # Copy bundled node_modules/ws if not already extracted
        src_ws = src / "node_modules" / "ws"
        dst_ws = work / "node_modules" / "ws"
        if src_ws.exists() and not dst_ws.exists():
            shutil.copytree(src_ws, dst_ws)

        return work
    else:
        # Running as script: client/ is one level up from app/
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

        self._proc       = None
        self._connected  = False
        self._start_time = None
        self._pulse_job  = None
        self._pulse_on   = False
        self._closing    = False
        self._blocked    = False
        self._retry_job  = None

        self._build_ui()
        self.protocol("WM_DELETE_WINDOW", self._on_close)
        self._log("Dashboard ready", "dim")
        self._ping_server()
        self.after(1500, self._check_update)

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

        self._refresh_btn = ctk.CTkButton(
            hdr, text="↻", width=34, height=34,
            font=ctk.CTkFont("Consolas", 16),
            fg_color="#151528", hover_color="#1f1f3a",
            corner_radius=8, command=self._ping_server,
        )
        self._refresh_btn.pack(side="right", padx=14)

        ctk.CTkLabel(
            hdr, text="v2.0  ",
            font=ctk.CTkFont("Consolas", 11),
            text_color="#22223a",
        ).pack(side="right")

        card = ctk.CTkFrame(self, fg_color="#0d0d1e", corner_radius=14)
        card.pack(fill="x", padx=18, pady=(14, 6))

        self._server_dot = self._srow(card, "RENDER SERVER", "● CHECKING", "#ffaa00")
        self._sep(card)
        self._tunnel_dot = self._srow(card, "TUNNEL",        "● OFFLINE",  "#2a2a44")
        self._sep(card)
        self._uptime_lbl = self._srow(card, "UPTIME",        "--:--:--",        "#2a2a44", bold=False)

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
                    creationflags=0x00000010,  # CREATE_NEW_CONSOLE — allows GUI popups
                )
            except Exception:
                pass
        threading.Thread(target=_run, daemon=True).start()

    def _ping_server(self):
        # Cancel any pending auto-retry before starting a fresh ping
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
                # Auto-retry: Render spins down idle servers, cold start takes ~20-30s
                self._retry_job = self.after(15000, self._ping_server)
            finally:
                self.after(0, lambda: self._refresh_btn.configure(state="normal"))

        threading.Thread(target=_check, daemon=True).start()

    # ── Proxy ─────────────────────────────────────────────────────────────────

    def _refresh_proxy(self):
        # Tell Windows/Chrome to immediately re-read proxy settings from the registry
        try:
            _wininet = ctypes.windll.Wininet
            _wininet.InternetSetOptionW(0, 39, 0, 0)  # INTERNET_OPTION_SETTINGS_CHANGED
            _wininet.InternetSetOptionW(0, 37, 0, 0)  # INTERNET_OPTION_REFRESH
        except Exception:
            pass

    def _enable_proxy(self):
        # Direct proxy — avoids file:// PAC URL which Chrome on managed machines blocks
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
        """Return path to node.exe, downloading portable LTS if not found."""
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
                self.after(0, self._on_disconnected)
            except Exception as e:
                self._tlog(f"Error starting proxy: {e}", "error")
                self.after(0, self._reset_ui)

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

    def _handle_server_cmd(self, cmd):
        if cmd == "block":
            self._blocked   = True
            self._connected = False  # stop pulse immediately so it can't overwrite red
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
        self._closing   = True
        self._connected = False
        if self._pulse_job:
            self.after_cancel(self._pulse_job)
        if self._retry_job:
            self.after_cancel(self._retry_job)
        if self._proc:
            self._proc.terminate()
        self._disable_proxy()
        self.destroy()


if __name__ == "__main__":
    threading.Thread(target=_install_start_menu, daemon=True).start()
    App().mainloop()
