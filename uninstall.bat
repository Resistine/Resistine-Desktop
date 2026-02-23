@echo off
:: ============================================================
:: Resistine VPN — Uninstaller
:: ============================================================
setlocal EnableDelayedExpansion

set SCRIPT_DIR=%~dp0
if "%SCRIPT_DIR:~-1%"=="\" set SCRIPT_DIR=%SCRIPT_DIR:~0,-1%

set VENV_PYTHON=%SCRIPT_DIR%\venv\Scripts\python.exe
set SERVICE_SCRIPT=%SCRIPT_DIR%\plugins\vpn\wireguard\vpn_windows_service.py
set SHORTCUT=%USERPROFILE%\Desktop\Resistine VPN.lnk
set STARTUP_KEY=HKCU\Software\Microsoft\Windows\CurrentVersion\Run
set SERVICE_NAME=ResistineVPN

:: ============================================================
:: Service removal section (runs elevated)
:: ============================================================
if "%1"=="/service" goto :remove_service

:: ============================================================
:: User-level removal
:: ============================================================
echo ============================================================
echo  Resistine VPN Uninstaller
echo ============================================================
echo.

:: ---- Kill running tray process ----
echo [1/4] Stopping tray icon...
taskkill /f /im python.exe /fi "WINDOWTITLE eq ResistineVPN*" >nul 2>&1
:: More reliable: kill by script name
for /f "tokens=2" %%i in ('tasklist /v 2^>nul ^| findstr /i "tray.py"') do (
    taskkill /f /pid %%i >nul 2>&1
)
echo       OK

:: ---- Remove startup registry entries ----
echo [2/4] Removing startup entries...
reg delete "%STARTUP_KEY%" /v "%SERVICE_NAME%Tray" /f >nul 2>&1
reg delete "%STARTUP_KEY%" /v "%SERVICE_NAME%"     /f >nul 2>&1
echo       OK

:: ---- Remove desktop shortcut ----
echo [3/4] Removing desktop shortcut...
if exist "%SHORTCUT%" (
    del "%SHORTCUT%"
    echo       OK - Shortcut removed
) else (
    echo       Not found, skipping
)

:: ---- Remove service (needs admin) ----
echo [4/4] Removing Windows service ^(requires Admin^)...
powershell -Command "Start-Process cmd -ArgumentList '/c \"%~f0\" /service & pause' -Verb RunAs -Wait"
if %errorlevel% neq 0 (
    echo WARNING: Service removal failed or was cancelled.
)

:: ============================================================
:: Done
:: ============================================================
echo.
echo ============================================================
echo  Uninstall complete.
echo.
echo  The following were kept ^(delete manually if needed^):
echo    Config  : %APPDATA%\Resistine
echo    Logs    : %PROGRAMDATA%\Resistine
echo    Venv    : %SCRIPT_DIR%\venv
echo.
echo  To fully clean up run:
echo    rmdir /s /q "%APPDATA%\Resistine"
echo    rmdir /s /q "%PROGRAMDATA%\Resistine"
echo    rmdir /s /q "%SCRIPT_DIR%\venv"
echo ============================================================
echo.
pause
exit /b 0


:: ============================================================
:: SERVICE REMOVAL (elevated)
:: ============================================================
:remove_service
net session >nul 2>&1
if %errorlevel% neq 0 (
    echo ERROR: Not running as Administrator.
    pause
    exit /b 1
)

echo ============================================================
echo  Removing ResistineVPN Service
echo ============================================================

:: Stop WireGuard tunnel first
echo Stopping WireGuard tunnel...
sc stop WireGuardTunnel$resistine_default >nul 2>&1
sc stop WireGuardTunnel$resistine_vpn     >nul 2>&1
timeout /t 2 /nobreak >nul

:: Stop and remove the service
sc query %SERVICE_NAME% >nul 2>&1
if %errorlevel% equ 0 (
    echo Stopping service...
    sc stop %SERVICE_NAME% >nul 2>&1
    timeout /t 3 /nobreak >nul

    echo Removing service...
    if exist "%VENV_PYTHON%" (
        "%VENV_PYTHON%" "%SERVICE_SCRIPT%" remove
    ) else (
        sc delete %SERVICE_NAME%
    )

    timeout /t 2 /nobreak >nul

    :: Verify removed
    sc query %SERVICE_NAME% >nul 2>&1
    if %errorlevel% neq 0 (
        echo       OK - Service removed
    ) else (
        echo WARNING: Service may still be registered, try restarting Windows
    )
) else (
    echo Service not found, skipping.
)

:: Remove WireGuard tunnel service
echo Removing WireGuard tunnel services...
"%PROGRAMFILES%\WireGuard\wireguard.exe" /uninstalltunnelservice resistine_default >nul 2>&1
"%PROGRAMFILES%\WireGuard\wireguard.exe" /uninstalltunnelservice resistine_vpn     >nul 2>&1
echo       OK

echo.
echo Service removal complete.
exit /b 0