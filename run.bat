@echo off
setlocal

:: Change to the project root (same directory as this script)
cd /d "%~dp0"

:: Check if .venv exists, if not run install.bat
if not exist ".venv" (
    echo .venv folder not found. Running install.bat first...
    call scripts\install\install.bat
    if errorlevel 1 exit /b %errorlevel%
)

:: Activate virtual environment
if exist ".venv\Scripts\activate.bat" (
    call .venv\Scripts\activate.bat
) else (
    echo Error: Cannot find activation script. Please run install.bat.
    exit /b 1
)

:: Install/update requirements
:: Add GTK3 runtime to PATH for Cairo (needed by cairosvg/cairocffi)
if exist "C:\Program Files\GTK3-Runtime Win64\bin" (
    set "PATH=C:\Program Files\GTK3-Runtime Win64\bin;%PATH%"
) else (
    echo WARNING: GTK3 runtime not found. Cairo-based features may not work.
    echo Install it with: winget install -e --id tschoonj.GTKForWindows
)

echo Updating dependencies...
python -m pip install -U -q -r scripts\requirements\requirements-windows.txt
if %errorlevel% neq 0 (
    echo Failed to install requirements.
    exit /b 1
)

:: Check ResistineVPN service; start it if installed-but-stopped, reinstall if missing
call :check_service_state
if "%SERVICE_RUNNING%"=="1" (
    echo [run.bat] service: RUNNING -- skipping
) else if "%SERVICE_EXISTS%"=="1" (
    echo [run.bat] service: installed but not running -- starting
    powershell -NoProfile -Command "Start-Process -FilePath 'sc.exe' -ArgumentList 'start','ResistineVPN' -Verb RunAs -Wait" 2>nul
    if errorlevel 1 (
        echo [run.bat] UAC declined or start failed -- launching GUI anyway
    )
) else (
    echo [run.bat] service: not installed -- reinstall required
    powershell -NoProfile -Command "Start-Process -FilePath '%~dp0scripts\install\install_service.bat' -ArgumentList '/quiet' -Verb RunAs -Wait" 2>nul
    if errorlevel 1 (
        echo [run.bat] UAC declined -- launching GUI without service ^(VPN will be unavailable^)
    )
)

:: Run the application
echo Starting the application...
python main.py %*

:: Deactivate is implicitly handled by script exit since we used call/local
:: but we can be explicit if needed.
:: call deactivate
goto :eof

:check_service_state
set "SERVICE_EXISTS="
set "SERVICE_RUNNING="
sc query ResistineVPN >nul 2>&1
if errorlevel 1 goto :check_service_state_done
set "SERVICE_EXISTS=1"
sc query ResistineVPN | findstr /C:"RUNNING" >nul 2>&1
if errorlevel 1 goto :check_service_state_done
set "SERVICE_RUNNING=1"
:check_service_state_done
goto :eof
