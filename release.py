"""
Build FortiProxy, zip it with install.bat, and publish a GitHub release.

Usage:
    python release.py          # auto-increments version (V7 → V8)
    python release.py V9       # explicit version

Requires GITHUB_TOKEN env var (repo scope) or will prompt for it.
"""
import sys
import os
import subprocess
import zipfile
import json
import urllib.request
import urllib.error
from pathlib import Path

ROOT = Path(__file__).parent
REPO = "ZDStudios/Fortiguard-Proxy"


def _next_version():
    out = subprocess.run(
        ["git", "tag", "--sort=-version:refname"],
        capture_output=True, text=True, cwd=str(ROOT),
    ).stdout
    tags = [t.strip() for t in out.splitlines() if t.strip().upper().startswith("V")]
    if not tags:
        return "V1"
    try:
        return f"V{int(tags[0][1:]) + 1}"
    except ValueError:
        return "V1"


def _build():
    print("[release] Building EXE...")
    # Kill any running FortiProxy/node so the EXE isn't locked
    subprocess.run(
        ["powershell", "-Command",
         "Stop-Process -Name FortiProxy,node -Force -ErrorAction SilentlyContinue"],
        capture_output=True,
    )
    r = subprocess.run([sys.executable, "app/build_exe.py"], cwd=str(ROOT))
    if r.returncode != 0:
        print("[ERROR] Build failed — aborting release")
        sys.exit(1)
    print("[release] EXE built")


def _zip(version: str) -> Path:
    exe = ROOT / "FortiProxy.exe"
    bat = ROOT / "install.bat"
    for f in (exe, bat):
        if not f.exists():
            print(f"[ERROR] Missing: {f}")
            sys.exit(1)
    zip_path = ROOT / f"FortiProxy-{version}.zip"
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.write(exe, "FortiProxy.exe")
        zf.write(bat, "install.bat")
    print(f"[release] Zip: {zip_path.name} ({zip_path.stat().st_size // 1024} KB)")
    return zip_path


def _token() -> str:
    t = os.environ.get("GITHUB_TOKEN", "").strip()
    if not t:
        t = input("GitHub personal access token (repo scope): ").strip()
    return t


def _api(method: str, url: str, token: str, data=None, content_type="application/json"):
    req = urllib.request.Request(
        url, data=data, method=method,
        headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
            "Content-Type": content_type,
        },
    )
    try:
        with urllib.request.urlopen(req) as resp:
            return json.loads(resp.read())
    except urllib.error.HTTPError as e:
        print(f"[ERROR] GitHub API {e.code}: {e.read().decode()}")
        sys.exit(1)


def _create_release(version: str, token: str) -> str:
    print(f"[release] Creating GitHub release {version}...")
    data = json.dumps({
        "tag_name": version,
        "name": f"FortiProxy {version}",
        "body": (
            f"## Installation\n\n"
            f"1. Download **FortiProxy-{version}.zip** below\n"
            f"2. Extract the zip anywhere\n"
            f"3. Run **install.bat**\n"
            f"4. Search **FortiProxy** in Windows Search to launch"
        ),
        "draft": False,
        "prerelease": False,
    }).encode()
    result = _api("POST", f"https://api.github.com/repos/{REPO}/releases", token, data)
    # upload_url is a URI template like ...assets{?name,label} — strip the template part
    return result["upload_url"].split("{")[0]


def _upload(upload_url: str, zip_path: Path, token: str):
    url = f"{upload_url}?name={zip_path.name}"
    print(f"[release] Uploading {zip_path.name}...")
    result = _api("POST", url, token, zip_path.read_bytes(), "application/zip")
    print(f"[release] Download URL: {result['browser_download_url']}")


if __name__ == "__main__":
    version = sys.argv[1].strip() if len(sys.argv) > 1 else _next_version()
    print(f"[release] Version: {version}")

    _build()
    zip_path = _zip(version)
    token    = _token()
    upload_url = _create_release(version, token)
    _upload(upload_url, zip_path, token)

    zip_path.unlink(missing_ok=True)  # clean up local zip
    print(f"\n[release] FortiProxy {version} is live on GitHub Releases.")
