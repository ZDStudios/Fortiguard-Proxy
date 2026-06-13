# FortiProxy

Bypasses Fortiguard web filtering on school networks by tunneling traffic through a WebSocket proxy hosted on Render.

## How it works

- The Windows app (`FortiProxy.exe`) starts a local proxy on `127.0.0.1:8080`
- All browser traffic routes through that proxy, which tunnels it over WebSocket to a Render server
- Fortiguard sees WebSocket traffic to a Render domain instead of the blocked site

## Usage

1. Download `FortiProxy.exe`
2. Run it — it appears in Windows Search as **FortiProxy**
3. Click **START**
4. Browse normally; click **DISCONNECT** when done

## Stack

- **Client** — Python (CustomTkinter GUI) + Node.js (WebSocket tunnel)
- **Server** — Node.js on Render (WebSocket proxy + admin dashboard)

## Admin dashboard

Visit the Render server URL and log in to see connected devices and block/unblock them.
