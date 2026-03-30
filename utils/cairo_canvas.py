# @file utils/cairo_canvas.py
"""
Drop-in tk.Canvas replacement that renders via Cairo on Linux.

On non-Linux platforms the class is just an alias for tk.Canvas, so every
call-site can unconditionally use ``CairoCanvas`` without platform checks.

Uses cairosvg (already a project dependency) to rasterise inline SVG
fragments, which are then displayed as PhotoImages on the underlying canvas.

Usage:
    from utils.cairo_canvas import CairoCanvas
    dot = CairoCanvas(parent, width=8, height=8, bg="#1a1a1a", highlightthickness=0)
    dot.create_oval(1, 1, 7, 7, fill="#ccc", outline="", tags="dot")
"""

import io
import sys
import tkinter as tk

_USE_CAIRO = sys.platform == "linux"

if _USE_CAIRO:
    try:
        import cairosvg
        from PIL import Image, ImageTk
    except (ImportError, OSError):
        _USE_CAIRO = False


if not _USE_CAIRO:
    CairoCanvas = tk.Canvas
else:

    class CairoCanvas(tk.Canvas):
        """A tk.Canvas that paints via cairosvg on Linux."""

        def __init__(self, master=None, **kw):
            super().__init__(master, **kw)
            self._cairo_items: dict[int, dict] = {}
            self._next_id = 1
            self._photo = None  # prevent GC of the current PhotoImage
            self._redraw_pending = False
            self._configured = False
            self.bind("<Configure>", self._on_configure)

        # ---- synthetic item IDs ---------------------------------------

        def _alloc_id(self) -> int:
            iid = self._next_id
            self._next_id += 1
            return iid

        def _on_configure(self, event):
            """Fires when the widget gets its real size from the layout."""
            self._configured = True
            if self._cairo_items:
                self._schedule_redraw()

        # ---- schedule a single coalesced redraw -----------------------

        def _schedule_redraw(self):
            if not self._configured:
                return
            if not self._redraw_pending:
                self._redraw_pending = True
                self.after_idle(self._cairo_redraw)

        # ---- drawing primitives (pure Cairo, no native Tk items) ------

        def create_oval(self, x0, y0, x1, y1, **kw):
            item_id = self._alloc_id()
            self._cairo_items[item_id] = {
                "type": "oval", "coords": (x0, y0, x1, y1),
                "fill": kw.get("fill", ""),
                "outline": kw.get("outline", "black"),
                "width": float(kw.get("width", 1)),
                "tags": kw.get("tags", ""),
            }
            self._schedule_redraw()
            return item_id

        def create_line(self, *args, **kw):
            item_id = self._alloc_id()
            self._cairo_items[item_id] = {
                "type": "line", "coords": tuple(args),
                "fill": kw.get("fill", "black"),
                "width": float(kw.get("width", 1)),
                "tags": kw.get("tags", ""),
            }
            self._schedule_redraw()
            return item_id

        def create_rectangle(self, x0, y0, x1, y1, **kw):
            item_id = self._alloc_id()
            self._cairo_items[item_id] = {
                "type": "rect", "coords": (x0, y0, x1, y1),
                "fill": kw.get("fill", ""),
                "outline": kw.get("outline", "black"),
                "width": float(kw.get("width", 1)),
                "tags": kw.get("tags", ""),
            }
            self._schedule_redraw()
            return item_id

        # ---- item mutation (Cairo-only, no super calls) ---------------

        def itemconfigure(self, tag_or_id, **kw):
            for iid, props in self._cairo_items.items():
                if self._matches(iid, tag_or_id):
                    for key in ("fill", "outline"):
                        if key in kw:
                            props[key] = kw[key]
                    if "width" in kw:
                        props["width"] = float(kw["width"])
            self._schedule_redraw()

        itemconfig = itemconfigure

        def delete(self, tag_or_id):
            if tag_or_id == "_cairo_img":
                super().delete(tag_or_id)
                return
            to_remove = [
                iid for iid in self._cairo_items
                if self._matches(iid, tag_or_id)
            ]
            for iid in to_remove:
                del self._cairo_items[iid]
            self._schedule_redraw()

        # ---- internal -------------------------------------------------

        def _matches(self, item_id: int, spec) -> bool:
            if isinstance(spec, int) or (isinstance(spec, str) and spec.isdigit()):
                return item_id == int(spec)
            tags = self._cairo_items.get(item_id, {}).get("tags", "")
            if isinstance(tags, (list, tuple)):
                return spec in tags
            return spec == tags

        def _resolve_color(self, color: str) -> str | None:
            """Resolve a Tk colour name to a hex string via winfo_rgb."""
            if not color or color == "":
                return None
            if color.startswith("#"):
                return color
            try:
                r, g, b = self.winfo_rgb(color)
                return f"#{r >> 8:02x}{g >> 8:02x}{b >> 8:02x}"
            except Exception:
                return None

        # ---- SVG generation -------------------------------------------

        def _build_svg(self, w: int, h: int) -> str:
            """Build an SVG string from all tracked items."""
            parts = [
                f'<svg xmlns="http://www.w3.org/2000/svg" '
                f'width="{w}" height="{h}" '
                f'viewBox="0 0 {w} {h}">'
            ]

            bg = self._resolve_color(self.cget("background"))
            if bg:
                parts.append(
                    f'<rect x="0" y="0" width="{w}" height="{h}" '
                    f'fill="{bg}" />'
                )

            for props in self._cairo_items.values():
                kind = props["type"]
                fill = self._resolve_color(props.get("fill", ""))
                outline = self._resolve_color(props.get("outline", ""))
                stroke_w = props.get("width", 1)

                fill_attr = f'fill="{fill}"' if fill else 'fill="none"'
                stroke_attr = (
                    f'stroke="{outline}" stroke-width="{stroke_w}"'
                    if outline else 'stroke="none"'
                )

                if kind == "oval":
                    x0, y0, x1, y1 = props["coords"]
                    cx = (x0 + x1) / 2
                    cy = (y0 + y1) / 2
                    rx = (x1 - x0) / 2
                    ry = (y1 - y0) / 2
                    parts.append(
                        f'<ellipse cx="{cx}" cy="{cy}" rx="{rx}" ry="{ry}" '
                        f'{fill_attr} {stroke_attr} />'
                    )

                elif kind == "line":
                    pts = props["coords"]
                    if len(pts) < 4:
                        continue
                    line_color = self._resolve_color(props["fill"])
                    points = " ".join(
                        f"{pts[i]},{pts[i+1]}" for i in range(0, len(pts), 2)
                    )
                    parts.append(
                        f'<polyline points="{points}" fill="none" '
                        f'stroke="{line_color or "black"}" '
                        f'stroke-width="{stroke_w}" />'
                    )

                elif kind == "rect":
                    x0, y0, x1, y1 = props["coords"]
                    parts.append(
                        f'<rect x="{x0}" y="{y0}" '
                        f'width="{x1 - x0}" height="{y1 - y0}" '
                        f'{fill_attr} {stroke_attr} />'
                    )

            parts.append("</svg>")
            return "\n".join(parts)

        # ---- redraw ---------------------------------------------------

        def _cairo_redraw(self):
            self._redraw_pending = False
            if not self.winfo_exists():
                return

            w = self.winfo_width() or int(self.cget("width"))
            h = self.winfo_height() or int(self.cget("height"))
            if w < 1 or h < 1:
                return

            svg = self._build_svg(w, h)
            try:
                png_data = cairosvg.svg2png(
                    bytestring=svg.encode("utf-8"),
                    output_width=w,
                    output_height=h,
                )
            except Exception as e:
                print(f"[CairoCanvas] svg2png FAILED: {e}")
                return

            img = Image.open(io.BytesIO(png_data))
            self._photo = ImageTk.PhotoImage(img)

            self.delete("_cairo_img")
            super().create_image(0, 0, anchor="nw", image=self._photo,
                                 tags="_cairo_img")
