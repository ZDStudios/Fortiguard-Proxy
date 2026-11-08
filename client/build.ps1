# Builds fortiproxy-client.exe (the Go tunnel client).
#
# Reads PROXY_TOKEN from secrets.env in the project root, XOR-obfuscates it with
# the key baked into main.go, and injects it at link time. The plain token never
# appears in source or in a `strings` scan of the exe.
#
#   cd client
#   .\build.ps1
#
# Output: ..\fortiproxy-client.exe (picked up by app\build_exe.py)

$ErrorActionPreference = "Stop"
$clientDir = $PSScriptRoot
$root      = Split-Path $clientDir -Parent

# ── Locate Go ─────────────────────────────────────────────────────────────────
if (-not (Get-Command go -ErrorAction SilentlyContinue)) {
    Write-Host "[ERROR] Go not found. Install it: winget install GoLang.Go" -ForegroundColor Red
    exit 1
}

# ── Read PROXY_TOKEN from secrets.env ─────────────────────────────────────────
$secretsPath = Join-Path $root "secrets.env"
if (-not (Test-Path $secretsPath)) {
    Write-Host "[ERROR] secrets.env not found in project root." -ForegroundColor Red
    Write-Host "        Copy secrets.env.example to secrets.env and fill in your token." -ForegroundColor Yellow
    exit 1
}

$token = $null
foreach ($line in Get-Content $secretsPath) {
    if ($line -match '^\s*PROXY_TOKEN\s*=\s*(.+?)\s*$') {
        $token = $Matches[1].Trim('"').Trim("'")
    }
}
if ([string]::IsNullOrWhiteSpace($token)) {
    Write-Host "[ERROR] PROXY_TOKEN missing or empty in secrets.env" -ForegroundColor Red
    exit 1
}

# ── XOR-obfuscate + base64 (must match obfKey in main.go) ─────────────────────
$obfKey = [byte[]](0x5A, 0x3C, 0x71, 0x2E, 0x88, 0x19, 0x4D, 0xA7)
$bytes  = [System.Text.Encoding]::UTF8.GetBytes($token)
for ($i = 0; $i -lt $bytes.Length; $i++) {
    $bytes[$i] = $bytes[$i] -bxor $obfKey[$i % $obfKey.Length]
}
$obf = [System.Convert]::ToBase64String($bytes)

# ── Build ─────────────────────────────────────────────────────────────────────
Push-Location $clientDir
try {
    Write-Host "[build] go mod tidy..."
    go mod tidy
    if ($LASTEXITCODE -ne 0) { throw "go mod tidy failed" }

    $out = Join-Path $root "fortiproxy-client.exe"
    Write-Host "[build] compiling fortiproxy-client.exe..."
    $env:GOOS = "windows"
    $env:GOARCH = "amd64"
    # -H windowsgui: no console window (the client runs hidden in the background;
    # the desktop app pipes its output). Avoids a flashing black window.
    go build -trimpath -ldflags "-s -w -H windowsgui -X main.tokenObf=$obf" -o $out .
    if ($LASTEXITCODE -ne 0) { throw "go build failed" }

    $kb = [math]::Round((Get-Item $out).Length / 1KB)
    Write-Host "[build] OK -> $out ($kb KB)" -ForegroundColor Green
}
finally {
    Pop-Location
}
