# Description: This script installs the dependencies and runs the application
# Author: Peres J.
# Date: 2025-09-01
# License: Apache License 2.0


#!/bin/bash

# Print commands and their arguments as they are executed
set -x

# Exit immediately if a command exits with a non-zero status
set -e

# Check if the venv folder already exists in the libraries folder
if [ -d "libraries/venv" ]; then
    echo "libraries/venv folder already exists. Do you want to delete it? (y/n)"
    read delete_venv
    if [ "$delete_venv" == "y" ]; then
        rm -rf libraries/venv
    else
        echo "Please delete the libraries/venv folder and run this script again."
        exit 1
    fi
fi

# Detect the operating system
OS="$(uname -s)"
case "$OS" in
    Linux*)
        # Install Linux Dependencies
        sudo apt update
        sudo apt install -y python3 python3-venv python3-pip python3-tk
        # Check if the venv folder is empty
        # Create a Virtual Environment
        python3 -m venv libraries/venv
        source venv/bin/activate
        # Install Python Dependencies
        pip install -r libraries/requirements-linux.txt
        # Run the Application
        python3 main.py

# Install Python Dependencies
        ;;
    Darwin*)
        # Install macOS Dependencies
        brew update
        brew install python3
        brew install python-tk
        brew install wireguard-tools
        
        # Check if the venv folder is empty
        # Create a Virtual Environment
        python3 -m venv libraries/venv
        source libraries/venv/bin/activate
        # Install Python Dependencies
        pip install -r libraries/requirements-mac.txt
        # Run the Application
        python3 main.py
        
        ;;
    CYGWIN*|MINGW*|MSYS*)
        # Install Windows Dependencies using Chocolatey
        choco install -y python3 python3-venv python3-pip
        # Create a Virtual Environment
        if [ ! -d "libraries/venv" ]; then
            python3 -m venv libraries/venv
        fi
        source libraries/venv/Scripts/activate
        # Install Python Dependencies
        pip install -r libraries/requirements-windows.txt
        # Run the Application
        python main.py
        ;;
    *)
        echo "Unsupported OS: $OS"
        exit 1
        ;;
esac

