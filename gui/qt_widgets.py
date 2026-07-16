"""Reusable presentational widgets for the PyQt UI.

Small building blocks shared across plugin screens — a flow layout that reflows
cards on resize, status badges, section cards, an icon loader that picks the
light/dark PNG variant, and a couple of layout helpers.

Author: Resistine Team
Copyright (c) Resistine 2025
Licensed under the GNU General Public License v2 or later
"""

from __future__ import annotations

import os

from PyQt6.QtCore import QPoint, QRect, QSize, Qt
from PyQt6.QtGui import QIcon, QPixmap
from PyQt6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QLayout,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from gui import theme

_ROOT = os.path.dirname(os.path.dirname(os.path.realpath(__file__)))


def resource(*parts: str) -> str:
    """Absolute path under the repo root (e.g. resource('resources','icons'))."""
    return os.path.join(_ROOT, *parts)


def load_icon(light_path: str, dark_path: str) -> QIcon:
    """Pick the icon variant matching the active appearance mode."""
    path = light_path if not theme.is_dark() else dark_path
    if path and os.path.isfile(path):
        return QIcon(path)
    return QIcon()


def pixmap(path: str, size: int) -> QPixmap:
    if path and os.path.isfile(path):
        return QPixmap(path).scaled(
            size, size,
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
    return QPixmap()


class StatusBadge(QLabel):
    """A small rounded pill coloured by status (ok/info/warning/error/...)."""

    def __init__(self, status: str | None, parent: QWidget | None = None):
        super().__init__(parent)
        self.set_status(status)

    def set_status(self, status: str | None) -> None:
        if not status:
            self.hide()
            return
        self.show()
        self.setText(str(status).title())
        self.setProperty("badge", str(status).lower())
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setSizePolicy(QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Fixed)
        self.style().unpolish(self)
        self.style().polish(self)


class Card(QFrame):
    """A bordered, rounded surface used for cards and panels."""

    def __init__(self, parent: QWidget | None = None, object_name: str = "Card"):
        super().__init__(parent)
        self.setObjectName(object_name)
        self.setFrameShape(QFrame.Shape.NoFrame)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(16, 16, 16, 16)
        lay.setSpacing(8)
        self.body = lay


def section_title(text: str) -> QLabel:
    lbl = QLabel(text)
    lbl.setObjectName("H2")
    return lbl


def heading(text: str) -> QLabel:
    lbl = QLabel(text)
    lbl.setObjectName("H1")
    return lbl


def muted(text: str) -> QLabel:
    lbl = QLabel(text)
    lbl.setObjectName("Muted")
    lbl.setWordWrap(True)
    return lbl


def scroll_page(inner: QWidget) -> QScrollArea:
    """Wrap content in a vertically scrolling page."""
    area = QScrollArea()
    area.setWidgetResizable(True)
    area.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
    area.setWidget(inner)
    return area


def centered(inner: QWidget, max_width: int = 760, min_width: int = 420) -> QWidget:
    """Constrain content to a centered column (mirrors AV/VPN layout)."""
    wrap = QWidget()
    h = QHBoxLayout(wrap)
    h.setContentsMargins(24, 20, 24, 24)
    h.addStretch(1)
    inner.setMaximumWidth(max_width)
    inner.setMinimumWidth(min_width)
    h.addWidget(inner, 3)
    h.addStretch(1)
    return wrap


class FlowLayout(QLayout):
    """A reflowing layout — items wrap to the next row as width shrinks."""

    def __init__(self, parent=None, margin=0, spacing=16, center=False):
        super().__init__(parent)
        if parent is not None:
            self.setContentsMargins(margin, margin, margin, margin)
        self._spacing = spacing
        self._center = center
        self._items: list = []

    def addItem(self, item):
        self._items.append(item)

    def count(self):
        return len(self._items)

    def itemAt(self, index):
        return self._items[index] if 0 <= index < len(self._items) else None

    def takeAt(self, index):
        return self._items.pop(index) if 0 <= index < len(self._items) else None

    def expandingDirections(self):
        return Qt.Orientation(0)

    def hasHeightForWidth(self):
        return True

    def heightForWidth(self, width):
        return self._do_layout(QRect(0, 0, width, 0), test_only=True)

    def setGeometry(self, rect):
        super().setGeometry(rect)
        self._do_layout(rect, test_only=False)

    def sizeHint(self):
        return self.minimumSize()

    def minimumSize(self):
        size = QSize()
        for item in self._items:
            size = size.expandedTo(item.minimumSize())
        size += QSize(2 * self._spacing, 2 * self._spacing)
        return size

    def _do_layout(self, rect, test_only):
        # Group items into rows first, then position each row — centering it
        # horizontally within the available width when `center` is enabled.
        rows = []  # (items[(item, w, h)], row_width, row_height)
        cur, cur_w, cur_h = [], 0, 0
        for item in self._items:
            w = item.sizeHint().width()
            h = item.sizeHint().height()
            add_w = w if not cur else self._spacing + w
            if cur and cur_w + add_w > rect.width():
                rows.append((cur, cur_w, cur_h))
                cur, cur_w, cur_h = [], 0, 0
                add_w = w
            cur.append((item, w, h))
            cur_w += add_w
            cur_h = max(cur_h, h)
        if cur:
            rows.append((cur, cur_w, cur_h))

        y = rect.y()
        for items, row_w, row_h in rows:
            x = rect.x()
            if self._center:
                x += max(0, (rect.width() - row_w) // 2)
            for item, w, h in items:
                if not test_only:
                    item.setGeometry(QRect(QPoint(x, y), QSize(w, h)))
                x += w + self._spacing
            y += row_h + self._spacing
        return (y - self._spacing - rect.y()) if rows else 0
