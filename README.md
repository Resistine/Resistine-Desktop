# Resistine AI EndPoint Detection and Response (AI EDR)

for Windows, Mac and Linux Desktops

## Prerequisites

- Python 3.12 or later (unless using the precompiled distribution)
- Windows 11, Linux or macOS 10.15 or later
- Apple Developer Account (for code signing and notarization)

## Installation

$ ./install.sh

This will install and run Resistine AI EDR

## Running Resistine

$ ./run.sh

This will update the dependencies and run Resistine EndPoint

## Command Line Arguments

usage: main.py [-h] [-d] [-v] [--log-level {DEBUG,INFO,WARNING,ERROR,CRITICAL}]

Resistine Desktop Application

options:
-h, --help Show this help message and exit
-d, --debug Enable debug window for real-time logging
-v, --verbose Enable verbose logging output
--log-level {DEBUG,INFO,WARNING,ERROR,CRITICAL}
Set logging level (default: INFO)

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

See the [LICENSE](../LICENSE) file for more details.
