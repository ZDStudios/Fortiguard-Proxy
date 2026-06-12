const http = require("http");
const net = require("net");
const { WebSocket, WebSocketServer } = require("ws");

const PORT = process.env.PORT || 8080;
const TOKEN = process.env.PROXY_TOKEN || "";

const server = http.createServer((req, res) => {
  res.writeHead(200, { "Content-Type": "text/plain" });
  res.end("FortiProxy OK");
});

const wss = new WebSocketServer({ server, path: "/tunnel" });

wss.on("connection", (ws, req) => {
  const params = new URL(req.url, "http://localhost").searchParams;

  if (TOKEN && params.get("token") !== TOKEN) {
    ws.close(4001, "Unauthorized");
    return;
  }

  const host = params.get("host");
  const port = parseInt(params.get("port"), 10) || 80;

  if (!host) {
    ws.close(4002, "Missing host");
    return;
  }

  const socket = net.connect(port, host);

  socket.on("connect", () => {
    ws.on("message", (data) => {
      if (!socket.destroyed) socket.write(data);
    });
  });

  socket.on("data", (data) => {
    if (ws.readyState === WebSocket.OPEN) ws.send(data);
  });

  socket.on("error", (err) => {
    console.error(`TCP error ${host}:${port} — ${err.message}`);
    ws.close(4003, err.message);
  });

  socket.on("close", () => ws.terminate());
  ws.on("close", () => socket.destroy());
  ws.on("error", () => socket.destroy());
});

server.listen(PORT, () => {
  console.log(`FortiProxy running on port ${PORT}`);
  console.log(TOKEN ? "Auth: ENABLED" : "Auth: DISABLED");
});
