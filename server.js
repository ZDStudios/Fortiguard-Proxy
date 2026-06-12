const http = require("http");
const net  = require("net");
const { WebSocket, WebSocketServer } = require("ws");

const PORT  = process.env.PORT || 8080;
const TOKEN = process.env.PROXY_TOKEN || "";

// ── State ─────────────────────────────────────────────────────────────────────
const devices  = new Map(); // deviceName → DeviceInfo  (persists between connections)
const controls = new Map(); // deviceName → control WebSocket
const blocked  = new Set(); // blocked device names

function touch(name, ip) {
  const now = new Date().toISOString();
  if (!devices.has(name)) {
    devices.set(name, { device: name, ip, firstSeen: now, lastSeen: now, requests: 0, blocked: false, activeTunnels: 0 });
  } else {
    const d = devices.get(name);
    d.lastSeen = now;
    d.ip = ip;
  }
  return devices.get(name);
}

// ── Dashboard page ────────────────────────────────────────────────────────────
const PAGE = `<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>FortiProxy</title>
<style>
*{box-sizing:border-box;margin:0;padding:0}
body{background:#08080f;color:#aaaacc;font-family:Consolas,'Courier New',monospace;min-height:100vh;display:flex;flex-direction:column}
#login{display:flex;align-items:center;justify-content:center;flex:1;min-height:100vh}
.card{background:#0d0d1e;border:1px solid #151528;border-radius:16px;padding:48px 44px;width:360px;text-align:center}
.card h1{color:#00d4ff;font-size:1.3em;letter-spacing:3px;margin-bottom:6px}
.card .sub{color:#333355;font-size:.75em;letter-spacing:2px;margin-bottom:32px}
.card input{width:100%;background:#06060e;border:1px solid #1e1e3a;border-radius:8px;padding:13px 16px;color:#aaaacc;font-family:Consolas,monospace;font-size:.95em;outline:none;margin-bottom:12px;letter-spacing:2px}
.card input:focus{border-color:#00d4ff}
.card button{width:100%;background:#005c2e;border:none;border-radius:8px;padding:13px;color:#00ff88;font-family:Consolas,monospace;font-size:.95em;font-weight:bold;letter-spacing:2px;cursor:pointer}
.card button:hover{background:#008040}
.err{color:#ff3355;font-size:.8em;margin-top:14px;min-height:18px}
#dash{display:none;flex-direction:column;flex:1}
.hdr{background:#04040c;padding:16px 28px;border-bottom:1px solid #111128;display:flex;align-items:center;justify-content:space-between}
.hdr h1{color:#00d4ff;font-size:1.2em;letter-spacing:3px}
.hdr-r{display:flex;align-items:center;gap:16px}
.meta{color:#222244;font-size:.75em}
.btn-sm{background:transparent;border:1px solid #1e1e3a;border-radius:6px;padding:4px 12px;color:#444466;font-family:Consolas,monospace;font-size:.75em;cursor:pointer}
.btn-sm:hover{border-color:#ff3355;color:#ff3355}
.stats{display:flex;gap:1px;background:#111128}
.stat{flex:1;background:#0a0a18;padding:18px 28px}
.sv{font-size:1.9em;font-weight:bold;color:#00d4ff}
.sl{color:#333355;font-size:.7em;letter-spacing:2px;margin-top:4px}
.wrap{padding:22px 28px;flex:1}
.stitle{color:#222244;font-size:.7em;letter-spacing:3px;margin-bottom:14px}
table{width:100%;border-collapse:collapse}
thead th{text-align:left;padding:10px 14px;color:#333355;font-size:.7em;letter-spacing:2px;border-bottom:1px solid #111128}
tbody tr:hover{background:#0d0d1e}
tbody td{padding:11px 14px;border-bottom:1px solid #0d0d1e;font-size:.87em;vertical-align:middle}
.dot-g{color:#00ff88}.dot-r{color:#ff3355}.dot-y{color:#ffaa00}.dot-d{color:#333355}
.ip{color:#00d4ff}.dev{color:#ffaa00}.dim{color:#444466}
.badge{display:inline-block;padding:2px 8px;border-radius:3px;font-size:.7em;margin-left:4px}
.badge-live{background:#001a0d;color:#00ff88;border:1px solid #003318}
.badge-idle{background:#111128;color:#444466;border:1px solid #1e1e3a}
.badge-blocked{background:#2a0006;color:#ff3355;border:1px solid #550011}
.block-btn{background:#1a0006;border:1px solid #550011;border-radius:5px;padding:4px 10px;color:#ff3355;font-family:Consolas,monospace;font-size:.75em;cursor:pointer;letter-spacing:1px}
.block-btn:hover{background:#330011}
.unblock-btn{background:#001a0d;border:1px solid #003318;border-radius:5px;padding:4px 10px;color:#00ff88;font-family:Consolas,monospace;font-size:.75em;cursor:pointer;letter-spacing:1px}
.unblock-btn:hover{background:#003316}
.empty{text-align:center;padding:48px;color:#222244}
#ldot{display:inline-block;width:7px;height:7px;border-radius:50%;background:#00ff88;margin-right:6px;vertical-align:middle}
@keyframes blink{0%,100%{opacity:1}50%{opacity:.2}}
.blink{animation:blink 1.8s infinite}
</style>
</head>
<body>

<div id="login">
  <div class="card">
    <h1>&#128737;&nbsp; FORTIPROXY</h1>
    <div class="sub">SERVER DASHBOARD</div>
    <input type="password" id="tok" placeholder="Access token" autocomplete="current-password"
           onkeydown="if(event.key==='Enter')doLogin()">
    <button id="loginbtn" onclick="doLogin()">ACCESS DASHBOARD</button>
    <div class="err" id="lerr"></div>
  </div>
</div>

<div id="dash">
  <div class="hdr">
    <h1>&#128737;&nbsp; FORTIPROXY</h1>
    <div class="hdr-r">
      <div class="meta"><span id="ldot" class="blink"></span>LIVE &bull; 3s</div>
      <button class="btn-sm" onclick="doLogout()">LOGOUT</button>
    </div>
  </div>
  <div class="stats">
    <div class="stat"><div class="sv" id="s-online">0</div><div class="sl">ONLINE NOW</div></div>
    <div class="stat"><div class="sv" id="s-total">0</div><div class="sl">KNOWN DEVICES</div></div>
    <div class="stat"><div class="sv" id="s-blocked">0</div><div class="sl">BLOCKED</div></div>
    <div class="stat"><div class="sv" id="s-tunnels">0</div><div class="sl">ACTIVE TUNNELS</div></div>
  </div>
  <div class="wrap">
    <div class="stitle">DEVICES</div>
    <table>
      <thead><tr><th>STATUS</th><th>DEVICE</th><th>IP ADDRESS</th><th>REQUESTS</th><th>LAST SEEN</th><th>ACTION</th></tr></thead>
      <tbody id="tbody"><tr><td colspan="6" class="empty">No devices seen yet</td></tr></tbody>
    </table>
  </div>
</div>

<script>
let _tok='', _refreshTimer=null;

// Safe localStorage wrappers — school browsers may block storage entirely
function lsGet(k){try{return localStorage.getItem(k);}catch{return null;}}
function lsSet(k,v){try{localStorage.setItem(k,v);}catch{}}
function lsDel(k){try{localStorage.removeItem(k);}catch{}}

try{
  const s=lsGet('fp_token');
  if(s) verify(s,true);
}catch(e){console.warn('boot error',e);}

function verify(token,silent){
  const btn=document.getElementById('loginbtn');
  fetch('/api/auth',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({token})})
  .then(function(r){return r.json();})
  .then(function(d){
    if(d&&d.ok){_tok=token;lsSet('fp_token',token);showDash();}
    else{lsDel('fp_token');if(!silent)setErr('Invalid token');}
  })
  .catch(function(e){console.error('auth error',e);if(!silent)setErr('Connection error — check console');})
  .finally(function(){if(btn){btn.disabled=false;btn.textContent='ACCESS DASHBOARD';}});
}
function doLogin(){
  const btn=document.getElementById('loginbtn');
  const t=document.getElementById('tok').value.trim();
  if(!t){setErr('Enter your token');return;}
  setErr('');
  btn.disabled=true;
  btn.textContent='CHECKING...';
  verify(t,false);
}
function doLogout(){
  lsDel('fp_token');
  _tok='';
  clearInterval(_refreshTimer);
  document.getElementById('dash').style.display='none';
  document.getElementById('login').style.display='flex';
  document.getElementById('tok').value='';
}
function setErr(m){document.getElementById('lerr').textContent=m;}
function showDash(){
  document.getElementById('login').style.display='none';
  document.getElementById('dash').style.display='flex';
  refresh();
  _refreshTimer=setInterval(refresh,3000);
}

function esc(s){return String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');}
function ago(ts){
  const s=Math.floor((Date.now()-new Date(ts))/1000);
  if(s<5)  return 'just now';
  if(s<60) return s+'s ago';
  if(s<3600) return Math.floor(s/60)+'m ago';
  return Math.floor(s/3600)+'h ago';
}

function blockDevice(name){
  if(!confirm('Block '+name+'? This will disable their proxy immediately.')) return;
  fetch('/api/block',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({token:_tok,device:name})})
  .then(()=>refresh());
}
function unblockDevice(name){
  fetch('/api/unblock',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({token:_tok,device:name})})
  .then(()=>refresh());
}

function refresh(){
  fetch('/api/devices',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({token:_tok})})
  .then(r=>{if(r.status===401){doLogout();return null;}return r.json();})
  .then(data=>{
    if(!data) return;
    const now=Date.now();
    const ONLINE_THRESHOLD=30000; // online if seen within 30s

    let online=0,blk=0,tunnels=0;
    data.forEach(d=>{
      if(!d.blocked && (now-new Date(d.lastSeen))<ONLINE_THRESHOLD) online++;
      if(d.blocked) blk++;
      tunnels+=d.activeTunnels||0;
    });

    document.getElementById('s-online').textContent=online;
    document.getElementById('s-total').textContent=data.length;
    document.getElementById('s-blocked').textContent=blk;
    document.getElementById('s-tunnels').textContent=tunnels;

    const tb=document.getElementById('tbody');
    if(!data.length){tb.innerHTML='<tr><td colspan="6" class="empty">No devices seen yet</td></tr>';return;}

    // Sort: online first, then by lastSeen desc
    data.sort((a,b)=>{
      const ao=(now-new Date(a.lastSeen))<ONLINE_THRESHOLD && !a.blocked;
      const bo=(now-new Date(b.lastSeen))<ONLINE_THRESHOLD && !b.blocked;
      if(ao!==bo) return bo-ao;
      return new Date(b.lastSeen)-new Date(a.lastSeen);
    });

    tb.innerHTML='';
    data.forEach(d=>{
      const isOnline=(now-new Date(d.lastSeen))<ONLINE_THRESHOLD && !d.blocked;
      const tr=document.createElement('tr');
      let statusHtml, actionHtml;

      if(d.blocked){
        statusHtml='<span class="dot-r">&#9679;</span><span class="badge badge-blocked">BLOCKED</span>';
        actionHtml='<button class="unblock-btn" onclick="unblockDevice(\''+esc(d.device)+'\')">UNBLOCK</button>';
      } else if(isOnline){
        statusHtml='<span class="dot-g blink">&#9679;</span><span class="badge badge-live">ONLINE</span>';
        actionHtml='<button class="block-btn" onclick="blockDevice(\''+esc(d.device)+'\')">BLOCK</button>';
      } else {
        statusHtml='<span class="dot-d">&#9679;</span><span class="badge badge-idle">OFFLINE</span>';
        actionHtml='<button class="block-btn" onclick="blockDevice(\''+esc(d.device)+'\')">BLOCK</button>';
      }

      tr.innerHTML=
        '<td>'+statusHtml+'</td>'+
        '<td class="dev">'+esc(d.device)+'</td>'+
        '<td class="ip">'+esc(d.ip)+'</td>'+
        '<td class="dim">'+d.requests+'</td>'+
        '<td class="dim">'+ago(d.lastSeen)+'</td>'+
        '<td>'+actionHtml+'</td>';
      tb.appendChild(tr);
    });
  }).catch(()=>{});
}
</script>
</body>
</html>`;

