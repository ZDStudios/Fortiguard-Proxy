'use strict';
const http   = require("http");
const net    = require("net");
const crypto = require("crypto");
const { WebSocket, WebSocketServer } = require("ws");

const PORT        = process.env.PORT        || 8080;
const PROXY_TOKEN = process.env.PROXY_TOKEN || "";
const ADMIN_TOKEN = process.env.ADMIN_TOKEN || PROXY_TOKEN;

if (!process.env.ADMIN_TOKEN) {
  console.log("[security] WARNING: ADMIN_TOKEN env var not set — set it separately from PROXY_TOKEN for full admin isolation.");
}

// ── Layer 4: Rate limiting ─────────────────────────────────────────────────────
const _rates  = new Map();   // ip → { count, resetAt }
const _nonces = new Set();   // Layer 5: used nonces for replay prevention

setInterval(() => _nonces.clear(), 60_000);
setInterval(() => { const n = Date.now(); for (const [k,v] of _rates) if (n > v.resetAt) _rates.delete(k); }, 120_000);

function _rateFail(ip) {
  const now = Date.now();
  let e = _rates.get(ip);
  if (!e || now > e.resetAt) { e = { count: 0, resetAt: now + 60_000 }; _rates.set(ip, e); }
  e.count++;
  if (e.count > 10) console.log(`[security] Rate limit exceeded: ${ip}`);
}

function _isRateLimited(ip) {
  const e = _rates.get(ip);
  return !!(e && Date.now() <= e.resetAt && e.count > 10);
}

// ── Layer 2: HMAC verification for proxy connections ───────────────────────────
function _verifyHmac(secret, sig, ts, device, nonce) {
  try {
    if (!secret || !sig || !ts || !nonce) return false;
    if (Math.abs(Date.now() - parseInt(ts, 10)) > 60_000) return false;
    if (_nonces.has(nonce)) return false;
    const expected = crypto.createHmac("sha256", secret)
      .update(`${ts}:${device}:${nonce}`).digest("hex");
    if (sig.length !== expected.length) return false;
    const ok = crypto.timingSafeEqual(Buffer.from(sig, "hex"), Buffer.from(expected, "hex"));
    if (ok) _nonces.add(nonce);
    return ok;
  } catch { return false; }
}

// ── Lockdown mode (server shutdown from dashboard) ─────────────────────────────
let _locked = false;

// ── State ─────────────────────────────────────────────────────────────────────
const devices      = new Map();
const controls     = new Map();
const blocked      = new Set();
const adminClients = new Set();

function touch(name, ip) {
  const now = new Date().toISOString();
  if (!devices.has(name)) {
    console.log(`[device] NEW: ${name} from ${ip}`);
    devices.set(name, { device: name, ip, firstSeen: now, lastSeen: now,
                        requests: 0, blocked: false, activeTunnels: 0 });
  } else {
    const d = devices.get(name); d.lastSeen = now; d.ip = ip;
  }
  broadcastToAdmins();
  return devices.get(name);
}

function getDevicesSnapshot() {
  const now = Date.now(), THRESH = 30000;
  return [...devices.values()].map(d => ({
    ...d,
    blocked: blocked.has(d.device),
    online:  !blocked.has(d.device) && (now - new Date(d.lastSeen)) < THRESH,
  }));
}

function broadcastToAdmins() {
  if (!adminClients.size) return;
  const msg = JSON.stringify({ type: "state", devices: getDevicesSnapshot(), locked: _locked });
  for (const c of adminClients) if (c.readyState === WebSocket.OPEN) c.send(msg);
}

setInterval(broadcastToAdmins, 5000);

