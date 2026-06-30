"""Frame-rate throttle for live window-resize work.

On Windows, Tk's modal move/size loop (``WM_ENTERSIZEMOVE``..``WM_EXITSIZEMOVE``)
does not service Tcl ``after()`` timer callbacks until the drag ends.  A classic
``after()``-based *debounce* therefore leaves content frozen for the whole drag and
snaps it into place only on release.

``<Configure>`` events *do* arrive live during the drag, however, so the fix is to do
the layout work synchronously, inline in the handler.  ``ResizeThrottle`` coalesces
that inline work to a target frame rate: it applies on the leading edge (immediately,
live during the drag) at most once per interval, and schedules a single trailing
``after()`` so the final size still settles once motion stops.
"""

import time
import tkinter as tk


class ResizeThrottle:
    """Run ``apply_fn`` at most once per ``interval_ms``, driven from a ``<Configure>``.

    Leading-edge calls run synchronously (so they fire live during a Windows modal
    resize); a lone trailing ``after()`` guarantees the final frame is applied once
    the drag stops.  ``apply_fn`` takes no arguments — capture whatever it needs in a
    closure and read the current size with ``winfo_*`` when it runs.
    """

    def __init__(self, widget, apply_fn, interval_ms=33):
        self._widget = widget
        self._apply = apply_fn
        self._interval = max(0.0, interval_ms / 1000.0)
        self._last = 0.0
        self._job = None

    def trigger(self, event=None):
        """Bind this to ``<Configure>``; applies now or schedules a trailing pass."""
        now = time.monotonic()
        if now - self._last >= self._interval:
            self._last = now
            self.cancel()
            self._apply()
        elif self._job is None:
            delay = max(1, int((self._interval - (now - self._last)) * 1000))
            try:
                self._job = self._widget.after(delay, self._fire_trailing)
            except tk.TclError:
                self._job = None

    def _fire_trailing(self):
        self._job = None
        self._last = time.monotonic()
        self._apply()

    def cancel(self):
        """Cancel any pending trailing pass (safe to call on teardown)."""
        if self._job is not None:
            try:
                self._widget.after_cancel(self._job)
            except Exception:
                pass
            self._job = None
