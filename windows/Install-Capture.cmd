@echo off
setlocal
"%SystemRoot%\System32\WindowsPowerShell\v1.0\powershell.exe" -NoProfile -ExecutionPolicy Bypass -File "%~dp0Install-Capture.ps1" %*
set "captureExit=%errorlevel%"
if "%~1"=="" (
    echo Press any key to close this window.
    pause >nul
)
exit /b %captureExit%
