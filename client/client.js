const net      = require("net");
const os       = require("os");
const WebSocket = require("ws");

const SERVER     = "wss://fortiguard-proxy.onrender.com";
const TOKEN      = process.env.PROXY_TOKEN || "fortiguardsucks!!!";
const DEVICE     = os.hostname();
const LOCAL_PORT = 8080;

// ── Control channel ────────────────────────────────────────────────────────────
// Persistent WebSocket for receiving admin commands (block/unblock).
function openControl() {
  const url = `${SERVER}/control?token=${encodeURIComponent(TOKEN)}&device=${encodeURIComponent(DEVICE)}`;
  const ws  = new WebSocket(url, { rejectUnauthorized: false });

  ws.on("open", () => {
    console.log("[FortiProxy] Control channel connected");
    // Ping every 20s — Render kills idle WebSockets after 30s
    const ping = setInterval(() => {
      if (ws.readyState === WebSocket.OPEN) {
        ws.send(JSON.stringify({ type: "ping" }));
      } else {
        clearInterval(ping);
      }
    }, 20000);
    ws.once("close", () => clearInterval(ping));
  });

  ws.on("message", (data) => {
    try {
      const msg = JSON.parse(data.toString());
      if (msg.cmd === "block") {
        console.log("[FortiProxy] Blocked by server admin");
        // Special line dashboard.py looks for to show the blocked status
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
    // Reconnect after 5 seconds (unless we're shutting down)
    setTimeout(openControl, 5000);
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
      const sep = combined.indexOf("\r\n\r\n");
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

      const wsUrl =
        `${SERVER}/tunnel` +
        `?token=${encodeURIComponent(TOKEN)}` +
        `&host=${encodeURIComponent(host)}` +
        `&port=${port}` +
        `&device=${encodeURIComponent(DEVICE)}`;

      ws = new WebSocket(wsUrl, { rejectUnauthorized: false });

      ws.on("open", () => {
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
  console.log(`[FortiProxy] Tunnel: ${SERVER}`);
});
