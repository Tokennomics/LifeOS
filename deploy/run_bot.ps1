# Launch the Telegram bot from the repo root (short command line -> WinError 206 safe).
$root = Split-Path $PSScriptRoot -Parent
Set-Location $root
New-Item -ItemType Directory -Force (Join-Path $root "data") | Out-Null
& "$root\.venv\Scripts\python.exe" -m surfaces.bot.telegram *>> "$root\data\bot.log"