// ── HTTP server ────────────────────────────────────────────────────────────────
const server = http.createServer((req, res) => {
  const pathname = new URL(req.url, "http://localhost").pathname;

  function readBody(cb) {
    let body = "";
    req.on("data", d => body += d);
    req.on("end", () => { try { cb(JSON.parse(body || "{}")); } catch { res.writeHead(400); res.end(); } });
  }

  function withAuth(body, cb) {
    if (TOKEN && body.token !== TOKEN) {
      res.writeHead(401, { "Content-Type": "application/json" });
      res.end(JSON.stringify({ ok: false }));
    } else { cb(); }
  }

  if (pathname === "/api/auth" && req.method === "POST") {
    readBody(b => {
      const ok = !TOKEN || b.token === TOKEN;
      res.writeHead(200, { "Content-Type": "application/json" });
      res.end(JSON.stringify({ ok }));
    });
    return;
  }

  if (pathname === "/api/devices" && req.method === "POST") {
    readBody(b => withAuth(b, () => {
      res.writeHead(200, { "Content-Type": "application/json" });
      res.end(JSON.stringify([...devices.values()]));
    }));
    return;
  }

  if (pathname === "/api/block" && req.method === "POST") {
    readBody(b => withAuth(b, () => {
      const name = b.device;
      blocked.add(name);
      if (devices.has(name)) devices.get(name).blocked = true;
      // Send block command via control channel
      const ctrl = controls.get(name);
      if (ctrl && ctrl.readyState === WebSocket.OPEN) {
        ctrl.send(JSON.stringify({ cmd: "block" }));
      }
      res.writeHead(200, { "Content-Type": "application/json" });
      res.end(JSON.stringify({ ok: true }));
    }));
    return;
  }

  if (pathname === "/api/unblock" && req.method === "POST") {
    readBody(b => withAuth(b, () => {
      const name = b.device;
      blocked.delete(name);
      if (devices.has(name)) devices.get(name).blocked = false;
      const ctrl = controls.get(name);
      if (ctrl && ctrl.readyState === WebSocket.OPEN) {
        ctrl.send(JSON.stringify({ cmd: "unblock" }));
      }
      res.writeHead(200, { "Content-Type": "application/json" });
      res.end(JSON.stringify({ ok: true }));
    }));
    return;
  }

  if (pathname === "/" || pathname === "/dashboard") {
    res.writeHead(200, { "Content-Type": "text/html" });
    res.end(PAGE);
    return;
  }

  res.writeHead(200, { "Content-Type": "text/plain" });
  res.end("FortiProxy OK");
});

