/**
 * Vercel-compatible version of the FortiProxy server.
 * Handles control, tunnel, ws-admin and /fetch via noServer WebSocket approach.
 * Note: Vercel free tier has 60s function timeout — control/tunnel WS connections
 * will drop and auto-reconnect (client.js handles this automatically).
 */
const net  = require("net");
const { WebSocket, WebSocketServer } = require("ws");

const TOKEN = process.env.PROXY_TOKEN || "fortiguardsucks!!!";

// ── State (per Vercel instance — stateless across restarts) ───────────────────
const devices      = new Map();
const controls     = new Map();
const blocked      = new Set();
const adminClients = new Set();

function touch(name, ip) {
  const now = new Date().toISOString();
  if (!devices.has(name)) {
    devices.set(name, { device: name, ip, firstSeen: now, lastSeen: now,
                        requests: 0, blocked: false, activeTunnels: 0 });
  } else {
    const d  = devices.get(name);
    d.lastSeen = now;
    d.ip       = ip;
  }
  broadcastToAdmins();
  return devices.get(name);
}

function getDevicesSnapshot() {
  const now    = Date.now();
  const THRESH = 30000;
  return [...devices.values()].map(d => ({
    ...d,
    blocked: blocked.has(d.device),
    online:  !blocked.has(d.device) && (now - new Date(d.lastSeen)) < THRESH,
  }));
}

function broadcastToAdmins() {
  if (!adminClients.size) return;
  const msg = JSON.stringify({ type: "state", devices: getDevicesSnapshot() });
  for (const c of adminClients) {
    if (c.readyState === WebSocket.OPEN) c.send(msg);
  }
}

setInterval(broadcastToAdmins, 5000);

// ── CORS ──────────────────────────────────────────────────────────────────────
function corsHeaders(origin) {
  if (!origin) return {};
  return {
    "Access-Control-Allow-Origin":      origin,
    "Access-Control-Allow-Methods":     "GET, POST, OPTIONS",
    "Access-Control-Allow-Headers":     "Content-Type, Authorization",
    "Access-Control-Allow-Credentials": "true",
  };
}

// ── WebSocket server (noServer mode for Vercel) ───────────────────────────────
const wss = new WebSocketServer({ noServer: true });

wss.on("connection", (ws, req) => {
  const u      = new URL(req.url, "http://localhost");
  const path   = u.pathname;
  const device = u.searchParams.get("device") || "Unknown";
  const ip     = (req.headers["x-forwarded-for"] || req.socket.remoteAddress || "?")
                   .split(",")[0].trim();

  if (TOKEN && u.searchParams.get("token") !== TOKEN) {
    ws.close(4001, "Unauthorized"); return;
  }

  // ── Control ────────────────────────────────────────────────────────────────
  if (path === "/control") {
    touch(device, ip);
    controls.set(device, ws);
    if (blocked.has(device)) ws.send(JSON.stringify({ cmd: "block" }));

    ws.on("message", data => {
      try {
        const msg = JSON.parse(data.toString());
        if (msg.type === "ping") {
          touch(device, ip);
          ws.send(JSON.stringify({ type: "pong" }));
        }
      } catch {}
    });
    ws.on("close", () => { if (controls.get(device) === ws) controls.delete(device); });
    ws.on("error", () => {});
    return;
  }

  // ── WebSocket admin (GitHub Pages dashboard) ───────────────────────────────
  if (path === "/ws-admin") {
    adminClients.add(ws);
    ws.send(JSON.stringify({ type: "state", devices: getDevicesSnapshot() }));

    ws.on("message", data => {
      try {
        const msg  = JSON.parse(data.toString());
        const name = msg.device || "";
        if (msg.cmd === "block") {
          blocked.add(name);
          if (devices.has(name)) devices.get(name).blocked = true;
          const ctrl = controls.get(name);
          if (ctrl && ctrl.readyState === WebSocket.OPEN)
            ctrl.send(JSON.stringify({ cmd: "block" }));
          broadcastToAdmins();
        } else if (msg.cmd === "unblock") {
          blocked.delete(name);
          if (devices.has(name)) devices.get(name).blocked = false;
          const ctrl = controls.get(name);
          if (ctrl && ctrl.readyState === WebSocket.OPEN)
            ctrl.send(JSON.stringify({ cmd: "unblock" }));
          broadcastToAdmins();
        }
      } catch {}
    });
    ws.on("close", () => adminClients.delete(ws));
    ws.on("error", () => adminClients.delete(ws));
    return;
  }

  // ── Tunnel ─────────────────────────────────────────────────────────────────
  if (path === "/tunnel") {
    if (blocked.has(device)) { ws.close(4403, "Blocked"); return; }
    ws.once("message", initData => {
      let host, port;
      try {
        const msg = JSON.parse(initData.toString());
        host = msg.host;
        port = parseInt(msg.port, 10) || 80;
      } catch { ws.close(4002, "Bad init"); return; }
      if (!host) { ws.close(4002, "Missing host"); return; }

      const info   = touch(device, ip);
      info.requests++;
      info.activeTunnels = (info.activeTunnels || 0) + 1;

      const queued   = [];
      let   tcpReady = false;
      const socket   = net.connect(port, host);

      ws.on("message", data => {
        if (socket.destroyed) return;
        if (tcpReady) socket.write(data);
        else queued.push(data);
      });
      socket.on("connect", () => {
        tcpReady = true;
        for (const d of queued) socket.write(d);
        queued.length = 0;
      });
      socket.on("data", data => { if (ws.readyState === WebSocket.OPEN) ws.send(data); });

      const cleanup = () => {
        info.activeTunnels = Math.max(0, (info.activeTunnels || 1) - 1);
        broadcastToAdmins();
      };
      socket.on("error", () => { cleanup(); ws.close(4003, "Socket error"); });
      socket.on("close", () => { cleanup(); ws.terminate(); });
      ws.on("close",     () => { cleanup(); socket.destroy(); });
      ws.on("error",     () => { cleanup(); socket.destroy(); });
    });
    return;
  }

  ws.close(4004, "Unknown path");
});

