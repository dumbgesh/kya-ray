@echo off
setlocal
title Starting Kya-Ray...

echo ========================================================
echo  Starting Kya-Ray (Portable Windows Beta)
echo ========================================================
echo.

rem Check if Ollama is accessible
curl -s http://127.0.0.1:11434/api/version >nul 2>&1
if %ERRORLEVEL% NEQ 0 (
    echo [Notice] Ollama does not appear to be running on http://127.0.0.1:11434.
    echo Please make sure the Ollama application is launched and running.
    echo You can download Ollama from https://ollama.com if not already installed.
    echo.
)

rem Launch the windowed executable
if exist "%~dp0Kya-Ray\Kya-Ray.exe" (
    start "" "%~dp0Kya-Ray\Kya-Ray.exe"
) else if exist "%~dp0Kya-Ray.exe" (
    start "" "%~dp0Kya-Ray.exe"
) else (
    echo [Error] Could not locate Kya-Ray.exe.
    pause
    exit /b 1
)

echo Kya-Ray has launched in the background!
echo Highlight text in any application and press Ctrl + Shift + J.
echo.
timeout /t 3 >nul
exit /b 0

