# Launch the HTTP gateway from the repo root (short command line -> WinError 206 safe).
$root = Split-Path $PSScriptRoot -Parent
Set-Location $root
New-Item -ItemType Directory -Force (Join-Path $root "data") | Out-Null
& "$root\.venv\Scripts\python.exe" -m uvicorn gateway.main:create_app --factory --host 127.0.0.1 --port 8787 *>> "$root\data\gateway.log"
