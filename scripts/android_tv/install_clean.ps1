# FamilyScreen Android TV Box - Clean Installation Script
# Usage: .\scripts\android_tv\install_clean.ps1 [-BackendUrl "http://192.168.1.YY:8000"] [-DeviceId <serial/ip:port>]

param(
    [string]$BackendUrl = "http://10.0.2.2:8000",
    [string]$DeviceId = ""
)

Write-Host "==========================================================" -ForegroundColor Cyan
Write-Host " FamilyScreen TV Box - Clean Installation" -ForegroundColor Cyan
Write-Host "==========================================================" -ForegroundColor Cyan

# 1. Check ADB
$adbCmd = Get-Command adb -ErrorAction SilentlyContinue
if (-not $adbCmd) {
    Write-Host "[ERROR] ADB is not installed or not in PATH!" -ForegroundColor Red
    Write-Host "Please install Android Platform-Tools and add adb to PATH." -ForegroundColor Yellow
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
    Write-Host "Run: adb connect <TV_IP_ADDRESS>:5555" -ForegroundColor Yellow
    exit 1
}

# 3. Locate APK
$apkPath = "build_output\apk\debug\app-debug.apk"
if (-not (Test-Path $apkPath)) {
    Write-Host "[ERROR] APK file not found at: $apkPath" -ForegroundColor Red
    Write-Host "Please download or build app-debug.apk first." -ForegroundColor Yellow
    exit 1
}

Write-Host "[OK] Target APK found ($([math]::Round((Get-Item $apkPath).Length / 1MB, 2)) MB)" -ForegroundColor Green

# 4. Uninstall existing version for clean install
Write-Host "`n[1/4] Uninstalling any existing version for clean install..." -ForegroundColor Cyan
& adb @adbArgs uninstall mn.familyscreen.tv 2>&1 | Out-Null

# 5. Install APK
Write-Host "[2/4] Installing $apkPath..." -ForegroundColor Cyan
$installRes = & adb @adbArgs install -r $apkPath
Write-Host $installRes
if ($installRes -notmatch "Success") {
    Write-Host "[ERROR] Installation failed!" -ForegroundColor Red
    exit 1
}

# 6. Grant Permissions
Write-Host "[3/4] Granting required Android TV permissions..." -ForegroundColor Cyan
& adb @adbArgs shell pm grant mn.familyscreen.tv android.permission.PACKAGE_USAGE_STATS 2>&1 | Out-Null
& adb @adbArgs shell appops set mn.familyscreen.tv GET_USAGE_STATS allow
& adb @adbArgs shell appops set mn.familyscreen.tv SYSTEM_ALERT_WINDOW allow

# Grant notification permission if Android 13+
$sdkVer = (& adb @adbArgs shell getprop ro.build.version.sdk).Trim()
if ([int]$sdkVer -ge 33) {
    & adb @adbArgs shell pm grant mn.familyscreen.tv android.permission.POST_NOTIFICATIONS 2>&1 | Out-Null
}

Write-Host "[OK] Permissions configured successfully." -ForegroundColor Green

# 7. Launch Activity with Configured Backend URL
Write-Host "[4/4] Launching FamilyScreen TV with Backend: $BackendUrl..." -ForegroundColor Cyan
& adb @adbArgs shell am start -n mn.familyscreen.tv/.ui.FamilyScreenLauncherActivity --es EXTRA_BACKEND_URL "$BackendUrl"

Write-Host "`n==========================================================" -ForegroundColor Green
Write-Host " Installation Successful!" -ForegroundColor Green
Write-Host " Next Steps:" -ForegroundColor Cyan
Write-Host "  1. On TV, when prompted 'Select a Home app', choose 'FamilyScreen TV' -> 'Always'."
Write-Host "  2. Read the 6-digit pairing code displayed on screen."
Write-Host "  3. Open the FamilyScreen Mobile App and complete pairing."
Write-Host "==========================================================" -ForegroundColor Green
