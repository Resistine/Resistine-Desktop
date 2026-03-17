## @file main.py
## @namespace main
"""
This script is to run the main window for the Resistine AI EndPoint application.
Author: Petr, Javier, Jackie and the Resistine Team
Copyright (c) Resistine 2025
Licensed under the GNU General Public License v2 or later
"""

import argparse
import ctypes
import os
import sys
import customtkinter
import customtkinter.windows.widgets.ctk_scrollable_frame as _sf

if sys.platform.startswith("linux"):
    import math
    import tkinter
    try:
        import cairo
    except ImportError:
        import cairocffi as cairo
    from PIL import Image, ImageTk
    from customtkinter.windows.widgets.core_rendering import DrawEngine
    from customtkinter.windows.widgets.core_rendering import CTkCanvas

    def _get_rgba(widget, attr_name, default_color="black", alpha=1.0):
        """Resolves any CTk color (list, hex, name) to Cairo RGBA.
        
        Mirrors CTk's own _draw() logic: if the requested attribute is
        'transparent', fall back to _bg_color (what CTk uses for border_parts
        when border_color == 'transparent'), not invisible black.
        """
        color_val = getattr(widget, attr_name, None)
        if color_val is None:
            color_val = default_color
        if isinstance(color_val, (list, tuple)):
            color_val = widget._apply_appearance_mode(color_val)
        
        # "transparent" means: show whatever is behind this widget — i.e. bg_color
        if color_val == "transparent":
            bg = getattr(widget, "_bg_color", None)
            if bg is None:
                return (0, 0, 0, 0)
            if isinstance(bg, (list, tuple)):
                bg = widget._apply_appearance_mode(bg)
            color_val = bg

        if color_val is None:
            return (0, 0, 0, 0)
            
        try:
            r, g, b = widget.winfo_rgb(color_val)
            return (r/65535.0, g/65535.0, b/65535.0, alpha)
        except Exception:
            return (0, 0, 0, 0)

    def _render_cairo_to_tk(self, width, height, draw_func):
        """Bridge between Cairo rendering and Tkinter PhotoImage."""
        # Use a small padding to prevent edge clipping during AA
        w, h = math.ceil(width), math.ceil(height)
        surface = cairo.ImageSurface(cairo.FORMAT_ARGB32, w, h)
        ctx = cairo.Context(surface)
        draw_func(ctx, w, h)
        
        # Convert Cairo surface to PIL Image, then to PhotoImage
        # Use bytes() as cairocffi buffer doesn't have .tobytes()
        img = Image.frombuffer("RGBA", (w, h), bytes(surface.get_data()), "raw", "BGRA", 0, 1)
        photo = ImageTk.PhotoImage(img)
        
        # GC Prevention: store the photo on the widget instance
        if not hasattr(self, "_cairo_photos"): self._cairo_photos = {}
        return photo

    def _cairo_rounded_rect(ctx, x, y, w, h, r):
        if r <= 0: ctx.rectangle(x, y, w, h); return
        r = min(r, w/2, h/2)
        ctx.new_sub_path()
        ctx.arc(x + w - r, y + r, r, -0.5 * math.pi, 0)
        ctx.arc(x + w - r, y + h - r, r, 0, 0.5 * math.pi)
        ctx.arc(x + r, y + h - r, r, 0.5 * math.pi, math.pi)
        ctx.arc(x + r, y + r, r, math.pi, 1.5 * math.pi)
        ctx.close_path()

    def _draw_smooth_polygon_shapes(self, width, height, corner_radius, border_width):
        master = self._canvas.master
        def draw(ctx, w, h):
            r, bw = (corner_radius or 0), (border_width or 0)
            # Fill entire surface with bg_color first — this is what shows through
            # at the rounded corners, matching what canvas.configure(bg=_bg_color) does
            # for the Tk polygon approach. Without this, corners composite against black.
            ctx.set_source_rgba(*_get_rgba(master, "_bg_color"))
            ctx.paint()
            if bw > 0:
                ctx.set_source_rgba(*_get_rgba(master, "_border_color", default_color="transparent"))
                _cairo_rounded_rect(ctx, 0, 0, width, height, r)
                ctx.fill()
            ctx.set_source_rgba(*_get_rgba(master, "_fg_color"))
            _cairo_rounded_rect(ctx, bw, bw, width - 2*bw, height - 2*bw, max(0, r - bw))
            ctx.fill()

        photo = _render_cairo_to_tk(self, width, height, draw)
        self._cairo_photos["main"] = photo
        
        if not self._canvas.find_withtag("cairo_main"):
            self._canvas.create_image(0, 0, anchor="nw", image=photo, tags=("cairo_main", "inner_parts"))
        else:
            self._canvas.itemconfig("cairo_main", image=photo)
        self._canvas.tag_lower("cairo_main")
        return False

    def _draw_smooth_scrollbar(self, width, height, corner_radius, inner_corner_radius, start_value, end_value, orientation):
        master = self._canvas.master
        def draw(ctx, w, h):
            ctx.set_source_rgba(*_get_rgba(master, "_fg_color")) # Track/BG
            ctx.rectangle(0, 0, width, height)
            ctx.fill()
            ctx.set_source_rgba(*_get_rgba(master, "_button_color")) # Handle
            if orientation == "vertical":
                bar_w, bar_h = width - 2 * corner_radius, (height - 2 * corner_radius) * (end_value - start_value)
                y, x = (height - 2 * corner_radius) * start_value + corner_radius, corner_radius
            else:
                bar_w, bar_h = (width - 2 * corner_radius) * (end_value - start_value), height - 2 * corner_radius
                x, y = (width - 2 * corner_radius) * start_value + corner_radius, corner_radius
            _cairo_rounded_rect(ctx, x - inner_corner_radius, y - inner_corner_radius, 
                                bar_w + 2*inner_corner_radius, bar_h + 2*inner_corner_radius, inner_corner_radius)
            ctx.fill()

        photo = _render_cairo_to_tk(self, width, height, draw)
        self._cairo_photos["scrollbar"] = photo
        
        if not self._canvas.find_withtag("cairo_scrollbar"):
            self._canvas.create_image(0, 0, anchor="nw", image=photo, tags=("cairo_scrollbar", "scrollbar_parts"))
        else:
            self._canvas.itemconfig("cairo_scrollbar", image=photo)
        return False

    def _draw_smooth_progress_bar(self, width, height, corner_radius, border_width, v1, v2, orientation):
        master = self._canvas.master
        def draw(ctx, w, h):
            r, bw = (corner_radius or 0), (border_width or 0)
            inner_r = max(0, r - bw)
            # Fill corners with bg_color so rounded corners don't composite against black
            ctx.set_source_rgba(*_get_rgba(master, "_bg_color"))
            ctx.paint()
            # 1. Background/Border
            if bw > 0:
                ctx.set_source_rgba(*_get_rgba(master, "_border_color", default_color="transparent"))
                _cairo_rounded_rect(ctx, 0, 0, width, height, r)
                ctx.fill()
            ctx.set_source_rgba(*_get_rgba(master, "_fg_color"))
            _cairo_rounded_rect(ctx, bw, bw, width - 2*bw, height - 2*bw, inner_r)
            ctx.fill()

            # 2. Progress Fill
            if abs(v1 - v2) > 0.0001:
                ctx.set_source_rgba(*_get_rgba(master, "_progress_color"))
                if orientation in ["horizontal", "w", "e"]:
                    usable_w = max(0, width - 2 * bw)
                    x_start, x_end = bw + usable_w * v1, bw + usable_w * v2
                    _cairo_rounded_rect(ctx, x_start, bw, max(1, x_end - x_start), max(1, height - 2 * bw), inner_r)
                else:
                    usable_h = max(0, height - 2 * bw)
                    y_start, y_end = bw + usable_h * (1 - v2), bw + usable_h * (1 - v1)
                    _cairo_rounded_rect(ctx, bw, y_start, max(1, width - 2 * bw), max(1, y_end - y_start), inner_r)
                ctx.fill()

        photo = _render_cairo_to_tk(self, width, height, draw)
        self._cairo_photos["progress"] = photo
        if not self._canvas.find_withtag("cairo_progress"):
            self._canvas.create_image(0, 0, anchor="nw", image=photo, tags=("cairo_progress", "progress_parts"))
        else:
            self._canvas.itemconfig("cairo_progress", image=photo)
        self._canvas.tag_lower("cairo_progress")
        return False

    def _draw_smooth_slider(self, width, height, corner_radius, border_width, button_length, button_corner_radius, slider_value, orientation):
        master = self._canvas.master
        def draw(ctx, w, h):
            r, bw = (corner_radius or 0), (border_width or 0)
            inner_r = max(0, r - bw)
            # Fill corners with bg_color so rounded corners don't composite against black
            ctx.set_source_rgba(*_get_rgba(master, "_bg_color"))
            ctx.paint()
            # 1. Background/Border
            if bw > 0:
                ctx.set_source_rgba(*_get_rgba(master, "_border_color", default_color="transparent"))
                _cairo_rounded_rect(ctx, 0, 0, width, height, r)
                ctx.fill()
            ctx.set_source_rgba(*_get_rgba(master, "_fg_color"))
            _cairo_rounded_rect(ctx, bw, bw, width - 2*bw, height - 2*bw, inner_r)
            ctx.fill()

            # 2. Progress Fill
            ctx.set_source_rgba(*_get_rgba(master, "_progress_color"))
            if orientation in ["horizontal", "w", "e"]:
                usable_w = max(0, width - 2 * bw)
                _cairo_rounded_rect(ctx, bw, bw, usable_w * slider_value, height - 2 * bw, inner_r)
            else:
                usable_h = max(0, height - 2 * bw)
                _cairo_rounded_rect(ctx, bw, bw + usable_h * (1 - slider_value), width - 2 * bw, usable_h * slider_value, inner_r)
            ctx.fill()

            # 3. Slider Button
            ctx.set_source_rgba(*_get_rgba(master, "_button_color"))
            br = (button_corner_radius or 0)
            if orientation in ["horizontal", "w", "e"]:
                if button_length == 0:
                    # Circular dot: clamp radius to fit inside the track height
                    dot_r = min(br, (height - 2 * bw) / 2)
                    # Centre x travels only within [bw+dot_r, width-bw-dot_r] so dot stays inside track
                    usable_w = max(0, width - 2 * bw - 2 * dot_r)
                    cx = bw + dot_r + usable_w * slider_value
                    cy = height / 2
                    ctx.arc(cx, cy, dot_r, 0, 2 * math.pi)
                    ctx.fill()
                else:
                    bx = (width - button_length) * slider_value
                    _cairo_rounded_rect(ctx, bx, 0, button_length, height, br)
                    ctx.fill()
            else:
                if button_length == 0:
                    dot_r = min(br, (width - 2 * bw) / 2)
                    usable_h = max(0, height - 2 * bw - 2 * dot_r)
                    cx = width / 2
                    cy = bw + dot_r + usable_h * (1 - slider_value)
                    ctx.arc(cx, cy, dot_r, 0, 2 * math.pi)
                    ctx.fill()
                else:
                    by = (height - button_length) * (1 - slider_value)
                    _cairo_rounded_rect(ctx, 0, by, width, button_length, br)
                    ctx.fill()

        photo = _render_cairo_to_tk(self, width, height, draw)
        self._cairo_photos["slider"] = photo
        if not self._canvas.find_withtag("cairo_slider"):
            self._canvas.create_image(0, 0, anchor="nw", image=photo, tags=("cairo_slider", "slider_parts"))
        else:
            self._canvas.itemconfig("cairo_slider", image=photo)
        self._canvas.tag_lower("cairo_slider")
        return False

    def _draw_smooth_vertical_split(self, width, height, corner_radius, border_width, left_section_width):
        master = self._canvas.master
        def draw(ctx, w, h):
            r, bw, lw = (corner_radius or 0), (border_width or 0), (left_section_width or 0)
            inner_r = max(0, r - bw)
            # Fill corners with bg_color so rounded corners don't composite against black
            ctx.set_source_rgba(*_get_rgba(master, "_bg_color"))
            ctx.paint()
            if bw > 0:
                ctx.set_source_rgba(*_get_rgba(master, "_border_color", default_color="transparent"))
                _cairo_rounded_rect(ctx, 0, 0, width, height, r)
                ctx.fill()
            ctx.set_source_rgba(*_get_rgba(master, "_left_section_color"))
            ctx.new_sub_path()
            ctx.arc(bw + inner_r, height - bw - inner_r, inner_r, 0.5 * math.pi, math.pi)
            ctx.arc(bw + inner_r, bw + inner_r, inner_r, math.pi, 1.5 * math.pi)
            ctx.line_to(lw, bw)
            ctx.line_to(lw, height - bw)
            ctx.close_path()
            ctx.fill()
            ctx.set_source_rgba(*_get_rgba(master, "_right_section_color"))
            ctx.new_sub_path()
            ctx.move_to(lw, bw)
            ctx.arc(width - bw - inner_r, bw + inner_r, inner_r, -0.5 * math.pi, 0)
            ctx.arc(width - bw - inner_r, height - bw - inner_r, inner_r, 0, 0.5 * math.pi)
            ctx.line_to(lw, height - bw)
            ctx.close_path()
            ctx.fill()

        photo = _render_cairo_to_tk(self, width, height, draw)
        self._cairo_photos["vertical_split"] = photo
        
        if not self._canvas.find_withtag("cairo_vertical_split"):
            self._canvas.create_image(0, 0, anchor="nw", image=photo, tags=("cairo_vertical_split", "inner_parts"))
        else:
            self._canvas.itemconfig("cairo_vertical_split", image=photo)
        return False

    DrawEngine._draw_smooth_polygon_shapes = _draw_smooth_polygon_shapes
    DrawEngine._draw_smooth_scrollbar = _draw_smooth_scrollbar
    DrawEngine._draw_smooth_progress_bar = _draw_smooth_progress_bar
    DrawEngine._draw_smooth_slider = _draw_smooth_slider
    DrawEngine._draw_smooth_vertical_split = _draw_smooth_vertical_split
    _orig_draw, _orig_vertical = DrawEngine.draw_rounded_rect_with_border, DrawEngine.draw_rounded_rect_with_border_vertical_split
    _orig_progress, _orig_slider, _orig_scrollbar = DrawEngine.draw_rounded_progress_bar_with_border, DrawEngine.draw_rounded_slider_with_border_and_button, DrawEngine.draw_rounded_scrollbar
    
    def _patched_draw(self, w, h, r, bw, meth=None, *args, **kwargs):
        if (meth or self.preferred_drawing_method) == "smooth_polygon_shapes": return self._draw_smooth_polygon_shapes(w, h, r, bw)
        return _orig_draw(self, w, h, r, bw, meth, *args, **kwargs)
    def _patched_vertical(self, w, h, r, bw, lw, meth=None, *args, **kwargs):
        if (meth or self.preferred_drawing_method) == "smooth_polygon_shapes": return self._draw_smooth_vertical_split(w, h, r, bw, lw)
        return _orig_vertical(self, w, h, r, bw, lw, meth, *args, **kwargs)
    def _patched_progress(self, w, h, r, bw, v1, v2, o, *args, **kwargs):
        if self.preferred_drawing_method == "smooth_polygon_shapes": return self._draw_smooth_progress_bar(w, h, r, bw, v1, v2, o)
        return _orig_progress(self, w, h, r, bw, v1, v2, o, *args, **kwargs)
    def _patched_slider(self, w, h, r, bw, bl, bcr, sv, o, *args, **kwargs):
        if self.preferred_drawing_method == "smooth_polygon_shapes": return self._draw_smooth_slider(w, h, r, bw, bl, bcr, sv, o)
        return _orig_slider(self, w, h, r, bw, bl, bcr, sv, o, *args, **kwargs)
    def _patched_scrollbar(self, w, h, r, s, sv, ev, o, *args, **kwargs):
        if self.preferred_drawing_method == "smooth_polygon_shapes":
            if getattr(self, "_round_width_to_even_numbers", False): w = math.floor(w / 2) * 2
            if getattr(self, "_round_height_to_even_numbers", False): h = math.floor(h / 2) * 2
            r = min(r, w/2, h/2); s = round(s); icr = max(0, r - s)
            return self._draw_smooth_scrollbar(w, h, r, icr, sv, ev, o)
        return _orig_scrollbar(self, w, h, r, s, sv, ev, o, *args, **kwargs)
    
    DrawEngine.draw_rounded_rect_with_border, DrawEngine.draw_rounded_rect_with_border_vertical_split = _patched_draw, _patched_vertical
    DrawEngine.draw_rounded_progress_bar_with_border, DrawEngine.draw_rounded_slider_with_border_and_button = _patched_progress, _patched_slider
    DrawEngine.draw_rounded_scrollbar, DrawEngine.preferred_drawing_method = _patched_scrollbar, "smooth_polygon_shapes"

    # Patch CTkCanvas to intercept fill/outline recolors on our Cairo images.
    # CTkButton._on_enter/leave calls itemconfig("inner_parts", fill=hover_color) to
    # recolor the button background — for Tk polygon shapes that just repaints them,
    # but our Cairo image ignores fill. We detect that case and re-render the Cairo
    # image with the new color so hover effects work on the button background too.
    _orig_canvas_itemconfigure = CTkCanvas.itemconfigure
    def _patched_canvas_itemconfigure(self, tagOrId, cnf=None, **kwargs):
        if not kwargs: return _orig_canvas_itemconfigure(self, tagOrId, cnf, **kwargs)
        items = self.find_withtag(tagOrId)
        if not items: return _orig_canvas_itemconfigure(self, tagOrId, cnf, **kwargs)

        has_image = any(self.type(i) == "image" for i in items)
        if not has_image: return _orig_canvas_itemconfigure(self, tagOrId, cnf, **kwargs)

        # If a fill color is being applied to a tag that includes our Cairo image,
        # re-render it with that color standing in for _fg_color.
        fill_color = kwargs.get("fill")
        if fill_color and self.find_withtag("cairo_main") and tagOrId == "inner_parts":
            master = self.master
            de = getattr(master, "_draw_engine", None)
            if de is not None:
                orig_fg = master._fg_color
                master._fg_color = fill_color
                try:
                    canvas_w = self.winfo_width()
                    canvas_h = self.winfo_height()
                    if canvas_w > 1 and canvas_h > 1:
                        de._draw_smooth_polygon_shapes(canvas_w, canvas_h,
                            getattr(master, "_corner_radius", 0),
                            getattr(master, "_border_width", 0))
                finally:
                    master._fg_color = orig_fg

        for item in items:
            item_kwargs = kwargs.copy()
            if self.type(item) == "image":
                item_kwargs.pop("fill", None)
                item_kwargs.pop("outline", None)
            _orig_canvas_itemconfigure(self, item, cnf, **item_kwargs)
    CTkCanvas.itemconfigure = CTkCanvas.itemconfig = _patched_canvas_itemconfigure


