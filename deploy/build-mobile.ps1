# Build the LifeOS native shells (Capacitor) around surfaces\app\www.
#
# No tokens or API keys are required by the app — it talks to your own gateway,
# which runs fully offline-fallback without ANTHROPIC_API_KEY.
#
# ANDROID (this machine, once Android Studio is installed):
#   1. Install Android Studio (brings the SDK + an emulator).
#   2. powershell -ExecutionPolicy Bypass -File deploy\build-mobile.ps1
#   3. npx cap open android   -> Run on device/emulator, or Build > APK.
#
# iOS (requires a Mac — Apple does not allow iOS builds elsewhere):
#   cd surfaces/app && npm install && npx cap add ios && npx cap open ios
#
# NO-TOOLCHAIN PATH (works TODAY on both platforms): install as a PWA.
#   Phone on the same network -> http://<this-pc>:8787/app/
#   iOS Safari: Share -> Add to Home Screen.  Android Chrome: menu -> Install app.

$app = Join-Path (Split-Path $PSScriptRoot -Parent) "surfaces\app"
Set-Location $app

npm install
if ($LASTEXITCODE -ne 0) { Write-Error "npm install failed"; exit 1 }

if (-not (Test-Path "$app\android")) { npx cap add android }
npx cap sync android

Write-Host ""
Write-Host "Android project ready at surfaces\app\android."
Write-Host "Open it:  npx cap open android   (requires Android Studio to build the APK)"
Write-Host "First run: open the in-app Settings (gear) and set your gateway URL, e.g. http://nucbox:8787"
