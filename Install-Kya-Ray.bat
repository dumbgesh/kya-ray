@echo off
setlocal
title Kya-Ray Windows Installer

echo ========================================================
echo  Installing Kya-Ray (Desktop AI Companion)
echo ========================================================
echo.

powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0installer\install.ps1"

if %ERRORLEVEL% NEQ 0 (
    echo.
    echo [Error] Installation encountered an issue.
    pause
    exit /b %ERRORLEVEL%
)

echo.
set /p "LAUNCH=Would you like to launch Kya-Ray now? (Y/N): "
if /i "%LAUNCH%"=="Y" (
    start "" "%LOCALAPPDATA%\Programs\Kya-Ray\Kya-Ray.exe"
)

echo.
pause

