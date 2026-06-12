const http = require("http");
const net  = require("net");
const { WebSocket, WebSocketServer } = require("ws");

const PORT  = process.env.PORT || 8080;
const TOKEN = process.env.PROXY_TOKEN || "";

const tunnels = new Map();
let   nextId  = 0;

// ── Dashboard HTML ────────────────────────────────────────────────────────────
const PAGE = `<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>FortiProxy</title>
<style>
*{box-sizing:border-box;margin:0;padding:0}
body{background:#08080f;color:#aaaacc;font-family:Consolas,'Courier New',monospace;min-height:100vh;display:flex;flex-direction:column}

/* ── login ── */
#login{display:flex;align-items:center;justify-content:center;flex:1;min-height:100vh}
.login-card{background:#0d0d1e;border:1px solid #151528;border-radius:16px;padding:48px 44px;width:360px;text-align:center}
.login-card h1{color:#00d4ff;font-size:1.3em;letter-spacing:3px;margin-bottom:6px}
.login-card .sub{color:#333355;font-size:.75em;letter-spacing:2px;margin-bottom:32px}
.login-card input{width:100%;background:#06060e;border:1px solid #1e1e3a;border-radius:8px;padding:13px 16px;color:#aaaacc;font-family:Consolas,monospace;font-size:.95em;outline:none;margin-bottom:12px;letter-spacing:2px}
.login-card input:focus{border-color:#00d4ff}
.login-card button{width:100%;background:#005c2e;border:none;border-radius:8px;padding:13px;color:#00ff88;font-family:Consolas,monospace;font-size:.95em;font-weight:bold;letter-spacing:2px;cursor:pointer;transition:background .2s}
.login-card button:hover{background:#008040}
.login-err{color:#ff3355;font-size:.8em;margin-top:14px;min-height:18px}
.login-card .spinner{color:#444466;font-size:.8em;margin-top:14px}

/* ── dashboard ── */
#dash{display:none;flex-direction:column;flex:1}
.hdr{background:#04040c;padding:16px 28px;border-bottom:1px solid #111128;display:flex;align-items:center;justify-content:space-between}
.hdr h1{color:#00d4ff;font-size:1.2em;letter-spacing:3px}
.hdr-right{display:flex;align-items:center;gap:16px}
.hdr .meta{color:#222244;font-size:.75em}
.logout{background:transparent;border:1px solid #1e1e3a;border-radius:6px;padding:4px 12px;color:#444466;font-family:Consolas,monospace;font-size:.75em;cursor:pointer}
.logout:hover{border-color:#ff3355;color:#ff3355}
.stats{display:flex;gap:1px;background:#111128}
.stat{flex:1;background:#0a0a18;padding:18px 28px}
.stat-val{font-size:1.9em;font-weight:bold;color:#00d4ff}
.stat-lbl{color:#333355;font-size:.7em;letter-spacing:2px;margin-top:4px}
.wrap{padding:22px 28px;flex:1}
.sec-title{color:#222244;font-size:.7em;letter-spacing:3px;margin-bottom:14px}
table{width:100%;border-collapse:collapse}
thead th{text-align:left;padding:10px 14px;color:#333355;font-size:.7em;letter-spacing:2px;border-bottom:1px solid #111128}
tbody tr:hover{background:#0d0d1e}
tbody td{padding:11px 14px;border-bottom:1px solid #0d0d1e;font-size:.87em}
.live{color:#00ff88}.ip{color:#00d4ff}.dev{color:#ffaa00}.host{color:#aaaacc}.dim{color:#333355}
.badge{display:inline-block;padding:2px 8px;border-radius:3px;font-size:.7em;background:#001a0d;color:#00ff88;border:1px solid #003318;margin-left:6px}
.empty{text-align:center;padding:48px;color:#222244}
#live-dot{display:inline-block;width:7px;height:7px;border-radius:50%;background:#00ff88;margin-right:6px;vertical-align:middle}
@keyframes blink{0%,100%{opacity:1}50%{opacity:.2}}
.blink{animation:blink 1.8s infinite}
</style>
</head>
<body>

<!-- LOGIN SCREEN -->
<div id="login">
  <div class="login-card">
    <h1>&#128737;&nbsp; FORTIPROXY</h1>
    <div class="sub">SERVER DASHBOARD</div>
    <input type="password" id="tok" placeholder="Access token" autocomplete="current-password"
           onkeydown="if(event.key==='Enter')doLogin()">
    <button onclick="doLogin()">ACCESS DASHBOARD</button>
    <div class="login-err" id="lerr"></div>
  </div>
</div>

<!-- DASHBOARD SCREEN -->
<div id="dash">
  <div class="hdr">
    <h1>&#128737;&nbsp; FORTIPROXY</h1>
    <div class="hdr-right">
      <div class="meta"><span id="live-dot" class="blink"></span>LIVE &bull; 3s REFRESH</div>
      <button class="logout" onclick="doLogout()">LOGOUT</button>
    </div>
  </div>
  <div class="stats">
    <div class="stat"><div class="stat-val" id="s-active">0</div><div class="stat-lbl">ACTIVE TUNNELS</div></div>
    <div class="stat"><div class="stat-val" id="s-peak">0</div><div class="stat-lbl">PEAK TODAY</div></div>
    <div class="stat"><div class="stat-val" id="s-devices">0</div><div class="stat-lbl">UNIQUE DEVICES</div></div>
  </div>
  <div class="wrap">
    <div class="sec-title">ACTIVE CONNECTIONS</div>
    <table>
      <thead><tr><th>STATUS</th><th>DEVICE</th><th>IP ADDRESS</th><th>TUNNELLING TO</th><th>DURATION</th><th>SINCE</th></tr></thead>
      <tbody id="tbody"><tr><td colspan="6" class="empty">No active connections</td></tr></tbody>
    </table>
  </div>
</div>

<script>
let _token = '';
let _peak  = 0;

// ── boot ──────────────────────────────────────────────────────────────────────
(function boot() {
  const saved = localStorage.getItem('fp_token');
  if (saved) { verify(saved, true); }
})();

// ── auth ──────────────────────────────────────────────────────────────────────
function verify(token, silent) {
  fetch('/api/auth', {
    method: 'POST',
    headers: {'Content-Type':'application/json'},
    body: JSON.stringify({token})
  })
  .then(r => r.json())
  .then(d => {
    if (d.ok) { _token = token; showDash(); }
    else {
      localStorage.removeItem('fp_token');
      if (!silent) setErr('Invalid token');
    }
  })
  .catch(() => { if (!silent) setErr('Connection error'); });
}

function doLogin() {
  const t = document.getElementById('tok').value.trim();
  if (!t) { setErr('Enter your token'); return; }
  setErr('');
  verify(t, false);
  localStorage.setItem('fp_token', t);
}

function doLogout() {
  localStorage.removeItem('fp_token');
  _token = '';
  document.getElementById('dash').style.display = 'none';
  document.getElementById('login').style.display = 'flex';
  document.getElementById('tok').value = '';
}

function setErr(msg) { document.getElementById('lerr').textContent = msg; }

function showDash() {
  document.getElementById('login').style.display = 'none';
  document.getElementById('dash').style.display  = 'flex';
  refresh();
  setInterval(refresh, 3000);
}

// ── dashboard ─────────────────────────────────────────────────────────────────
function esc(s){ return String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;'); }
function fmt(s){ return [Math.floor(s/3600),Math.floor(s%3600/60),s%60].map(n=>String(n).padStart(2,'0')).join(':'); }

function refresh() {
  fetch('/api/connections', {
    method: 'POST',
    headers: {'Content-Type':'application/json'},
    body: JSON.stringify({token: _token})
  })
  .then(r => { if (r.status===401){doLogout();return null;} return r.json(); })
  .then(data => {
    if (!data) return;
    _peak = Math.max(_peak, data.length);
    document.getElementById('s-active').textContent  = data.length;
    document.getElementById('s-peak').textContent    = _peak;
    document.getElementById('s-devices').textContent = new Set(data.map(c=>c.device)).size;

    const tb = document.getElementById('tbody');
    if (!data.length) {
      tb.innerHTML = '<tr><td colspan="6" class="empty">No active connections</td></tr>';
      return;
    }
    tb.innerHTML = '';
    data.forEach(c => {
      const el = Math.floor((Date.now() - new Date(c.connectedAt)) / 1000);
      const tr = document.createElement('tr');
      tr.innerHTML =
        '<td><span class="live blink">&#9679;</span><span class="badge">LIVE</span></td>'+
        '<td class="dev">'+esc(c.device)+'</td>'+
        '<td class="ip">'+esc(c.ip)+'</td>'+
        '<td class="host">'+esc(c.host)+':'+c.port+'</td>'+
        '<td class="dim">'+fmt(el)+'</td>'+
        '<td class="dim">'+new Date(c.connectedAt).toLocaleTimeString()+'</td>';
      tb.appendChild(tr);
    });
  })
  .catch(()=>{});
}
</script>
</body>
</html>`;

