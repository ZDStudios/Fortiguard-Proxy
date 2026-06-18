const net       = require("net");
const os        = require("os");
const WebSocket = require("ws");

// ── Server pool (primary = Render, secondary = Vercel or custom) ───────────────
// Set SERVER_SECONDARY env var to your Vercel deployment URL
const SERVERS = [
  process.env.SERVER_PRIMARY   || "wss://fortiguard-proxy.onrender.com",
  process.env.SERVER_SECONDARY || "",   // e.g. wss://fortiproxy.vercel.app
].filter(Boolean);

const TOKEN      = process.env.PROXY_TOKEN || "fortiguardsucks!!!";
const DEVICE     = os.hostname();
const LOCAL_PORT = 8080;

let serverIdx = 0;          // which server we're currently trying
let activeServer = SERVERS[0];

function getServer() { return SERVERS[serverIdx % SERVERS.length]; }

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
  let connected = false;
  let pingTimer = null;

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
    // If we never established a connection, try next server
    if (!connected) nextServer("control failed");
    setTimeout(openControl, connected ? 3000 : 5000);
  });
}

openControl();

// ── Tunnel proxy ───────────────────────────────────────────────────────────────
const proxy = net.createServer((client) => {
  const headerChunks = [];
  let   headerDone   = false;
  let   ws           = null;
  const pending      = [];

  client.on("data", (chunk) => {
    if (ws && ws.readyState === WebSocket.OPEN) {
      ws.send(chunk); return;
    }

    if (!headerDone) {
      headerChunks.push(chunk);
      const combined = Buffer.concat(headerChunks);
      const sep      = combined.indexOf("\r\n\r\n");
      if (sep === -1) return;

      headerDone = true;
      const headerText  = combined.slice(0, sep).toString();
      const afterHeader = combined.slice(sep + 4);
      if (afterHeader.length) pending.push(afterHeader);

      const [method, target] = headerText.split("\r\n")[0].split(" ");

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

      // host/port sent as first WS message body — keeps destination out of URL
      // so Fortiguard can't block on the target hostname in the WebSocket URL
      const SERVER = activeServer;
      const wsUrl  = `${SERVER}/tunnel?token=${encodeURIComponent(TOKEN)}&device=${encodeURIComponent(DEVICE)}`;
      ws = new WebSocket(wsUrl, { rejectUnauthorized: false });

      ws.on("open", () => {
        ws.send(JSON.stringify({ host, port }));
        if (method === "CONNECT") {
          client.write("HTTP/1.1 200 Connection Established\r\nProxy-agent: FortiProxy/2.0\r\n\r\n");
          for (const d of pending) ws.send(d);
        } else {
          ws.send(Buffer.concat([Buffer.from(headerText + "\r\n\r\n"), ...pending]));
        }
        pending.length = 0;
      });

      ws.on("message", (data) => client.write(data));
      ws.on("close",   () => client.destroy());
      ws.on("error",   (e) => { console.error(`WS: ${e.message}`); client.destroy(); });
    } else {
      pending.push(chunk);
    }
  });

  client.on("close", () => ws && ws.terminate());
  client.on("error", () => ws && ws.terminate());
});

proxy.listen(LOCAL_PORT, "127.0.0.1", () => {
  console.log(`[FortiProxy] Proxy ready on 127.0.0.1:${LOCAL_PORT}`);
  console.log(`[FortiProxy] Device: ${DEVICE}`);
  console.log(`[FortiProxy] Primary: ${SERVERS[0]}`);
  if (SERVERS[1]) console.log(`[FortiProxy] Backup: ${SERVERS[1]}`);
});
