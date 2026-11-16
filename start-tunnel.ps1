# Opens the public link to HomeFlix (a free Cloudflare quick tunnel) and saves it in tunnel-url.txt.
# The link changes every time the tunnel starts; rebuilding or restarting the Docker image doesn't change it.
# Run it again any time: if the tunnel is already up it only shows the current link.
# -AtSignIn (used by the Windows Startup shortcut): open Docker Desktop if needed and wait for HomeFlix.

param([switch]$AtSignIn)

$ErrorActionPreference = 'Stop'
$cloudflared = 'C:\Program Files (x86)\cloudflared\cloudflared.exe'
$log = Join-Path $PSScriptRoot 'tunnel.log'
$urlFile = Join-Path $PSScriptRoot 'tunnel-url.txt'

function Test-Url($url) {
    try { (Invoke-WebRequest "$url/login" -UseBasicParsing -TimeoutSec 15).StatusCode -eq 200 } catch { $false }
}

function Test-HomeFlix {
    try { Invoke-WebRequest 'http://localhost:5000/login' -UseBasicParsing -TimeoutSec 5 | Out-Null; $true } catch { $false }
}

if ($AtSignIn -and -not (Test-HomeFlix)) {
    # The HomeFlix containers restart by themselves once Docker is running (restart: always)
    if (-not (Get-Process 'Docker Desktop' -ErrorAction SilentlyContinue)) {
        Start-Process 'C:\Program Files\Docker\Docker\Docker Desktop.exe'
    }
    for ($i = 0; $i -lt 60 -and -not (Test-HomeFlix); $i++) { Start-Sleep -Seconds 5 }
}

if (-not (Test-HomeFlix)) {
    Write-Host 'HomeFlix is not running on this PC. Start Docker Desktop, wait a minute, and run this again.' -ForegroundColor Yellow
    exit 1
}

if ((Get-Process cloudflared -ErrorAction SilentlyContinue) -and (Test-Path $urlFile)) {
    $url = (Get-Content $urlFile -TotalCount 1).Trim()
    if (Test-Url $url) {
        Write-Host "HomeFlix is already online: $url" -ForegroundColor Green
        exit 0
    }
}

Remove-Item $log, $urlFile -ErrorAction SilentlyContinue
# Hidden, so closing a terminal doesn't take the link down; it stops when the PC shuts down
Start-Process $cloudflared -ArgumentList 'tunnel', '--no-autoupdate', '--url', 'http://localhost:5000', '--logfile', "`"$log`"" -WindowStyle Hidden

$url = $null
for ($i = 0; $i -lt 60 -and -not $url; $i++) {
    Start-Sleep -Seconds 1
    if (Test-Path $log) {
        $match = Select-String -Path $log -Pattern 'https://[a-z0-9-]+\.trycloudflare\.com' | Select-Object -First 1
        if ($match) { $url = $match.Matches[0].Value }
    }
}
if (-not $url) {
    Write-Host "The tunnel didn't give a link within a minute. Details: $log" -ForegroundColor Yellow
    exit 1
}

Set-Content -Path $urlFile -Value $url -Encoding ascii
# A new link takes a few seconds before Cloudflare answers on it
for ($i = 0; $i -lt 20 -and -not (Test-Url $url); $i++) { Start-Sleep -Seconds 2 }
Write-Host "HomeFlix is online: $url" -ForegroundColor Green
Write-Host "Saved in $urlFile"
