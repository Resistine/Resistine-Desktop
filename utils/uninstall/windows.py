"""
Windows Uninstaller Backend — Stub.

TODO: Implement Windows-specific cleanup (registry entries,
Start Menu shortcuts, AppData, etc.)

Author: Resistine Team
Copyright (c) Resistine 2025
Licensed under the GNU General Public License v2 or later
"""

from utils.logger import logger


def is_available():
    """Return True if uninstall is supported."""
    return False


def run_uninstall(app, progress_callback=None):
    """Execute the Windows uninstall sequence."""
    logger.info("[UNINSTALL-WIN] Not implemented")
    return (False, "Uninstall not yet implemented on Windows")
