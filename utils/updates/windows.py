"""
Windows Auto-Update Backend — WinSparkle appcast-based updater.

Uses the same appcast.xml format as macOS Sparkle for cross-platform updates.
Checks resistine.github.io for Windows releases and notifies user.

Author: Resistine Team
Copyright (c) Resistine 2025
Licensed under the GNU General Public License v2 or later
"""

import threading
import xml.etree.ElementTree as ET
from urllib.request import urlopen
from urllib.error import URLError

from utils.logger import logger
from utils.updates.version import get_current_version


APPCAST_URL = "https://resistine.github.io/appcast.xml"
_current_version = None
_latest_version = None
_download_url = None
_update_checker_thread = None
_stop_event = None
_gui_callback = None


def _load_current_version():
    """Load the current app version via the shared version helper."""
    global _current_version
    _current_version = get_current_version()
    logger.info(f"[UPDATE-WIN] Current version: {_current_version}")


def _compare_versions(v1: str, v2: str) -> int:
    """Compare two version strings. Returns > 0 if v1 > v2."""
    try:
        parts1 = [int(x) for x in v1.split(".")]
        parts2 = [int(x) for x in v2.split(".")]
        for p1, p2 in zip(parts1, parts2):
            if p1 > p2:
                return 1
            if p1 < p2:
                return -1
        return len(parts1) - len(parts2)
    except (ValueError, AttributeError):
        return 1 if v1 > v2 else (-1 if v1 < v2 else 0)


def _check_appcast():
    """Fetch and parse appcast.xml for Windows updates."""
    if not _current_version:
        _load_current_version()

    try:
        logger.info(f"[UPDATE-WIN] Fetching {APPCAST_URL}")
        with urlopen(APPCAST_URL, timeout=10) as response:
            appcast_data = response.read()

        logger.info(f"[UPDATE-WIN] Parsing appcast (size: {len(appcast_data)} bytes)")
        root = ET.fromstring(appcast_data)

        items = root.findall(".//item")
        logger.info(f"[UPDATE-WIN] Found {len(items)} items in appcast")

        for i, item in enumerate(items):
            os_attr = item.get("os")
            title = item.findtext("title", "Unknown")
            logger.debug(f"[UPDATE-WIN] Item {i}: title={title}, os={os_attr}")

            # Skip non-Windows items
            if os_attr and os_attr.lower() != "windows":
                logger.debug(f"[UPDATE-WIN]   Skipping (os={os_attr}, not Windows)")
                continue
            if os_attr is None:
                # Items without os attribute (macOS), skip them
                enclosure = item.find("enclosure")
                if enclosure is not None:
                    url = enclosure.get("url", "")
                    if url.endswith(".dmg") or "android" in url.lower():
                        logger.debug(f"[UPDATE-WIN]   Skipping (macOS/Android file: {url})")
                        continue

            # Found a Windows item - get version from enclosure attributes
            enclosure = item.find("enclosure")
            if enclosure is None:
                logger.debug("[UPDATE-WIN]   No enclosure found, skipping")
                continue

            # Version is in the enclosure attributes (with sparkle namespace)
            version = enclosure.get("{http://www.andymatuschak.org/xml-namespaces/sparkle}version") or \
                     enclosure.get("{http://www.andymatuschak.org/xml-namespaces/sparkle}shortVersionString")

            logger.info(f"[UPDATE-WIN] Processing Windows item: version={version}")

            if not version:
                logger.debug("[UPDATE-WIN]   No version attribute found, skipping")
                continue

            cmp = _compare_versions(version, _current_version)
            logger.info(f"[UPDATE-WIN] Version comparison: {version} vs {_current_version} = {cmp}")

            if cmp > 0:
                url = enclosure.get("url")
                description = item.findtext("description", "")

                logger.info(f"[UPDATE-WIN] ✓ Update available: {version}")
                logger.info(f"[UPDATE-WIN]   Download URL: {url}")

                # Store for Settings plugin to access
                global _latest_version, _download_url
                _latest_version = version
                _download_url = url

                # Try to notify GUI if callback exists
                logger.info(f"[UPDATE-WIN] GUI callback: {_gui_callback}")
                if _gui_callback:
                    try:
                        logger.info("[UPDATE-WIN] Calling GUI callback...")
                        _gui_callback(version, url, description)
                        logger.info("[UPDATE-WIN] GUI callback completed")
                    except Exception as e:
                        logger.error(f"[UPDATE-WIN] GUI callback failed: {e}")
                else:
                    logger.warning("[UPDATE-WIN] No GUI callback available")

                return True

        logger.info("[UPDATE-WIN] No updates available")
        return False

    except URLError as e:
        logger.error(f"[UPDATE-WIN] Network error: {e}")
        return False
    except ET.ParseError as e:
        logger.error(f"[UPDATE-WIN] Invalid appcast XML: {e}")
        return False
    except Exception as e:
        logger.exception(f"[UPDATE-WIN] Unexpected error: {e}")
        return False


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
    """
    Trigger an interactive update check.
    Returns: "update_available", "up_to_date", or "error"
    """
    logger.info("[UPDATE-WIN] Checking for updates...")
    if not _current_version:
        _load_current_version()
    logger.info(f"[UPDATE-WIN] Current version loaded: {_current_version}")

    try:
        result = _check_appcast()
        if result:
            logger.info("[UPDATE-WIN] Update available")
            return "update_available"
        else:
            logger.info("[UPDATE-WIN] User is up to date")
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
