"""Builds FortiProxy.exe using PyInstaller. Run via build.bat."""
import subprocess
import sys
from pathlib import Path

app_dir    = Path(__file__).parent
client_dir = app_dir.parent / "client"
out_dir    = app_dir.parent  # EXE lands in project root

def add_data(src: Path, dest: str) -> list:
    return ["--add-data", f"{src};{dest}"]

args = [
    sys.executable, "-m", "PyInstaller",
    "--onefile",
    "--windowed",
    "--collect-all", "customtkinter",
    *add_data(client_dir / "client.js",   "."),
    *add_data(client_dir / "proxy.pac",   "."),
    *add_data(client_dir / "package.json","."),
    "--name",      "FortiProxy",
    "--distpath",  str(out_dir),
    "--workpath",  str(app_dir / "build"),
    "--specpath",  str(app_dir),
    str(app_dir / "dashboard.py"),
]

print("[FortiProxy] Running PyInstaller...")
result = subprocess.run(args)

# Clean build artefacts
import shutil
build_dir = app_dir / "build"
spec_file = app_dir / "FortiProxy.spec"
if build_dir.exists():
    shutil.rmtree(build_dir)
if spec_file.exists():
    spec_file.unlink()

sys.exit(result.returncode)
