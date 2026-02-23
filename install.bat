@echo off
:: ============================================================
:: Resistine VPN — Installer
:: Handles service (admin) + app (user) in one file
:: ============================================================
setlocal EnableDelayedExpansion

set SCRIPT_DIR=%~dp0
if "%SCRIPT_DIR:~-1%"=="\" set SCRIPT_DIR=%SCRIPT_DIR:~0,-1%

set SERVICE_SCRIPT=%SCRIPT_DIR%\plugins\vpn\wireguard\vpn_windows_service.py
set MAIN_SCRIPT=%SCRIPT_DIR%\main.py
set TRAY_SCRIPT=%SCRIPT_DIR%\tray.py
set ICON=%SCRIPT_DIR%\resources\icons\icon.ico
set VENV_DIR=%SCRIPT_DIR%\venv
set VENV_PYTHON=%VENV_DIR%\Scripts\python.exe
set VENV_PIP=%VENV_DIR%\Scripts\pip.exe
set REQUIREMENTS=%SCRIPT_DIR%\requirements.txt
set APPDATA_DIR=%APPDATA%\Resistine
set WG_DIR=%APPDATA_DIR%\wireguard
set PROGRAMDATA_DIR=%PROGRAMDATA%\Resistine
set PROGRAMDATA_WG=%PROGRAMDATA_DIR%\wireguard
set SHORTCUT=%USERPROFILE%\Desktop\Resistine VPN.lnk
set STARTUP_KEY=HKCU\Software\Microsoft\Windows\CurrentVersion\Run
set SERVICE_NAME=ResistineVPN

:: ============================================================
:: Check if we were called with /service flag (means we're
:: already elevated — just do the service part and exit)
:: ============================================================
if "%1"=="/service" goto :install_service

:: ============================================================
:: PART 1 — User-level setup (no admin needed)
:: ============================================================
echo ============================================================
echo  Resistine VPN Installer
echo ============================================================
echo.

:: ---- Find real Python ----
echo [1/5] Locating Python...
set PYTHON_FULL=

for /f "tokens=*" %%i in ('where python 2^>nul') do (
    echo %%i | findstr /i "WindowsApps" >nul 2>&1
    if !errorlevel! neq 0 (
        if not defined PYTHON_FULL set PYTHON_FULL=%%i
    )
)

if not defined PYTHON_FULL (
    for /f "tokens=*" %%i in ('py -3 -c "import sys; print(sys.executable)" 2^>nul') do (
        set PYTHON_FULL=%%i
    )
)

if not defined PYTHON_FULL (
    for %%v in (313 312 311 310) do (
        if not defined PYTHON_FULL (
            for %%p in (
                "%LOCALAPPDATA%\Programs\Python\Python%%v\python.exe"
                "%PROGRAMFILES%\Python%%v\python.exe"
                "%PROGRAMFILES(x86)%\Python%%v\python.exe"
            ) do (
                if exist %%p if not defined PYTHON_FULL set PYTHON_FULL=%%~p
            )
        )
    )
)

if not defined PYTHON_FULL (
    echo ERROR: Python not found. Install from https://www.python.org/downloads/
    pause & exit /b 1
)

"%PYTHON_FULL%" --version >nul 2>&1
if %errorlevel% neq 0 (
    echo ERROR: Python at %PYTHON_FULL% failed to run.
    pause & exit /b 1
)
for /f "tokens=*" %%i in ('"%PYTHON_FULL%" --version') do echo       %%i
echo       Path: %PYTHON_FULL%
echo       OK

:: ---- Create or reuse venv ----
echo [2/5] Setting up virtual environment...
if not exist "%VENV_PYTHON%" (
    echo       Creating venv...
    "%PYTHON_FULL%" -m venv "%VENV_DIR%"
    if !errorlevel! neq 0 (
        echo ERROR: Failed to create venv.
        pause & exit /b 1
    )
) else (
    echo       Existing venv found
)

:: ---- Install dependencies ----
echo       Installing dependencies...
if exist "%REQUIREMENTS%" (
    "%VENV_PIP%" install --quiet -r "%REQUIREMENTS%"
) else (
    "%VENV_PIP%" install --quiet customtkinter pillow pystray loguru pywin32 pywin32-ctypes
)
if %errorlevel% neq 0 (
    echo ERROR: Failed to install dependencies.
    pause & exit /b 1
)
echo       OK

:: ---- Create AppData dirs ----
echo [3/5] Creating app directories...
if not exist "%WG_DIR%"      mkdir "%WG_DIR%"
if not exist "%APPDATA_DIR%" mkdir "%APPDATA_DIR%"
echo       OK

