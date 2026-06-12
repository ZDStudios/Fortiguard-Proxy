const http = require("http");
const net  = require("net");
const { WebSocket, WebSocketServer } = require("ws");

const PORT  = process.env.PORT || 8080;
const TOKEN = process.env.PROXY_TOKEN || "";

// ── Active tunnel registry ────────────────────────────────────────────────
const tunnels = new Map();
let   nextId  = 0;

// ── Web dashboard HTML ────────────────────────────────────────────────────
const DASHBOARD = `<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>FortiProxy</title>
<style>
  *{box-sizing:border-box;margin:0;padding:0}
  body{background:#08080f;color:#aaaacc;font-family:Consolas,'Courier New',monospace;min-height:100vh}
  .hdr{background:#04040c;padding:16px 28px;border-bottom:1px solid #111128;display:flex;align-items:center;justify-content:space-between}
  .hdr h1{color:#00d4ff;font-size:1.25em;letter-spacing:3px}
  .hdr .meta{color:#222244;font-size:.75em}
  .stats{display:flex;gap:1px;background:#111128}
  .stat{flex:1;background:#0a0a18;padding:20px 28px}
  .stat-val{font-size:2em;font-weight:bold;color:#00d4ff}
  .stat-lbl{color:#333355;font-size:.7em;letter-spacing:2px;margin-top:4px}
  .wrap{padding:24px 28px}
  .sec-title{color:#222244;font-size:.7em;letter-spacing:3px;margin-bottom:14px}
  table{width:100%;border-collapse:collapse}
  thead th{text-align:left;padding:10px 14px;color:#333355;font-size:.7em;letter-spacing:2px;border-bottom:1px solid #111128}
  tbody tr:hover{background:#0d0d1e}
  tbody td{padding:12px 14px;border-bottom:1px solid #0d0d1e;font-size:.88em}
  .live{color:#00ff88}.ip{color:#00d4ff}.dev{color:#ffaa00}.host{color:#aaaacc}.dim{color:#333355}
  .badge{display:inline-block;padding:2px 8px;border-radius:3px;font-size:.7em;background:#001a0d;color:#00ff88;border:1px solid #003318;margin-left:6px}
  .empty{text-align:center;padding:48px;color:#222244}
  @keyframes pulse{0%,100%{opacity:1}50%{opacity:.25}}
  .pulse{animation:pulse 1.8s infinite}
  #dot{display:inline-block;width:8px;height:8px;border-radius:50%;background:#00ff88;margin-right:6px;animation:pulse 2s infinite}
</style>
</head>
<body>
<div class="hdr">
  <h1>&#128737;&nbsp; FORTIPROXY</h1>
  <div class="meta"><span id="dot"></span>LIVE &bull; REFRESHES EVERY 3s</div>
</div>
<div class="stats">
  <div class="stat"><div class="stat-val" id="s-active">0</div><div class="stat-lbl">ACTIVE TUNNELS</div></div>
  <div class="stat"><div class="stat-val" id="s-total">0</div><div class="stat-lbl">TOTAL TODAY</div></div>
  <div class="stat"><div class="stat-val" id="s-devices">0</div><div class="stat-lbl">UNIQUE DEVICES</div></div>
</div>
<div class="wrap">
  <div class="sec-title">ACTIVE CONNECTIONS</div>
  <table>
    <thead><tr><th>STATUS</th><th>DEVICE</th><th>IP ADDRESS</th><th>TUNNELLING TO</th><th>DURATION</th><th>SINCE</th></tr></thead>
    <tbody id="tbody"><tr><td colspan="6" class="empty">No active connections</td></tr></tbody>
  </table>
</div>
<script>
const TOKEN = new URLSearchParams(location.search).get('token')||'';
let peakTotal=0;
function fmt(s){return[Math.floor(s/3600),Math.floor(s%3600/60),s%60].map(n=>String(n).padStart(2,'0')).join(':')}
function esc(s){return String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;')}
function refresh(){
  fetch('/api/connections?token='+encodeURIComponent(TOKEN))
    .then(r=>r.json()).then(data=>{
      document.getElementById('s-active').textContent=data.length;
      peakTotal=Math.max(peakTotal,data.length);
      document.getElementById('s-total').textContent=peakTotal;
      document.getElementById('s-devices').textContent=new Set(data.map(c=>c.device)).size;
      const tb=document.getElementById('tbody');
      if(!data.length){tb.innerHTML='<tr><td colspan="6" class="empty">No active connections</td></tr>';return}
      tb.innerHTML='';
      data.forEach(c=>{
        const el=Math.floor((Date.now()-new Date(c.connectedAt))/1000);
        const tr=document.createElement('tr');
        tr.innerHTML=
          '<td><span class="live pulse">&#9679;</span><span class="badge">LIVE</span></td>'+
          '<td class="dev">'+esc(c.device)+'</td>'+
          '<td class="ip">'+esc(c.ip)+'</td>'+
          '<td class="host">'+esc(c.host)+':'+c.port+'</td>'+
          '<td class="dim">'+fmt(el)+'</td>'+
          '<td class="dim">'+new Date(c.connectedAt).toLocaleTimeString()+'</td>';
        tb.appendChild(tr);
      });
    }).catch(()=>{});
}
refresh();setInterval(refresh,3000);
</script>
</body>
</html>`;

// ── HTTP server ────────────────────────────────────────────────────────────
const server = http.createServer((req, res) => {
  const u = new URL(req.url, "http://localhost");

  if (u.pathname === "/api/connections") {
    if (TOKEN && u.searchParams.get("token") !== TOKEN) {
      res.writeHead(401); res.end("Unauthorized"); return;
    }
    res.writeHead(200, { "Content-Type": "application/json" });
    res.end(JSON.stringify([...tunnels.values()]));
    return;
  }

  if (u.pathname === "/" || u.pathname === "/dashboard") {
    res.writeHead(200, { "Content-Type": "text/html" });
    res.end(DASHBOARD);
    return;
  }

  res.writeHead(200, { "Content-Type": "text/plain" });
  res.end("FortiProxy OK");
});

// ── WebSocket tunnel ───────────────────────────────────────────────────────
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
    ws.on("message", (data) => { if (!socket.destroyed) socket.write(data); });
  });

  socket.on("data", (data) => {
    if (ws.readyState === WebSocket.OPEN) ws.send(data);
  });

  socket.on("error", (err) => {
    console.error(`TCP ${host}:${port} — ${err.message}`);
    tunnels.delete(id);
    ws.close(4003, err.message);
  });

  const cleanup = () => { tunnels.delete(id); };
  socket.on("close", () => { cleanup(); ws.terminate(); });
  ws.on("close",     () => { cleanup(); socket.destroy(); });
  ws.on("error",     () => { cleanup(); socket.destroy(); });
});

server.listen(PORT, () => {
  console.log(`FortiProxy on port ${PORT}`);
  console.log(`Dashboard → http://localhost:${PORT}/?token=${TOKEN}`);
});
