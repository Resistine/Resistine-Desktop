@echo off
setlocal enabledelayedexpansion

echo ##################################################
echo # Resistine Desktop Installer for Windows        #
echo ##################################################

:: Check if .venv folder already exists
if exist ".venv" (
    set /p delete_venv=".venv folder already exists. Do you want to delete it? (y/n): "
    if /i "!delete_venv!"=="y" (
        echo Deleting existing .venv...
        rd /s /q .venv
    ) else (
        echo In case you want to run the app, just run run.bat.
        echo In case you want to reinstall it, please delete the .venv folder and run this script again.
        exit /b 1
    )
)

:: Check for Python
python --version >nul 2>&1
if %errorlevel% neq 0 (
    echo Python not found. Checking for winget...
    winget --version >nul 2>&1
    if !errorlevel! neq 0 (
        echo winget not found. Please ensure App Installer is installed from Microsoft Store.
        exit /b 1
    )
    echo Installing Python via winget...
    winget install -e --id Python.Python.3.14 --accept-package-agreements --accept-source-agreements
    if !errorlevel! neq 0 (
        echo Failed to install Python. Please install it manually from python.org.
        exit /b 1
    )
    
    :: Note: The current terminal session won't see the new Python in PATH immediately.
    echo.
    echo Python has been installed! 
    echo NOTE: You may need to restart your terminal for 'python' to be recognized.
    echo Attempting to continue anyway...
    echo.
) else (
    echo Python is already installed.
)

:: Create virtual environment
echo Creating virtual environment...
python -m venv .venv
if %errorlevel% neq 0 (
    echo Failed to create virtual environment.
    exit /b 1
)

:: Check for GTK3 runtime (provides Cairo DLL needed by cairosvg)
if not exist "C:\Program Files\GTK3-Runtime Win64\bin\libcairo-2.dll" (
    echo Installing GTK3 runtime ^(required for Cairo graphics^)...
    winget install -e --id tschoonj.GTKForWindows --accept-package-agreements --accept-source-agreements
    if !errorlevel! neq 0 (
        echo WARNING: Failed to install GTK3 runtime. Some features may not work.
        echo You can install it manually from: https://github.com/tschoonj/GTK-for-Windows-Runtime-Environment-Installer
    )
)

echo.
echo Installation setup complete! Handing over to run.bat...
echo.
call run.bat