// ── HTTP server ────────────────────────────────────────────────────────────────
const server = http.createServer((req, res) => {
  const u    = new URL(req.url, "http://localhost");
  const path = u.pathname;

  // Auth check helper (reads JSON body)
  function withAuth(cb) {
    let body = "";
    req.on("data", d => body += d);
    req.on("end", () => {
      try {
        const { token } = JSON.parse(body || "{}");
        if (TOKEN && token !== TOKEN) {
          res.writeHead(401, { "Content-Type": "application/json" });
          res.end(JSON.stringify({ ok: false }));
        } else {
          cb();
        }
      } catch {
        res.writeHead(400); res.end("Bad Request");
      }
    });
  }

  // POST /api/auth — verify token, return {ok}
  if (path === "/api/auth" && req.method === "POST") {
    let body = "";
    req.on("data", d => body += d);
    req.on("end", () => {
      try {
        const { token } = JSON.parse(body || "{}");
        const ok = !TOKEN || token === TOKEN;
        res.writeHead(ok ? 200 : 401, { "Content-Type": "application/json" });
        res.end(JSON.stringify({ ok }));
      } catch {
        res.writeHead(400); res.end();
      }
    });
    return;
  }

  // POST /api/connections — return active tunnels
  if (path === "/api/connections" && req.method === "POST") {
    withAuth(() => {
      res.writeHead(200, { "Content-Type": "application/json" });
      res.end(JSON.stringify([...tunnels.values()]));
    });
    return;
  }

  // GET / — dashboard SPA (login gates itself client-side)
  if (path === "/" || path === "/dashboard") {
    res.writeHead(200, { "Content-Type": "text/html" });
    res.end(PAGE);
    return;
  }

  res.writeHead(200, { "Content-Type": "text/plain" });
  res.end("FortiProxy OK");
});