// ── Auth helpers (legacy Render dashboard — uses ADMIN_TOKEN) ──────────────────
function parseCookies(req) {
  const out = {};
  (req.headers.cookie || "").split(";").forEach(pair => {
    const eq = pair.indexOf("=");
    if (eq < 0) return;
    out[pair.slice(0, eq).trim()] = pair.slice(eq + 1).trim();
  });
  return out;
}
function isAdminAuthed(req) {
  if (!ADMIN_TOKEN) return true;
  return parseCookies(req).fp_auth === ADMIN_TOKEN;
}
function setCookie(res, v) {
  res.setHeader("Set-Cookie", `fp_auth=${encodeURIComponent(v)}; HttpOnly; Path=/; Max-Age=86400; SameSite=Lax`);
}
function clearCookie(res) {
  res.setHeader("Set-Cookie", "fp_auth=; HttpOnly; Path=/; Max-Age=0");
}

// ── CORS ───────────────────────────────────────────────────────────────────────
function corsHeaders(origin) {
  if (!origin) return {};
  return {
    "Access-Control-Allow-Origin":      origin,
    "Access-Control-Allow-Methods":     "GET, POST, OPTIONS",
    "Access-Control-Allow-Headers":     "Content-Type, Authorization",
    "Access-Control-Allow-Credentials": "true",
  };
}

