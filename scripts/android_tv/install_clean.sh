#!/usr/bin/env bash
# FamilyScreen Android TV Box - Clean Installation Script
# Usage: ./scripts/android_tv/install_clean.sh [-u "http://192.168.1.YY:8000"] [-s <serial/ip:port>]

set -e

BACKEND_URL="http://10.0.2.2:8000"
DEVICE_ARG=""

while getopts "u:s:" opt; do
  case $opt in
    u) BACKEND_URL="$OPTARG" ;;
    s) DEVICE_ARG="-s $OPTARG" ;;
    *) echo "Usage: $0 [-u <backend_url>] [-s <device_id>]" && exit 1 ;;
  esac
done

echo "=========================================================="
echo " FamilyScreen TV Box - Clean Installation"
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

echo "[1/4] Uninstalling any previous version for clean state..."
adb $DEVICE_ARG uninstall mn.familyscreen.tv || true

echo "[2/4] Installing $APK_PATH..."
adb $DEVICE_ARG install -r "$APK_PATH"

echo "[3/4] Granting required Android TV permissions..."
adb $DEVICE_ARG shell pm grant mn.familyscreen.tv android.permission.PACKAGE_USAGE_STATS || true
adb $DEVICE_ARG shell appops set mn.familyscreen.tv GET_USAGE_STATS allow
adb $DEVICE_ARG shell appops set mn.familyscreen.tv SYSTEM_ALERT_WINDOW allow

SDK_VER=$(adb $DEVICE_ARG shell getprop ro.build.version.sdk | tr -d '\r')
if [ "$SDK_VER" -ge 33 ]; then
    adb $DEVICE_ARG shell pm grant mn.familyscreen.tv android.permission.POST_NOTIFICATIONS || true
fi

echo "[4/4] Launching Launcher with Backend URL: $BACKEND_URL..."
adb $DEVICE_ARG shell am start -n mn.familyscreen.tv/.ui.FamilyScreenLauncherActivity --es EXTRA_BACKEND_URL "$BACKEND_URL"

echo "=========================================================="
echo " Installation Complete!"
echo "=========================================================="
