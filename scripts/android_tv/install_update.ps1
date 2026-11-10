# FamilyScreen Android TV Box - Update Installation Script
# Usage: .\scripts\android_tv\install_update.ps1 [-BackendUrl "http://192.168.1.YY:8000"] [-DeviceId <serial/ip:port>]

param(
    [string]$BackendUrl = "",
    [string]$DeviceId = ""
)

Write-Host "==========================================================" -ForegroundColor Cyan
Write-Host " FamilyScreen TV Box - Update Installation (Preserves Data)" -ForegroundColor Cyan
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

# 3. Locate APK
$apkPath = "build_output\apk\debug\app-debug.apk"
if (-not (Test-Path $apkPath)) {
    Write-Host "[ERROR] APK file not found at: $apkPath" -ForegroundColor Red
    exit 1
}

# 4. Install update with -r flag (preserves offline db, device_token, and settings)
Write-Host "`n[1/3] Updating app ($apkPath)..." -ForegroundColor Cyan
$installRes = & adb @adbArgs install -r $apkPath
Write-Host $installRes
if ($installRes -notmatch "Success") {
    Write-Host "[ERROR] Update installation failed!" -ForegroundColor Red
    exit 1
}

# 5. Ensure Permissions
Write-Host "[2/3] Verifying permissions..." -ForegroundColor Cyan
& adb @adbArgs shell pm grant mn.familyscreen.tv android.permission.PACKAGE_USAGE_STATS 2>&1 | Out-Null
& adb @adbArgs shell appops set mn.familyscreen.tv GET_USAGE_STATS allow
& adb @adbArgs shell appops set mn.familyscreen.tv SYSTEM_ALERT_WINDOW allow

# 6. Restart Activity
Write-Host "[3/3] Restarting FamilyScreen Launcher..." -ForegroundColor Cyan
$startArgs = @("shell", "am", "start", "-n", "mn.familyscreen.tv/.ui.FamilyScreenLauncherActivity")
if ($BackendUrl -ne "") {
    $startArgs += @("--es", "EXTRA_BACKEND_URL", "$BackendUrl")
}
& adb @adbArgs @startArgs

Write-Host "`n==========================================================" -ForegroundColor Green
Write-Host " Update Completed Successfully (Data Preserved)!" -ForegroundColor Green
Write-Host "==========================================================" -ForegroundColor Green
