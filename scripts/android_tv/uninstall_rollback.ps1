# FamilyScreen Android TV Box - Uninstall / Rollback Script
# Usage: .\scripts\android_tv\uninstall_rollback.ps1 [-RollbackApk "path\to\previous.apk"] [-DeviceId <serial/ip:port>]

param(
    [string]$RollbackApk = "",
    [string]$DeviceId = ""
)

Write-Host "==========================================================" -ForegroundColor Cyan
Write-Host " FamilyScreen TV Box - Uninstall & Rollback" -ForegroundColor Cyan
Write-Host "==========================================================" -ForegroundColor Cyan

# 1. Check ADB
$adbCmd = Get-Command adb -ErrorAction SilentlyContinue
if (-not $adbCmd) {
    Write-Host "[ERROR] ADB is not installed or not in PATH!" -ForegroundColor Red
    exit 1
}

# 2. Check Device
$adbArgs = @()
if ($DeviceId -ne "") {
    $adbArgs = @("-s", $DeviceId)
}

$rawDevices = & adb devices
$deviceLines = $rawDevices | Where-Object { $_ -match "\bdevice\b" -and $_ -notmatch "List of devices" }
if (-not $deviceLines) {
    Write-Host "[ERROR] No authorized Android device connected!" -ForegroundColor Red
    exit 1
}

# 3. Clear Home Activity Default
Write-Host "`n[1/3] Resetting default Android TV Home Launcher..." -ForegroundColor Cyan
& adb @adbArgs shell cmd package set-home-activity --clear 2>&1 | Out-Null
Write-Host "[OK] Default Home launcher reset." -ForegroundColor Green

# 4. Uninstall Package
Write-Host "[2/3] Uninstalling mn.familyscreen.tv..." -ForegroundColor Cyan
$uninstRes = & adb @adbArgs uninstall mn.familyscreen.tv
Write-Host $uninstRes

# 5. Rollback to previous APK if specified
if ($RollbackApk -ne "") {
    if (Test-Path $RollbackApk) {
        Write-Host "`n[3/3] Installing rollback APK ($RollbackApk)..." -ForegroundColor Cyan
        $rollRes = & adb @adbArgs install -r -d $RollbackApk
        Write-Host $rollRes
        if ($rollRes -match "Success") {
            Write-Host "[OK] Rollback APK installed successfully." -ForegroundColor Green
            & adb @adbArgs shell pm grant mn.familyscreen.tv android.permission.PACKAGE_USAGE_STATS 2>&1 | Out-Null
            & adb @adbArgs shell appops set mn.familyscreen.tv GET_USAGE_STATS allow
            & adb @adbArgs shell appops set mn.familyscreen.tv SYSTEM_ALERT_WINDOW allow
            & adb @adbArgs shell am start -n mn.familyscreen.tv/.ui.FamilyScreenLauncherActivity
        }
    } else {
        Write-Host "[WARNING] Rollback APK path not found: $RollbackApk" -ForegroundColor Yellow
    }
} else {
    Write-Host "[3/3] No rollback APK specified. Device restored to factory default launcher." -ForegroundColor Cyan
}

Write-Host "`n==========================================================" -ForegroundColor Green
Write-Host " Rollback / Uninstall Process Complete." -ForegroundColor Green
Write-Host "==========================================================" -ForegroundColor Green
