@echo off
:: ============================================================
:: Resistine VPN — Uninstaller
:: ============================================================
setlocal EnableDelayedExpansion

set SCRIPT_DIR=%~dp0
if "%SCRIPT_DIR:~-1%"=="\" set SCRIPT_DIR=%SCRIPT_DIR:~0,-1%

set SERVICE_NAME=ResistineVPN

:: Project root is always two levels up from scripts\install\.
:: Resolved unconditionally so VENV_DIR, MAIN_SCRIPT, etc. below always expand
:: correctly — regardless of which SERVICE_SCRIPT path matches.
for %%I in ("%SCRIPT_DIR%\..\..") do set PROJECT_ROOT=%%~fI

:: Try bundled-installer layout first, then fall back to the project-root layout.
set SERVICE_SCRIPT=%SCRIPT_DIR%\windows_vpn_service.py
if not exist "%SERVICE_SCRIPT%" set SERVICE_SCRIPT=%PROJECT_ROOT%\plugins\vpn\wireguard\windows_vpn_service.py
set MAIN_SCRIPT=%PROJECT_ROOT%\main.py
set TRAY_SCRIPT=%PROJECT_ROOT%\gui\tray.py
set ICON=%PROJECT_ROOT%\resources\icons\icon.ico
set VENV_DIR=%PROJECT_ROOT%\.venv
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
powershell -NoProfile -Command "Get-CimInstance Win32_Process -Filter \"Name='python.exe' OR Name='pythonw.exe'\" | Where-Object { $_.CommandLine -like '*tray.py*' } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }" >nul 2>&1
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
set "SERVICE_LOG=%PROGRAMDATA_DIR%\uninstall_service.log"
set "UNINSTALL_WRAPPER=%TEMP%\resistine_uninstall_service_wrapper.bat"
if not exist "%PROGRAMDATA_DIR%" mkdir "%PROGRAMDATA_DIR%" >nul 2>&1
:: PowerShell's -ArgumentList doesn't reliably pass `>` and nested quotes
:: through cmd's argument parser. Write a wrapper bat with the redirect
:: in plain cmd syntax, then elevate that.
> "%UNINSTALL_WRAPPER%" echo @echo off
>> "%UNINSTALL_WRAPPER%" echo call "%~f0" /service ^> "%SERVICE_LOG%" 2^>^&1
powershell -Command "Start-Process -FilePath '%UNINSTALL_WRAPPER%' -Verb RunAs -Wait"
if %errorlevel% neq 0 (
    echo WARNING: Service removal failed or was cancelled.
)
del "%UNINSTALL_WRAPPER%" >nul 2>&1
echo       Service removal log: %SERVICE_LOG%

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
:: Flattened control flow (no labels inside parenthesized blocks) so cmd's
:: parser can't choke with ". was unexpected at this time".
echo Removing ResistineVPN service...
sc query %SERVICE_NAME% >nul 2>&1
if %errorlevel% neq 0 goto :service_not_present

echo       Stopping service...
sc stop %SERVICE_NAME% >nul 2>&1
call :wait_for_stopped 30

echo       Removing service...
if defined SYS_PYTHON (
    "%SYS_PYTHON%" "%SERVICE_SCRIPT%" remove >nul 2>&1
) else if exist "%VENV_PYTHON%" (
    "%VENV_PYTHON%" "%SERVICE_SCRIPT%" remove >nul 2>&1
)

:: Safety net: always follow up with sc delete in case the python-based
:: remove failed silently (pywin32 mismatch, stale registration, etc.).
:: Idempotent — harmless if the service is already gone.
sc delete %SERVICE_NAME% >nul 2>&1

call :wait_for_absence 10
goto :service_removal_done

:service_not_present
echo       Not found, skipping

:service_removal_done

echo.
echo ============================================================
echo  Service removal complete.
echo ============================================================
exit /b 0


:: ============================================================
:: Subroutine: wait_for_stopped <max_seconds>
:: ============================================================
:: Polls `sc query %SERVICE_NAME%` until STATE is STOPPED, up to <max_seconds>.
:: sc stop is async — calling sc delete on a still-stopping service only
:: marks it for deletion, leaving a zombie registration that blocks reinstalls.
:: Flattened goto-based flow so no labels sit inside parenthesized blocks
:: (cmd's parser chokes with ". was unexpected" on multi-label blocks).
:wait_for_stopped
set /a _WAIT_MAX=%~1
set /a _WAIT_COUNT=0
:_wait_stopped_iter
sc query %SERVICE_NAME% | findstr /C:"STOPPED" >nul 2>&1
if %errorlevel% equ 0 goto :_wait_stopped_done
if !_WAIT_COUNT! geq !_WAIT_MAX! goto :_wait_stopped_timeout
set /a _WAIT_COUNT+=1
echo       Waiting for STOPPED state... ^(!_WAIT_COUNT!/!_WAIT_MAX!^)
timeout /t 1 /nobreak >nul
goto :_wait_stopped_iter
:_wait_stopped_timeout
echo WARNING: Service did not reach STOPPED in !_WAIT_MAX! seconds; proceeding anyway.
:_wait_stopped_done
goto :eof


:: ============================================================
:: Subroutine: wait_for_absence <max_seconds>
:: ============================================================
:: Polls `sc query %SERVICE_NAME%` until the service is absent (not registered),
:: up to <max_seconds>. Prints a final "OK - Service removed" or a warning.
:wait_for_absence
set /a _ABS_MAX=%~1
set /a _ABS_COUNT=0
:_wait_absence_iter
sc query %SERVICE_NAME% >nul 2>&1
if %errorlevel% neq 0 goto :_wait_absence_gone
if !_ABS_COUNT! geq !_ABS_MAX! goto :_wait_absence_timeout
set /a _ABS_COUNT+=1
echo       Waiting for cleanup... ^(!_ABS_COUNT!/!_ABS_MAX!^)
timeout /t 1 /nobreak >nul
goto :_wait_absence_iter
:_wait_absence_timeout
echo WARNING: Service still registered after !_ABS_MAX! seconds.
echo          It may be marked for deletion; a reboot will complete removal.
goto :eof
:_wait_absence_gone
echo       OK - Service removed
goto :eof