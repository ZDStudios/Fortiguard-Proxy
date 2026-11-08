# FortiProxy

Routes your traffic through an encrypted tunnel to the hosted proxy at
`proxy.zdstudios.network`, bypassing Fortiguard web filtering on managed
networks.

## Installation

1. Go to the [Releases](../../releases/latest) page and download `FortiProxy.zip`
2. Extract the zip anywhere (Desktop, Downloads, etc.)
3. Run `install.bat`
4. FortiProxy is now installed — you can delete the zip and extracted folder
5. Search **FortiProxy** in Windows Search to launch it anytime

## Usage

1. Open FortiProxy from Windows Search (or the Start Menu)
2. Wait for the **Server** tile to show **Online**
3. Click **Connect**
4. Browse normally — all traffic is routed through the tunnel
5. Click **Disconnect** when done

## How it works

- `install.bat` copies `FortiProxy.exe` to `%APPDATA%\FortiProxy\` and creates a
  Start Menu shortcut.
- The app launches `fortiproxy-client.exe`, which opens a local HTTP proxy on
  `127.0.0.1:8080` (and a SOCKS5 proxy on `127.0.0.1:1080`), then sets the HTTP
  proxy as the Windows system proxy.
- The client keeps **4 WebSocket links** open to `proxy.zdstudios.network`, each
  carrying a [yamux](https://github.com/hashicorp/yamux)-multiplexed session.
  Every browser connection becomes one stream, so the links are shared and one
  stalled request never freezes the others. See `API.md` for the full protocol.
- Blocking is enforced server-side: if your device is kicked, disabled or
  banned from the proxy's own dashboard, the tunnel is refused and the app shows
  the reason.

## Reliability & self-healing

A system-wide proxy is only dangerous if it's left pointing at a dead local
port — then every app loses internet until it's cleared. FortiProxy has several
independent layers so that can't happen, even after a hard crash:

1. **Panic isolation** — each connection runs with its own recovery, so one bad
   request can never take the whole client down.
2. **Clean-exit cleanup** — the client clears the system proxy on any normal
   exit, Ctrl-C/close, or panic.
3. **Guardian process** — the client launches a detached watchdog. If the client
   dies hard (crash, `taskkill /F`, power event) and nothing is listening on
   `127.0.0.1:8080`, the guardian clears the proxy.
4. **App-side poll** — the desktop app checks every 2 seconds; if the proxy is
   set to our port but the client isn't running, it clears it and resets.
5. **Auto-restart** — if the client stops unexpectedly while connected, the app
   restarts it (up to 5 times with backoff).
6. **Launch heal** — every time FortiProxy starts, it clears any leftover proxy
   and kills any stale listener, so a bad previous session is undone on open.
   (Combined with "Start on boot", a reboot fully recovers the machine.)

The proxy is only ever cleared when it still points at FortiProxy, so an
unrelated proxy you configured yourself is never touched.

## Stack

- **Client** — Go (`client/`), compiled to `fortiproxy-client.exe`
- **Desktop app** — Python (CustomTkinter GUI, `app/`)
- **Server** — hosted at `proxy.zdstudios.network` (not in this repo; see `API.md`)

## Building from source

A prebuilt `fortiproxy-client.exe` is already in the project root, so you can
skip straight to step 3. To rebuild the client yourself you need **Python 3**,
**Go 1.23+**, and a `secrets.env` file.

1. Copy `secrets.env.example` to `secrets.env` and set your `PROXY_TOKEN`
   (this is baked into the client exe at build time and never committed).
2. Build the Go tunnel client:
   ```powershell
   cd client
   .\build.ps1
   ```
   This produces `fortiproxy-client.exe` in the project root.
3. Build the Windows app (bundles the client exe):
   ```
   app\build.bat
   ```
   `FortiProxy.exe` lands in the project root.

To run the app without building an exe (for development):
```
launch.bat
```
(Build the Go client first, or **Connect** won't work.)

## Releasing a new version

The version string lives in `docs/version.txt` (currently **V26**). A release has
two halves, and **both** matter for the auto-updater (see below):

1. **Build the zip** — on Windows:
   ```
   package.bat
   ```
   Builds `FortiProxy.exe` (and the Go client) and produces
   `FortiProxy-<version>.zip` (= `FortiProxy.exe` + `install.bat`), the file users
   download and extract.

2. **Publish to GitHub** — on Windows:
   ```
   publish.bat
   ```
   Clones the repo, syncs the code, **commits `FortiProxy-<version>.zip` to the
   repo root**, and pushes to `main` — preserving all history.

To cut the version number up, edit `docs/version.txt` and bump `APP_VERSION` in
`app/dashboard.py` to match, then repeat the two steps. `release.py` additionally
publishes to the GitHub Releases page (needs `GITHUB_TOKEN`), but that's optional
and separate from the auto-updater.

## How auto-update works

The installed app checks for updates on launch:

- It reads `docs/version.txt` from
  `raw.githubusercontent.com/.../main/docs/version.txt`. If that number is higher
  than its own `APP_VERSION`, an update is available.
- It downloads `raw.githubusercontent.com/.../main/FortiProxy-<version>.zip`,
  extracts it, and runs the bundled `install.bat`, which replaces the exe and
  relaunches.

**This is why the release zip is committed to the repo root (and why
`FortiProxy-V*.zip` is _not_ git-ignored).** If the zip is only on the Releases
page, older installs can't find it. Every release must push both the bumped
`docs/version.txt` and the matching `FortiProxy-<version>.zip` to `main` — which
is exactly what `publish.bat` does.

Note: the shipped exe contains the (obfuscated) proxy token by design — it's the
app users run. Treat every published build as carrying that shared secret, as
`API.md` explains.

## Secrets

`secrets.env` and `API-KEYS.local.md` are git-ignored and must never be
committed. The proxy token is at least 32 characters; the dashboard password is
at least 8. To rotate them, update `secrets.env`, change the matching values on
the server (Coolify), rebuild, and reinstall on every device.
