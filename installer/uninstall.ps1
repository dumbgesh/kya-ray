# installer/uninstall.ps1 - Windows Uninstaller for Kya-Ray
[CmdletBinding()]
param(
    [string]$InstallDir = "$env:LOCALAPPDATA\Programs\Kya-Ray",
    [switch]$KeepUserData
)

$ErrorActionPreference = "SilentlyContinue"

Write-Host "==========================================================" -ForegroundColor Yellow
Write-Host "             Uninstalling Kya-Ray Desktop                 " -ForegroundColor Yellow
Write-Host "==========================================================" -ForegroundColor Yellow
Write-Host ""

# 1. Terminate running Kya-Ray processes
Write-Host "[1/4] Closing any running Kya-Ray instances..." -ForegroundColor Gray
Get-Process -Name "Kya-Ray" | Stop-Process -Force
Start-Sleep -Milliseconds 800

# 2. Remove Shortcuts
Write-Host "[2/4] Removing Start Menu and Desktop shortcuts..." -ForegroundColor Gray
$startShortcut = "$env:APPDATA\Microsoft\Windows\Start Menu\Programs\Kya-Ray.lnk"
if (Test-Path $startShortcut) { Remove-Item -Path $startShortcut -Force }

$desktopShortcut = Join-Path ([Environment]::GetFolderPath("Desktop")) "Kya-Ray.lnk"
if (Test-Path $desktopShortcut) { Remove-Item -Path $desktopShortcut -Force }

# 3. Remove Registry Uninstall Key
Write-Host "[3/4] Removing Windows Add/Remove Programs entry..." -ForegroundColor Gray
$regPath = "HKCU:\Software\Microsoft\Windows\CurrentVersion\Uninstall\Kya-Ray"
if (Test-Path $regPath) { Remove-Item -Path $regPath -Recurse -Force }

# 4. Remove Installation Directory
Write-Host "[4/4] Removing application directory..." -ForegroundColor Gray
if (Test-Path $InstallDir) {
    if ($KeepUserData) {
        Get-ChildItem -Path $InstallDir -Exclude ".env" | Remove-Item -Recurse -Force
        Write-Host "User .env preserved in $InstallDir" -ForegroundColor Cyan
    } else {
        # If running from inside the install dir, spawn a detached cleanup process
        Start-Process powershell -WindowStyle Hidden -ArgumentList "-Command", "Start-Sleep -Seconds 1; Remove-Item -LiteralPath '$InstallDir' -Recurse -Force -ErrorAction SilentlyContinue"
    }
}

Write-Host ""
Write-Host "Kya-Ray was successfully uninstalled from this computer." -ForegroundColor Green
Write-Host ""

