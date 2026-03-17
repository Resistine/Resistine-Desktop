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

# Linux: use a custom high-poly smooth polygon renderer to avoid both the
# "blob" artifacts of font_shapes (anti-aliased font) and the "jaggies" of 
# polygon_shapes (coarse Tkinter rounding). This calculates 40+ points per 
# rectangle for truly smooth curves on X11.
if sys.platform.startswith("linux"):
    import math
    import tkinter
    from customtkinter.windows.widgets.core_rendering import DrawEngine

    def _get_smooth_points(w, h, r, offset=0, inset=1.0):
        """Calculates a high-poly path with symmetric precision and explicit endpoints."""
        r = min(r, (w - 2*inset)/2, (h - 2*inset)/2)
        if r <= 0:
            pts = [inset-offset, inset-offset, w-inset+offset, inset-offset, 
                   w-inset+offset, h-inset+offset, inset-offset, h-inset+offset]
            pts.extend(pts[:2])
            return pts
        pts = []
        steps = max(24, int(r * 2))
        for i in range(steps + 1): # TR
            a = math.radians(270 + 90 * i / steps)
            pts.extend([w - inset - r + (r + offset) * math.cos(a), inset + r + (r + offset) * math.sin(a)])
        for i in range(steps + 1): # BR
            a = math.radians(0 + 90 * i / steps)
            pts.extend([w - inset - r + (r + offset) * math.cos(a), h - inset - r + (r + offset) * math.sin(a)])
        for i in range(steps + 1): # BL
            a = math.radians(90 + 90 * i / steps)
            pts.extend([inset + r + (r + offset) * math.cos(a), h - inset - r + (r + offset) * math.sin(a)])
        for i in range(steps + 1): # TL
            a = math.radians(180 + 90 * i / steps)
            pts.extend([inset + r + (r + offset) * math.cos(a), inset + r + (r + offset) * math.sin(a)])
        pts.extend(pts[:2])
        return pts

    def _draw_smooth_polygon_shapes(self, width, height, corner_radius, border_width):
        requires_recoloring = False
        r, bw = (corner_radius or 0), (border_width or 0)
        inner_r = max(0, r - bw)
        if bw > 0:
            if not self._canvas.find_withtag("border_parts"):
                self._canvas.create_polygon((0,0,0,0), tags=("border_line_1", "border_parts"), width=0, outline="")
                requires_recoloring = True
            self._canvas.coords("border_line_1", *_get_smooth_points(width, height, r))
        else: self._canvas.delete("border_parts")
        if not self._canvas.find_withtag("inner_parts"):
            self._canvas.create_polygon((0,0,0,0), tags=("inner_line_1", "inner_parts"), width=0, outline="")
            requires_recoloring = True
        pts = _get_smooth_points(width - 2*bw, height - 2*bw, inner_r)
        for i in range(0, len(pts), 2): pts[i] += bw; pts[i+1] += bw
        self._canvas.coords("inner_line_1", *pts)
        return requires_recoloring

    def _draw_smooth_scrollbar(self, width, height, corner_radius, inner_corner_radius, start_value, end_value, orientation):
        requires_recoloring = False
        if not self._canvas.find_withtag("border_parts"):
            self._canvas.create_rectangle(0, 0, 0, 0, tags=("border_rectangle_1", "border_parts"), width=0, outline="")
            requires_recoloring = True
        self._canvas.coords("border_rectangle_1", 0, 0, width, height)
        if not self._canvas.find_withtag("scrollbar_parts"):
            self._canvas.create_polygon((0, 0, 0, 0), tags=("scrollbar_polygon_1", "scrollbar_parts"), width=0, outline="")
            self._canvas.tag_raise("scrollbar_parts", "border_parts")
            requires_recoloring = True
        if orientation == "vertical":
            bar_w, bar_h = width - 2 * corner_radius, (height - 2 * corner_radius) * (end_value - start_value)
            y_offset, x_offset = (height - 2 * corner_radius) * start_value + corner_radius, corner_radius
        else:
            bar_w, bar_h = (width - 2 * corner_radius) * (end_value - start_value), height - 2 * corner_radius
            x_offset, y_offset = (width - 2 * corner_radius) * start_value + corner_radius, corner_radius
        pts = _get_smooth_points(bar_w + 2*inner_corner_radius, bar_h + 2*inner_corner_radius, inner_corner_radius)
        for i in range(0, len(pts), 2): pts[i] += x_offset - inner_corner_radius; pts[i+1] += y_offset - inner_corner_radius
        self._canvas.coords("scrollbar_polygon_1", *pts)
        return requires_recoloring

    def _draw_smooth_progress_bar(self, width, height, corner_radius, border_width, v1, v2, orientation):
        r, bw = (corner_radius or 0), (border_width or 0)
        if r > width / 2 or r > height / 2: r = min(width / 2, height / 2)
        requires_recoloring = self._draw_smooth_polygon_shapes(width, height, r, bw)
        if not self._canvas.find_withtag("progress_parts"):
            self._canvas.create_polygon((0,0,0,0), tags=("progress_line_1", "progress_parts"), width=0, outline="")
            requires_recoloring = True
        inner_r = max(0, r - bw)
        if v1 == v2:
            self._canvas.coords("progress_line_1", (0, 0, 0, 0))
            return requires_recoloring
        if orientation in ["horizontal", "w", "e"]:
            usable_w = max(0, width - 2 * bw)
            x_start, x_end = bw + usable_w * v1, bw + usable_w * v2
            pts = _get_smooth_points(max(1, x_end - x_start), max(1, height - 2 * bw), inner_r)
            for i in range(0, len(pts), 2): pts[i] += x_start; pts[i+1] += bw
        else:
            usable_h = max(0, height - 2 * bw)
            y_start, y_end = bw + usable_h * (1 - v2), bw + usable_h * (1 - v1)
            pts = _get_smooth_points(max(1, width - 2 * bw), max(1, y_end - y_start), inner_r)
            for i in range(0, len(pts), 2): pts[i] += bw; pts[i+1] += y_start
        self._canvas.coords("progress_line_1", *pts)
        self._canvas.tag_raise("progress_parts")
        return requires_recoloring

    def _draw_smooth_slider(self, width, height, corner_radius, border_width, button_length, button_corner_radius, slider_value, orientation):
        requires_recoloring = self._draw_smooth_progress_bar(width, height, corner_radius, border_width, 0, slider_value, orientation)
        if not self._canvas.find_withtag("slider_parts"):
            self._canvas.create_polygon((0,0,0,0), tags=("slider_button_line_1", "slider_parts"), width=0, outline="")
            requires_recoloring = True
        r, br = (corner_radius or 0), (button_corner_radius or 0)
        if r > width / 2 or r > height / 2: r = min(width / 2, height / 2)
        if br > width / 2 or br > height / 2: br = min(width / 2, height / 2)
        total_button_w, total_button_h = button_length + 2 * br, button_length + 2 * br
        if orientation in ["horizontal", "w", "e"]:
            bx = max(0, width - total_button_w) * slider_value
            pts = _get_smooth_points(total_button_w, height, br)
            for i in range(0, len(pts), 2): pts[i] += bx; pts[i+1] += 0
        else:
            by = max(0, height - total_button_h) * (1 - slider_value)
            pts = _get_smooth_points(width, total_button_h, br)
            for i in range(0, len(pts), 2): pts[i] += 0; pts[i+1] += by
        self._canvas.coords("slider_button_line_1", *pts)
        self._canvas.tag_raise("slider_parts")
        return requires_recoloring

    def _draw_smooth_vertical_split(self, width, height, corner_radius, border_width, left_section_width):
        requires_recoloring = False
        r, bw, lw = (corner_radius or 0), (border_width or 0), (left_section_width or 0)
        inner_r = max(0, r - bw)
        
        # 1. Left Section
        if not self._canvas.find_withtag("left_section_parts"):
            self._canvas.create_polygon((0,0,0,0), tags=("left_pol_1", "left_section_parts"), width=0, outline="")
            requires_recoloring = True
        
        # Calculate high-poly path for the left half: 
        # TL (arc), BL (arc), then vertical cut at lw
        steps = max(24, int(inner_r * 2))
        pts_l = []
        for i in range(steps + 1): # BL
            a = math.radians(90 + 90 * i / steps)
            pts_l.extend([bw + inner_r + inner_r * math.cos(a), height - bw - inner_r + inner_r * math.sin(a)])
        for i in range(steps + 1): # TL
            a = math.radians(180 + 90 * i / steps)
            pts_l.extend([bw + inner_r + inner_r * math.cos(a), bw + inner_r + inner_r * math.sin(a)])
        # Close with vertical line at the split
        pts_l.extend([lw, bw, lw, height - bw])
        self._canvas.coords("left_pol_1", *pts_l)

        # 2. Right Section
        if not self._canvas.find_withtag("right_section_parts"):
            self._canvas.create_polygon((0,0,0,0), tags=("right_pol_1", "right_section_parts"), width=0, outline="")
            requires_recoloring = True
            
        # Path for right half:
        # vertical cut at lw, then TR (arc), BR (arc)
        pts_r = [lw, bw]
        for i in range(steps + 1): # TR
            a = math.radians(270 + 90 * i / steps)
            pts_r.extend([width - bw - inner_r + inner_r * math.cos(a), bw + inner_r + inner_r * math.sin(a)])
        for i in range(steps + 1): # BR
            a = math.radians(0 + 90 * i / steps)
            pts_r.extend([width - bw - inner_r + inner_r * math.cos(a), height - bw - inner_r + inner_r * math.sin(a)])
        pts_r.extend([lw, height - bw])
        self._canvas.coords("right_pol_1", *pts_r)
        
        # 3. Border (Background)
        if bw > 0:
            if not self._canvas.find_withtag("border_parts"):
                self._canvas.create_polygon((0,0,0,0), tags=("border_pol_1", "border_parts"), width=0, outline="")
                requires_recoloring = True
            self._canvas.coords("border_pol_1", *_get_smooth_points(width, height, r))
            self._canvas.tag_lower("border_parts")
        else: self._canvas.delete("border_parts")
        
        return requires_recoloring

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
