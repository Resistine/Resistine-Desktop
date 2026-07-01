"""
Wazuh agent connection-state parsing — platform-agnostic.

The Wazuh agent writes its live manager-connection status to
``<install>/var/run/wazuh-agentd.state`` (an ini-like file with lines such
as ``status='connected'``). The plugin previously only checked whether the
agent *process* was alive, which cannot distinguish a healthy agent from one
whose key was invalidated server-side (e.g. the operator deleted the old
agent after a reinstall). Reading the real status lets the UI show
"connected vs not" and lets the auto-heal path re-enroll a dead key.

This module is pure (no platform imports, no I/O side effects beyond reading
the caller-supplied paths) so it is trivially unit-testable on any OS.

Author: Resistine Team
Copyright (c) Resistine 2025
Licensed under the GNU General Public License v2 or later
"""

import os

# Canonical connection states returned by this module.
CONNECTED = "connected"
PENDING = "pending"
DISCONNECTED = "disconnected"
UNKNOWN = "unknown"

_VALID_STATES = (CONNECTED, PENDING, DISCONNECTED)


def parse_agentd_state(text: str) -> str:
    """Parse ``wazuh-agentd.state`` contents into a canonical status.

    The file looks like::

        # State file
        status='connected'
        last_keepalive='2026-06-30 22:00:00'
        last_ack='2026-06-30 22:00:00'

    Returns one of ``connected``/``pending``/``disconnected``, or
    ``unknown`` if no recognizable status line is present.
    """
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        key, sep, value = line.partition("=")
        if sep and key.strip().lower() == "status":
            value = value.strip().strip("'\"").lower()
            if value in _VALID_STATES:
                return value
    return UNKNOWN


def parse_ossec_log_tail(text: str) -> str:
    """Infer connection status from recent ``ossec.log`` lines.

    Used only as a fallback when the state file is missing (older agents, or
    before the first status write). Scans in order and keeps the *last*
    decisive signal, since the log is chronological.
    """
    result = UNKNOWN
    for raw in text.splitlines():
        line = raw.strip()
        if "Connected to the server" in line:
            result = CONNECTED
        elif (
            "Unable to connect to any configured manager" in line
            or "Lost connection with manager" in line
            or "Unable to connect to enrollment service" in line
            or "Unable to connect to" in line
        ):
            result = DISCONNECTED
    return result


def read_agent_connection(
    state_path: str,
    log_path: str | None = None,
    log_tail_bytes: int = 16384,
) -> str:
    """Read the agent's manager-connection status from disk.

    Prefers the authoritative ``wazuh-agentd.state`` file; falls back to the
    tail of ``ossec.log`` when the state file is absent or unparseable.
    Never raises — returns ``unknown`` when nothing can be determined.
    """
    try:
        with open(state_path, "r", errors="replace") as fh:
            status = parse_agentd_state(fh.read())
        if status != UNKNOWN:
            return status
    except OSError:
        pass

    if log_path:
        try:
            with open(log_path, "rb") as fh:
                try:
                    fh.seek(-log_tail_bytes, os.SEEK_END)
                except OSError:
                    fh.seek(0)
                tail = fh.read().decode("utf-8", "replace")
            return parse_ossec_log_tail(tail)
        except OSError:
            pass

    return UNKNOWN
