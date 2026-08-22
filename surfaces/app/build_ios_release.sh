#!/usr/bin/env bash
# =========================================================================
#  LifeOS iOS Release Build & Xcode Prep Automation
# =========================================================================
set -e

echo "[1/2] Synchronizing Web Assets with Capacitor iOS..."
npx cap sync ios

echo "[2/2] Opening Xcode Workspace for App Store Archive / TestFlight..."
npx cap open ios

echo "------------------------------------------------------------------------"
echo " In Xcode: Select 'Any iOS Device (arm64)' -> Product -> Archive"
echo " Then Distribute App -> App Store Connect / TestFlight"
echo "------------------------------------------------------------------------"
