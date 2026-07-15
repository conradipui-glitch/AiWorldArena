@echo off
setlocal EnableExtensions DisableDelayedExpansion

rem Keep this wrapper ASCII-only. cmd.exe otherwise parses UTF-8 text
rem inconsistently on different Windows installations.
set "ROOT=%~dp0"
set "OBSERVER_SCRIPT=%ROOT%scripts\observer.ps1"
set "API_PORT=8000"
set "UI_PORT=5173"

rem Optional environment overrides are useful when the default ports are busy.
if not "%AIWORLD_API_PORT%"=="" set "API_PORT=%AIWORLD_API_PORT%"
if not "%AIWORLD_UI_PORT%"=="" set "UI_PORT=%AIWORLD_UI_PORT%"

where powershell.exe >nul 2>nul
if errorlevel 1 goto :missing_powershell

if not exist "%OBSERVER_SCRIPT%" goto :missing_script

echo Starting AI World Arena observer...
if /I "%AIWORLD_NO_BROWSER%"=="1" (
    powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%OBSERVER_SCRIPT%" -ApiPort "%API_PORT%" -UiPort "%UI_PORT%"
) else (
    powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%OBSERVER_SCRIPT%" -ApiPort "%API_PORT%" -UiPort "%UI_PORT%" -OpenBrowser
)
set "EXIT_CODE=%ERRORLEVEL%"

if not "%EXIT_CODE%"=="0" goto :observer_error
exit /b 0

:missing_powershell
echo.
echo Windows PowerShell was not found.
set "EXIT_CODE=1"
goto :failed

:missing_script
echo.
echo The observer startup script was not found: scripts\observer.ps1
set "EXIT_CODE=1"
goto :failed

:observer_error
echo.
echo The local observer could not be started.
echo See work\observer-api.err.log and work\observer-ui.err.log for details.
goto :failed

:failed
if /I "%AIWORLD_NO_PAUSE%"=="1" exit /b %EXIT_CODE%
echo.
pause
exit /b %EXIT_CODE%
