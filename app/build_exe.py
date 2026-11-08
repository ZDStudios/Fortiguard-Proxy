"""Builds FortiProxy.exe using PyInstaller. Run via build.bat.

Bundles the Go tunnel client (fortiproxy-client.exe). If that exe is missing,
this script builds it first by calling client/build.ps1, which reads your token
from secrets.env.
"""
import subprocess
import sys
import shutil
from pathlib import Path

app_dir    = Path(__file__).parent
root       = app_dir.parent
client_dir = root / "client"
out_dir    = root  # EXE lands in project root

CLIENT_EXE = root / "fortiproxy-client.exe"


def add_data(src: Path, dest: str) -> list:
    return ["--add-data", f"{src};{dest}"]


# ── Step 1: ensure the Go client exe exists (build it if not) ────────────────
if not CLIENT_EXE.exists():
    print("[FortiProxy] fortiproxy-client.exe not found — building it...")
    r = subprocess.run(
        ["powershell", "-ExecutionPolicy", "Bypass", "-File",
         str(client_dir / "build.ps1")],
        cwd=str(client_dir),
    )
    if r.returncode != 0 or not CLIENT_EXE.exists():
        print("[ERROR] Failed to build fortiproxy-client.exe")
        print("        Make sure Go is installed (winget install GoLang.Go) and")
        print("        secrets.env exists in the project root with PROXY_TOKEN set.")
        sys.exit(1)
    print("[FortiProxy] Go client built")

# ── Step 2: build EXE with the Go client bundled inside ──────────────────────
icon_path = root / "icon.ico"

args = [
    sys.executable, "-m", "PyInstaller",
    "--onefile",
    "--windowed",
    "--collect-all", "customtkinter",
    "--collect-all", "pystray",
    "--collect-all", "PIL",
    "--hidden-import", "pystray._win32",
    "--hidden-import", "PIL._tkinter_finder",
    *add_data(CLIENT_EXE,              "."),
    *add_data(client_dir / "proxy.pac", "."),
    "--icon",      str(icon_path),
    "--name",      "FortiProxy",
    "--distpath",  str(out_dir),
    "--workpath",  str(app_dir / "build"),
    "--specpath",  str(app_dir),
    str(app_dir / "dashboard.py"),
]

print("[FortiProxy] Running PyInstaller...")
result = subprocess.run(args)

# ── Step 3: clean build artefacts ─────────────────────────────────────────────
build_dir = app_dir / "build"
spec_file = app_dir / "FortiProxy.spec"
if build_dir.exists():
    shutil.rmtree(build_dir)
if spec_file.exists():
    spec_file.unlink()

sys.exit(result.returncode)