// ── HTTP handler ──────────────────────────────────────────────────────────────
async function handleHTTP(req, res) {
  const u        = new URL(req.url, "http://localhost");
  const pathname = u.pathname;
  const origin   = req.headers.origin || "";
  const cors     = corsHeaders(origin);

  if (req.method === "OPTIONS") {
    res.writeHead(204, cors); res.end(); return;
  }

  // Health check
  if (pathname === "/" || pathname === "/health") {
    res.writeHead(200, { "Content-Type": "application/json", ...cors });
    res.end(JSON.stringify({ ok: true, server: "vercel" }));
    return;
  }

  // Devices list
  if (pathname === "/api/devices" && req.method === "GET") {
    const token = u.searchParams.get("token") || req.headers["x-token"] || "";
    if (TOKEN && token !== TOKEN) {
      res.writeHead(401, { "Content-Type": "application/json", ...cors });
      res.end(JSON.stringify({ error: "Unauthorized" }));
      return;
    }
    res.writeHead(200, { "Content-Type": "application/json", ...cors });
    res.end(JSON.stringify(getDevicesSnapshot()));
    return;
  }

  // Block / unblock
  if ((pathname === "/api/block" || pathname === "/api/unblock") && req.method === "POST") {
    let body = "";
    req.on("data", d => body += d.toString());
    req.on("end", () => {
      let b = {};
      try { b = JSON.parse(body); } catch {}
      const token = b.token || req.headers["x-token"] || "";
      if (TOKEN && token !== TOKEN) {
        res.writeHead(401, { "Content-Type": "application/json", ...cors });
        res.end(JSON.stringify({ error: "Unauthorized" }));
        return;
      }
      const name = b.device || "";
      if (pathname === "/api/block") {
        blocked.add(name);
        if (devices.has(name)) devices.get(name).blocked = true;
        const ctrl = controls.get(name);
        if (ctrl && ctrl.readyState === WebSocket.OPEN)
          ctrl.send(JSON.stringify({ cmd: "block" }));
      } else {
        blocked.delete(name);
        if (devices.has(name)) devices.get(name).blocked = false;
        const ctrl = controls.get(name);
        if (ctrl && ctrl.readyState === WebSocket.OPEN)
          ctrl.send(JSON.stringify({ cmd: "unblock" }));
      }
      broadcastToAdmins();
      res.writeHead(200, { "Content-Type": "application/json", ...cors });
      res.end(JSON.stringify({ ok: true }));
    });
    return;
  }

  // /fetch — MITM proxy
  if (pathname === "/fetch" && req.method === "POST") {
    let body = "";
    req.on("data", d => body += d.toString());
    req.on("end", async () => {
      try {
        const { url, method = "GET", headers = {}, body: fetchBody, token } = JSON.parse(body);
        if (TOKEN && token !== TOKEN) {
          res.writeHead(401, { "Content-Type": "application/json", ...cors });
          res.end(JSON.stringify({ error: "Unauthorized" }));
          return;
        }
        if (!url) {
          res.writeHead(400, { "Content-Type": "application/json", ...cors });
          res.end(JSON.stringify({ error: "Missing url" }));
          return;
        }
        const resp     = await fetch(url, { method, headers, body: fetchBody || undefined });
        const text     = await resp.text();
        const respHdrs = {};
        resp.headers.forEach((v, k) => { respHdrs[k] = v; });
        res.writeHead(200, { "Content-Type": "application/json", ...cors });
        res.end(JSON.stringify({ status: resp.status, statusText: resp.statusText,
                                 headers: respHdrs, body: text }));
      } catch (e) {
        res.writeHead(500, { "Content-Type": "application/json", ...cors });
        res.end(JSON.stringify({ error: e.message }));
      }
    });
    return;
  }

  res.writeHead(200, { "Content-Type": "application/json", ...cors });
  res.end(JSON.stringify({ ok: true, server: "vercel" }));
}

// ── Vercel export: handle both HTTP and WebSocket upgrades ─────────────────────
module.exports = function handler(req, res) {
  if (req.headers.upgrade && req.headers.upgrade.toLowerCase() === "websocket") {
    wss.handleUpgrade(req, req.socket, Buffer.alloc(0), ws => {
      wss.emit("connection", ws, req);
    });
  } else {
    handleHTTP(req, res);
  }
};