:: ---- Desktop shortcut ----
echo [4/5] Creating desktop shortcut...
set VBS=%TEMP%\resistine_shortcut.vbs
> "%VBS%" echo Set oWS = WScript.CreateObject("WScript.Shell")
>> "%VBS%" echo Set oLink = oWS.CreateShortcut("%SHORTCUT%")
>> "%VBS%" echo oLink.TargetPath = "%VENV_PYTHON%"
>> "%VBS%" echo oLink.Arguments = """%MAIN_SCRIPT%"""
>> "%VBS%" echo oLink.WorkingDirectory = "%SCRIPT_DIR%"
>> "%VBS%" echo oLink.IconLocation = "%ICON%, 0"
>> "%VBS%" echo oLink.Description = "Resistine VPN"
>> "%VBS%" echo oLink.Save
cscript //nologo "%VBS%"
del "%VBS%" >nul 2>&1

if exist "%SHORTCUT%" (
    echo       OK - Shortcut created on Desktop
) else (
    echo WARNING: Shortcut creation failed
)

:: ---- Register tray for startup ----
echo [5/5] Registering tray for startup...
reg add "%STARTUP_KEY%" ^
    /v "%SERVICE_NAME%Tray" ^
    /t REG_SZ ^
    /d "\"%VENV_PYTHON%\" \"%TRAY_SCRIPT%\"" ^
    /f >nul 2>&1
echo       OK

:: ============================================================
:: PART 2 — Service install (elevate to admin)
:: ============================================================
echo.
echo Installing Windows service ^(requires Admin^)...
powershell -Command "Start-Process cmd -ArgumentList '/c \"%~f0\" /service & pause' -Verb RunAs -Wait"
if %errorlevel% neq 0 (
    echo WARNING: Service installation failed or was cancelled.
    echo          VPN toggle will not work until the service is installed.
)

:: ---- Launch tray now ----
echo.
echo Starting tray icon...
start "" "%VENV_PYTHON%" "%TRAY_SCRIPT%"

echo.
echo ============================================================
echo  Installation complete!
echo  Desktop shortcut : %SHORTCUT%
echo  Config dir       : %WG_DIR%
echo  Tray             : auto-starts on login
echo ============================================================
echo.
pause
exit /b 0


:: ============================================================
:: SERVICE SECTION (runs elevated via /service flag)
:: ============================================================
:install_service
echo ============================================================
echo  Installing ResistineVPN Service
echo ============================================================

:: Confirm admin
net session >nul 2>&1
if %errorlevel% neq 0 (
    echo ERROR: Not running as Administrator.
    exit /b 1
)

:: Check WireGuard
if not exist "%PROGRAMFILES%\WireGuard\wireguard.exe" (
    echo ERROR: WireGuard not found.
    echo Install from https://www.wireguard.com/install/
    exit /b 1
)
echo WireGuard found.

:: Create ProgramData dirs
if not exist "%PROGRAMDATA_WG%"  mkdir "%PROGRAMDATA_WG%"
if not exist "%PROGRAMDATA_DIR%" mkdir "%PROGRAMDATA_DIR%"
echo Directories created.

:: pywin32 post-install
for /f "tokens=*" %%p in ('"%VENV_PYTHON%" -c "import sys; print(sys.prefix)"') do (
    if exist "%%p\Scripts\pywin32_postinstall.py" (
        "%VENV_PYTHON%" "%%p\Scripts\pywin32_postinstall.py" -install >nul 2>&1
    )
)

:: Remove existing service
sc query %SERVICE_NAME% >nul 2>&1
if %errorlevel% equ 0 (
    echo Stopping existing service...
    sc stop %SERVICE_NAME% >nul 2>&1
    timeout /t 3 /nobreak >nul
    "%VENV_PYTHON%" "%SERVICE_SCRIPT%" remove >nul 2>&1
    timeout /t 2 /nobreak >nul
)

:: Install and start
echo Registering service...
"%VENV_PYTHON%" "%SERVICE_SCRIPT%" --startup auto install
if %errorlevel% neq 0 (
    echo ERROR: Failed to install service.
    exit /b 1
)

sc start %SERVICE_NAME% >nul 2>&1
if %errorlevel% neq 0 (
    echo WARNING: Service installed but failed to start.
    echo Check: %PROGRAMDATA_DIR%\vpn_service.log
) else (
    echo Service started successfully.
)

echo.
echo ============================================================
echo  Service installed!
echo  Config dir : %PROGRAMDATA_WG%
echo  Log file   : %PROGRAMDATA_DIR%\vpn_service.log
echo ============================================================
exit /b 0

:: Verify service is running after install
timeout /t 3 /nobreak >nul
sc query %SERVICE_NAME% | findstr "RUNNING" >nul 2>&1
if %errorlevel% neq 0 (
    echo WARNING: Service installed but not running, attempting start...
    sc start %SERVICE_NAME%
    timeout /t 3 /nobreak >nul
    sc query %SERVICE_NAME% | findstr "RUNNING" >nul 2>&1
    if !errorlevel! neq 0 (
        echo ERROR: Service failed to start.
        echo Check: %PROGRAMDATA%\Resistine\vpn_service.log
    ) else (
        echo       OK - Service running
    )
) else (
    echo       OK - Service running
)