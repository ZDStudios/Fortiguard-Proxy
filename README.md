# FortiProxy

Routes **all** of your traffic through an encrypted tunnel to the hosted proxy at
`proxy.zdstudios.network`, bypassing Fortiguard web filtering — and the network's
DNS — on managed networks.

FortiProxy works like a VPN: it creates a virtual network adapter and sends every
app's traffic (and every DNS lookup) through the tunnel, so the local network
never sees where you're going. Creating that adapter needs administrator rights,
so Windows shows a prompt when you connect. That system-wide routing is what lets
it get past filtering that a browser-only proxy can't.

## Installation

1. Go to the [Releases](../../releases/latest) page and download `FortiProxy.zip`
2. Extract the zip anywhere (Desktop, Downloads, etc.)
3. Run `install.bat` and approve the Windows prompt
4. FortiProxy is now installed — you can delete the zip and extracted folder
5. Search **FortiProxy** in Windows Search to launch it anytime

### If Windows warns about the app

FortiProxy is a new, unsigned program that asks for administrator rights and
creates a network adapter — the same profile as VPN software — so **Windows
SmartScreen or Defender may warn about it or flag it the first time**. This is a
**false positive**: the app isn't malware, it just has no signing certificate yet
(see [Code signing](#code-signing-and-false-positives)).

To run it anyway:

- **SmartScreen** ("Windows protected your PC"): click **More info → Run anyway**.
- **Defender flagged / quarantined it:** open **Windows Security → Virus & threat
  protection → Protection history**, find FortiProxy, and choose **Restore** /
  **Allow on device**. If it won't run, add the install folder
  `%APPDATA%\FortiProxy` as an exclusion under **Virus & threat protection →
  Manage settings → Exclusions**.

## Usage

1. Open FortiProxy from Windows Search (or the Start Menu)
2. Click **Connect** and approve the administrator prompt
3. Wait for it to show **On** — all traffic now goes through the tunnel
4. Browse normally
5. Click **Disconnect** when done — your normal network is restored

## How it works

- FortiProxy is a single Go application (`cmd/client`) with a built-in webview UI.
- On connect it creates a virtual network adapter
  ([sing-tun](https://github.com/sagernet/sing-tun) with a gVisor TCP/IP stack)
  and routes **all** IPv4/IPv6 traffic through it (`AutoRoute` + `StrictRoute`).
  Your real LAN, Tailscale and multicast ranges are excluded so printers,
  casting and file shares keep working.
- **DNS is captured too.** Lookups (port 53) are sent through the tunnel and
  resolved by a public resolver on the far side, so the network's own DNS never
  sees the names you look up. `StrictRoute` stops any lookup leaking around the
  tunnel.
- Traffic rides **4 WebSocket links** to `proxy.zdstudios.network`, each a
  [yamux](https://github.com/hashicorp/yamux)-multiplexed session, so links are
  shared and one stalled request never freezes the others. See `API.md` for the
  protocol.
- Blocking is enforced server-side: if your device is kicked, disabled or banned
  from the proxy's own dashboard, the tunnel is refused and the app shows why.

## Reliability & self-healing

A system-wide tunnel is only dangerous if it's left in place after the app dies —
then apps can lose internet until it's cleared. FortiProxy only ever changes its
own virtual adapter (never the Wi-Fi or Ethernet driver), and has several layers
so a crash can't strand you:

1. **Process-tied adapter** — the adapter, its routes and firewall filters are
   bound to the app's process, so Windows removes them when the process dies.
2. **Watchdog** — a detached second process waits for the app to exit; if it died
   while connected, the watchdog removes anything left behind and flushes DNS.
3. **Launch repair** — if the watchdog was killed too, the app repairs the
   network on its next start.
4. **Fail-safe** — if the server is unreachable for 30 seconds, the tunnel turns
   itself off so your internet keeps working.
5. **Repair button** — Settings → Repair network (and `FortiProxy.exe --repair`)
   clears anything left behind at any time.

## Stack

- **Client + UI** — Go (`cmd/client`, webview), compiled to `FortiProxy.exe`
- **Shared tunnel protocol** — `internal/tunnel`, `internal/proto`
- **Server** — hosted at `proxy.zdstudios.network` (not in this repo; see `API.md`)

## Building from source

You need **Go 1.23+** and a `secrets.env` file. On Windows:

1. Copy `secrets.env.example` to `secrets.env` and set your `PROXY_TOKEN`
   (baked into `FortiProxy.exe` at build time, never committed).
2. Build:
   ```powershell
   .\build.ps1
   ```
   This generates the admin manifest + icon and produces `FortiProxy.exe` in the
   repo root, with the server URL, token and version baked in.

## Releasing a new version

The version lives in `docs/version.txt` (currently **V27**) and is baked into the
exe at build time. A release has two halves, and **both** matter for the
auto-updater (see below):

1. **Build the zip** — on Windows:
   ```
   package.bat
   ```
   Builds `FortiProxy.exe` and produces `FortiProxy-<version>.zip`
   (= `FortiProxy.exe` + `install.bat`), the file users download and extract.

2. **Publish to GitHub** — on Windows:
   ```
   publish.bat
   ```
   Clones the repo, syncs the code, **commits `FortiProxy-<version>.zip` to the
   repo root**, and pushes to `main` — preserving all history.

To cut the version number up, edit only `docs/version.txt`, then repeat the two
steps (the exe picks up the new number automatically).

## How auto-update works

The installed app checks for updates on launch:

- It reads `docs/version.txt` from
  `raw.githubusercontent.com/.../main/docs/version.txt`. If that number is higher
  than the running build, it offers to update.
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

## Code signing and false positives

Because FortiProxy is unsigned, new, and behaves like a VPN (admin + virtual
adapter + routing all traffic), Windows Defender's machine-learning heuristics
and SmartScreen reputation checks sometimes flag a fresh build — usually a generic
`!ml` name like `Wacatac` or `Wacapew`. It is a **false positive**.

The build already avoids the things that make it worse — it is **not** packed
(no UPX), ships full version metadata (company, description, original filename),
and is **not** symbol-stripped. But the only way to actually stop the warnings is:

1. **Code-sign `FortiProxy.exe`** with a certificate. An OV certificate reduces
   detections; an **EV certificate** gives immediate SmartScreen reputation. Sign
   in `build.ps1` after `go build`, e.g.
   `signtool sign /fd SHA256 /tr <timestamp-url> /td SHA256 /a FortiProxy.exe`.
2. **Report false positives to Microsoft** at
   <https://www.microsoft.com/en-us/wdsi/filesubmission> so the specific build is
   allowlisted (needed per build until the exe is signed).

Until the exe is signed, expect to tell users about the warning (see
[If Windows warns about the app](#if-windows-warns-about-the-app)).

## Secrets

`secrets.env` and `API-KEYS.local.md` are git-ignored and must never be
committed. To rotate the token, update `secrets.env`, change the matching value
on the server (Coolify), rebuild, and reinstall.
