# Resistine AI - Desktop Application


## Prerequisites

- macOS 10.15 or later
- Apple Developer Account (for code signing and notarization)

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

### 3. Email (Optional)

If you want to bypass login, configure the email settings template:

```bash
cp utils/email-settings.txt.template utils/email-settings.txt
```

Edit `utils/email-settings.txt` with your email :



## Building the Application

### Quick Build (Signed but not notarized)

```bash
python3 build_dmg_simple.py
```

This will:

- Build the application with PyInstaller
- Sign the app with your Developer ID certificate
- Create a DMG installer file
- Notarize and staple the dmg
## Output Files
- `dist/Resistine AI.app` - The signed application bundle
- `Resistine AI-Notarized-1.0.0.dmg` - Notarized DMG (if using full build)


## License

See LICENSE file for details.
