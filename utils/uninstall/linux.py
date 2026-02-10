"""
Linux Uninstaller Backend — Stub.

TODO: Implement Linux-specific cleanup (config dirs, desktop entries, etc.)

Author: Resistine Team
Copyright (c) Resistine 2025
Licensed under the GNU General Public License v2 or later
"""

from utils.logger import logger


def is_available():
    """Return True if uninstall is supported."""
    return False


def run_uninstall(app, progress_callback=None):
    """Execute the Linux uninstall sequence."""
    logger.info("[UNINSTALL-LINUX] Not implemented")
    return (False, "Uninstall not yet implemented on Linux")
