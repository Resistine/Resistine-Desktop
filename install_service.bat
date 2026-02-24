@echo off
:: ============================================================
:: Resistine VPN Service Installer
:: Must be run as Administrator
:: ============================================================

setlocal EnableDelayedExpansion

set NO_PAUSE=
for %%A in (%*) do (
    if /I "%%~A"=="/quiet" set NO_PAUSE=1
)

:: ---- Config ----
set SERVICE_NAME=ResistineVPN
set SCRIPT_DIR=%~dp0
if "%SCRIPT_DIR:~-1%"=="\" set SCRIPT_DIR=%SCRIPT_DIR:~0,-1%

set SERVICE_SCRIPT=%SCRIPT_DIR%\plugins\vpn\wireguard\windows_vpn_service.py
set PROGRAMDATA_DIR=%PROGRAMDATA%\Resistine\wireguard
set LOG_DIR=%PROGRAMDATA%\Resistine

:: ============================================================
:: 1. Check Admin
:: ============================================================
echo [1/6] Checking administrator privileges...
net session >nul 2>&1
if %errorlevel% neq 0 (
    echo ERROR: This script must be run as Administrator.
    echo Right-click install_service.bat and select "Run as administrator"
    call :pause_if_needed
    exit /b 1
)
echo       OK - Running as Administrator

:: ============================================================
:: 2. Find real Python (skip WindowsApps stub)
:: ============================================================
echo [2/6] Locating Python installation...
set PYTHON_FULL=

for /f "tokens=*" %%i in ('where python 2^>nul') do (
    echo %%i | findstr /i "WindowsApps" >nul 2>&1
    if !errorlevel! neq 0 (
        if not defined PYTHON_FULL (
            set PYTHON_FULL=%%i
        )
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
                if exist %%p (
                    if not defined PYTHON_FULL (
                        set PYTHON_FULL=%%~p
                    )
                )
            )
        )
    )
)

if not defined PYTHON_FULL (
    echo ERROR: Could not find a real Python installation.
    echo Please install Python 3.10+ from https://www.python.org/downloads/
    call :pause_if_needed
    exit /b 1
)

"%PYTHON_FULL%" --version >nul 2>&1
if %errorlevel% neq 0 (
    echo ERROR: Python at %PYTHON_FULL% failed to run.
    call :pause_if_needed
    exit /b 1
)

for /f "tokens=*" %%i in ('"%PYTHON_FULL%" --version') do echo       %%i
echo       Path: %PYTHON_FULL%
echo       OK

:: ============================================================
:: 3. Check WireGuard
:: ============================================================
echo [3/6] Checking WireGuard installation...
if not exist "%PROGRAMFILES%\WireGuard\wireguard.exe" (
    echo ERROR: WireGuard not found.
    echo Please install from https://www.wireguard.com/install/
    call :pause_if_needed
    exit /b 1
)
echo       OK - WireGuard found

:: ============================================================
:: 4. Install Python dependencies
:: ============================================================
echo [4/6] Installing Python dependencies...

"%PYTHON_FULL%" -m pip install --quiet --upgrade pip

set SERVICE_DEPS=pywin32 pywin32-ctypes

for %%d in (%SERVICE_DEPS%) do (
    echo       Installing %%d...
    "%PYTHON_FULL%" -m pip install --quiet %%d
    if !errorlevel! neq 0 (
        echo ERROR: Failed to install %%d
        call :pause_if_needed
        exit /b 1
    )
)

:: pywin32 post-install
echo       Running pywin32 post-install...
for /f "tokens=*" %%p in ('"%PYTHON_FULL%" -c "import sys; print(sys.prefix)"') do (
    if exist "%%p\Scripts\pywin32_postinstall.py" (
        "%PYTHON_FULL%" "%%p\Scripts\pywin32_postinstall.py" -install >nul 2>&1
    )
)
echo       OK - Dependencies installed

:: ============================================================
:: 5. Create ProgramData directories
:: ============================================================
echo [5/6] Creating service directories...
if not exist "%PROGRAMDATA_DIR%" (
    mkdir "%PROGRAMDATA_DIR%"
    echo       Created: %PROGRAMDATA_DIR%
) else (
    echo       Exists:  %PROGRAMDATA_DIR%
)
if not exist "%LOG_DIR%" mkdir "%LOG_DIR%"
echo       OK

:: ============================================================
:: 6. Install / reinstall Windows service
:: ============================================================
echo [6/6] Installing Windows service...

:: Stop and remove if exists
sc query %SERVICE_NAME% >nul 2>&1
if %errorlevel% equ 0 (
    echo       Stopping existing service...
    sc stop %SERVICE_NAME% >nul 2>&1
    timeout /t 3 /nobreak >nul
    echo       Removing existing service...
    "%PYTHON_FULL%" "%SERVICE_SCRIPT%" remove >nul 2>&1
    timeout /t 2 /nobreak >nul
)

:: Install
echo       Registering service...
"%PYTHON_FULL%" "%SERVICE_SCRIPT%" --startup auto install
if %errorlevel% neq 0 (
    echo ERROR: Failed to install service.
    call :pause_if_needed
    exit /b 1
)

:: Start
echo       Starting service...
sc start %SERVICE_NAME% >nul 2>&1
if %errorlevel% neq 0 (
    echo WARNING: Service installed but failed to start.
    echo          Check: %LOG_DIR%\vpn_service.log
) else (
    echo       OK - Service started
)

:: ============================================================
:: Done
:: ============================================================
echo.
echo ============================================================
echo  Resistine VPN Service installed successfully!
echo  Python     : %PYTHON_FULL%
echo  Service    : %SERVICE_NAME%
echo  Config dir : %PROGRAMDATA_DIR%
echo  Log file   : %LOG_DIR%\vpn_service.log
echo ============================================================
echo.
call :pause_if_needed
exit /b 0

:pause_if_needed
if defined NO_PAUSE goto :eof
pause
goto :eof
