"""
Windows Auto-Update Backend — Stub.

TODO: Implement using WinSparkle (https://winsparkle.org/) or a custom
HTTP-based update checker. WinSparkle uses the same appcast.xml format
as Sparkle, so the server-side feed can be shared across platforms.

Author: Resistine Team
Copyright (c) Resistine 2025
Licensed under the GNU General Public License v2 or later
"""

from utils.logger import logger


def init_updater(app):
    """Initialize the Windows update backend."""
    logger.info("[UPDATE-WIN] Auto-updates not yet implemented on Windows")
    return False


def check_for_updates():
    """Trigger an interactive update check."""
    logger.info("[UPDATE-WIN] Not implemented")
    return False


def check_for_updates_in_background():
    """Trigger a silent background update check."""
    return False


def is_available():
    """Return True if the update backend is operational."""
    return False
