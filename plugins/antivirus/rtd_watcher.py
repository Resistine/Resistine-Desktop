"""Watch clamd.log for real-time threat detections and fire callbacks.

ClamdLogWatcher tails the shared clamd log file and invokes a callback
whenever clamonacc (or clamd) logs a FOUND line.  It handles log
rotation/truncation, deduplicates rapid-fire detections, and applies a
global rate limit so the user isn't overwhelmed with notifications.

Author: Resistine Team
Copyright (c) Resistine 2025
Licensed under the GNU General Public License v2 or later
"""

import os
import re
import threading
import time
from collections.abc import Callable

from plugins.antivirus.threat_log import (
    log_threat_detected,
    parse_infection_line,
)
from utils.logger import logger

_FOUND_RE = re.compile(r"->\s*(.+?:\s*.+?\s+FOUND)\s*$")

_POLL_INTERVAL = 1.0
_RETRY_INTERVAL = 5.0
_DEDUP_WINDOW = 30.0
_DEDUP_PRUNE_AGE = 60.0
_RATE_LIMIT = 5
_RATE_WINDOW = 30.0


class ClamdLogWatcher:
    """Tail clamd.log and fire *on_threat(filepath, signature)* on detections."""

    def __init__(
        self,
        log_path: str,
        on_threat: Callable[[str, str], None],
        on_summary: Callable[[int], None] | None = None,
    ):
        self._log_path = log_path
        self._on_threat = on_threat
        self._on_summary = on_summary
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None

    # ── Public API ───────────────────────────────────────────

    def start(self):
        if self._thread is not None and self._thread.is_alive():
            return
        self._stop_event.clear()
        self._thread = threading.Thread(
            target=self._run, daemon=True, name="rtd-watcher",
        )
        self._thread.start()

    def stop(self):
        self._stop_event.set()
        if self._thread is not None:
            self._thread.join(timeout=2)
            self._thread = None

    # ── Internal ─────────────────────────────────────────────

    def _run(self):
        """Main loop: open file, seek to end, tail lines."""
        while not self._stop_event.is_set():
            try:
                fh = self._open_at_end()
            except FileNotFoundError:
                logger.debug(
                    f"RTD watcher: {self._log_path} not found, retrying",
                )
                if self._stop_event.wait(timeout=_RETRY_INTERVAL):
                    return
                continue
            except PermissionError:
                logger.warning(
                    f"RTD watcher: no read access to {self._log_path}, "
                    "stopping",
                )
                return
            except OSError as exc:
                logger.warning(f"RTD watcher: open error: {exc}, retrying")
                if self._stop_event.wait(timeout=_RETRY_INTERVAL):
                    return
                continue

            try:
                self._tail(fh)
            except Exception as exc:
                logger.warning(f"RTD watcher: error during tail: {exc}")
            finally:
                try:
                    fh.close()
                except Exception:
                    pass

    def _open_at_end(self):
        fh = open(self._log_path)  # noqa: SIM115
        fh.seek(0, 2)
        return fh

    def _tail(self, fh):
        """Read new lines, detect rotation/truncation, dispatch threats."""
        dedup: dict[tuple[str, str], float] = {}
        rate_times: list[float] = []
        suppressed = [0]
        original_ino = os.fstat(fh.fileno()).st_ino

        while not self._stop_event.is_set():
            line = fh.readline()
            if line:
                self._process_line(line, dedup, rate_times, suppressed)
                continue

            # No new data — check for rotation / truncation
            try:
                st = os.stat(self._log_path)
            except FileNotFoundError:
                return
            except OSError:
                if self._stop_event.wait(timeout=_POLL_INTERVAL):
                    return
                continue

            # Inode changed → file was rotated
            if st.st_ino != original_ino:
                return

            # File truncated (size < position)
            if st.st_size < fh.tell():
                fh.seek(0)
                continue

            # If the burst is over, fire summary for suppressed detections
            self._maybe_flush_summary(rate_times, suppressed)

            self._prune_dedup(dedup)
            self._stop_event.wait(timeout=_POLL_INTERVAL)

    def _process_line(
        self,
        line: str,
        dedup: dict[tuple[str, str], float],
        rate_times: list[float],
        suppressed: list[int],
    ):
        if "FOUND" not in line:
            return

        # Extract the detection portion after the timestamp arrow
        m = _FOUND_RE.search(line)
        detection = m.group(1) if m else line.strip()
        filepath, signature = parse_infection_line(detection)

        if not filepath or signature == "Unknown":
            return

        now = time.monotonic()

        # Dedup: suppress identical (filepath, signature) within window
        key = (filepath, signature)
        last_seen = dedup.get(key)
        if last_seen is not None and (now - last_seen) < _DEDUP_WINDOW:
            return
        dedup[key] = now

        # Rate limit: prune old timestamps, check capacity
        cutoff = now - _RATE_WINDOW
        rate_times[:] = [t for t in rate_times if t > cutoff]

        if len(rate_times) >= _RATE_LIMIT:
            # Log to threats.log silently (no notification)
            try:
                log_threat_detected(signature, filepath)
            except Exception:
                pass
            suppressed[0] += 1
            return

        rate_times.append(now)
        try:
            self._on_threat(filepath, signature)
        except Exception as exc:
            logger.debug(f"RTD watcher: callback error: {exc}")

    def _maybe_flush_summary(
        self,
        rate_times: list[float],
        suppressed: list[int],
    ):
        """When a rate-limit burst is over, fire a summary callback."""
        if suppressed[0] == 0:
            return
        now = time.monotonic()
        cutoff = now - _RATE_WINDOW
        rate_times[:] = [t for t in rate_times if t > cutoff]
        # Burst still active — don't flush yet
        if len(rate_times) >= _RATE_LIMIT:
            return
        count = suppressed[0]
        suppressed[0] = 0
        if self._on_summary is not None:
            try:
                self._on_summary(count)
            except Exception as exc:
                logger.debug(f"RTD watcher: summary callback error: {exc}")

    def _prune_dedup(self, dedup: dict[tuple[str, str], float]):
        now = time.monotonic()
        stale = [k for k, ts in dedup.items() if now - ts > _DEDUP_PRUNE_AGE]
        for k in stale:
            del dedup[k]
