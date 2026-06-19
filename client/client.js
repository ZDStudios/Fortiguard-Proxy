const net       = require("net");
const os        = require("os");
const WebSocket = require("ws");

// ── Server pool — tries in order, falls back automatically ────────────────────
const SERVERS = [
  process.env.SERVER_PRIMARY   || "wss://fortiguard-proxy.onrender.com",
  process.env.SERVER_SECONDARY || "wss://fortiguard-proxy.vercel.app",
];

const TOKEN      = process.env.PROXY_TOKEN || "fortiguardsucks!!!";
const DEVICE     = os.hostname();
const HTTP_PORT  = 8080;
const SOCKS_PORT = 1080;

let serverIdx    = 0;
let activeServer = SERVERS[0];

function getServer()  { return SERVERS[serverIdx % SERVERS.length]; }

function nextServer(reason) {
  if (SERVERS.length < 2) return;
  serverIdx++;
  activeServer = getServer();
  console.log(`[FortiProxy] ${reason} — switching to ${activeServer}`);
}

// ── Control channel ────────────────────────────────────────────────────────────
function openControl() {
  const SERVER = getServer();
  activeServer = SERVER;

  const url = `${SERVER}/control?token=${encodeURIComponent(TOKEN)}&device=${encodeURIComponent(DEVICE)}`;
  const ws  = new WebSocket(url, { rejectUnauthorized: false });
  let connected  = false;
  let pingTimer  = null;

  ws.on("open", () => {
    connected = true;
    console.log(`[FortiProxy] Control connected: ${SERVER}`);
    pingTimer = setInterval(() => {
      if (ws.readyState === WebSocket.OPEN) ws.send(JSON.stringify({ type: "ping" }));
      else clearInterval(pingTimer);
    }, 20000);
    ws.once("close", () => clearInterval(pingTimer));
  });

  ws.on("message", (data) => {
    try {
      const msg = JSON.parse(data.toString());
      if (msg.cmd === "block") {
        console.log("[FortiProxy] Blocked by server admin");
        console.log("FORTIPROXY_CMD:block");
        setTimeout(() => process.exit(0), 150);
      } else if (msg.cmd === "unblock") {
        console.log("[FortiProxy] Unblocked by server admin");
        console.log("FORTIPROXY_CMD:unblock");
      }
    } catch {}
  });

  ws.on("error", () => {});
  ws.on("close", () => {
    clearInterval(pingTimer);
    if (!connected) nextServer("control failed");
    setTimeout(openControl, connected ? 3000 : 5000);
  });
}

openControl();

// ── Shared WebSocket tunnel ────────────────────────────────────────────────────
// Opens a WS tunnel to the server for a given host:port and pipes it to/from
// the already-connected local TCP client socket.
// `method`      — "CONNECT" (for HTTP proxy) or "TUNNEL" (for SOCKS5)
// `initialData` — Buffer already received from client before tunnel opened
function openTunnel(client, method, host, port, initialData) {
  let wsOpened = false;
  const pending = initialData && initialData.length ? [initialData] : [];

  const SERVER = activeServer;
  const wsUrl  = `${SERVER}/tunnel?token=${encodeURIComponent(TOKEN)}&device=${encodeURIComponent(DEVICE)}`;
  const ws     = new WebSocket(wsUrl, { rejectUnauthorized: false });

  ws.on("open", () => {
    wsOpened = true;
    ws.send(JSON.stringify({ host, port }));
    if (method === "CONNECT") {
      client.write("HTTP/1.1 200 Connection Established\r\nProxy-agent: FortiProxy/2.0\r\n\r\n");
    }
    for (const d of pending) ws.send(d);
    pending.length = 0;
  });

  ws.on("message", (data) => {
    if (Buffer.isBuffer(data)) client.write(data);
    else client.write(Buffer.from(data));
  });

  ws.on("close", () => { if (!client.destroyed) client.destroy(); });

  ws.on("error", (e) => {
    if (!e.message.includes("closed before the connection was established")) {
      console.error(`WS: ${e.message}`);
    }
    if (!wsOpened) {
      try {
        if (method === "CONNECT") {
          client.write("HTTP/1.1 503 Service Unavailable\r\nProxy-agent: FortiProxy/2.0\r\nContent-Length: 0\r\n\r\n");
        }
      } catch {}
    }
    if (!client.destroyed) client.destroy();
  });

  client.on("data", (chunk) => {
    if (ws.readyState === WebSocket.OPEN) ws.send(chunk);
    else pending.push(chunk);
  });
  client.on("close", () => { if (!ws._closed) ws.terminate(); });
  client.on("error", () => { if (!ws._closed) ws.terminate(); });
}

