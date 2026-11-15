# Builds FortiProxy.exe (in the repo root) with the server URL, proxy token and
# version baked in. The version comes from docs\version.txt so the auto-updater
# always knows which build it is.
$ErrorActionPreference = 'Stop'
Set-Location $PSScriptRoot
$env:Path += ';C:\Program Files\Go\bin'

function New-Secret($bytes) {
    $b = New-Object byte[] $bytes
    [Security.Cryptography.RandomNumberGenerator]::Create().GetBytes($b)
    -join ($b | ForEach-Object { $_.ToString('x2') })
}

if (-not (Test-Path secrets.env)) {
    @(
        'PROXY_URL=https://proxy.zdstudios.network'
        "PROXY_TOKEN=$(New-Secret 32)"
    ) | Set-Content secrets.env -Encoding ascii
    Write-Host 'Created secrets.env — set PROXY_TOKEN to your server token, then run again.'
    exit 1
}

$secrets = @{}
foreach ($line in Get-Content secrets.env) {
    if ($line -match '^\s*([A-Z_]+)=(.*)$') { $secrets[$Matches[1]] = $Matches[2].Trim() }
}
if (-not $secrets.PROXY_URL)   { $secrets.PROXY_URL = 'https://proxy.zdstudios.network' }
if (-not $secrets.PROXY_TOKEN) { throw 'secrets.env has no PROXY_TOKEN' }

$version = (Get-Content docs\version.txt -Raw).Trim()
if (-not $version) { throw 'docs\version.txt is empty' }

Push-Location cmd\client
go run github.com/tc-hib/go-winres@v0.3.3 make --in winres\winres.json --out rsrc --arch amd64
$code = $LASTEXITCODE
Pop-Location
if ($code -ne 0) { throw 'Generating the app icon and manifest failed' }

$ldflags = "-s -w -H=windowsgui " +
    "-X main.serverURL=$($secrets.PROXY_URL) " +
    "-X main.proxyToken=$($secrets.PROXY_TOKEN) " +
    "-X main.appVersion=$version"
go build -trimpath -tags with_gvisor -ldflags $ldflags -o FortiProxy.exe .\cmd\client
if ($LASTEXITCODE -ne 0) { throw 'Build failed' }
Write-Host "Built FortiProxy.exe ($version) for $($secrets.PROXY_URL)"