# Patch customtkinter bug where scroll events pass a string instead of a widget
_orig_check = _sf.CTkScrollableFrame.check_if_master_is_canvas
def _patched_check(self, widget):
    if isinstance(widget, str):
        return False
    return _orig_check(self, widget)
_sf.CTkScrollableFrame.check_if_master_is_canvas = _patched_check

# ── Windows resize performance patch ────────────────────────────────────────
# ROOT CAUSE of the resize glitching on Windows:
#
#   _fit_frame_dimensions_to_canvas is bound to the canvas <Configure> event
#   with NO debounce at all.  Every pixel of window resize fires it.
#   Each call does canvas.itemconfigure(inner_frame_id, width=N) which forces
#   a full Tk geometry-manager layout pass for every widget inside the frame.
#   Each CTkWidget in that tree fires its own <Configure>, which calls
#   CTkBaseClass._update_dimensions_event → _draw(no_color_updates=True) →
#   draw_rounded_rect_with_border() → canvas.delete(...) then canvas.create_...
#   That delete-before-redraw gap is the "blank / pixelated" flash users see.
#
#   With ~8 cards × ~7 CTk widgets each ≈ 56 _draw() calls per pixel on GDI.
#   On macOS the Quartz compositor hides these intermediate states; on Windows
#   every half-drawn frame is visible immediately via GDI.
#
# FIX: freeze the inner frame during the entire drag (200 ms debounce).
#   While dragging the inner-frame content stays at the old width (may be
#   clipped or show a small gap at the edge — standard Windows "deferred
#   resize" behavior).  Only the 2-3 outer chrome frames (nav sidebar, scroll
#   frame border) redraw during drag — fast.  200 ms after dragging stops,
#   everything snaps to the new size in one coordinated GDI pass:
#     t+200 ms → inner frame snaps (56 redraws, once)
#     t+250 ms → grid rebuild if column count changed
#   Zero intermediate flicker.
if sys.platform.startswith("win"):
    _orig_fit = _sf.CTkScrollableFrame._fit_frame_dimensions_to_canvas

    def _throttled_fit(self, event):
        if not hasattr(self, "_fit_job"):
            self._fit_job = None
        if self._fit_job is not None:
            try:
                self._parent_canvas.after_cancel(self._fit_job)
            except Exception:
                pass

        def _do_fit(inst=self):
            inst._fit_job = None
            if inst._orientation == "horizontal":
                inst._parent_canvas.itemconfigure(
                    inst._create_window_id,
                    height=inst._parent_canvas.winfo_height(),
                )
            elif inst._orientation == "vertical":
                inst._parent_canvas.itemconfigure(
                    inst._create_window_id,
                    width=inst._parent_canvas.winfo_width(),
                )

        # 200 ms: long enough to span any normal drag event burst so the inner
        # frame never updates mid-drag, only once when the drag stops.
        self._fit_job = self._parent_canvas.after(200, _do_fit)

    _sf.CTkScrollableFrame._fit_frame_dimensions_to_canvas = _throttled_fit
