const net = require("net");
const WebSocket = require("ws");

const SERVER = "wss://fortiguard-proxy.onrender.com";
const TOKEN = process.env.PROXY_TOKEN || "fortiguardsucks!!!";
const LOCAL_PORT = 8080;

function openTunnel(host, port, onOpen, onData, onClose) {
  const url = `${SERVER}/tunnel?token=${encodeURIComponent(TOKEN)}&host=${encodeURIComponent(host)}&port=${port}`;
  const ws = new WebSocket(url);
  ws.on("open", onOpen);
  ws.on("message", onData);
  ws.on("close", onClose);
  ws.on("error", onClose);
  return ws;
}

const proxy = net.createServer((client) => {
  let header = "";
  let done = false;

  client.on("data", (chunk) => {
    if (done) return;

    header += chunk.toString("binary");
    const sep = header.indexOf("\r\n\r\n");
    if (sep === -1) return;

    done = true;
    const headerText = header.substring(0, sep);
    const bodyBin = header.substring(sep + 4);
    const body = Buffer.from(bodyBin, "binary");

    const firstLine = headerText.split("\r\n")[0];
    const [method, target] = firstLine.split(" ");

    let host, port;
    if (method === "CONNECT") {
      const parts = target.split(":");
      host = parts[0];
      port = parseInt(parts[1], 10) || 443;
    } else {
      try {
        const u = new URL(target);
        host = u.hostname;
        port = parseInt(u.port, 10) || 80;
      } catch {
        client.destroy();
        return;
      }
    }

    const ws = openTunnel(
      host,
      port,
      () => {
        if (method === "CONNECT") {
          client.write("HTTP/1.1 200 Connection Established\r\nProxy-agent: FortiProxy/2.0\r\n\r\n");
        } else {
          ws.send(Buffer.from(headerText + "\r\n\r\n", "binary"));
          if (body.length) ws.send(body);
        }

        client.removeAllListeners("data");
        client.on("data", (d) => {
          if (ws.readyState === WebSocket.OPEN) ws.send(d);
        });
      },
      (data) => client.write(data),
      () => client.destroy()
    );

    client.on("close", () => ws.terminate());
    client.on("error", () => ws.terminate());
  });

  client.on("error", () => {});
});

proxy.listen(LOCAL_PORT, "127.0.0.1", () => {
  console.log(`[FortiProxy] Local proxy ready on 127.0.0.1:${LOCAL_PORT}`);
  console.log(`[FortiProxy] Tunneling through ${SERVER}`);
  console.log("[FortiProxy] Set your system proxy to 127.0.0.1:8080");
  console.log("[FortiProxy] Press Ctrl+C to stop");
});
