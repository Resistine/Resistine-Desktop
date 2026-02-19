"""
Wazuh Agent Plugin — Centralized Configuration
All changeable values (package URL, version, manager address) live here.
Author: Resistine Team
Copyright (c) Resistine 2025
Licensed under the GNU General Public License v2 or later
"""

# --- Package Download ---
WAZUH_BASE_URL = "https://packages.wazuh.com/4.x/macos"
WAZUH_VERSION = "4.14.2-1"

# Maps platform.machine() output to the expected filename component
WAZUH_PKG_ARCH_MAP = {
    "arm64": "arm64",
    "x86_64": "intel64",
}

# --- Manager Connection ---
WAZUH_MANAGER = "dashboard.resisti.net"

# --- macOS Paths ---
WAZUH_LAUNCHD_PLIST = "/Library/LaunchDaemons/com.wazuh.agent.plist"
WAZUH_AGENT_CONTROL = "/Library/Ossec/bin/wazuh-control"
WAZUH_ENV_FILE = "/tmp/wazuh_envs"
