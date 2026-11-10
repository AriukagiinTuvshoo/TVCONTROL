#!/usr/bin/env bash
# FamilyScreen Android TV Box - Device Diagnostic Script
# Usage: ./scripts/android_tv/diagnose_device.sh [-s <serial/ip:port>]

set -e

DEVICE_ARG=""
while getopts "s:" opt; do
  case $opt in
    s) DEVICE_ARG="-s $OPTARG" ;;
    *) echo "Usage: $0 [-s <device_id>]" && exit 1 ;;
  esac
done

echo "=========================================================="
echo " FamilyScreen TV Box - Device Diagnostics"
echo "=========================================================="

if ! command -v adb &> /dev/null; then
    echo "[ERROR] ADB (Android Debug Bridge) is not installed or not in PATH!"
    echo "Please download platform-tools from: https://developer.android.com/tools/releases/platform-tools"
    exit 1
fi

echo "[OK] ADB found at: $(command -v adb)"

DEVICES=$(adb devices | grep -E '\b(device|unauthorized|offline)\b' | grep -v 'List of devices' || true)
if [ -z "$DEVICES" ]; then
    echo "[ERROR] No Android TV Box detected!"
    echo "To connect via Wi-Fi: adb connect <TV_IP>:5555"
    exit 1
fi

echo "[OK] Connected Device(s):"
echo "$DEVICES"

echo ""
echo "--- Device Specifications ---"
BRAND=$(adb $DEVICE_ARG shell getprop ro.product.brand | tr -d '\r')
MODEL=$(adb $DEVICE_ARG shell getprop ro.product.model | tr -d '\r')
ANDROID_VER=$(adb $DEVICE_ARG shell getprop ro.build.version.release | tr -d '\r')
SDK_VER=$(adb $DEVICE_ARG shell getprop ro.build.version.sdk | tr -d '\r')
ABI=$(adb $DEVICE_ARG shell getprop ro.product.cpu.abi | tr -d '\r')

echo "Brand/Model : $BRAND $MODEL"
echo "Android OS  : $ANDROID_VER (API Level $SDK_VER)"
echo "CPU ABI     : $ABI"

if [ "$SDK_VER" -lt 26 ]; then
    echo "[WARNING] Android API $SDK_VER is below minimum supported API 26 (Android 8.0)!"
else
    echo "[OK] Android version is fully compatible (minSdk = 26)"
fi

echo ""
echo "--- App Status (mn.familyscreen.tv) ---"
if adb $DEVICE_ARG shell pm dump mn.familyscreen.tv | grep -q "Unable to find package"; then
    echo "[INFO] FamilyScreen TV app is NOT installed on this device."
    echo "Run ./scripts/android_tv/install_clean.sh to install it."
else
    echo "[OK] FamilyScreen TV is installed."
    USAGE_STATS=$(adb $DEVICE_ARG shell appops get mn.familyscreen.tv GET_USAGE_STATS | tr -d '\r')
    OVERLAY=$(adb $DEVICE_ARG shell appops get mn.familyscreen.tv SYSTEM_ALERT_WINDOW | tr -d '\r')
    echo "PACKAGE_USAGE_STATS: $USAGE_STATS"
    echo "SYSTEM_ALERT_WINDOW: $OVERLAY"
    
    HOME_ACT=$(adb $DEVICE_ARG shell cmd package resolve-activity --brief -c android.intent.category.HOME | tr -d '\r')
    echo "Default Home Activity: $HOME_ACT"
fi

echo "=========================================================="