// ── WebSocket (tunnel + control on same server) ────────────────────────────────
const wss = new WebSocketServer({ server });

wss.on("connection", (ws, req) => {
  const u      = new URL(req.url, "http://localhost");
  const path   = u.pathname;
  const params = u.searchParams;

  if (TOKEN && params.get("token") !== TOKEN) {
    ws.close(4001, "Unauthorized"); return;
  }

  const device = params.get("device") || "Unknown";
  const ip     = (req.headers["x-forwarded-for"] || req.socket.remoteAddress || "?")
                   .split(",")[0].trim();

  // ── Control channel ──────────────────────────────────────────────────────────
  if (path === "/control") {
    touch(device, ip);
    controls.set(device, ws);

    // If already blocked, tell them immediately
    if (blocked.has(device)) {
      ws.send(JSON.stringify({ cmd: "block" }));
    }

    ws.on("close", () => { if (controls.get(device) === ws) controls.delete(device); });
    ws.on("error", () => {});
    return;
  }

  // ── Tunnel ───────────────────────────────────────────────────────────────────
  if (path === "/tunnel") {
    // Reject blocked devices
    if (blocked.has(device)) {
      ws.close(4403, "Blocked"); return;
    }

    const host = params.get("host");
    const port = parseInt(params.get("port"), 10) || 80;
    if (!host) { ws.close(4002, "Missing host"); return; }

    const info = touch(device, ip);
    info.requests++;
    info.activeTunnels = (info.activeTunnels || 0) + 1;

    const socket = net.connect(port, host);
    socket.on("connect", () => {
      ws.on("message", data => { if (!socket.destroyed) socket.write(data); });
    });
    socket.on("data", data => {
      if (ws.readyState === WebSocket.OPEN) ws.send(data);
    });
    socket.on("error", err => {
      info.activeTunnels = Math.max(0, (info.activeTunnels || 1) - 1);
      ws.close(4003, err.message);
    });

    const cleanup = () => {
      info.activeTunnels = Math.max(0, (info.activeTunnels || 1) - 1);
    };
    socket.on("close", () => { cleanup(); ws.terminate(); });
    ws.on("close",     () => { cleanup(); socket.destroy(); });
    ws.on("error",     () => { cleanup(); socket.destroy(); });
    return;
  }

  ws.close(4004, "Unknown path");
});

server.listen(PORT, () => {
  console.log(`FortiProxy on port ${PORT}`);
  console.log(`Dashboard → https://fortiguard-proxy.onrender.com/`);
});
