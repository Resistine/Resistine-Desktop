"""High-level scan runner for the Antivirus plugin.

Wraps clamav.scan_path in a background thread so the UI stays responsive.

Author: Resistine Team
Copyright (c) Resistine 2025
Licensed under the GNU General Public License v2 or later
"""

import threading
from collections.abc import Callable
from dataclasses import dataclass, field

from plugins.antivirus import clamav


@dataclass
class ScanResult:
    """Parsed output from a ClamAV scan."""

    target: str = ""
    scanned: int = 0
    infected: int = 0
    infections: list[str] = field(default_factory=list)
    duration: str = ""
    error: str = ""


def scan(
    target: str,
    on_progress: Callable | None = None,
    on_complete: Callable | None = None,
):
    """Run a ClamAV scan on *target* in a background thread.

    Parameters
    ----------
    target:
        File or directory path to scan.
    on_progress:
        Called with ``(line: str)`` for each output line.
    on_complete:
        Called with ``(result: ScanResult)`` when finished.
    """
    if not clamav.is_available():
        result = ScanResult(
            target=target,
            error="ClamAV not installed — install it via the Store plugin.",
        )
        if on_complete:
            on_complete(result)
        return

    def _run():
        try:
            raw = clamav.scan_path(target, on_line=on_progress)
            result = ScanResult(
                target=raw["target"],
                scanned=raw["scanned"],
                infected=raw["infected"],
                infections=raw["infections"],
                duration=raw["duration"],
                error=raw["error"],
            )
        except Exception as exc:
            result = ScanResult(target=target, error=str(exc))
        if on_complete:
            on_complete(result)

    thread = threading.Thread(target=_run, daemon=True)
    thread.start()
