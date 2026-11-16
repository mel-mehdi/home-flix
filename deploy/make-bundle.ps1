# Packs HomeFlix into homeflix-bundle.tgz for upload to the Oracle server (steps in deploy/ORACLE.md).
# .env is left out on purpose: it holds your keys, so you copy it to the server yourself.
# The database is copied with SQLite's backup, so a sync running at the same moment can't corrupt the copy.

$ErrorActionPreference = 'Stop'
$root = Split-Path $PSScriptRoot -Parent
$stage = Join-Path ([IO.Path]::GetTempPath()) 'homeflix-bundle'
$out = Join-Path $root 'homeflix-bundle.tgz'

if (Test-Path $stage) { Remove-Item $stage -Recurse -Force }
New-Item -ItemType Directory $stage | Out-Null

# robocopy exit codes below 8 mean success
robocopy $root $stage /E /NFL /NDL /NJH /NJS /NP `
    /XD .git .venv __pycache__ .claude `
    /XF .env homeflix.db 'homeflix.db.bak-*' tunnel.log tunnel-url.txt homeflix-bundle.tgz '*.pyc' | Out-Null
if ($LASTEXITCODE -ge 8) { throw "Copying the project failed (robocopy code $LASTEXITCODE)" }

$python = Join-Path $root '.venv\Scripts\python.exe'
if (-not (Test-Path $python)) { $python = 'python' }
# VACUUM rebuilds the copy, which also drops unused pages SQLite's integrity check complains about
& $python -c "import sqlite3, sys; src = sqlite3.connect(sys.argv[1]); dst = sqlite3.connect(sys.argv[2]); src.backup(dst); dst.execute('VACUUM'); print('database copy:', dst.execute('pragma integrity_check').fetchone()[0]); dst.close()" `
    (Join-Path $root 'homeflix.db') (Join-Path $stage 'homeflix.db')
if ($LASTEXITCODE -ne 0) { throw 'Copying the database failed' }

if (Test-Path $out) { Remove-Item $out }
tar.exe -czf $out -C $stage .
if ($LASTEXITCODE -ne 0) { throw 'Packing failed' }
Remove-Item $stage -Recurse -Force

$size = '{0:N1} MB' -f ((Get-Item $out).Length / 1MB)
Write-Host "Ready to upload: $out ($size)" -ForegroundColor Green
