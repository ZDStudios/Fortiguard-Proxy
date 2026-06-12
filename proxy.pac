function FindProxyForURL(url, host) {
    // Always go direct for local addresses
    if (isPlainHostName(host) ||
        isInNet(host, "127.0.0.1", "255.255.255.255") ||
        isInNet(host, "10.0.0.0",  "255.0.0.0")       ||
        isInNet(host, "192.168.0.0", "255.255.0.0"))   {
        return "DIRECT";
    }
    // Try proxy first — if it's not running, fall back to DIRECT automatically
    return "PROXY 127.0.0.1:8080; DIRECT";
}