// ── HTTP CONNECT proxy (port 8080) ────────────────────────────────────────────
const httpProxy = net.createServer((client) => {
  const headerChunks = [];
  let   headerDone   = false;
  let   method       = "";

  client.on("data", (chunk) => {
    if (headerDone) return; // openTunnel took over data events

    headerChunks.push(chunk);
    const combined = Buffer.concat(headerChunks);
    const sep      = combined.indexOf("\r\n\r\n");
    if (sep === -1) return;

    headerDone = true;
    const headerText  = combined.slice(0, sep).toString();
    const afterHeader = combined.slice(sep + 4);

    const parts  = headerText.split("\r\n")[0].split(" ");
    method       = parts[0];
    const target = parts[1];

    let host, port;
    if (method === "CONNECT") {
      const ci = target.lastIndexOf(":");
      host = target.slice(0, ci);
      port = parseInt(target.slice(ci + 1), 10) || 443;
    } else {
      try {
        const u = new URL(target);
        host = u.hostname;
        port = parseInt(u.port, 10) || (u.protocol === "https:" ? 443 : 80);
      } catch { client.destroy(); return; }
    }

    // For non-CONNECT, the full header+body is the initial data to forward
    const initialData = method === "CONNECT"
      ? (afterHeader.length ? afterHeader : null)
      : Buffer.concat([Buffer.from(headerText + "\r\n\r\n"), afterHeader]);

    openTunnel(client, method, host, port, initialData);
  });

  client.on("error", () => {});
});

httpProxy.on("error", (e) => {
  console.error(`[FortiProxy] HTTP proxy failed to start: ${e.message}`);
  process.exit(1);
});

httpProxy.listen(HTTP_PORT, "127.0.0.1", () => {
  console.log(`[FortiProxy] HTTP proxy  on 127.0.0.1:${HTTP_PORT}`);
  console.log(`[FortiProxy] Device: ${DEVICE}`);
  console.log(`[FortiProxy] Primary: ${SERVERS[0]}`);
  if (SERVERS[1]) console.log(`[FortiProxy] Backup: ${SERVERS[1]}`);
});

// ── SOCKS5 proxy (port 1080) ───────────────────────────────────────────────────
// TCP CONNECT only — no BIND, no UDP ASSOCIATE.
// Chrome/Electron (Discord) uses SOCKS5 and routes WebRTC TURN-TCP through it,
// which lets voice calls work when UDP is blocked by Fortiguard.
const socks5 = net.createServer((client) => {
  let buf  = Buffer.alloc(0);
  let step = 0;   // 0 = auth negotiation, 1 = request

  const onData = (chunk) => {
    buf = Buffer.concat([buf, chunk]);

    // Reject SOCKS4/4a — Windows registry "socks=" sends SOCKS4 not SOCKS5
    if (step === 0 && buf.length >= 1 && buf[0] !== 0x05) {
      client.destroy();
      return;
    }

    // ── Step 0: auth negotiation ──────────────────────────────────────────
    if (step === 0) {
      if (buf.length < 2) return;
      const nMethods = buf[1];
      if (buf.length < 2 + nMethods) return;
      client.write(Buffer.from([0x05, 0x00])); // no auth
      buf  = buf.slice(2 + nMethods);
      step = 1;
    }

    // ── Step 1: connection request ────────────────────────────────────────
    if (step === 1) {
      if (buf.length < 4) return;
      const cmd  = buf[1];
      const atyp = buf[3];

      let host, port, consumed;

      if (atyp === 0x01) {           // IPv4
        if (buf.length < 10) return;
        host     = `${buf[4]}.${buf[5]}.${buf[6]}.${buf[7]}`;
        port     = buf.readUInt16BE(8);
        consumed = 10;
      } else if (atyp === 0x03) {    // hostname
        if (buf.length < 5) return;
        const len = buf[4];
        if (buf.length < 5 + len + 2) return;
        host     = buf.slice(5, 5 + len).toString();
        port     = buf.readUInt16BE(5 + len);
        consumed = 5 + len + 2;
      } else if (atyp === 0x04) {    // IPv6
        if (buf.length < 22) return;
        const parts = [];
        for (let i = 0; i < 8; i++) parts.push(buf.readUInt16BE(4 + i * 2).toString(16));
        host     = parts.join(":");
        port     = buf.readUInt16BE(20);
        consumed = 22;
      } else {
        client.write(Buffer.from([0x05, 0x08, 0x00, 0x01, 0,0,0,0, 0,0])); // address type not supported
        client.destroy();
        return;
      }

      if (cmd !== 0x01) {
        // Only CONNECT (0x01) supported
        client.write(Buffer.from([0x05, 0x07, 0x00, 0x01, 0,0,0,0, 0,0])); // command not supported
        client.destroy();
        return;
      }

      const rest = buf.slice(consumed);
      buf  = Buffer.alloc(0);
      step = 2;

      // SOCKS5 success reply — bound addr 0.0.0.0:0
      client.write(Buffer.from([0x05, 0x00, 0x00, 0x01, 0,0,0,0, 0,0]));

      // Remove our listener; openTunnel will attach its own
      client.removeListener("data", onData);
      openTunnel(client, "TUNNEL", host, port, rest.length ? rest : null);
    }
  };

  client.on("data", onData);
  client.on("error", () => {});
});

socks5.on("error", (e) => {
  // Port 1080 may be taken by another app — HTTP proxy on 8080 still works
  console.log(`[FortiProxy] SOCKS5 unavailable (${e.code}) — continuing without it`);
});

socks5.listen(SOCKS_PORT, "127.0.0.1", () => {
  console.log(`[FortiProxy] SOCKS5 proxy on 127.0.0.1:${SOCKS_PORT}`);
});
