## Bundled and Installed Components

These components are either packaged inside the Resistine installer or
downloaded directly from the original vendor at install time. They are
governed by their own licenses and are not Python packages, so they do not
appear in the auto-generated section above.

### ClamAV
- **License**: GPL-2.0
- **Source**: https://www.clamav.net/
- **Used for**: On-access and on-demand antivirus scanning
- **Distribution**: Bundled in installer on macOS (custom build from the
  `Resistine/ClamAV-Mac` CI). Installed via system package manager on Linux
  (`apt`, `yum`, `dnf`, `pacman`). Not used on Windows — see Microsoft
  Defender AMSI below.

### WireGuard
- **License**: GPL-2.0 (kernel module and tools) / MIT (Go userspace implementation)
- **Source**: https://www.wireguard.com/
- **Used for**: VPN tunnel
- **Distribution**: Bundled in installer on Windows (WireGuard 1.1 MSI).
  Uses system WireGuard on Linux. Uses a Resistine-built Swift CLI
  (`resistine-vpn-cli`, GPL-2.0+) that bridges to macOS NetworkExtension.

### Wazuh Agent
- **License**: GPL-2.0
- **Source**: https://wazuh.com/ — https://github.com/wazuh/wazuh
- **Used for**: SIEM / endpoint monitoring agent
- **Distribution**: Downloaded from `packages.wazuh.com` when the user
  enables the Wazuh plugin. Not bundled in the Resistine installer.

### Microsoft Sysinternals Sysmon (Windows only)
- **License**: Microsoft Sysinternals License Terms (proprietary; free for
  personal and commercial use)
- **Source**: https://learn.microsoft.com/sysinternals/downloads/sysmon
- **Used for**: Enhanced Windows event monitoring (process, network,
  registry, file events) consumed by the Wazuh agent
- **Distribution**: Downloaded directly from Microsoft
  (`download.sysinternals.com`) when the user enables Wazuh on Windows.
  **Resistine does not redistribute, repackage, or modify the Sysmon
  binary.** The user implicitly accepts Microsoft's Sysinternals license
  via the `-accepteula` flag at install.

### SwiftOnSecurity Sysmon Config (Windows only)
- **License**: MIT
- **Source**: https://github.com/SwiftOnSecurity/sysmon-config
- **Used for**: Default Sysmon configuration (event filtering rules)
- **Distribution**: Downloaded from the SwiftOnSecurity GitHub repository
  at Sysmon install time.

### Microsoft Defender AMSI (Windows only)
- **License**: Part of the Microsoft Windows operating system
- **Used for**: Real-time antivirus scanning on Windows
- **Distribution**: Built into Windows. Resistine calls into the system
  AMSI interface. No additional software installed.

### Python 3.13
- **License**: Python Software Foundation License (PSF)
- **Source**: https://www.python.org/
- **Distribution**: Bundled inside the Windows MSI installer so end users
  do not need a separate Python installation. macOS and Linux use the
  system Python.

### Tcl/Tk
- **License**: Tcl/Tk License (BSD-style, permissive)
- **Source**: https://www.tcl.tk/
- **Used for**: GUI rendering (via Python's `tkinter` and CustomTkinter)
- **Distribution**: Shipped with Python on Windows. Provided by Homebrew
  on macOS / system packages on Linux.

### Sparkle (macOS only)
- **License**: MIT
- **Source**: https://sparkle-project.org/
- **Used for**: macOS auto-update mechanism
- **Distribution**: Built into the macOS app bundle.

### resistine-vpn-cli (macOS only)
- **License**: GPL-2.0-or-later (Resistine-authored)
- **Source**: https://github.com/Resistine/resistine-vpn-macos
- **Used for**: Swift CLI bridge between Python and the macOS
  NetworkExtension that hosts the WireGuard tunnel
- **Distribution**: Bundled in the macOS .app.

---

## Build-Time Tools (not shipped with the product)

These tools run on the build machine and are not distributed inside the
Resistine installer.

- **PyInstaller** (GPL-2.0-or-later, bootloader carries a linking
  exception) — packages the Python source into a self-contained app
- **Inno Setup** (proprietary, free for any use including commercial) —
  builds the Windows MSI installer
- **create-dmg** (MIT) — builds the macOS DMG
