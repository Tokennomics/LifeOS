# Launch the HTTP gateway from the repo root (short command line -> WinError 206 safe).
# Binds 0.0.0.0 so your phone on the same network can reach the app at http://<pc>:8787/app/
# — set LIFEOS_GATEWAY_TOKEN if the network isn't fully trusted.
$root = Split-Path $PSScriptRoot -Parent
Set-Location $root
New-Item -ItemType Directory -Force (Join-Path $root "data") | Out-Null
& "$root\.venv\Scripts\python.exe" -m uvicorn gateway.main:create_app --factory --host 0.0.0.0 --port 8787 *>> "$root\data\gateway.log"
