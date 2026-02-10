"""
Linux Auto-Update Backend — Stub.

TODO: Implement using AppImageUpdate (if distributing as AppImage),
Flatpak update mechanism, or a custom HTTP-based update checker.
The appcast.xml feed can be shared across platforms.

Author: Resistine Team
Copyright (c) Resistine 2025
Licensed under the GNU General Public License v2 or later
"""

from utils.logger import logger


def init_updater(app):
    """Initialize the Linux update backend."""
    logger.info("[UPDATE-LINUX] Auto-updates not yet implemented on Linux")
    return False


def check_for_updates():
    """Trigger an interactive update check."""
    logger.info("[UPDATE-LINUX] Not implemented")
    return False


def check_for_updates_in_background():
    """Trigger a silent background update check."""
    return False


def is_available():
    """Return True if the update backend is operational."""
    return False