// ── WebSocket tunnel ───────────────────────────────────────────────────────────
const wss = new WebSocketServer({ server, path: "/tunnel" });

wss.on("connection", (ws, req) => {
  const params = new URL(req.url, "http://localhost").searchParams;

  if (TOKEN && params.get("token") !== TOKEN) {
    ws.close(4001, "Unauthorized"); return;
  }

  const host   = params.get("host");
  const port   = parseInt(params.get("port"), 10) || 80;
  const device = params.get("device") || "Unknown";
  const ip     = (req.headers["x-forwarded-for"] || req.socket.remoteAddress || "?")
                   .split(",")[0].trim();

  if (!host) { ws.close(4002, "Missing host"); return; }

  const id = ++nextId;
  tunnels.set(id, { ip, device, host, port, connectedAt: new Date().toISOString() });

  const socket = net.connect(port, host);

  socket.on("connect", () => {
    ws.on("message", data => { if (!socket.destroyed) socket.write(data); });
  });

  socket.on("data", data => {
    if (ws.readyState === WebSocket.OPEN) ws.send(data);
  });

  socket.on("error", err => {
    console.error(`TCP ${host}:${port} — ${err.message}`);
    tunnels.delete(id);
    ws.close(4003, err.message);
  });

  const cleanup = () => tunnels.delete(id);
  socket.on("close", () => { cleanup(); ws.terminate(); });
  ws.on("close",     () => { cleanup(); socket.destroy(); });
  ws.on("error",     () => { cleanup(); socket.destroy(); });
});

server.listen(PORT, () => {
  console.log(`FortiProxy on port ${PORT}`);
  console.log(`Dashboard → https://fortiguard-proxy.onrender.com/`);
});