# ────────────────────────────────────────────────────────────────────────────

# DEPRECATED: Debug Window - controlled by command-line arguments
from gui.debug_window import DebugWindow
from gui.inspector import RuntimeInspector
from gui.user_interface import AppUI
from utils import functions as functions
from utils import settings
from utils.logger import logger, setup_logging

DEBUG_WINDOW = False
DEBUG = False


def resource_path(relative_path: str) -> str:
    """Delegates to central utils.functions.get_resource_path."""
    from utils.functions import get_resource_path
    return get_resource_path(relative_path)

class App(AppUI):
    """
    @brief Main application class for Resistine.
    Main application class for Resistine.
    """

    def __init__(self):
        """
        @brief Initialize the main application window.
        Initialize the main application window, set its title, size, and position.
        Check if the email is registered and create the appropriate screen.
        """
        super().__init__()

        # Theme: fixed Resistine CTk theme; only appearance mode varies (System/Light/Dark)
        customtkinter.set_default_color_theme(resource_path("resources/themes/resistine_ctk.json"))
        customtkinter.set_appearance_mode("System")

        if DEBUG_WINDOW:
            self.debug_window = DebugWindow(self)
            self.debug_window.create_debug_window()

        self.title("Resistine")
        screen_width = self.winfo_screenwidth()
        screen_height = self.winfo_screenheight()
        window_width = int(screen_width * 0.7)
        window_height = int(screen_height * 0.7)
        min_width = 750
        min_height = 350
        position_right = int(screen_width / 2 - window_width / 2)
        position_down = int(screen_height / 2 - window_height / 2)
        self.geometry(
            f"{window_width}x{window_height}+{position_right}+{position_down}"
        )
        self.minsize(min_width, min_height)

        # Check if already logged in
        if settings.get("auth", "logged_in", False):
            logger.info("✅ User already logged in.")
            self.create_dashboard()
        else:
            # Always show login screen since we're using Odoo authentication
            logger.info("🔐 Creating login screen...")
            try:
                from plugins.login.main import Plugin as LoginPlugin

                login_plugin = LoginPlugin(self)
                login_plugin.show()
                logger.info("✅ Login screen created")
            except (ImportError, ModuleNotFoundError):
                logger.warning("⚠️ Login plugin not found. Skipping login screen.")
                self.create_dashboard()
            except Exception as e:
                logger.error(f"❌ Failed to load login plugin: {e}")
                self.create_dashboard()

        # Ensure the window is visible
        self.update()

        # Initialize auto-updater (cross-platform: Sparkle on macOS, stubs on Win/Linux)
        try:
            from utils import updates

            updates.init(self)
        except Exception as e:
            logger.warning(f"Failed to start auto-updater: {e}")

        self.protocol("WM_DELETE_WINDOW", self._on_closing)

    def _on_closing(self):
        """Clean up resources before closing."""
        try:
            from utils import updates

            updates.shutdown()
        except Exception:
            pass
        self.destroy()


