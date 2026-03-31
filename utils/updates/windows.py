"""
Windows Auto-Update Backend — appcast-based updater.

Uses the same appcast.xml and shared parser as macOS and Linux.
Windows items are identified by sparkle:os="windows" on the enclosure.
Checks resistine.github.io for Windows releases and notifies user.

Author: Resistine Team
Copyright (c) Resistine 2025
Licensed under the GNU General Public License v2 or later
"""

import threading

from utils.logger import logger
from utils.updates.appcast import get_latest_windows_update
from utils.updates.version import get_current_version

_current_version = None
_latest_version = None
_download_url = None
_update_checker_thread = None
_stop_event = None
_gui_callback = None


def _check_appcast():
    """Check appcast for Windows updates using the shared parser.

    Returns True if an update is available, False otherwise.
    """
    global _latest_version, _download_url

    if not _current_version:
        _load_current_version()

    item = get_latest_windows_update(_current_version)
    if item is None:
        logger.info("[UPDATE-WIN] No updates available")
        return False

    _latest_version = item.version
    _download_url = item.download_url
    logger.info(f"[UPDATE-WIN] Update available: {item.version} → {item.download_url}")

    if _gui_callback:
        try:
            _gui_callback(item.version, item.download_url, item.release_notes_html)
        except Exception as e:
            logger.error(f"[UPDATE-WIN] GUI callback failed: {e}")

    return True


def _load_current_version():
    """Load the current app version via the shared version helper."""
    global _current_version
    _current_version = get_current_version()
    logger.info(f"[UPDATE-WIN] Current version: {_current_version}")


def _background_check_loop():
    """Background update check loop."""
    check_interval = 24 * 3600  # 24 hours

    while not _stop_event.is_set():
        try:
            _check_appcast()
        except Exception as e:
            logger.error(f"[UPDATE-WIN] Background check error: {e}")

        _stop_event.wait(check_interval)


def init_updater(app):
    """Initialize the Windows update backend."""
    global _update_checker_thread, _stop_event, _gui_callback

    _load_current_version()
    _gui_callback = getattr(app, 'on_update_available', None)

    if _stop_event is None:
        _stop_event = threading.Event()

    if _update_checker_thread is None or not _update_checker_thread.is_alive():
        _update_checker_thread = threading.Thread(
            target=_background_check_loop,
            daemon=True
        )
        _update_checker_thread.start()
        logger.info("[UPDATE-WIN] Auto-updater initialized")

    return True


def check_for_updates():
    """Trigger an interactive update check.

    Returns: "update_available", "up_to_date", or "error".
    """
    if not _current_version:
        _load_current_version()

    try:
        if _check_appcast():
            return "update_available"
        return "up_to_date"
    except Exception as e:
        logger.error(f"[UPDATE-WIN] Check failed: {e}")
        return "error"


def check_for_updates_in_background():
    """Trigger a silent background update check."""
    return check_for_updates()


def is_available():
    """Return True if the update backend is operational."""
    return True
