import os
import sys
import math
import tkinter as tk

import customtkinter
from customtkinter import ThemeManager
from PIL import Image, ImageDraw

from gui.notifications import ToastNotification
from plugins.plugin_manager import PluginManager
from utils.logger import logger


class AppUI(customtkinter.CTk):
    """
    Base application class handling UI creation and management.
    Inherits from CTk to serve as the main window base.
    """

    # Status colors for plugin status indicators.
    # TODO: Use theme colors instead of hex values.
    status_colors = {
        "ok": "#00FF00",      # Green
        "info": "#3B8ED0",      # Blue
        "warning": "#FFA500",   # Orange
        "error": "#FF0000",     # Red
        "critical": "#8B0000"   # Dark Red
    }    

    @staticmethod
    def _add_rounded_corners(image, radius):
        """Add rounded corners to a PIL Image."""
        # Create a mask with rounded corners
        mask = Image.new('L', image.size, 0)
        draw = ImageDraw.Draw(mask)
        draw.rounded_rectangle([(0, 0), image.size], radius=radius, fill=255)
        
        # Apply the mask to the image
        output = Image.new('RGBA', image.size, (0, 0, 0, 0))
        output.paste(image, (0, 0))
        output.putalpha(mask)
        
        return output

    @classmethod
    def create_tab_button(cls, frame, name, icon, command=None, row=0, col=0):
        """Create a sleek, theme-aware sidebar button."""
        text_color = cls._get_theme_color("CTkButton", "text_color")
        hover_color = cls._get_theme_color("CTkButton", "hover_color")
        border_color = cls._get_theme_color("CTkButton", "border_color")
        # font_family = AppUI.get_font()

        # Using the color tuples directly allows CTk to handle theme switching
        corner_radius = cls._get_theme_corner_radius()
        btn = customtkinter.CTkButton(
            frame,
            corner_radius=corner_radius,
            height=45,
            border_spacing=12,
            text=name,
            fg_color="transparent",
            text_color=text_color,
            hover_color=hover_color,
            border_width=0,
            border_color=border_color,
            image=icon,
            anchor="w",
            font=customtkinter.CTkFont(size=14, weight="normal"),
            command=command,
        )

        # Hover effects for "transparent" buttons to show border
        def on_enter(_e):
            btn.configure(border_width=1)

        def on_leave(_e):
            # Only remove border if not the active tab (checked via fg_color usually, but here relies on state)
            # Simplification: Always remove border on leave if transparent.
            # Active state is handled by changing fg_color, so this check works.
            if btn.cget("fg_color") == "transparent":
                btn.configure(border_width=0)

        btn.bind("<Enter>", on_enter)
        btn.bind("<Leave>", on_leave)
        btn.grid(row=row, column=col, sticky="ew", padx=10, pady=2)
        return btn

    @classmethod
    def update_tab_button_active_state(
        cls, button: customtkinter.CTkButton, is_active: bool
    ):
        """Apply active/inactive styling."""
        hover_color = cls._get_theme_color("CTkButton", "hover_color")
        border_color = cls._get_theme_color("CTkButton", "border_color")

        if is_active:
            button.configure(
                fg_color=hover_color, border_width=1, border_color=border_color
            )
        else:
            button.configure(fg_color="transparent", border_width=0)

    @classmethod
    def create_plugin_card(cls, row, column, container_frame, plugin, show_description=False, extra_buttons_func=None, truncate=False):
        """
        Create a plugin card with theme-aware colors.
        """
        card_bg = cls._get_theme_color("CTkFrame", "fg_color")
        border_color = cls._get_theme_color("CTkFrame", "border_color")
        accent_green = cls._get_theme_color("CTkCheckBox", "fg_color")
        text_primary = cls._get_theme_color("CTkLabel", "text_color")
        hover_bg = cls._get_theme_color("CTkButton", "hover_color")
        accent_blue = cls._get_theme_color("CTkButton", "border_color")
        corner_radius = cls._get_theme_corner_radius()
        divider_color = ThemeManager.theme.get("Theme", {}).get(
            "divider_color", ("#E5E7EB", "#2A2A2A")
        )

        frame = customtkinter.CTkFrame(
            container_frame,
            corner_radius=20,
            fg_color=card_bg,
            border_width=1,
            border_color=border_color,
        )
        # Let the card size naturally (fixed heights caused clipping on some layouts),
        # but keep the intended 70/30 split via weights + minimum sizes.
        frame.grid(row=row, column=column, padx=10, pady=10, sticky="nsew")
        frame.grid_columnconfigure(0, weight=1)
        frame.grid_rowconfigure(0, weight=7, minsize=85)  # top content (~70%)
        frame.grid_rowconfigure(1, weight=0)  # divider line
        frame.grid_rowconfigure(2, weight=3, minsize=45)  # status row
        if extra_buttons_func:
            frame.grid_rowconfigure(3, weight=0)  # divider line (for buttons)
            frame.grid_rowconfigure(4, weight=0, minsize=40)  # buttons row

        # --- Top content row (HStack): icon panel | text panel ---
        top_row = customtkinter.CTkFrame(frame, fg_color="transparent")
        top_row.grid(row=0, column=0, sticky="nsew")
        top_row.grid_rowconfigure(0, weight=1)
        top_row.grid_columnconfigure(0, weight=3, uniform="top")  # icon panel (~32%)
        top_row.grid_columnconfigure(1, weight=0, minsize=1)       # divider
        top_row.grid_columnconfigure(2, weight=7, uniform="top")  # text panel (~68%)

        icon_panel = customtkinter.CTkFrame(top_row, fg_color="transparent")
        icon_panel.grid(row=0, column=0, sticky="nsew", padx=(12, 0), pady=(10, 10))
        icon_panel.grid_rowconfigure(0, weight=1)
        icon_panel.grid_columnconfigure(0, weight=1)

        text_panel = customtkinter.CTkFrame(top_row, fg_color="transparent")
        text_panel.grid(row=0, column=2, sticky="nsew", padx=(12, 12), pady=(8, 8))
        text_panel.grid_columnconfigure(0, weight=1)
        text_panel.grid_rowconfigure(2, weight=0)  # description doesn't expand - only takes needed space

        # Icon (centered)
        icon_image = plugin.get_icon_large() if hasattr(plugin, "get_icon_large") else plugin.get_icon()
        if icon_image:
            icon_label = customtkinter.CTkLabel(icon_panel, image=icon_image, text="")
            icon_label.grid(row=0, column=0, sticky="nsew")

        # Title strip
        title_label = customtkinter.CTkLabel(
            text_panel,
            text=plugin.get_name(),
            font=customtkinter.CTkFont(size=17, weight="bold"),
            text_color=text_primary,
            anchor="center",
            justify="center",
        )
        title_label.grid(row=0, column=0, sticky="ew", pady=(0, 6))

        # Description area (optional)
        if show_description:
            description = plugin.get_description()
            if truncate and len(description) > 60:
                description = description[:57] + "..."

            desc_label = customtkinter.CTkLabel(
                text_panel,
                text=description,
                font=customtkinter.CTkFont(size=15),
                text_color=text_primary,
                justify="center",
                anchor="center",
            )
            desc_label.grid(row=2, column=0, sticky="ew", pady=(10, 0))
            
            # Update wraplength to match text_panel width dynamically
            # This works for both regular frames (dashboard) and scrollable frames (store)
            def update_wraplength(event=None):
                try:
                    # Get the actual width of the text_panel
                    panel_width = text_panel.winfo_width()
                    if panel_width > 1:  # Only update if panel has been rendered
                        # Account for padding: 16px left + 16px right = 32px total
                        available_width = max(100, panel_width - 32)  # Minimum 100px width
                        desc_label.configure(wraplength=available_width)
                except (tk.TclError, AttributeError, RuntimeError):
                    # Widget may have been destroyed or not yet created - ignore
                    pass
            
            # Bind to text_panel for updates when it resizes
            # Also bind to frame to catch initial layout and parent container changes
            try:
                text_panel.bind("<Configure>", update_wraplength)
                frame.bind("<Configure>", update_wraplength)
                # Set initial wraplength after widgets are rendered
                # Use after_idle to ensure it runs after layout is complete
                frame.after_idle(update_wraplength)
            except (tk.TclError, AttributeError, RuntimeError):
                pass

        # --- Bottom status row (full width) ---
        status_row = customtkinter.CTkFrame(frame, fg_color="transparent")
        status_row.grid(row=2, column=0, sticky="nsew")
        status_row.grid_columnconfigure(0, weight=1)

        status_left = customtkinter.CTkFrame(status_row, fg_color="transparent")
        status_left.grid(row=0, column=0, padx=12, pady=8)

        current_status = plugin.get_status()
        if current_status is not None:
            status_dot_color = cls.status_colors.get(str(current_status).lower(), "#808080")

            status_dot = customtkinter.CTkFrame(
                status_left,
                width=10,
                height=10,
                corner_radius=5,
                fg_color=status_dot_color,
            )
            status_dot.pack(side="left", padx=(0, 8))

            status_label = customtkinter.CTkLabel(
                status_left,
                text=f"Status: {str(current_status).title()}",
                font=customtkinter.CTkFont(size=15, weight="normal"),
                text_color=text_primary,
            )
            status_label.pack(side="left")

            # Optional secondary info (best-effort)
            last_check = None
            if hasattr(plugin, "get_last_check"):
                try:
                    last_check = plugin.get_last_check()
                except Exception:
                    last_check = None
            elif hasattr(plugin, "last_check"):
                last_check = getattr(plugin, "last_check", None)

            if last_check:
                last_check_label = customtkinter.CTkLabel(
                    status_left,
                    text=f"  •  Last check: {last_check}",
                    font=customtkinter.CTkFont(size=15, weight="normal"),
                    text_color=text_primary,
                )
                last_check_label.pack(side="left")

        # Extra Buttons (Store actions, etc.) on a separate row
        if extra_buttons_func:
            # Buttons row
            buttons_row = customtkinter.CTkFrame(frame, fg_color="transparent")
            buttons_row.grid(row=4, column=0, sticky="ew")
            buttons_row.grid_columnconfigure(0, weight=1)
            
            buttons_container = customtkinter.CTkFrame(buttons_row, fg_color="transparent")
            buttons_container.grid(row=0, column=0, padx=12, pady=8)
            
            extra_buttons_func(buttons_container, plugin)

        # Click Interaction
        def on_click(_event=None):
            # Find App instance
            curr = container_frame
            while curr and not hasattr(curr, "select_frame_by_name"):
                curr = curr.master
            if curr:
                curr.select_frame_by_name(f"frame_{plugin.get_name()}")

        def on_enter(_e):
            frame.configure(border_width=1, border_color=accent_blue, fg_color=hover_bg)

        def on_leave(_e):
            frame.configure(border_width=0, border_color=border_color, fg_color=card_bg)

        # Bind events
        def bind_recursive(widget):
            # Don't bind on_click to interactive elements
            if isinstance(widget, customtkinter.CTkButton):
                return
                
            widget.bind("<Button-1>", on_click)
            widget.bind("<Enter>", on_enter)
            widget.bind("<Leave>", on_leave)
            for child in widget.winfo_children():
                bind_recursive(child)

        bind_recursive(frame)

        return frame

    def show_readme(self, plugin):
        """
        Open a new window to show the plugin's README.md file.
        """
        import sys
        from plugins.help.markdown_viewer import MarkdownViewer
        
        # Determine the README path
        plugin_module = plugin.__class__.__module__
        # Assuming plugin modules are in plugins.name.main or name.main
        # We can try to get the file path from the module
        module = sys.modules.get(plugin_module)
        if not module or not hasattr(module, "__file__"):
            self.show_notification("Could not find plugin source for README", type="error")
            return
            
        plugin_dir = os.path.dirname(module.__file__)
        readme_path = os.path.join(plugin_dir, "README.md")
        
        if not os.path.exists(readme_path):
            self.show_notification(f"README.md not found for {plugin.get_name()}", type="warning")
            return

        # Create Toplevel window
        window = customtkinter.CTkToplevel(self)
        window.title(f"{plugin.get_name()} - Documentation")
        window.geometry("800x600")
        window.attributes("-topmost", True) # Keep on top for visibility
        window.after(100, lambda: window.attributes("-topmost", False)) # But allow moving behind

        viewer = MarkdownViewer(window, docs_dir=plugin_dir)
        viewer.pack(fill="both", expand=True, padx=20, pady=20)
        viewer.load_file(readme_path)

    @classmethod
    def get_font(cls, key="CTkFont"):
        """Resolves the font family from ThemeManager."""
        try:
            return ThemeManager.theme[key]["family"]
        except (KeyError, TypeError):
            # Fallback if the specific structure isn't exactly as expected for 'family'
            # The JSON shows CTkFont -> macOS/Windows/Linux -> family
            # But ThemeManager might flatten it or we need to check platform manually if ThemeManager doesn't.
            # Actually, ThemeManager.theme["CTkFont"] in the user's JSON has "macOS" etc.
            # Standard ThemeManager.theme usually resolves this?
            # Let's check how the user's JSON was ("CTkFont": { "macOS": ... }).
            # If ThemeManager loads it directly, we might need platform check or rely on CTkFont default.
            # However, usage of `customtkinter.CTkFont` usually handles family automatically if not specified?
            # Or we can just use "Inter" if we know it.
            # Let's try to lookup properly.
            # The JSON has "CTkFont": { "macOS": ... }
            # If we want to be safe, we just use the name "Inter" if available or leave it to CTk default.
            return "Inter"

    @classmethod
    def _get_theme_color(cls, widget_type, attribute):
        """Helper to safely get color tuple from ThemeManager."""
        try:
            return ThemeManager.theme[widget_type][attribute]
        except KeyError:
            return None

    @classmethod
    def _get_theme_corner_radius(cls):
        """Helper to get the global corner radius from theme."""
        try:
            return ThemeManager.theme["Theme"]["corner_radius"]
        except KeyError:
            return 15  # Default fallback

    @classmethod
    def calculate_rows_cols(cls, num_plugins):
        """Calculate rows and columns for a grid layout."""
        cols = math.ceil(math.sqrt(num_plugins))
        rows = math.ceil(num_plugins / cols)
        return tuple(range(rows)), tuple(range(cols))

    @classmethod
    def create_grid(cls, frame, row, column, plugins, color, sticky="nsew"):
        """Create a grid layout for plugins."""
        rows_tuple, cols_tuple = cls.calculate_rows_cols(len(plugins))

        container = customtkinter.CTkFrame(frame, corner_radius=0, fg_color=color)
        container.grid(row=row, column=column, sticky=sticky)
        # Configure grid dimensions correctly (columns -> cols_tuple, rows -> rows_tuple)
        container.grid_columnconfigure(cols_tuple, weight=1)
        container.grid_rowconfigure(rows_tuple, weight=1)

        # Fill grid (logic from old function, just establishing grid cells)
        for r in rows_tuple:
            for c in cols_tuple:
                # Just configure weights, we don't strictly need empty frames unless for spacing
                container.grid_columnconfigure(c, weight=1)
                container.grid_rowconfigure(r, weight=1)

        return container

    def create_dashboard(self):
        """
        Create the main dashboard of the application.
        """
        for widget in self.winfo_children():
            if isinstance(widget, (tk.Toplevel, customtkinter.CTkToplevel)):
                continue
            widget.grid_forget()

        # Re-configure the main window
        self.grid_rowconfigure(0, weight=1)
        self.grid_columnconfigure(0, weight=0)  # Navigation column
        self.grid_columnconfigure(1, weight=1)  # Content column

        # Plugin List Management
        self.plugin_list = self.get_plugin_manager().plugins
        number_plugins = len(self.plugin_list) + 1

        # Theme-aware sidebar colors
        sidebar_bg = self._get_theme_color("CTkFrame", "fg_color")
        sidebar_text_color = self._get_theme_color("CTkLabel", "text_color")

        self.navigation_frame = customtkinter.CTkFrame(
            self, corner_radius=0, fg_color=sidebar_bg
        )
        self.navigation_frame.grid(row=0, column=0, sticky="nsew", padx=0, pady=0)
        self.grid_columnconfigure(0, minsize=200)
        self.navigation_frame.grid_rowconfigure(number_plugins, weight=1)
        self.navigation_frame.grid_columnconfigure(0, weight=1)

        # Logo
        logo_path = os.path.join(
            os.path.dirname(os.path.dirname(os.path.realpath(__file__))),
            "ResistineLogoWhiteText.png",
        )
        logo_image = None
        if os.path.exists(logo_path):
            try:
                logo_img = Image.open(logo_path)
                max_width = 180
                aspect_ratio = logo_img.height / logo_img.width if logo_img.width else 1
                logo_height = int(max_width * aspect_ratio)
                logo_img = logo_img.resize(
                    (max_width, logo_height), Image.Resampling.LANCZOS
                )
                
                # Add rounded corners to the Resistine Logo
                logo_img = self._add_rounded_corners(logo_img, 15)
                
                logo_image = customtkinter.CTkImage(
                    light_image=logo_img,
                    dark_image=logo_img,
                    size=(max_width, logo_height),
                )
            except Exception as e:
                logger.error(f"Error loading logo: {e}")

        self.navigation_frame_label = customtkinter.CTkLabel(
            self.navigation_frame,
            text="" if logo_image else "Resistine",
            image=logo_image,
            compound="left",
            font=(
                customtkinter.CTkFont(size=18, weight="bold")
                if not logo_image
                else None
            ),
            text_color=sidebar_text_color if not logo_image else None,
        )
        self.navigation_frame_label.grid(
            row=0, column=0, padx=20, pady=(25, 10), sticky="ew"
        )

        self.frames = {}
        row = 1
        for plugin in self.plugin_list:
            # Skip plugins with negative or zero order (e.g. Login at 0, hidden at -1)
            # Order 0: Shows in Dashboard but not Sidebar
            # Order -1: Hidden everywhere
            if plugin.order <= 0:
                # Still register the frame so it can be navigated to if needed (e.g. from Dashboard)
                frame_name = f"frame_{plugin.get_name()}"
                self.frames[frame_name] = plugin
                continue

            frame_name = f"frame_{plugin.get_name()}"
            self.frames[frame_name] = plugin

            try:
                # Create sidebar button
                btn = self.create_tab_button(
                    self.navigation_frame,
                    plugin.get_name(),
                    plugin.get_icon(),
                    lambda p=plugin: self.select_frame_by_name(
                        f"frame_{p.get_name()}", button=p.get_button()
                    ),
                    row,
                    0,
                )
                plugin.set_button(btn)
            except Exception as e:
                logger.error(f"Error loading plugin button {plugin.get_name()}: {e}")
            row += 1

        self.select_frame_by_name("frame_Dashboard")

    def select_frame_by_name(self, name, button=None):
        """
        Select and display the specified frame.
        """
        self.current_frame_name = name

        # Clear current screen
        try:
            if hasattr(self, "_current_main_screen") and self._current_main_screen:
                self._current_main_screen.grid_forget()
                self._current_main_screen.destroy()
        except Exception:
            pass
        self._current_main_screen = None

        # Update button active states
        for frame_name, frame in getattr(self, "frames", {}).items():
            btn = frame.get_button() if hasattr(frame, "get_button") else None
            if not btn:
                continue
            self.update_tab_button_active_state(btn, is_active=(frame_name == name))

        # Show new screen
        frame = self.frames.get(name) if hasattr(self, "frames") else None
        if not frame:
            return

        try:
            main_screen = frame.create_main_screen()
            main_screen.grid(row=0, column=1, sticky="nsew")
            main_screen.grid_columnconfigure(0, weight=1)
            main_screen.grid_rowconfigure(0, weight=1)
            self._current_main_screen = main_screen
        except Exception as e:
            logger.error(f"Error loading plugin frame {name}: {e}")
            self.show_notification(
                f"Error loading plugin {name.replace('frame_', '')}: {e}", type="error"
            )

            # Update status to error so it shows on the dashboard
            if hasattr(frame, "set_status"):
                frame.set_status("Error")

            # Show error message in place of the plugin content
            error_frame = customtkinter.CTkFrame(self)
            error_frame.grid(row=0, column=1, sticky="nsew")
            error_frame.grid_columnconfigure(0, weight=1)
            error_frame.grid_rowconfigure(0, weight=1)

            error_label = customtkinter.CTkLabel(
                error_frame,
                text=f"Error loading plugin:\n{e}",
                text_color="#FF3333",
                wraplength=400,
                font=customtkinter.CTkFont(size=14, weight="bold"),
            )
            error_label.pack(expand=True, padx=20, pady=20)
            self._current_main_screen = error_frame

    def refresh_ui_theme(self):
        """Refresh sidebar colors (if needed beyond automatic CTk updates)."""
        # Most CTk widgets update automatically if initialized with tuple colors.
        # We only really need to re-render to catch dynamic checks if any.
        try:
            name = getattr(self, "current_frame_name", None)
            if name:
                self.select_frame_by_name(name)
        except Exception:
            pass

    def get_plugin_manager(self):
        """
        Get the PluginManager instance.
        """
        if not hasattr(self.__class__, "plugin_manager"):
             from plugins.plugin_manager import PluginManager
             self.__class__.plugin_manager = PluginManager(self)
        return self.__class__.plugin_manager

    def show_notification(self, message, type="info"):
        """
        Show a non-blocking toast notification.
        :param message: The text to display.
        :param type: 'info' (green), 'error' (red), 'warning' (orange).
        """
        colors = {
            "info": "#00D100",  # Green
            "warning": "#FFA500",  # Orange
            "error": "#FF0000",  # Red
        }
        icon_col = colors.get(type, "#00D100")
        
        # Ensure we use the root window for placement
        root = self.winfo_toplevel()
        toast = ToastNotification(root, text=message, icon_color=icon_col)
        toast.show()
