# FortiProxy

Bypasses Fortiguard web filtering on school networks by tunneling traffic through a WebSocket proxy hosted on Render.

## Installation

1. Go to the [Releases](../../releases/latest) page and download `FortiProxy.zip`
2. Extract the zip anywhere (Desktop, Downloads, etc.)
3. Run `install.bat`
4. FortiProxy is now installed — you can delete the zip and extracted folder
5. Search **FortiProxy** in Windows Search to launch it anytime

## Usage

1. Open FortiProxy from Windows Search (or the Start Menu)
2. Wait for the server status to show **ONLINE**
3. Click **START**
4. Browse normally — all traffic is routed through the tunnel
5. Click **DISCONNECT** when done

## How it works

- `install.bat` copies `FortiProxy.exe` to `%APPDATA%\FortiProxy\` and creates a Start Menu shortcut
- The app starts a local proxy on `127.0.0.1:8080` and sets it as the system PAC proxy
- Browser traffic tunnels over WebSocket to a Render server, bypassing Fortiguard

## Stack

- **Client** — Python (CustomTkinter GUI) + Node.js (WebSocket tunnel)
- **Server** — Node.js on Render (WebSocket proxy + admin dashboard)

