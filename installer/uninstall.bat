@echo off
setlocal
title Kya-Ray Uninstaller

echo ========================================================
echo  Kya-Ray Uninstallation
echo ========================================================
echo.
set /p "CONFIRM=Are you sure you want to uninstall Kya-Ray? (Y/N): "
if /i not "%CONFIRM%"=="Y" (
    echo Uninstallation cancelled.
    pause
    exit /b 0
)

echo.
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0uninstall.ps1"
echo.
pause

