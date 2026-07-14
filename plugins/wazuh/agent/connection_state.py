"""
Wazuh agent connection-state reader.

The Wazuh agent daemon writes a small state file every few seconds describing
whether it is actually connected to the manager (i.e. "active on the
dashboard"), independent of whether the local service is merely running:

    # State file for wazuh-agentd
    status='connected'
    last_keepalive='2026-07-14 18:00:00'
    ...

`status` is one of: 'connected', 'pending', 'disconnected' (and we treat an
unreadable/absent file as 'unknown'). This is the authoritative local signal
for "is the agent registered and talking to the manager", which the
re-registration loop uses to decide whether to re-enroll.

The file is root/wazuh-owned; on some installs it is world-readable (mode 0644)
and a plain open() works, on others it is not and we return 'unknown' so the
caller can fall back to a privileged read.

Author: Resistine Team
Copyright (c) Resistine 2025
Licensed under the GNU General Public License v2 or later
"""

import platform
import re

from plugins.wazuh.config import (
    LINUX_WAZUH_DIR,
    WAZUH_INSTALL_DIR,
    WINDOWS_WAZUH_DIR,
)

CONNECTED = "connected"
PENDING = "pending"
DISCONNECTED = "disconnected"
UNKNOWN = "unknown"

_STATUS_RE = re.compile(r"status\s*=\s*'([^']*)'")


def state_file_path():
    """Return the wazuh-agentd state file path for this platform."""
    system = platform.system()
    if system == "Darwin":
        return f"{WAZUH_INSTALL_DIR}/var/run/wazuh-agentd.state"
    if system == "Windows":
        return f"{WINDOWS_WAZUH_DIR}\\wazuh-agent.state"
    return f"{LINUX_WAZUH_DIR}/var/run/wazuh-agentd.state"


def parse_state(text):
    """Extract the status token from state-file text; UNKNOWN if absent."""
    if not text:
        return UNKNOWN
    match = _STATUS_RE.search(text)
    if not match:
        return UNKNOWN
    value = match.group(1).strip().lower()
    return value or UNKNOWN


def get_connection_state():
    """Return the agent's connection status to the manager.

    One of CONNECTED / PENDING / DISCONNECTED / UNKNOWN. UNKNOWN means the state
    file couldn't be read (missing, or permission denied) — the caller decides
    how to treat that (typically: don't act on it).
    """
    path = state_file_path()
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            return parse_state(f.read())
    except (OSError, ValueError):
        return UNKNOWN


def is_connected():
    """True only when the agent reports an active manager connection."""
    return get_connection_state() == CONNECTED
