import inspect
import os
import pprint
import tkinter as tk
import customtkinter as ctk
from utils.logger import logger
from utils.i18n import get_text

# --- Monkey Patching for Source Tracking ---
# We patch tk.Widget.__init__ to capture where widgets are created.
_original_init = tk.Widget.__init__


def _is_library_file(filename):
    """Check if the file belongs to system libraries (tkinter, customtkinter context)."""
    if filename is None:
        return True

    norm = os.path.normpath(filename).lower()

    # Standard library heuristic
    if "lib\\tkinter" in norm or "lib/tkinter" in norm:
        return True

    # Python site-packages (library code)
    if "site-packages" in norm:
        return True

    return False


def _patched_init(self, master=None, *args, **kwargs):
    # Walk the stack to find the first non-library caller
    stack = inspect.stack()
    self._creation_data = None

    for frame_info in stack[1:]:
        filename = frame_info.filename
        if not _is_library_file(filename):
            self._creation_data = {
                "file": filename,
                "line": frame_info.lineno,
                "context": frame_info.function,
            }
            break

    _original_init(self, master, *args, **kwargs)


# Apply patch immediately on import
tk.Widget.__init__ = _patched_init


class RuntimeInspector:
    def __init__(self, root):
        self.root = root
        self.root.bind_all("<Control-Button-1>", self.on_click, add="+")
        self.highlighter = None
        self.inspector_window = None

    def on_click(self, event):
        # Find widget under mouse
        x, y = self.root.winfo_pointerxy()
        widget = self.root.winfo_containing(x, y)

        if widget:
            # SMART SELECTION:
            # If the clicked widget is "internal" (library code), try to find a parent
            # that is "user code".
            target_widget = self.find_user_widget(widget)
            self.inspect_widget(target_widget)

    def find_user_widget(self, start_widget):
        """Walk up the hierarchy to find the specific widget the user likely created."""
        curr = start_widget
        last_valid = start_widget

        while curr:
            # If this widget has known user-source, it's a strong candidate
            if hasattr(curr, "_creation_data") and curr._creation_data:
                return curr

            # If we hit the root, stop
            if curr == self.root:
                break

            curr = curr.master

        # Fallback: If no user-created parent found (e.g. clicking directly on root or pure lib widget),
        # return original
        return last_valid

    def inspect_widget(self, widget):
        logger.info(f"--- Inspecting Widget: {widget} ---")
        self.highlight_widget(widget)
        self.log_properties(widget)
        self.show_inspector_ui(widget)

    def highlight_widget(self, widget):
        if self.highlighter:
            self.highlighter.destroy()

        try:
            # Get screen coordinates
            x = widget.winfo_rootx()
            y = widget.winfo_rooty()
            w = widget.winfo_width()
            h = widget.winfo_height()

            # Create overlay window
            self.highlighter = tk.Toplevel(self.root)
            self.highlighter.overrideredirect(True)
            self.highlighter.geometry(f"{w}x{h}+{x}+{y}")
            self.highlighter.attributes("-topmost", True)
            self.highlighter.attributes("-alpha", 0.3)  # Semi-transparent
            self.highlighter.configure(bg="red")

            # Auto-hide after 1 second
            self.highlighter.after(1000, self.highlighter.destroy)
        except Exception as e:
            logger.error(f"Could not highlight widget: {e}")

    def get_widget_name(self, widget):
        """Try to find the variable name of the widget in its master."""
        if not widget.master:
            return "root"

        # Search in master's __dict__
        for name, obj in widget.master.__dict__.items():
            if obj is widget:
                return f"self.{name}"

        return "Unknown (Anonymous)"

    def log_properties(self, widget):
        # Basic Info
        props = {
            "Variable Name": self.get_widget_name(widget),
            "Class": widget.__class__.__name__,
            "Master": widget.master,
        }

        # Source Code Info
        if hasattr(widget, "_creation_data") and widget._creation_data:
            props.update(
                {
                    "Source File": widget._creation_data["file"],
                    "Source Line": widget._creation_data["line"],
                    "Created In": widget._creation_data["context"],
                }
            )
        else:
            props.update(
                {
                    "Source File": "Library/Internal",
                    "Source Line": "-",
                }
            )

        # Geometry
        props.update(
            {
                "Geometry": widget.winfo_geometry(),
                "Size": f"{widget.winfo_width()}x{widget.winfo_height()}",
                "Position": f"({widget.winfo_x()}, {widget.winfo_y()})",
                "Root Position": f"({widget.winfo_rootx()}, {widget.winfo_rooty()})",
                "Mapped": bool(widget.winfo_ismapped()),
            }
        )

        # Config Attributes (Try to get generic attributes)
        try:
            for key in widget.keys():
                props[key] = widget.cget(key)
        except:
            pass

        # Grid/Pack Info
        try:
            props["Grid Info"] = widget.grid_info()
        except:
            pass

        try:
            props["Pack Info"] = widget.pack_info()
        except:
            pass

        try:
            props["Place Info"] = widget.place_info()
        except:
            pass

        logger.debug(pprint.pformat(props))
        return props

    def show_inspector_ui(self, widget):
        if self.inspector_window is not None:
            if self.inspector_window.winfo_exists():
                self.inspector_window.destroy()

        self.inspector_window = ctk.CTkToplevel(self.root)
        self.inspector_window.title("Inspector")
        self.inspector_window.geometry("500x600")

        # Keep on top
        self.inspector_window.attributes("-topmost", True)

        scroll = ctk.CTkScrollableFrame(self.inspector_window)
        scroll.pack(fill="both", expand=True, padx=10, pady=10)

        # Title
        display_name = self.get_widget_name(widget)
        if display_name == "Unknown (Anonymous)":
            display_name = widget.__class__.__name__

        header = ctk.CTkLabel(
            scroll, text=get_text("gui.inspector.inspecting_display_name", display_name=display_name), font=("Arial", 16, "bold")
        )
        header.pack(anchor="w", pady=(0, 10))

        props = self.log_properties(widget)  # Re-get props to display

        # Display logic order
        priority_keys = [
            "Variable Name",
            "Source File",
            "Source Line",
            "Class",
            "Geometry",
        ]

        # 1. Priority Items
        for k in priority_keys:
            if k in props:
                self._add_prop_row(scroll, k, props[k], highlight=True)

        # 2. Separator
        sep = ctk.CTkFrame(scroll, height=2, fg_color="gray50")
        sep.pack(fill="x", pady=10)

        # 3. Rest of items
        for k, v in props.items():
            if k not in priority_keys:
                self._add_prop_row(scroll, k, v)

    def _add_prop_row(self, parent, key, value, highlight=False):
        f = ctk.CTkFrame(parent, fg_color="transparent")
        f.pack(fill="x", pady=1)

        font_style = ("Arial", 12, "bold") if highlight else ("Arial", 12)

        lbl_k = ctk.CTkLabel(f, text=f"{key}:", font=font_style, width=120, anchor="w")
        lbl_k.pack(side="left", padx=5)

        val_str = str(value)
        # Clean up file path for display
        if key == "Source File" and "Library" not in val_str:
            try:
                # Show relative path if possible
                val_str = os.path.relpath(val_str)
            except:
                pass

        if key == "Source Line" and value != "-":
            val_str = f"Line {val_str}"

        lbl_v = ctk.CTkLabel(
            f, text=val_str, wraplength=300, anchor="w", justify="left"
        )
        if highlight:
            lbl_v.configure(
                text_color=("#1f6aa5", "#4a90e2")
            )  # Blue-ish for highlights

        lbl_v.pack(side="left", padx=5, fill="x", expand=True)
