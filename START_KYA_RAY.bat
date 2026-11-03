@echo off
setlocal enabledelayedexpansion
title Starting Kya-Ray Desktop Companion...

echo ========================================================
echo  Starting Kya-Ray (Standalone Desktop Companion)
echo ========================================================
echo.

rem 1. Locate Kya-Ray.exe in standard distribution locations
set "EXE_PATH="
if exist "%~dp0dist\Kya-Ray\Kya-Ray.exe" (
    set "EXE_PATH=%~dp0dist\Kya-Ray\Kya-Ray.exe"
    set "APP_DIR=%~dp0dist\Kya-Ray"
) else if exist "%~dp0Kya-Ray\Kya-Ray.exe" (
    set "EXE_PATH=%~dp0Kya-Ray\Kya-Ray.exe"
    set "APP_DIR=%~dp0Kya-Ray"
) else if exist "%~dp0Kya-Ray.exe" (
    set "EXE_PATH=%~dp0Kya-Ray.exe"
    set "APP_DIR=%~dp0"
)

if not defined EXE_PATH (
    echo [Error] Could not locate Kya-Ray.exe.
    echo Please build the application with PyInstaller or extract the distribution archive.
    echo.
    pause
    exit /b 1
)

rem 2. Validate configuration (.env file or GROQ_API_KEY environment variable)
set "CONFIG_FOUND=0"
if defined GROQ_API_KEY (
    set "CONFIG_FOUND=1"
) else if exist "%APP_DIR%\.env" (
    findstr /i "GROQ_API_KEY" "%APP_DIR%\.env" >nul 2>&1
    if !ERRORLEVEL! EQU 0 (
        set "CONFIG_FOUND=1"
    )
) else if exist "%~dp0.env" (
    findstr /i "GROQ_API_KEY" "%~dp0.env" >nul 2>&1
    if !ERRORLEVEL! EQU 0 (
        set "CONFIG_FOUND=1"
    )
)

if "!CONFIG_FOUND!"=="0" (
    echo [Notice] GROQ_API_KEY is not configured in .env or system environment.
    echo Kya-Ray will start in setup guidance mode.
    echo To enable AI responses, copy .env.example to .env and set your GROQ_API_KEY.
    echo.
)

rem 3. Check if local backend is already healthy
curl -s -m 2 http://127.0.0.1:8000/health >nul 2>&1
if %ERRORLEVEL% EQU 0 (
    echo [Info] Kya-Ray Cloud Backend is already running on http://127.0.0.1:8000.
) else (
    echo [Info] Backend will be automatically launched by Kya-Ray.
)

rem 4. Check if Kya-Ray is already running to prevent duplicate processes
tasklist /FI "IMAGENAME eq Kya-Ray.exe" 2>NUL | find /I /N "Kya-Ray.exe" >nul 2>&1
if %ERRORLEVEL% EQU 0 (
    echo [Info] Kya-Ray is already running in the background.
    echo Select text in any window and press Ctrl + Alt + Space.
    echo.
    timeout /t 3 >nul
    exit /b 0
)

rem 5. Launch the application
echo Launching Kya-Ray...
start "" "%EXE_PATH%"

echo.
echo Kya-Ray has launched in the background!
echo Highlight text anywhere and press Ctrl + Alt + Space.
echo.
timeout /t 3 >nul
exit /b 0
