"""Builds FortiProxy.exe using PyInstaller. Run via build.bat."""
import subprocess
import sys
import shutil
from pathlib import Path

app_dir    = Path(__file__).parent
client_dir = app_dir.parent / "client"
out_dir    = app_dir.parent  # EXE lands in project root

def add_data(src: Path, dest: str) -> list:
    return ["--add-data", f"{src};{dest}"]

# ── Step 1: npm install in client/ so we can bundle node_modules/ws ──────────
ws_dir = client_dir / "node_modules" / "ws"
if not ws_dir.exists():
    print("[FortiProxy] Running npm install in client/ to bundle ws...")
    r = subprocess.run("npm install", cwd=str(client_dir), shell=True)
    if r.returncode != 0:
        print("[ERROR] npm install failed")
        sys.exit(1)
    print("[FortiProxy] npm install done")

# ── Step 2: build EXE with node_modules/ws bundled inside ────────────────────
icon_path = app_dir.parent / "icon.ico"

args = [
    sys.executable, "-m", "PyInstaller",
    "--onefile",
    "--windowed",
    "--collect-all", "customtkinter",
    *add_data(client_dir / "client.js",             "."),
    *add_data(client_dir / "proxy.pac",             "."),
    *add_data(client_dir / "package.json",          "."),
    *add_data(client_dir / "node_modules" / "ws",   "node_modules/ws"),
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