// ── HTML helpers ───────────────────────────────────────────────────────────────
function esc(s) {
  return String(s).replace(/&/g,"&amp;").replace(/</g,"&lt;").replace(/>/g,"&gt;").replace(/"/g,"&quot;");
}
function ago(ts) {
  const s = Math.floor((Date.now() - new Date(ts)) / 1000);
  if (s < 5) return "just now";
  if (s < 60) return s + "s ago";
  if (s < 3600) return Math.floor(s/60) + "m ago";
  return Math.floor(s/3600) + "h ago";
}
function buildRows(devArr) {
  if (!devArr.length) return `<tr><td colspan="6" class="empty">No devices connected yet</td></tr>`;
  const THRESH = 30000, now = Date.now();
  return devArr.sort((a,b)=>{
    const ao = !a.blocked && (now-new Date(a.lastSeen))<THRESH;
    const bo = !b.blocked && (now-new Date(b.lastSeen))<THRESH;
    return ao!==bo ? bo-ao : new Date(b.lastSeen)-new Date(a.lastSeen);
  }).map(d => {
    const online = !d.blocked && (now-new Date(d.lastSeen))<THRESH;
    let st, act;
    if (d.blocked) {
      st  = `<span class="dot-r">&#9679;</span><span class="badge badge-blocked">BLOCKED</span>`;
      act = `<button class="unblock-btn" onclick="doUnblock('${esc(d.device)}')">UNBLOCK</button>`;
    } else if (online) {
      st  = `<span class="dot-g blink">&#9679;</span><span class="badge badge-live">ONLINE</span>`;
      act = `<button class="block-btn"   onclick="doBlock('${esc(d.device)}')">BLOCK</button>`;
    } else {
      st  = `<span class="dot-d">&#9679;</span><span class="badge badge-idle">OFFLINE</span>`;
      act = `<button class="block-btn"   onclick="doBlock('${esc(d.device)}')">BLOCK</button>`;
    }
    return `<tr><td>${st}</td><td class="dev">${esc(d.device)}</td><td class="ip">${esc(d.ip)}</td>
      <td class="dim">${d.requests}</td><td class="dim">${ago(d.lastSeen)}</td><td>${act}</td></tr>`;
  }).join("");
}

const CSS = `*{box-sizing:border-box;margin:0;padding:0}body{background:#08080f;color:#aaaacc;font-family:Consolas,'Courier New',monospace;min-height:100vh;display:flex;flex-direction:column}.hdr{background:#04040c;padding:16px 28px;border-bottom:1px solid #111128;display:flex;align-items:center;justify-content:space-between}.hdr h1{color:#00d4ff;font-size:1.2em;letter-spacing:3px}.hdr-r{display:flex;align-items:center;gap:16px}.meta{color:#222244;font-size:.75em}.btn-sm{background:transparent;border:1px solid #1e1e3a;border-radius:6px;padding:4px 12px;color:#444466;font-family:Consolas,monospace;font-size:.75em;cursor:pointer;text-decoration:none;display:inline-block}.btn-sm:hover{border-color:#ff3355;color:#ff3355}.stats{display:flex;gap:1px;background:#111128}.stat{flex:1;background:#0a0a18;padding:18px 28px}.sv{font-size:1.9em;font-weight:bold;color:#00d4ff}.sl{color:#333355;font-size:.7em;letter-spacing:2px;margin-top:4px}.wrap{padding:22px 28px;flex:1}.stitle{color:#222244;font-size:.7em;letter-spacing:3px;margin-bottom:14px}.err-bar{color:#ff3355;font-size:.75em;padding:8px 0;min-height:22px}table{width:100%;border-collapse:collapse}thead th{text-align:left;padding:10px 14px;color:#333355;font-size:.7em;letter-spacing:2px;border-bottom:1px solid #111128}tbody tr:hover{background:#0d0d1e}tbody td{padding:11px 14px;border-bottom:1px solid #0d0d1e;font-size:.87em;vertical-align:middle}.dot-g{color:#00ff88}.dot-r{color:#ff3355}.dot-d{color:#333355}.ip{color:#00d4ff}.dev{color:#ffaa00}.dim{color:#444466}.badge{display:inline-block;padding:2px 8px;border-radius:3px;font-size:.7em;margin-left:4px}.badge-live{background:#001a0d;color:#00ff88;border:1px solid #003318}.badge-idle{background:#111128;color:#444466;border:1px solid #1e1e3a}.badge-blocked{background:#2a0006;color:#ff3355;border:1px solid #550011}.block-btn{background:#1a0006;border:1px solid #550011;border-radius:5px;padding:4px 10px;color:#ff3355;font-family:Consolas,monospace;font-size:.75em;cursor:pointer}.block-btn:hover{background:#330011}.unblock-btn{background:#001a0d;border:1px solid #003318;border-radius:5px;padding:4px 10px;color:#00ff88;font-family:Consolas,monospace;font-size:.75em;cursor:pointer}.unblock-btn:hover{background:#003316}.empty{text-align:center;padding:48px;color:#222244}#ldot{display:inline-block;width:7px;height:7px;border-radius:50%;background:#00ff88;margin-right:6px;vertical-align:middle}@keyframes blink{0%,100%{opacity:1}50%{opacity:.2}}.blink{animation:blink 1.8s infinite}`;

function loginPage(err) {
  return `<!DOCTYPE html><html><head><meta charset="UTF-8"><title>FortiProxy</title><style>*{box-sizing:border-box;margin:0;padding:0}body{background:#08080f;color:#aaaacc;font-family:Consolas,monospace;min-height:100vh;display:flex;align-items:center;justify-content:center}.card{background:#0d0d1e;border:1px solid #151528;border-radius:16px;padding:48px 44px;width:360px;text-align:center}h1{color:#00d4ff;font-size:1.3em;letter-spacing:3px;margin-bottom:6px}.sub{color:#333355;font-size:.75em;letter-spacing:2px;margin-bottom:32px}input{width:100%;background:#06060e;border:1px solid #1e1e3a;border-radius:8px;padding:13px 16px;color:#aaaacc;font-family:Consolas,monospace;font-size:.95em;outline:none;margin-bottom:12px;letter-spacing:2px}input:focus{border-color:#00d4ff}button{width:100%;background:#005c2e;border:none;border-radius:8px;padding:13px;color:#00ff88;font-family:Consolas,monospace;font-size:.95em;font-weight:bold;letter-spacing:2px;cursor:pointer}button:hover{background:#008040}.err{color:#ff3355;font-size:.8em;margin-top:14px}</style></head><body><div class="card"><h1>&#128737;&nbsp;FORTIPROXY</h1><div class="sub">SERVER DASHBOARD</div><form method="POST" action="/api/login"><input type="password" name="token" placeholder="Admin token" autofocus><button type="submit">ACCESS DASHBOARD</button></form>${err?'<div class="err">Invalid token</div>':''}</div></body></html>`;
}

function dashboardPage(devArr) {
  const THRESH=30000,now=Date.now();
  let online=0,blk=0,tunnels=0;
  devArr.forEach(d=>{if(!d.blocked&&(now-new Date(d.lastSeen))<THRESH)online++;if(d.blocked)blk++;tunnels+=d.activeTunnels||0;});
  return `<!DOCTYPE html><html><head><meta charset="UTF-8"><meta http-equiv="Cache-Control" content="no-store"><title>FortiProxy</title><style>${CSS}</style></head><body><div class="hdr"><h1>&#128737;&nbsp;FORTIPROXY</h1><div class="hdr-r"><div class="meta"><span id="ldot" class="blink"></span>LIVE &bull; 3s</div><a class="btn-sm" href="/api/logout">LOGOUT</a></div></div><div class="stats"><div class="stat"><div class="sv" id="s-online">${online}</div><div class="sl">ONLINE NOW</div></div><div class="stat"><div class="sv" id="s-total">${devArr.length}</div><div class="sl">KNOWN DEVICES</div></div><div class="stat"><div class="sv" id="s-blocked">${blk}</div><div class="sl">BLOCKED</div></div><div class="stat"><div class="sv" id="s-tunnels">${tunnels}</div><div class="sl">ACTIVE TUNNELS</div></div></div><div class="wrap"><div class="stitle">DEVICES</div><div class="err-bar" id="err-bar"></div><table><thead><tr><th>STATUS</th><th>DEVICE</th><th>IP</th><th>REQUESTS</th><th>LAST SEEN</th><th>ACTION</th></tr></thead><tbody id="tbody">${buildRows(devArr)}</tbody></table></div><script>var THRESH=30000;function esc(s){return String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');}function ago(ts){var s=Math.floor((Date.now()-new Date(ts))/1000);if(s<5)return'just now';if(s<60)return s+'s ago';if(s<3600)return Math.floor(s/60)+'m ago';return Math.floor(s/3600)+'h ago';}function doBlock(n){if(!confirm('Block '+n+'?'))return;fetch('/api/block',{method:'POST',credentials:'include',headers:{'Content-Type':'application/json'},body:JSON.stringify({device:n})}).then(function(){refresh();});}function doUnblock(n){fetch('/api/unblock',{method:'POST',credentials:'include',headers:{'Content-Type':'application/json'},body:JSON.stringify({device:n})}).then(function(){refresh();});}function showErr(m){document.getElementById('err-bar').textContent=m;}function refresh(){fetch('/api/devices',{credentials:'include'}).then(function(r){if(r.status===401){window.location='/';return null;}return r.json();}).then(function(data){if(!data)return;showErr('');var now=Date.now();var online=0,blk=0,tunnels=0;data.forEach(function(d){if(!d.blocked&&(now-new Date(d.lastSeen))<THRESH)online++;if(d.blocked)blk++;tunnels+=d.activeTunnels||0;});document.getElementById('s-online').textContent=online;document.getElementById('s-total').textContent=data.length;document.getElementById('s-blocked').textContent=blk;document.getElementById('s-tunnels').textContent=tunnels;data.sort(function(a,b){var ao=!a.blocked&&(now-new Date(a.lastSeen))<THRESH,bo=!b.blocked&&(now-new Date(b.lastSeen))<THRESH;if(ao!==bo)return bo-ao;return new Date(b.lastSeen)-new Date(a.lastSeen);});var tb=document.getElementById('tbody');tb.innerHTML='';data.forEach(function(d){var isOnline=!d.blocked&&(now-new Date(d.lastSeen))<THRESH;var st,act;if(d.blocked){st='<span class="dot-r">&#9679;</span><span class="badge badge-blocked">BLOCKED</span>';act='<button class="unblock-btn" onclick="doUnblock(\\''+esc(d.device)+'\\')">UNBLOCK</button>';}else if(isOnline){st='<span class="dot-g blink">&#9679;</span><span class="badge badge-live">ONLINE</span>';act='<button class="block-btn" onclick="doBlock(\\''+esc(d.device)+'\\')">BLOCK</button>';}else{st='<span class="dot-d">&#9679;</span><span class="badge badge-idle">OFFLINE</span>';act='<button class="block-btn" onclick="doBlock(\\''+esc(d.device)+'\\')">BLOCK</button>';}var tr=document.createElement('tr');tr.innerHTML='<td>'+st+'</td><td class="dev">'+esc(d.device)+'</td><td class="ip">'+esc(d.ip)+'</td><td class="dim">'+d.requests+'</td><td class="dim">'+ago(d.lastSeen)+'</td><td>'+act+'</td>';document.getElementById('tbody').appendChild(tr);});}).catch(function(e){showErr('Error: '+e.message);});}setInterval(refresh,3000);</script></body></html>`;
}

// ── HTTP server ────────────────────────────────────────────────────────────────
const server = http.createServer(async (req, res) => {
  const u        = new URL(req.url, "http://localhost");
  const pathname = u.pathname;
  const origin   = req.headers.origin || "";
  const cors     = corsHeaders(origin);

  if (req.method === "OPTIONS") { res.writeHead(204, cors); res.end(); return; }

  if (pathname === "/api/login" && req.method === "POST") {
    let body = "";
    req.on("data", d => body += d.toString());
    req.on("end", () => {
      const tok = new URLSearchParams(body).get("token") || "";
      if (!ADMIN_TOKEN || tok === ADMIN_TOKEN) {
        setCookie(res, ADMIN_TOKEN || "ok");
        res.writeHead(302, { "Location": "/dashboard" });
      } else {
        res.writeHead(302, { "Location": "/?err=1" });
      }
      res.end();
    });
    return;
  }

  if (pathname === "/api/logout") {
    clearCookie(res); res.writeHead(302, { "Location": "/" }); res.end(); return;
  }

  if (pathname === "/dashboard") {
    if (!isAdminAuthed(req)) { res.writeHead(302, { "Location": "/" }); res.end(); return; }
    res.writeHead(200, { "Content-Type": "text/html", "Cache-Control": "no-store" });
    res.end(dashboardPage([...devices.values()]));
    return;
  }

  if (pathname === "/api/devices" && req.method === "GET") {
    if (!isAdminAuthed(req)) {
      res.writeHead(401, { "Content-Type": "application/json", ...cors });
      res.end(JSON.stringify({ error: "Unauthorized" })); return;
    }
    res.writeHead(200, { "Content-Type": "application/json", "Cache-Control": "no-store", ...cors });
    res.end(JSON.stringify(getDevicesSnapshot()));
    return;
  }

  if ((pathname === "/api/block" || pathname === "/api/unblock") && req.method === "POST") {
    if (!isAdminAuthed(req)) {
      res.writeHead(401, { "Content-Type": "application/json", ...cors });
      res.end(JSON.stringify({ error: "Unauthorized" })); return;
    }
    let body = "";
    req.on("data", d => body += d.toString());
    req.on("end", () => {
      let b = {};
      try { b = JSON.parse(body); } catch {}
      const name = b.device || "";
      if (pathname === "/api/block") {
        blocked.add(name);
        if (devices.has(name)) devices.get(name).blocked = true;
        const ctrl = controls.get(name);
        if (ctrl?.readyState === WebSocket.OPEN) ctrl.send(JSON.stringify({ cmd: "block" }));
        console.log(`[block] ${name}`);
      } else {
        blocked.delete(name);
        if (devices.has(name)) devices.get(name).blocked = false;
        const ctrl = controls.get(name);
        if (ctrl?.readyState === WebSocket.OPEN) ctrl.send(JSON.stringify({ cmd: "unblock" }));
        console.log(`[unblock] ${name}`);
      }
      broadcastToAdmins();
      res.writeHead(200, { "Content-Type": "application/json", ...cors });
      res.end(JSON.stringify({ ok: true }));
    });
    return;
  }

  if (pathname === "/fetch" && req.method === "POST") {
    let body = "";
    req.on("data", d => body += d.toString());
    req.on("end", async () => {
      try {
        const { url, method = "GET", headers = {}, body: fetchBody, token } = JSON.parse(body);
        if (ADMIN_TOKEN && token !== ADMIN_TOKEN) {
          res.writeHead(401, { "Content-Type": "application/json", ...cors });
          res.end(JSON.stringify({ error: "Unauthorized" })); return;
        }
        if (!url) {
          res.writeHead(400, { "Content-Type": "application/json", ...cors });
          res.end(JSON.stringify({ error: "Missing url" })); return;
        }
        const resp     = await fetch(url, { method, headers, body: fetchBody || undefined });
        const text     = await resp.text();
        const respHdrs = {};
        resp.headers.forEach((v, k) => { respHdrs[k] = v; });
        res.writeHead(200, { "Content-Type": "application/json", ...cors });
        res.end(JSON.stringify({ status: resp.status, statusText: resp.statusText, headers: respHdrs, body: text }));
      } catch (e) {
        res.writeHead(500, { "Content-Type": "application/json", ...cors });
        res.end(JSON.stringify({ error: e.message }));
      }
    });
    return;
  }

  if (pathname === "/" || pathname === "") {
    if (isAdminAuthed(req)) { res.writeHead(302, { "Location": "/dashboard" }); res.end(); return; }
    res.writeHead(200, { "Content-Type": "text/html", "Cache-Control": "no-store" });
    res.end(loginPage(u.searchParams.has("err")));
    return;
  }

  res.writeHead(200, { "Content-Type": "text/plain" });
  res.end("FortiProxy OK");
});

// ── WebSocket ──────────────────────────────────────────────────────────────────
const wss = new WebSocketServer({ server });

wss.on("connection", (ws, req) => {
  const u    = new URL(req.url, "http://localhost");
  const path = u.pathname;
  const ip   = (req.headers["x-forwarded-for"] || req.socket.remoteAddress || "?")
                 .split(",")[0].trim();

  // ── Control channel ──────────────────────────────────────────────────────────
  // Layer 2: First message must be HMAC-signed auth (not URL query param)
  if (path === "/control") {
    ws.once("message", rawAuth => {
      let device = "Unknown", authed = false;
      try {
        const m = JSON.parse(rawAuth.toString());
        if (m.type === "auth") {
          device = String(m.device || "Unknown").slice(0, 64);
          authed = PROXY_TOKEN
            ? _verifyHmac(PROXY_TOKEN, m.sig, m.ts, device, m.nonce)
            : true;
        }
      } catch {}

      if (!authed) { _rateFail(ip); ws.close(4001, "Unauthorized"); return; }
      if (_isRateLimited(ip)) { ws.close(4429, "Too Many Requests"); return; }
      if (_locked) { ws.close(4403, "Server locked"); return; }

      touch(device, ip);
      controls.set(device, ws);
      if (blocked.has(device)) ws.send(JSON.stringify({ cmd: "block" }));
      console.log(`[control] connected: ${device} (${ip})`);

      ws.on("message", data => {
        try {
          const msg = JSON.parse(data.toString());
          if (msg.type === "ping") { touch(device, ip); ws.send(JSON.stringify({ type: "pong" })); }
        } catch {}
      });
      ws.on("close", () => { if (controls.get(device) === ws) controls.delete(device); });
      ws.on("error", () => {});
    });
    return;
  }

  // ── Admin WebSocket (GitHub Pages dashboard) ──────────────────────────────────
  // Layer 1: Requires ADMIN_TOKEN — completely separate from PROXY_TOKEN
  if (path === "/ws-admin") {
    ws.once("message", rawAuth => {
      let authed = false;
      try {
        const m = JSON.parse(rawAuth.toString());
        if (m.type === "auth") authed = !ADMIN_TOKEN || m.token === ADMIN_TOKEN;
      } catch {}

      if (!authed) { _rateFail(ip); ws.close(4001, "Unauthorized"); return; }
      if (_isRateLimited(ip)) { ws.close(4429, "Too Many Requests"); return; }

      adminClients.add(ws);
      console.log(`[ws-admin] dashboard connected (${ip})`);
      ws.send(JSON.stringify({ type: "state", devices: getDevicesSnapshot(), locked: _locked }));

      ws.on("message", data => {
        try {
          const msg  = JSON.parse(data.toString());
          const name = msg.device || "";

          if (msg.cmd === "block") {
            blocked.add(name);
            if (devices.has(name)) devices.get(name).blocked = true;
            const ctrl = controls.get(name);
            if (ctrl?.readyState === WebSocket.OPEN) ctrl.send(JSON.stringify({ cmd: "block" }));
            console.log(`[block] ${name} (admin)`);
            broadcastToAdmins();

          } else if (msg.cmd === "unblock") {
            blocked.delete(name);
            if (devices.has(name)) devices.get(name).blocked = false;
            const ctrl = controls.get(name);
            if (ctrl?.readyState === WebSocket.OPEN) ctrl.send(JSON.stringify({ cmd: "unblock" }));
            console.log(`[unblock] ${name} (admin)`);
            broadcastToAdmins();

          } else if (msg.cmd === "shutdown") {
            // Lock down: reject all new connections and disconnect all devices
            console.log("[admin] LOCKDOWN initiated");
            _locked = true;
            for (const ctrl of controls.values()) {
              try { ctrl.send(JSON.stringify({ cmd: "block" })); ctrl.close(1001, "Server locked"); } catch {}
            }
            controls.clear();
            broadcastToAdmins();

          } else if (msg.cmd === "unlock") {
            console.log("[admin] UNLOCK initiated");
            _locked = false;
            broadcastToAdmins();

          } else if (msg.cmd === "restart") {
            // Force a clean restart (Render auto-restarts crashed processes)
            console.log("[admin] RESTART initiated");
            broadcastToAdmins();
            for (const client of wss.clients) {
              try { client.close(1001, "Server restarting"); } catch {}
            }
            setTimeout(() => process.exit(0), 800);
          }
        } catch {}
      });
      ws.on("close", () => adminClients.delete(ws));
      ws.on("error", () => adminClients.delete(ws));
    });
    return;
  }

  // ── Tunnel ────────────────────────────────────────────────────────────────────
  // Layer 2: First message = HMAC auth. Second message = { host, port }.
  if (path === "/tunnel") {
    ws.once("message", rawAuth => {
      let device = "Unknown", authed = false;
      try {
        const m = JSON.parse(rawAuth.toString());
        if (m.type === "auth") {
          device = String(m.device || "Unknown").slice(0, 64);
          authed = PROXY_TOKEN
            ? _verifyHmac(PROXY_TOKEN, m.sig, m.ts, device, m.nonce)
            : true;
        }
      } catch {}

      if (!authed) { _rateFail(ip); ws.close(4001, "Unauthorized"); return; }
      if (_isRateLimited(ip)) { ws.close(4429, "Too Many Requests"); return; }
      if (_locked || blocked.has(device)) { ws.close(4403, "Blocked"); return; }

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
    });
    return;
  }

  ws.close(4004, "Unknown path");
});

// ── Start ──────────────────────────────────────────────────────────────────────
server.listen(PORT, () => {
  console.log(`FortiProxy server on port ${PORT}`);
});
