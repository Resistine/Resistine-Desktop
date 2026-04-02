@echo off
:: ============================================================
:: Resistine VPN — Uninstaller
:: ============================================================
setlocal EnableDelayedExpansion

set SCRIPT_DIR=%~dp0
if "%SCRIPT_DIR:~-1%"=="\" set SCRIPT_DIR=%SCRIPT_DIR:~0,-1%

set SERVICE_NAME=ResistineVPN

:: Try to find service script in installation directory first (bundled with installer)
set SERVICE_SCRIPT=%SCRIPT_DIR%\windows_vpn_service.py
if not exist "%SERVICE_SCRIPT%" set SERVICE_SCRIPT=%SCRIPT_DIR%\plugins\vpn\wireguard\windows_vpn_service.py
if not exist "%SERVICE_SCRIPT%" set SERVICE_SCRIPT=%SCRIPT_DIR%\..\plugins\vpn\wireguard\windows_vpn_service.py

:: Fallback: assume running from project root (development mode)
if not exist "%SERVICE_SCRIPT%" (
    set PROJECT_ROOT=%SCRIPT_DIR%\..\..
    for %%I in ("%PROJECT_ROOT%") do set PROJECT_ROOT=%%~fI
    set SERVICE_SCRIPT=%PROJECT_ROOT%\plugins\vpn\wireguard\windows_vpn_service.py
)
set MAIN_SCRIPT=%PROJECT_ROOT%\main.py
set TRAY_SCRIPT=%PROJECT_ROOT%\gui\tray.py
set ICON=%PROJECT_ROOT%\resources\icons\icon.ico
set VENV_DIR=%PROJECT_ROOT%\venv
set VENV_PYTHON=%VENV_DIR%\Scripts\python.exe
set VENV_PIP=%VENV_DIR%\Scripts\pip.exe
set REQUIREMENTS=%PROJECT_ROOT%\requirements\requirements-windows.txt
set APPDATA_DIR=%APPDATA%\Resistine
set WG_DIR=%APPDATA_DIR%\wireguard
set PROGRAMDATA_DIR=%PROGRAMDATA%\Resistine
set PROGRAMDATA_WG=%PROGRAMDATA_DIR%\wireguard
set SHORTCUT=%USERPROFILE%\Desktop\Resistine VPN.lnk
set STARTUP_KEY=HKCU\Software\Microsoft\Windows\CurrentVersion\Run
set WG_EXE=%PROGRAMFILES%\WireGuard\wireguard.exe

:: ============================================================
:: Jump to service section if elevated
:: ============================================================
if "%1"=="/service" goto :remove_service

:: ============================================================
:: PART 1 — User level
:: ============================================================
echo ============================================================
echo  Resistine VPN Uninstaller
echo ============================================================
echo.

:: ---- Kill tray process ----
echo [1/4] Stopping tray icon...
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

:: ---- Find system Python to pass to elevated section ----
:: The service was installed with system Python (not venv), so removal
:: must also use system Python. Pass the path across the UAC boundary
:: via a temp file, same pattern as install.bat.
set PYTHON_FULL=
for /f "tokens=*" %%i in ('py -3 -c "import sys; print(sys.executable)" 2^>nul') do (
    if not defined PYTHON_FULL set PYTHON_FULL=%%i
)
if not defined PYTHON_FULL (
    for /f "tokens=*" %%i in ('where python 2^>nul') do (
        echo %%i | findstr /i "WindowsApps" >nul 2>&1
        if !errorlevel! neq 0 if not defined PYTHON_FULL set PYTHON_FULL=%%i
    )
)

if defined PYTHON_FULL (
    echo %PYTHON_FULL%> "%TEMP%\resistine_python_path.txt"
)

:: ---- Remove service (needs admin) ----
echo [4/4] Removing Windows service ^(requires Admin^)...
powershell -Command "Start-Process cmd -ArgumentList '/c \"%~f0\" /service & pause' -Verb RunAs -Wait"
if %errorlevel% neq 0 (
    echo WARNING: Service removal failed or was cancelled.
)

del "%TEMP%\resistine_python_path.txt" >nul 2>&1

echo.
echo ============================================================
echo  Uninstall complete.
echo.
echo  The following were kept ^(delete manually if needed^):
echo    Config  : %APPDATA_DIR%
echo    Logs    : %PROGRAMDATA_DIR%
echo    Venv    : %VENV_DIR%
echo.
echo  To fully clean up run:
echo    rmdir /s /q "%APPDATA_DIR%"
echo    rmdir /s /q "%PROGRAMDATA_DIR%"
echo    rmdir /s /q "%VENV_DIR%"
echo ============================================================
echo.
exit /b 0


