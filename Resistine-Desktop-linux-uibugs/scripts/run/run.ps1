# Description: This script updates all dependencies and runs the Resistine application.
# If the .venv folder does not exist, it will run install.bat first.
# Usage: ./run.ps1

# Author: P3 and the Resistine Team
# Copyright (c) Resistine 2025
# Licensed under the GNU General Public License v2 or later

$ErrorActionPreference = "Stop"

# Navigate to project root (two levels up from scripts/run/)
$ProjectRoot = Split-Path (Split-Path $PSScriptRoot -Parent) -Parent
Set-Location $ProjectRoot

# Check if .venv exists, if not run install.bat
if (-not (Test-Path ".venv")) {
    Write-Host ".venv folder not found. Running install.bat first..."
    & "$ProjectRoot\scripts\install\install.bat"
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
    exit 0
}

# Activate virtual environment
$activateScript = Join-Path $ProjectRoot ".venv\Scripts\Activate.ps1"
if (Test-Path $activateScript) {
    & $activateScript
} else {
    Write-Host "Error: Cannot find activation script. Please run install.bat."
    exit 1
}

# Add GTK3 runtime to PATH for Cairo (needed by cairosvg/cairocffi)
$gtkBin = "C:\Program Files\GTK3-Runtime Win64\bin"
if (Test-Path $gtkBin) {
    $env:PATH = "$gtkBin;$env:PATH"
} else {
    Write-Host "WARNING: GTK3 runtime not found. Cairo-based features may not work."
    Write-Host "Install it with: winget install -e --id tschoonj.GTKForWindows"
}

# Install/update requirements
Write-Host "Updating dependencies..."
$reqFile = Join-Path $ProjectRoot "requirements\requirements-windows.txt"
python -m pip install -U -q -r $reqFile
if ($LASTEXITCODE -ne 0) {
    Write-Host "Failed to install requirements."
    exit 1
}

# Run the application
Write-Host "Starting the application..."
python (Join-Path $ProjectRoot "main.py") @args

# Deactivate virtual environment
if (Get-Command deactivate -ErrorAction SilentlyContinue) {
    deactivate
}
