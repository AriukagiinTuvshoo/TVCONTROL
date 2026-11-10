#!/usr/bin/env bash
# FamilyScreen Android TV Box - Update Installation Script
# Usage: ./scripts/android_tv/install_update.sh [-u "http://192.168.1.YY:8000"] [-s <serial/ip:port>]

set -e

BACKEND_URL=""
DEVICE_ARG=""

while getopts "u:s:" opt; do
  case $opt in
    u) BACKEND_URL="$OPTARG" ;;
    s) DEVICE_ARG="-s $OPTARG" ;;
    *) echo "Usage: $0 [-u <backend_url>] [-s <device_id>]" && exit 1 ;;
  esac
done

echo "=========================================================="
echo " FamilyScreen TV Box - Update Installation (Preserves Data)"
echo "=========================================================="

if ! command -v adb &> /dev/null; then
    echo "[ERROR] ADB is not installed or not in PATH!"
    exit 1
fi

APK_PATH="build_output/apk/debug/app-debug.apk"
if [ ! -f "$APK_PATH" ]; then
    echo "[ERROR] APK file not found at: $APK_PATH"
    exit 1
fi

echo "[1/3] Updating $APK_PATH..."
adb $DEVICE_ARG install -r "$APK_PATH"

echo "[2/3] Verifying permissions..."
adb $DEVICE_ARG shell pm grant mn.familyscreen.tv android.permission.PACKAGE_USAGE_STATS || true
adb $DEVICE_ARG shell appops set mn.familyscreen.tv GET_USAGE_STATS allow
adb $DEVICE_ARG shell appops set mn.familyscreen.tv SYSTEM_ALERT_WINDOW allow

echo "[3/3] Restarting FamilyScreen Launcher..."
if [ -n "$BACKEND_URL" ]; then
    adb $DEVICE_ARG shell am start -n mn.familyscreen.tv/.ui.FamilyScreenLauncherActivity --es EXTRA_BACKEND_URL "$BACKEND_URL"
else
    adb $DEVICE_ARG shell am start -n mn.familyscreen.tv/.ui.FamilyScreenLauncherActivity
fi

echo "=========================================================="
echo " Update Complete!"
echo "=========================================================="
