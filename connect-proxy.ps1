$dir     = $PSScriptRoot + "\"
$regPath = "HKCU:\Software\Microsoft\Windows\CurrentVersion\Internet Settings"
$pacUrl  = [uri]::new((Join-Path $dir "proxy.pac")).AbsoluteUri

function Enable-Proxy {
    Set-ItemProperty $regPath AutoConfigURL $pacUrl
    Set-ItemProperty $regPath ProxyEnable   1
    # Clear direct ProxyServer so only the PAC is used
    Remove-ItemProperty $regPath ProxyServer -ErrorAction SilentlyContinue
}

function Disable-Proxy {
    Set-ItemProperty $regPath ProxyEnable 0
    Remove-ItemProperty $regPath AutoConfigURL -ErrorAction SilentlyContinue
    Write-Host ""
    Write-Host "[FortiProxy] Proxy disabled. Internet restored."
}

# ── Check Node ────────────────────────────────────────────────────────────────
try { $null = Get-Command node -ErrorAction Stop }
catch {
    Write-Host "[ERROR] Node.js not found. Download from https://nodejs.org"
    Read-Host  "Press Enter to exit"
    exit 1
}

# ── Install ws if needed ──────────────────────────────────────────────────────
if (-not (Test-Path (Join-Path $dir "node_modules\ws"))) {
    Write-Host "[....] Installing dependencies..."
    Push-Location $dir
    npm install
    $code = $LASTEXITCODE
    Pop-Location
    if ($code -ne 0) {
        Write-Host "[ERROR] npm install failed — see output above"
        Read-Host  "Press Enter to exit"
        exit 1
    }
    Write-Host "[OK]   Dependencies installed"
}

Write-Host ""
Write-Host " ==================================="
Write-Host "  FortiProxy Connector"
Write-Host " ==================================="
Write-Host ""
Write-Host "[OK]   PAC file: $pacUrl"

try {
    Enable-Proxy
    Write-Host "[OK]   System proxy enabled (PAC — auto-fallback to DIRECT when off)"
    Write-Host ""
    Write-Host "[....] Connecting to fortiguard-proxy.onrender.com..."
    Write-Host "       Close this window to disconnect."
    Write-Host ""
    & node (Join-Path $dir "client.js")
    if ($LASTEXITCODE -ne 0) {
        Write-Host ""
        Write-Host "[ERROR] client.js exited with code $LASTEXITCODE — see output above"
    }
}
finally {
    Disable-Proxy
    Read-Host "Press Enter to close"
}