:: ============================================================
:: SERVICE REMOVAL (elevated)
:: Uses system Python to match how install.bat registers the service.
:: ============================================================
:remove_service
net session >nul 2>&1
if %errorlevel% neq 0 (
    echo ERROR: Not running as Administrator.
    pause & exit /b 1
)

echo ============================================================
echo  Removing ResistineVPN Service ^(Admin^)
echo ============================================================

:: Read system Python path from temp file
set SYS_PYTHON=
if exist "%TEMP%\resistine_python_path.txt" (
    set /p SYS_PYTHON= < "%TEMP%\resistine_python_path.txt"
)

:: Fallback: search again if temp file missing
if not defined SYS_PYTHON (
    for /f "tokens=*" %%i in ('where python 2^>nul') do (
        echo %%i | findstr /i "WindowsApps" >nul 2>&1
        if !errorlevel! neq 0 if not defined SYS_PYTHON set SYS_PYTHON=%%i
    )
)

if defined SYS_PYTHON (
    echo       Using Python: %SYS_PYTHON%
) else (
    echo WARNING: System Python not found. Will fall back to sc delete.
)

:: ---- Discover and remove all WireGuard tunnels ----
echo Removing WireGuard tunnels...
if exist "%WG_EXE%" (

    :: Tunnels from ProgramData
    if exist "%PROGRAMDATA_WG%" (
        for %%f in ("%PROGRAMDATA_WG%\*.conf") do (
            set TUNNEL=%%~nf
            echo       Removing tunnel: !TUNNEL!
            "%WG_EXE%" /uninstalltunnelservice "!TUNNEL!" >nul 2>&1
            sc stop   "WireGuardTunnel$!TUNNEL!" >nul 2>&1
            sc delete "WireGuardTunnel$!TUNNEL!" >nul 2>&1
        )
    )

    :: Tunnels from AppData
    if exist "%WG_DIR%" (
        for %%f in ("%WG_DIR%\*.conf") do (
            set TUNNEL=%%~nf
            echo       Removing tunnel: !TUNNEL!
            "%WG_EXE%" /uninstalltunnelservice "!TUNNEL!" >nul 2>&1
            sc stop   "WireGuardTunnel$!TUNNEL!" >nul 2>&1
            sc delete "WireGuardTunnel$!TUNNEL!" >nul 2>&1
        )
    )

    :: Any remaining WireGuard tunnel services
    for /f "tokens=2" %%s in ('sc query type^= all state^= all 2^>nul ^| findstr /i "WireGuardTunnel"') do (
        echo       Removing discovered tunnel: %%s
        sc stop   "%%s" >nul 2>&1
        sc delete "%%s" >nul 2>&1
        "%WG_EXE%" /uninstalltunnelservice "%%s" >nul 2>&1
    )
) else (
    echo       WireGuard not found, skipping tunnel removal
)
echo       OK

:: ---- Stop and remove ResistineVPN service ----
echo Removing ResistineVPN service...
sc query %SERVICE_NAME% >nul 2>&1
if %errorlevel% equ 0 (
    echo       Stopping service...
    sc stop %SERVICE_NAME% >nul 2>&1
    timeout /t 1 /nobreak >nul

    echo       Removing service...
    if defined SYS_PYTHON (
        :: Use system Python — matches how the service was installed
        "%SYS_PYTHON%" "%SERVICE_SCRIPT%" remove >nul 2>&1
    ) else if exist "%VENV_PYTHON%" (
        :: Fallback to venv if system Python not found
        "%VENV_PYTHON%" "%SERVICE_SCRIPT%" remove >nul 2>&1
    ) else (
        :: Last resort: raw sc delete
        sc delete %SERVICE_NAME% >nul 2>&1
    )

    :: Wait for full cleanup
    set RETRY=0
    :wait_loop
    sc query %SERVICE_NAME% >nul 2>&1
    if %errorlevel% equ 0 (
        if !RETRY! lss 10 (
            set /a RETRY+=1
            echo       Waiting for cleanup... ^(!RETRY!/10^)
            timeout /t 1 /nobreak >nul
            goto :wait_loop
        ) else (
            echo WARNING: Service still registered.
            echo          Restart your PC to complete removal.
        )
    ) else (
        echo       OK - Service removed
    )
) else (
    echo       Not found, skipping
)

echo.
echo ============================================================
echo  Service removal complete.
echo ============================================================
exit /b 0