const http = require("http");
const https = require("https");
const net = require("net");
const url = require("url");

const PORT = process.env.PORT || 8080;
const AUTH_TOKEN = process.env.PROXY_TOKEN || "";

function checkAuth(req) {
  if (!AUTH_TOKEN) return true;
  const proxyAuth = req.headers["proxy-authorization"] || "";
  const [, encoded] = proxyAuth.split(" ");
  if (!encoded) return false;
  const decoded = Buffer.from(encoded, "base64").toString();
  return decoded === `proxy:${AUTH_TOKEN}`;
}

function sendAuthRequired(socket) {
  socket.write(
    "HTTP/1.1 407 Proxy Authentication Required\r\n" +
      "Proxy-Authenticate: Basic realm=\"FortiProxy\"\r\n" +
      "Content-Length: 0\r\n\r\n"
  );
  socket.destroy();
}

const server = http.createServer((req, res) => {
  if (!checkAuth(req)) {
    res.writeHead(407, { "Proxy-Authenticate": 'Basic realm="FortiProxy"' });
    res.end("Proxy Authentication Required");
    return;
  }

  const parsed = url.parse(req.url);
  const options = {
    hostname: parsed.hostname,
    port: parsed.port || 80,
    path: parsed.path,
    method: req.method,
    headers: req.headers,
  };

  delete options.headers["proxy-authorization"];

  const proxy = http.request(options, (proxyRes) => {
    res.writeHead(proxyRes.statusCode, proxyRes.headers);
    proxyRes.pipe(res, { end: true });
  });

  proxy.on("error", (err) => {
    console.error("HTTP proxy error:", err.message);
    res.writeHead(502);
    res.end("Bad Gateway");
  });

  req.pipe(proxy, { end: true });
});

// HTTPS tunneling via CONNECT
server.on("connect", (req, clientSocket, head) => {
  if (!checkAuth(req)) {
    sendAuthRequired(clientSocket);
    return;
  }

  const [hostname, port] = req.url.split(":");
  const targetPort = parseInt(port, 10) || 443;

  const serverSocket = net.connect(targetPort, hostname, () => {
    clientSocket.write(
      "HTTP/1.1 200 Connection Established\r\n" +
        "Proxy-agent: FortiProxy/1.0\r\n\r\n"
    );
    serverSocket.write(head);
    serverSocket.pipe(clientSocket);
    clientSocket.pipe(serverSocket);
  });

  serverSocket.on("error", (err) => {
    console.error("CONNECT tunnel error:", err.message);
    clientSocket.write(
      "HTTP/1.1 502 Bad Gateway\r\nContent-Length: 0\r\n\r\n"
    );
    clientSocket.destroy();
  });

  clientSocket.on("error", () => serverSocket.destroy());
});

server.listen(PORT, () => {
  console.log(`FortiProxy running on port ${PORT}`);
  if (AUTH_TOKEN) {
    console.log("Authentication: ENABLED");
  } else {
    console.log("Authentication: DISABLED (set PROXY_TOKEN env var to enable)");
  }
});
