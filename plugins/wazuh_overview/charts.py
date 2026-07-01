"""matplotlib-on-Qt chart helpers for the Wazuh Overview plugin.

The Events and Vulnerabilities tabs draw with matplotlib via its Qt backend
(``FigureCanvasQTAgg``). Qt resizes the canvas natively as its widget resizes,
so none of the original CustomTkinter "freeze-and-scale" snapshot machinery is
needed — a Figure in a Qt layout just tracks its cell.

Two deliberate footprint choices carried over from the source:

1. ``matplotlib.pyplot`` is never imported. pyplot is ~200KB of helpers built
   around a global figure registry this app doesn't use — every chart is a bare
   ``Figure(...)``; cleanup is ``fig.clear()``, not ``pyplot.close()``.
2. ``font.sans-serif`` is pinned to the bundled DejaVu Sans so
   ``font_manager.findfont()`` resolves on the first candidate instead of
   scoring the ~10-font default chain against the system cache on every render.

Author: Resistine Team
Copyright (c) Resistine 2025
Licensed under the GNU General Public License v2 or later
"""

from __future__ import annotations

from gui import theme

_Figure = None
_FigureCanvas = None


def ensure_matplotlib():
    """Lazy-import matplotlib with the Qt backend and a minimal footprint.

    Returns ``(Figure, FigureCanvasQTAgg)``. Safe to call repeatedly — the
    heavy import happens once and is cached at module scope."""
    global _Figure, _FigureCanvas
    if _Figure is None:
        import logging as _logging

        # matplotlib's font_manager logs a DEBUG line per scored font candidate
        # on every render; with Loguru intercepting stdlib logging at DEBUG
        # (main.py -d) that floods the log. Silence its DEBUG/INFO at the source.
        _logging.getLogger("matplotlib").setLevel(_logging.WARNING)

        import matplotlib

        matplotlib.use("QtAgg")
        # Pin fonts before any Figure is built so findfont short-circuits.
        matplotlib.rcParams["font.family"] = ["sans-serif"]
        matplotlib.rcParams["font.sans-serif"] = ["DejaVu Sans"]
        matplotlib.rcParams["text.usetex"] = False

        from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg
        from matplotlib.figure import Figure

        _Figure, _FigureCanvas = Figure, FigureCanvasQTAgg
    return _Figure, _FigureCanvas


def chart_theme():
    """Theme-resolved colours for chart chrome, matching the card the chart
    sits on so it blends in. Read on every render; cheap enough not to cache."""
    return {
        "bg": theme.color("card_bg"),
        "text": theme.color("text_primary"),
        "grid": theme.color("border"),
        "is_dark": theme.is_dark(),
    }


def make_canvas(parent, figsize, *, facecolor=None):
    """Build a bare Figure + Qt canvas parented to ``parent``.

    Returns ``(figure, canvas, axes)`` with a single subplot already added.
    ``facecolor`` defaults to the card background so the figure blends into its
    surrounding card."""
    Figure, FigureCanvas = ensure_matplotlib()
    if facecolor is None:
        facecolor = theme.color("card_bg")
    fig = Figure(figsize=figsize, dpi=100, facecolor=facecolor)
    canvas = FigureCanvas(fig)
    canvas.setParent(parent)
    canvas.setStyleSheet("background: transparent;")
    ax = fig.add_subplot(111)
    return fig, canvas, ax
