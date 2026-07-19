# Life OS NucBox install (Windows-native path — no Docker required).
# Run from an elevated PowerShell:  powershell -ExecutionPolicy Bypass -File deploy\nucbox-install.ps1
# Idempotent: safe to re-run after git pull.
#
# Secrets: set TELEGRAM_BOT_TOKEN / TELEGRAM_OWNER_CHAT_ID / ANTHROPIC_API_KEY /
# LIFEOS_CALENDAR_ICS as USER environment variables before the tasks first run, e.g.
#   [Environment]::SetEnvironmentVariable("TELEGRAM_BOT_TOKEN", "...", "User")

$root = Split-Path $PSScriptRoot -Parent
Set-Location $root

if (-not (Test-Path "$root\.venv")) { python -m venv "$root\.venv" }
& "$root\.venv\Scripts\python.exe" -m pip install --quiet -r "$root\requirements.txt"
& "$root\.venv\Scripts\python.exe" -m substrate.migrate
& "$root\.venv\Scripts\python.exe" -m pytest -q
if ($LASTEXITCODE -ne 0) { Write-Error "Tests failed — not registering tasks."; exit 1 }

# Scheduled tasks keep the command line tiny (WinError 206 safe) by pointing at run_*.ps1
$ps = "powershell.exe"
$botArgs = "-NoProfile -ExecutionPolicy Bypass -File `"$root\deploy\run_bot.ps1`""
$gwArgs  = "-NoProfile -ExecutionPolicy Bypass -File `"$root\deploy\run_gateway.ps1`""

schtasks /Create /F /TN "LifeOS-Bot" /SC ONLOGON /TR "$ps $botArgs" | Out-Null
schtasks /Create /F /TN "LifeOS-Gateway" /SC ONLOGON /TR "$ps $gwArgs" | Out-Null

Write-Host "Installed. Start now with:"
Write-Host "  schtasks /Run /TN LifeOS-Bot"
Write-Host "  schtasks /Run /TN LifeOS-Gateway"
Write-Host "Logs: data\bot.log, data\gateway.log"
