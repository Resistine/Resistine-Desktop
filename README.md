# Resistine AI EndPoint Detection and Response (AI EDR)

for Windows, Mac and Linux Desktops

## Prerequisites

- Python 3.12 or later (unless using the precompiled distribution)
- Windows 11, Linux and macOS 15 or later
- Apple Developer Account (for code signing and notarization)

## Installation

$ ./install.sh

This will install and run Resistine AI EDR

These scripts are for source/dev installs. For packaged installers, see "Windows Installer (.exe)" below.

## Running Resistine

$ ./run.sh

This will update the dependencies and run Resistine EndPoint

## Windows Installer (`.exe`)

Windows packaging uses Inno Setup and PyInstaller.

### What gets installed automatically

- Python dependencies are bundled into the packaged app via PyInstaller.
- The installer attempts to install missing `WireGuard` and `GTK3 runtime` via `winget` (best effort).
- The installer installs/repairs the required Resistine VPN Windows service during setup.

### Installer actions (maintenance mode)

- Fresh install: normal install flow
- Existing install detected: `Install` (overwrite), `Update` (if installer is newer), `Reinstall (Fix)`, or `Uninstall`

### Build the Windows installer

```powershell
.\build-windows-installer.ps1
```

Requirements for the build machine:

- `python` on PATH
- Inno Setup 6 (`ISCC.exe`) installed

## Command Line Arguments

usage: main.py [-h] [-d] [-l {DEBUG,INFO,WARNING,ERROR,CRITICAL}]

Resistine Desktop Application

options:
-h, --help Show this help message and exit
-d, --debug Enable debug mode for real-time debugging
-l, --log-level {DEBUG,INFO,WARNING,ERROR,CRITICAL}
Set logging level (default: INFO)

## Coding and debugging

To run Resistine in debug mode, use the following command:

$ ./run.sh -d

This will run Resistine in debug mode, which enables a few features:

- A runtime inspector that allows you to inspect the runtime state of the application
- DEPRECATED: You can also use the debug window that allows you to inspect the runtime state of the application

The application automatically detects if it is running in IDEs (like VSCode, PyCharm / JetBrains) and enables the debug mode.

## Setup Instructions for Mac OS

### 1. Configuration

#### Build Installer Configuration

Edit `build_dmg_simple.py` with your Apple Developer credentials:

- `SIGNING_IDENTITY`: Your code signing certificate ID
- `NOTARY_APPLE_ID`: Your Apple ID email
- `NOTARY_TEAM_ID`: Your Team ID from Apple Developer portal
- `NOTARY_PASSWORD`: Your app-specific password

#### WireGuard Configuration

Copy the example WireGuard configuration:

```bash
cp plugins/vpn/wireguard/wg0-example.conf plugins/vpn/wireguard/wg0.conf
```

Edit `plugins/vpn/wireguard/wg0.conf` with your VPN server details:

- `PrivateKey`: Your private key
- `Address`: Your VPN IP address
- `Endpoint`: Your VPN server endpoint
- `PublicKey`: Server's public key

### 2. API Configuration

#### OpenAI API Key

Add your OpenAI API key for functional AI.
Edit `plugins/chat/main.py` on line 47 with your OpenAI api key

### Building the Application

#### Quick Build (Signed but not notarized)

```bash
python3 build_dmg_simple.py
```

This will:

- Build the application with PyInstaller
- Sign the app with your Developer ID certificate
- Create a DMG installer file
- Notarize and staple the dmg

### Output Files

- `dist/Resistine.app` - The signed application bundle
- `Resistine-Notarized-1.0.0.dmg` - Notarized DMG (if using full build)

## License

Resistine AI EndPoint Detection and Response (AI EDR)

for Windows, Mac and Linux Desktops

Copyright (C) 2025 Resistine

This program is free software under the terms of the GNU General Public License v2 or later

Resistine comes with ABSOLUTELY NO WARRANTY.

See the [LICENSE](LICENSE.md) file for more details.
