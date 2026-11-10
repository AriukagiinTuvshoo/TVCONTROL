# FamilyScreen Android TV Box - Device Diagnostic Script
# Usage: .\scripts\android_tv\diagnose_device.ps1 [-DeviceId <serial/ip:port>]

param(
    [string]$DeviceId = ""
)

Write-Host "==========================================================" -ForegroundColor Cyan
Write-Host " FamilyScreen TV Box - Device Diagnostics" -ForegroundColor Cyan
Write-Host "==========================================================" -ForegroundColor Cyan

# 1. Check ADB Availability
$adbCmd = Get-Command adb -ErrorAction SilentlyContinue
if (-not $adbCmd) {
    Write-Host "[ERROR] ADB (Android Debug Bridge) is not installed or not in PATH!" -ForegroundColor Red
    Write-Host "Please download Android SDK Platform-Tools from:" -ForegroundColor Yellow
    Write-Host "  https://developer.android.com/tools/releases/platform-tools" -ForegroundColor Yellow
    Write-Host "Extract and add the directory containing 'adb.exe' to your PATH environment variable." -ForegroundColor Yellow
    exit 1
}

Write-Host "[OK] ADB found at: $($adbCmd.Source)" -ForegroundColor Green

# 2. Check Connected Devices
$adbArgs = @()
if ($DeviceId -ne "") {
    $adbArgs = @("-s", $DeviceId)
}

$rawDevices = & adb devices
$deviceLines = $rawDevices | Where-Object { $_ -match "\b(device|unauthorized|offline)\b" -and $_ -notmatch "List of devices" }

if (-not $deviceLines -or $deviceLines.Count -eq 0) {
    Write-Host "[ERROR] No Android TV Box detected!" -ForegroundColor Red
    Write-Host "To connect your TV Box over Wi-Fi:" -ForegroundColor Yellow
    Write-Host "  1. On your Android TV, open Settings -> Device Preferences -> About -> click 'Build' 7 times."
    Write-Host "  2. Go to Developer Options -> enable 'Network Debugging' (or 'USB Debugging')."
    Write-Host "  3. Find the TV's IP address (Settings -> Network & Internet)."
    Write-Host "  4. Run: adb connect <TV_IP_ADDRESS>:5555"
    Write-Host "  5. Re-run this diagnostic script."
    exit 1
}

Write-Host "[OK] Connected Device(s):" -ForegroundColor Green
$deviceLines | ForEach-Object { Write-Host "   $_" -ForegroundColor Gray }

# 3. Query Device Specs
Write-Host "`n--- Device Specifications ---" -ForegroundColor Cyan
$model = (& adb @adbArgs shell getprop ro.product.model).Trim()
$brand = (& adb @adbArgs shell getprop ro.product.brand).Trim()
$androidVer = (& adb @adbArgs shell getprop ro.build.version.release).Trim()
$sdkVer = (& adb @adbArgs shell getprop ro.build.version.sdk).Trim()
$abi = (& adb @adbArgs shell getprop ro.product.cpu.abi).Trim()

Write-Host "Brand/Model : $brand $model"
Write-Host "Android OS  : $androidVer (API Level $sdkVer)"
Write-Host "CPU ABI     : $abi"

if ([int]$sdkVer -lt 26) {
    Write-Host "[WARNING] Android API $sdkVer is below minimum supported API 26 (Android 8.0)!" -ForegroundColor Red
} else {
    Write-Host "[OK] Android version is fully compatible (minSdk = 26)" -ForegroundColor Green
}

# 4. Check FamilyScreen TV Installation
Write-Host "`n--- App Status (mn.familyscreen.tv) ---" -ForegroundColor Cyan
$pkgDump = & adb @adbArgs shell pm dump mn.familyscreen.tv 2>&1
if ($pkgDump -match "Unable to find package" -or $pkgDump -match "not installed") {
    Write-Host "[INFO] FamilyScreen TV app is NOT installed on this device." -ForegroundColor Yellow
    Write-Host "Run .\scripts\android_tv\install_clean.ps1 to install it." -ForegroundColor Yellow
} else {
    Write-Host "[OK] FamilyScreen TV is installed." -ForegroundColor Green
    $verName = ($pkgDump | Select-String "versionName=([^\s]+)").Matches.Groups[1].Value
    $verCode = ($pkgDump | Select-String "versionCode=([0-9]+)").Matches.Groups[1].Value
    Write-Host "Installed Version: $verName (Code: $verCode)"

    # Check Permissions
    Write-Host "`n--- Permissions & Special App Access ---" -ForegroundColor Cyan
    $usageStats = (& adb @adbArgs shell appops get mn.familyscreen.tv GET_USAGE_STATS).Trim()
    Write-Host "PACKAGE_USAGE_STATS (GET_USAGE_STATS): $usageStats"
    if ($usageStats -match "allow") {
        Write-Host "  -> [OK] Usage stats permission granted" -ForegroundColor Green
    } else {
        Write-Host "  -> [ACTION REQUIRED] Run: adb shell appops set mn.familyscreen.tv GET_USAGE_STATS allow" -ForegroundColor Red
    }

    $overlay = (& adb @adbArgs shell appops get mn.familyscreen.tv SYSTEM_ALERT_WINDOW).Trim()
    Write-Host "SYSTEM_ALERT_WINDOW (Overlay): $overlay"
    if ($overlay -match "allow") {
        Write-Host "  -> [OK] Overlay permission granted" -ForegroundColor Green
    } else {
        Write-Host "  -> [ACTION REQUIRED] Run: adb shell appops set mn.familyscreen.tv SYSTEM_ALERT_WINDOW allow" -ForegroundColor Red
    }

    # Check Default Home Launcher
    $homeActivity = (& adb @adbArgs shell cmd package resolve-activity --brief -c android.intent.category.HOME).Trim()
    Write-Host "Default Home Activity: $homeActivity"
    if ($homeActivity -match "mn.familyscreen.tv") {
        Write-Host "  -> [OK] FamilyScreen is the active default Home Launcher!" -ForegroundColor Green
    } else {
        Write-Host "  -> [NOTE] FamilyScreen is NOT the active default launcher." -ForegroundColor Yellow
        Write-Host "     Press HOME button on remote and select 'FamilyScreen TV' -> 'Always'." -ForegroundColor Yellow
    }
}

Write-Host "`n==========================================================" -ForegroundColor Cyan
Write-Host " Diagnostics Complete." -ForegroundColor Cyan
Write-Host "==========================================================" -ForegroundColor Cyan