# class App


if __name__ == "__main__":


    # Parse command-line arguments
    parser = argparse.ArgumentParser(
        description="Resistine Desktop Application",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "-d",
        "--debug",
        action="store_true",
        help="Enable debug mode for real-time debugging",
    )
    parser.add_argument(
        "-l",
        "--log-level",
        choices=["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"],
        default="INFO",
        help="Set logging level (default: INFO)",
    )

    args = parser.parse_args()

    # Determine if we should be in DEBUG mode
    if args.debug or functions.is_running_in_ide():
        DEBUG = True

    # Configure logging based on configuration and flags
    # Default to DEBUG level if we are in DEBUG/IDE mode and no explicit level was provided
    log_level = args.log_level
    if DEBUG and log_level == "INFO":
        # Check if the user explicitly requested INFO via command line
        if not any(arg in sys.argv for arg in ["-l", "--log-level"]):
            log_level = "DEBUG"

    setup_logging(level=log_level)

    # DEPRECATED: Debug window flag can be set from code only
    if DEBUG_WINDOW:
        logger.info("Debug window enabled")

    # Start the application
    app = App()

    if DEBUG:
        logger.info("Debug mode enabled")
        logger.info(f"Platform: {sys.platform}")
        logger.info(f"Python version: {sys.version}")
        logger.info(f"Working directory: {os.getcwd()}")
        logger.info(f"Running in IDE: {functions.is_running_in_ide()}")

        # Attach Inspector
        app.inspector = RuntimeInspector(app)

    # Application loop - run!
    app.mainloop()