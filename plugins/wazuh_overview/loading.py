"""Circular-progress loading screens for the Wazuh Overview tabs.

Each tab (Overview, Events, Vulnerabilities, Inventory) shows a centered ring
while its background fetches are in flight. Tabs whose loaders expose granular
readiness (Overview's six /me/* endpoints) drive the ring from a real fraction;
the rest use a time-based ramp that eases toward a ceiling and snaps to 100%
when the data lands, so the ring never stalls at a fixed value.

Colours are read from the theme at paint time, so light/dark switches are
picked up by a plain ``update()`` with no rebuild.

Author: Resistine Team
Copyright (c) Resistine 2025
Licensed under the GNU General Public License v2 or later
"""

from __future__ import annotations

import math
import time

from PyQt6.QtCore import QRectF, Qt, QTimer
from PyQt6.QtGui import QColor, QFont, QPainter, QPen
from PyQt6.QtWidgets import QLabel, QVBoxLayout, QWidget

from gui import theme

# Ring geometry (device-independent pixels).
_RING_SIZE = 104
_RING_THICKNESS = 8
# Displayed value chases the target at this fraction per frame (~60fps), which
# reads as a smooth catch-up rather than a jump when an endpoint lands.
_EASE = 0.14
_FRAME_MS = 16


class CircularProgress(QWidget):
    """A determinate ring with the percentage drawn in the middle."""

    def __init__(self, size=_RING_SIZE, thickness=_RING_THICKNESS, parent=None):
        super().__init__(parent)
        self._size = size
        self._thickness = thickness
        self._target = 0.0
        self._shown = 0.0
        self.setFixedSize(size, size)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)

        self._anim = QTimer(self)
        self._anim.setInterval(_FRAME_MS)
        self._anim.timeout.connect(self._step)

    def set_value(self, fraction):
        """Set the target fill, 0.0-1.0. The ring eases toward it."""
        self._target = max(0.0, min(1.0, float(fraction)))
        if not self._anim.isActive():
            self._anim.start()

    def value(self):
        return self._target

    def _step(self):
        delta = self._target - self._shown
        if abs(delta) < 0.001:
            self._shown = self._target
            self._anim.stop()
        else:
            self._shown += delta * _EASE
        self.update()

    def paintEvent(self, event):  # noqa: N802 - Qt override
        del event
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)

        inset = self._thickness / 2.0 + 1
        rect = QRectF(inset, inset, self._size - 2 * inset, self._size - 2 * inset)

        track = QPen(QColor(theme.color("track")), self._thickness)
        track.setCapStyle(Qt.PenCapStyle.RoundCap)
        p.setPen(track)
        p.drawArc(rect, 0, 360 * 16)

        if self._shown > 0:
            arc = QPen(QColor(theme.color("accent")), self._thickness)
            arc.setCapStyle(Qt.PenCapStyle.RoundCap)
            p.setPen(arc)
            # 12 o'clock start, clockwise sweep (Qt angles are 1/16 degree, CCW).
            p.drawArc(rect, 90 * 16, -int(round(360 * 16 * self._shown)))

        font = QFont(self.font())
        font.setPointSize(max(11, int(self._size * 0.17)))
        font.setBold(True)
        p.setFont(font)
        p.setPen(QColor(theme.color("text_primary")))
        p.drawText(
            self.rect(),
            Qt.AlignmentFlag.AlignCenter,
            f"{int(math.floor(self._shown * 100))}%",
        )
        p.end()


class RampProgress:
    """Synthetic progress for loaders that only report done/not-done.

    Approaches ``ceiling`` asymptotically on an exponential curve, so the ring
    keeps moving without ever implying completion it can't confirm.
    """

    def __init__(self, tau=4.0, ceiling=0.92):
        self._tau = tau
        self._ceiling = ceiling
        self._start = time.monotonic()

    def reset(self):
        self._start = time.monotonic()

    def __call__(self):
        elapsed = time.monotonic() - self._start
        return self._ceiling * (1.0 - math.exp(-elapsed / self._tau))


class LoadingScreen(QWidget):
    """Centered ring + caption, polled from a progress callable.

    ``progress_fn`` returns a float 0.0-1.0. ``done_fn`` (optional) returns True
    once the underlying data is ready; the ring then completes and polling
    stops. The caller is responsible for swapping this widget out for content —
    the existing per-tab readiness checks already do that.
    """

    _POLL_MS = 120

    def __init__(self, title, subtitle=None, progress_fn=None, done_fn=None, parent=None):
        super().__init__(parent)
        self.setObjectName("Transparent")
        self._progress_fn = progress_fn or RampProgress()
        self._done_fn = done_fn

        col = QVBoxLayout(self)
        col.setContentsMargins(24, 24, 24, 24)
        col.setSpacing(0)
        col.addStretch(1)

        self.ring = CircularProgress()
        col.addWidget(self.ring, alignment=Qt.AlignmentFlag.AlignHCenter)

        col.addSpacing(18)
        col.addWidget(
            _caption(title, size=15, bold=True), alignment=Qt.AlignmentFlag.AlignHCenter
        )
        if subtitle:
            col.addSpacing(6)
            col.addWidget(
                _caption(subtitle, size=12, secondary=True),
                alignment=Qt.AlignmentFlag.AlignHCenter,
            )
        col.addStretch(1)

        self._poll = QTimer(self)
        self._poll.setInterval(self._POLL_MS)
        self._poll.timeout.connect(self._tick)
        self._poll.start()
        self._tick()

    def _tick(self):
        if self._done_fn is not None and self._done_fn():
            self.ring.set_value(1.0)
            self._poll.stop()
            return
        try:
            self.ring.set_value(self._progress_fn())
        except Exception:
            self._poll.stop()


def _caption(text, *, size=13, bold=False, secondary=False):
    lab = QLabel(text)
    lab.setObjectName("Transparent")
    color = theme.color("text_secondary" if secondary else "text_primary")
    weight = "600" if bold else "400"
    lab.setStyleSheet(
        f"color:{color}; font-size:{size}px; font-weight:{weight}; background:transparent;"
    )
    lab.setAlignment(Qt.AlignmentFlag.AlignCenter)
    return lab
