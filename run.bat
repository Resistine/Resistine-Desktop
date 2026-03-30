@echo off
setlocal

:: Change to the project root (same directory as this script)
cd /d "%~dp0"

:: Check if .venv exists, if not run install.bat
if not exist ".venv" (
    echo .venv folder not found. Running install.bat first...
    call scripts\install\install.bat
    exit /b %errorlevel%
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

:: Run the application
echo Starting the application...
python main.py %*

:: Deactivate is implicitly handled by script exit since we used call/local
:: but we can be explicit if needed. 
:: call deactivate
