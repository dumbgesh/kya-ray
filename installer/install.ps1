# installer/install.ps1 - Windows Installer for Kya-Ray Desktop Companion
[CmdletBinding()]
param(
    [string]$SourceDir = "",
    [string]$InstallDir = "$env:LOCALAPPDATA\Programs\Kya-Ray",
    [switch]$NonInteractive
)

$ErrorActionPreference = "Stop"

Write-Host "==========================================================" -ForegroundColor Cyan
Write-Host "       Kya-Ray v1.0.0-beta.2 - Windows Application Installer     " -ForegroundColor Cyan
Write-Host "==========================================================" -ForegroundColor Cyan
Write-Host ""

# 1. Determine Source Directory containing the packaged binaries
if (-not $SourceDir) {
    $scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
    $parentDir = Split-Path -Parent $scriptDir
    if (Test-Path "$parentDir\dist\Kya-Ray\Kya-Ray.exe") {
        $SourceDir = "$parentDir\dist\Kya-Ray"
    } elseif (Test-Path "$parentDir\Kya-Ray\Kya-Ray.exe") {
        $SourceDir = "$parentDir\Kya-Ray"
    } elseif (Test-Path "$parentDir\Kya-Ray.exe") {
        $SourceDir = "$parentDir"
    } else {
        throw "Could not locate packaged Kya-Ray payload. Please build the application or extract the full release package."
    }
}

Write-Host "[1/6] Source payload: $SourceDir" -ForegroundColor Gray
Write-Host "[2/6] Target destination: $InstallDir" -ForegroundColor Gray

# 2. Stop running instances if updating
$running = Get-Process -Name "Kya-Ray" -ErrorAction SilentlyContinue
if ($running) {
    Write-Host "Stopping running Kya-Ray processes for upgrade..." -ForegroundColor Yellow
    $running | Stop-Process -Force -ErrorAction SilentlyContinue
    Start-Sleep -Milliseconds 800
}

# 3. Create target directory and preserve existing .env if present
if (-not (Test-Path $InstallDir)) {
    New-Item -ItemType Directory -Path $InstallDir -Force | Out-Null
}

$existingEnv = $null
if (Test-Path "$InstallDir\.env") {
    $existingEnv = Get-Content "$InstallDir\.env" -Raw
    Write-Host "Preserving existing user .env configuration." -ForegroundColor Green
}

# 4. Copy application files
Write-Host "[3/6] Copying application files..." -ForegroundColor Gray
Copy-Item -Path "$SourceDir\*" -Destination $InstallDir -Recurse -Force

if ($existingEnv) {
    Set-Content -Path "$InstallDir\.env" -Value $existingEnv -Force
} elseif (-not (Test-Path "$InstallDir\.env")) {
    if (Test-Path "$InstallDir\.env.example") {
        Copy-Item -Path "$InstallDir\.env.example" -Destination "$InstallDir\.env" -Force
    }
}

# Copy installer tools into install directory for uninstaller
$installerDir = Split-Path -Parent $MyInvocation.MyCommand.Path
Copy-Item -Path "$installerDir\uninstall.bat" -Destination "$InstallDir\uninstall.bat" -Force -ErrorAction SilentlyContinue
Copy-Item -Path "$installerDir\uninstall.ps1" -Destination "$InstallDir\uninstall.ps1" -Force -ErrorAction SilentlyContinue

# 5. Create Windows Shortcuts (Start Menu and Desktop)
Write-Host "[4/6] Creating Start Menu & Desktop shortcuts..." -ForegroundColor Gray
$WshShell = New-Object -ComObject WScript.Shell

# Start Menu Shortcut
$startMenuDir = "$env:APPDATA\Microsoft\Windows\Start Menu\Programs"
if (Test-Path $startMenuDir) {
    $shortcutPath = "$startMenuDir\Kya-Ray.lnk"
    $shortcut = $WshShell.CreateShortcut($shortcutPath)
    $shortcut.TargetPath = "$InstallDir\Kya-Ray.exe"
    $shortcut.WorkingDirectory = $InstallDir
    $shortcut.Description = "Kya-Ray Desktop AI Companion"
    $shortcut.IconLocation = "$InstallDir\Kya-Ray.exe,0"
    $shortcut.Save()
}

# Desktop Shortcut
$desktopDir = [Environment]::GetFolderPath("Desktop")
if (Test-Path $desktopDir) {
    $desktopShortcutPath = "$desktopDir\Kya-Ray.lnk"
    $shortcut = $WshShell.CreateShortcut($desktopShortcutPath)
    $shortcut.TargetPath = "$InstallDir\Kya-Ray.exe"
    $shortcut.WorkingDirectory = $InstallDir
    $shortcut.Description = "Kya-Ray Desktop AI Companion"
    $shortcut.IconLocation = "$InstallDir\Kya-Ray.exe,0"
    $shortcut.Save()
}

# 6. Register in Windows Add/Remove Programs (Registry)
Write-Host "[5/6] Registering in Windows Add/Remove Programs..." -ForegroundColor Gray
$regPath = "HKCU:\Software\Microsoft\Windows\CurrentVersion\Uninstall\Kya-Ray"
if (-not (Test-Path $regPath)) {
    New-Item -Path $regPath -Force | Out-Null
}

$sizeKb = [int]((Get-ChildItem -Path $InstallDir -Recurse | Measure-Object -Property Length -Sum).Sum / 1KB)

Set-ItemProperty -Path $regPath -Name "DisplayName" -Value "Kya-Ray (Desktop AI Companion)"
Set-ItemProperty -Path $regPath -Name "DisplayVersion" -Value "1.0.0-beta.2"
Set-ItemProperty -Path $regPath -Name "Publisher" -Value "Kya-Ray Contributors"
Set-ItemProperty -Path $regPath -Name "InstallLocation" -Value $InstallDir
Set-ItemProperty -Path $regPath -Name "DisplayIcon" -Value "$InstallDir\Kya-Ray.exe,0"
Set-ItemProperty -Path $regPath -Name "UninstallString" -Value "`"$InstallDir\uninstall.bat`""
Set-ItemProperty -Path $regPath -Name "EstimatedSize" -Value $sizeKb
Set-ItemProperty -Path $regPath -Name "NoModify" -Value 1
Set-ItemProperty -Path $regPath -Name "NoRepair" -Value 1

Write-Host "[6/6] Installation Complete!" -ForegroundColor Green
Write-Host ""
Write-Host "Kya-Ray has been installed to:" -ForegroundColor Cyan
Write-Host "  $InstallDir"
Write-Host ""
Write-Host "Shortcut key: Ctrl + Alt + Space (select text in any app)" -ForegroundColor Yellow
Write-Host ""

