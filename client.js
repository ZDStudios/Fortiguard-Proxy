const net = require("net");
const WebSocket = require("ws");

const SERVER = "wss://fortiguard-proxy.onrender.com";
const TOKEN = process.env.PROXY_TOKEN || "fortiguardsucks!!!";
const LOCAL_PORT = 8080;

const proxy = net.createServer((client) => {
  const headerChunks = [];
  let headerDone = false;
  let ws = null;
  const pending = []; // data that arrives while WS is still connecting

  client.on("data", (chunk) => {
    // Once WS is open, pipe directly
    if (ws && ws.readyState === WebSocket.OPEN) {
      ws.send(chunk);
      return;
    }

    if (!headerDone) {
      headerChunks.push(chunk);
      const combined = Buffer.concat(headerChunks);
      const sep = combined.indexOf("\r\n\r\n");
      if (sep === -1) return; // need more header bytes

      headerDone = true;
      const headerText = combined.slice(0, sep).toString();
      const afterHeader = combined.slice(sep + 4);
      if (afterHeader.length) pending.push(afterHeader);

      const firstLine = headerText.split("\r\n")[0];
      const [method, target] = firstLine.split(" ");

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
        } catch {
          client.destroy();
          return;
        }
      }

      const wsUrl = `${SERVER}/tunnel?token=${encodeURIComponent(TOKEN)}&host=${encodeURIComponent(host)}&port=${port}`;
      ws = new WebSocket(wsUrl);

      ws.on("open", () => {
        if (method === "CONNECT") {
          client.write("HTTP/1.1 200 Connection Established\r\nProxy-agent: FortiProxy/2.0\r\n\r\n");
          // Flush anything buffered while WS was connecting
          for (const d of pending) ws.send(d);
        } else {
          // Send the original HTTP request + any body that arrived
          const full = Buffer.concat([Buffer.from(headerText + "\r\n\r\n"), ...pending]);
          ws.send(full);
        }
        pending.length = 0;
      });

      ws.on("message", (data) => client.write(data));
      ws.on("close", () => client.destroy());
      ws.on("error", (e) => {
        console.error(`WS error: ${e.message}`);
        client.destroy();
      });
    } else {
      // Header parsed, WS not open yet — buffer
      pending.push(chunk);
    }
  });

  client.on("close", () => ws && ws.terminate());
  client.on("error", () => ws && ws.terminate());
});

proxy.listen(LOCAL_PORT, "127.0.0.1", () => {
  console.log(`[FortiProxy] Local proxy ready on 127.0.0.1:${LOCAL_PORT}`);
  console.log(`[FortiProxy] Tunneling through ${SERVER}`);
  console.log("[FortiProxy] Press Ctrl+C to stop");
});
