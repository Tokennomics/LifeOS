@echo off
REM =========================================================================
REM  LifeOS Android Release Build Automation
REM =========================================================================
echo [1/3] Synchronizing Web Assets with Capacitor...
call npx.cmd cap sync android
if %errorlevel% neq 0 (
    echo [ERROR] Capacitor sync failed!
    exit /b %errorlevel%
)

echo [2/3] Building Android App Bundle (.aab) for Google Play...
cd android
call gradlew.bat bundleRelease
if %errorlevel% neq 0 (
    echo [ERROR] Gradle bundleRelease build failed!
    cd ..
    exit /b %errorlevel%
)
cd ..

echo [3/3] Build Complete!
echo ------------------------------------------------------------------------
echo  Release Bundle: surfaces\app\android\app\build\outputs\bundle\release\app-release.aab
echo  Debug APK:      surfaces\app\android\app\build\outputs\apk\debug\app-debug.apk
echo ------------------------------------------------------------------------
echo Ready for upload to Google Play Console!
