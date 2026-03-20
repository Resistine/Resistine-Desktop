"""
Windows auto-updater using WinSparkle appcast format.
Checks resistine.github.io for updates and prompts user to download.

Authors: Resistine Team
"""
import os
import sys
import threading
import xml.etree.ElementTree as ET
from pathlib import Path
from urllib.request import urlopen
from urllib.error import URLError
from datetime import datetime
import json

from utils.logger import logger


class WindowsUpdater:
    """Check and manage Windows updates via appcast.xml"""

    APPCAST_URL = "https://resistine.github.io/appcast.xml"
    CURRENT_VERSION = None  # Will be read from packaging/Resistine.spec

    def __init__(self):
        """Initialize the updater and read current version."""
        self._load_current_version()
        self.latest_version = None
        self.download_url = None

    def _load_current_version(self):
        """Load the current app version from packaging/Resistine.spec."""
        try:
            spec_path = Path(__file__).parent.parent.parent / "packaging" / "Resistine.spec"
            if spec_path.exists():
                with open(spec_path, "r") as f:
                    for line in f:
                        if line.startswith("VERSION"):
                            # Extract version from: VERSION = '2026.03.19'
                            version = line.split("=")[1].strip().strip("'\"")
                            WindowsUpdater.CURRENT_VERSION = version
                            logger.debug(f"Loaded app version: {version}")
                            return
        except Exception as e:
            logger.error(f"Failed to load version from spec: {e}")

    def check_for_updates(self):
        """
        Check appcast.xml for Windows updates.
        Returns (has_update, version, url, description) or (False, None, None, None)
        """
        try:
            logger.info(f"Checking for Windows updates (current: {self.CURRENT_VERSION})")

            with urlopen(self.APPCAST_URL, timeout=10) as response:
                appcast_data = response.read()

            root = ET.fromstring(appcast_data)
            # Namespace for Sparkle
            ns = {"sparkle": "http://www.andymatuschak.org/xml-namespaces/sparkle"}

            # Find all items
            for item in root.findall(".//item"):
                # Check if this is a Windows item
                os_attr = item.get("os")
                if os_attr and os_attr.lower() != "windows":
                    continue
                if os_attr is None:
                    # Items without os attribute are typically macOS, skip them
                    enclosure = item.find("enclosure")
                    if enclosure is not None:
                        url = enclosure.get("url", "")
                        # Skip if it's a DMG (macOS) or Android
                        if url.endswith(".dmg") or "android" in url.lower():
                            continue

                # Found a Windows item
                title = item.findtext("title", "Unknown")
                version = item.findtext("sparkle:version", ns=ns) or \
                         item.findtext("sparkle:shortVersionString", ns=ns)

                if not version:
                    continue

                # Check if this version is newer
                if self._compare_versions(version, self.CURRENT_VERSION) > 0:
                    enclosure = item.find("enclosure")
                    if enclosure is not None:
                        url = enclosure.get("url")
                        length = enclosure.get("length", "0")

                        description = item.findtext("description", "")

                        self.latest_version = version
                        self.download_url = url

                        logger.info(
                            f"Update available: {version} at {url} ({length} bytes)"
                        )
                        return (True, version, url, description)

            logger.info("No updates available")
            return (False, None, None, None)

        except URLError as e:
            logger.warning(f"Failed to check updates (network error): {e}")
        except ET.ParseError as e:
            logger.error(f"Failed to parse appcast.xml: {e}")
        except Exception as e:
            logger.exception(f"Unexpected error checking updates: {e}")

        return (False, None, None, None)

    @staticmethod
    def _compare_versions(v1: str, v2: str) -> int:
        """
        Compare two version strings.
        Returns: > 0 if v1 > v2, 0 if equal, < 0 if v1 < v2
        """
        try:
            # Try numeric comparison for date-based versions (2026.03.19)
            parts1 = [int(x) for x in v1.split(".")]
            parts2 = [int(x) for x in v2.split(".")]

            for p1, p2 in zip(parts1, parts2):
                if p1 > p2:
                    return 1
                if p1 < p2:
                    return -1

            # If all compared parts are equal, longer version is newer
            return len(parts1) - len(parts2)
        except (ValueError, AttributeError):
            # Fallback: simple string comparison
            return 1 if v1 > v2 else (-1 if v1 < v2 else 0)

    def download_update(self, destination: str = None) -> bool:
        """
        Download the update installer.
        Returns True if successful, False otherwise.
        """
        if not self.download_url:
            logger.error("No update URL available")
            return False

        if destination is None:
            destination = os.path.join(
                os.environ.get("TEMP", "/tmp"),
                f"Resistine-Setup-{self.latest_version}.exe"
            )

        try:
            logger.info(f"Downloading update from {self.download_url}")

            with urlopen(self.download_url, timeout=30) as response:
                total_size = int(response.headers.get("content-length", 0))
                downloaded = 0
                chunk_size = 8192

                with open(destination, "wb") as f:
                    while True:
                        chunk = response.read(chunk_size)
                        if not chunk:
                            break
                        f.write(chunk)
                        downloaded += len(chunk)

                        if total_size > 0:
                            progress = (downloaded / total_size) * 100
                            logger.debug(f"Download progress: {progress:.1f}%")

            logger.info(f"Update downloaded to {destination}")
            return True

        except Exception as e:
            logger.error(f"Failed to download update: {e}")
            try:
                os.remove(destination)
            except Exception:
                pass
            return False

    def install_update(self, installer_path: str) -> bool:
        """
        Launch the installer to update the application.
        """
        try:
            import subprocess
            logger.info(f"Launching installer: {installer_path}")

            # Run installer and exit the app
            subprocess.Popen([installer_path])
            return True

        except Exception as e:
            logger.error(f"Failed to launch installer: {e}")
            return False


class BackgroundUpdateChecker:
    """Check for updates in the background periodically."""

    def __init__(self, check_interval_hours: int = 24):
        """Initialize background update checker."""
        self.check_interval = check_interval_hours * 3600  # Convert to seconds
        self.updater = WindowsUpdater()
        self.stop_event = threading.Event()
        self.thread = None

    def start(self):
        """Start the background update check thread."""
        if self.thread and self.thread.is_alive():
            logger.debug("Background update checker already running")
            return

        self.stop_event.clear()
        self.thread = threading.Thread(target=self._check_loop, daemon=True)
        self.thread.start()
        logger.info("Background update checker started")

    def stop(self):
        """Stop the background update check thread."""
        self.stop_event.set()
        if self.thread:
            self.thread.join(timeout=5)
        logger.info("Background update checker stopped")

    def _check_loop(self):
        """Periodically check for updates."""
        while not self.stop_event.is_set():
            try:
                has_update, version, url, desc = self.updater.check_for_updates()
                if has_update:
                    logger.info(f"Update available: {version}")
                    # TODO: Trigger UI notification/dialog
            except Exception as e:
                logger.error(f"Error in update check loop: {e}")

            # Wait for the interval or until stop is signaled
            self.stop_event.wait(self.check_interval)
