"""
Version Helper — reads the app version from packaging/Resistine.spec.

Provides a single source of truth for the current version on all platforms
when running from source (Linux, dev mode). On macOS frozen builds the
version comes from Info.plist instead, but this module serves as a fallback.

Author: Resistine Team
Copyright (c) Resistine 2025
Licensed under the GNU General Public License v2 or later
"""

import os
import re

from utils.logger import logger

_VERSION_RE = re.compile(r"^VERSION\s*=\s*['\"](.+?)['\"]", re.MULTILINE)

# Project root: utils/updates/version.py -> utils/updates -> utils -> project root
_PROJECT_ROOT = os.path.dirname(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
)


def get_project_root() -> str:
    """Return the absolute path to the project root directory."""
    return _PROJECT_ROOT


def get_current_version() -> str:
    """Parse VERSION = '...' from packaging/Resistine.spec.

    Returns the version string (e.g. '2026.03.19') or '0.0.0' if the
    spec file is missing or the VERSION line cannot be found.
    """
    spec_path = os.path.join(_PROJECT_ROOT, "packaging", "Resistine.spec")
    try:
        with open(spec_path, "r", encoding="utf-8") as f:
            content = f.read()
        match = _VERSION_RE.search(content)
        if match:
            return match.group(1)
    except (OSError, IOError) as e:
        logger.warning(f"[VERSION] Could not read spec file: {e}")
    return "0.0.0"


def compare_versions(current: str, remote: str) -> int:
    """Compare two dot-separated version strings.

    Splits on '.' and compares each segment as an integer.
    Returns -1 if current < remote, 0 if equal, 1 if current > remote.
    """
    def _parts(v):
        try:
            return [int(x) for x in v.split(".")]
        except (ValueError, AttributeError):
            return [0]

    c = _parts(current)
    r = _parts(remote)
    # Pad to equal length
    length = max(len(c), len(r))
    c.extend([0] * (length - len(c)))
    r.extend([0] * (length - len(r)))

    for a, b in zip(c, r):
        if a < b:
            return -1
        if a > b:
            return 1
    return 0
