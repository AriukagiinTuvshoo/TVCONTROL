#!/usr/bin/env bash
# FamilyScreen Android TV Box - Uninstall & Rollback Script
# Usage: ./scripts/android_tv/uninstall_rollback.sh [-r "path/to/previous.apk"] [-s <serial/ip:port>]

set -e

ROLLBACK_APK=""
DEVICE_ARG=""

while getopts "r:s:" opt; do
  case $opt in
    r) ROLLBACK_APK="$OPTARG" ;;
    s) DEVICE_ARG="-s $OPTARG" ;;
    *) echo "Usage: $0 [-r <rollback_apk_path>] [-s <device_id>]" && exit 1 ;;
  esac
done

echo "=========================================================="
echo " FamilyScreen TV Box - Uninstall & Rollback"
echo "=========================================================="

if ! command -v adb &> /dev/null; then
    echo "[ERROR] ADB is not installed or not in PATH!"
    exit 1
fi

echo "[1/3] Resetting default Home activity..."
adb $DEVICE_ARG shell cmd package set-home-activity --clear || true

echo "[2/3] Uninstalling mn.familyscreen.tv..."
adb $DEVICE_ARG uninstall mn.familyscreen.tv

if [ -n "$ROLLBACK_APK" ] && [ -f "$ROLLBACK_APK" ]; then
    echo "[3/3] Installing rollback APK ($ROLLBACK_APK)..."
    adb $DEVICE_ARG install -r -d "$ROLLBACK_APK"
    adb $DEVICE_ARG shell pm grant mn.familyscreen.tv android.permission.PACKAGE_USAGE_STATS || true
    adb $DEVICE_ARG shell appops set mn.familyscreen.tv GET_USAGE_STATS allow
    adb $DEVICE_ARG shell appops set mn.familyscreen.tv SYSTEM_ALERT_WINDOW allow
    adb $DEVICE_ARG shell am start -n mn.familyscreen.tv/.ui.FamilyScreenLauncherActivity
else
    echo "[3/3] No rollback APK specified. Device restored to factory default launcher."
fi

echo "=========================================================="
echo " Rollback / Uninstall Process Complete."
echo "=========================================================="
