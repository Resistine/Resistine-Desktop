import math
import os
import tkinter as tk

import customtkinter
from customtkinter import ThemeManager
from PIL import Image

from plugins.plugin_manager import PluginManager


class AppUI(customtkinter.CTk):
    """
    Base application class handling UI creation and management.
    Inherits from CTk to serve as the main window base.
    """

    # --- UI Helpers (Moved from global scope) ---

    @staticmethod
    def create_tab_button(frame, name, icon, command=None, row=0, col=0):
        """Create a sleek, theme-aware sidebar button."""
        text_color = AppUI._get_theme_color("CTkButton", "text_color")
        hover_color = AppUI._get_theme_color("CTkButton", "hover_color")
        border_color = AppUI._get_theme_color("CTkButton", "border_color")
        # font_family = AppUI.get_font()

        # Using the color tuples directly allows CTk to handle theme switching
        btn = customtkinter.CTkButton(
            frame,
            corner_radius=10,
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

    @staticmethod
    def update_tab_button_active_state(
        button: customtkinter.CTkButton, is_active: bool
    ):
        """Apply active/inactive styling."""
        hover_color = AppUI._get_theme_color("CTkButton", "hover_color")
        border_color = AppUI._get_theme_color("CTkButton", "border_color")

        if is_active:
            button.configure(
                fg_color=hover_color, border_width=1, border_color=border_color
            )
        else:
            button.configure(fg_color="transparent", border_width=0)

    @staticmethod
    def create_plugin_card(row, column, container_frame, plugin):
        """Create a plugin card with theme-aware colors."""
        card_bg = AppUI._get_theme_color("CTkFrame", "fg_color")
        border_color = AppUI._get_theme_color("CTkFrame", "border_color")
        accent_green = AppUI._get_theme_color("CTkCheckBox", "fg_color")
        text_primary = AppUI._get_theme_color("CTkLabel", "text_color")
        hover_bg = AppUI._get_theme_color("CTkButton", "hover_color")
        accent_blue = AppUI._get_theme_color("CTkButton", "border_color")

        frame = customtkinter.CTkFrame(
            container_frame,
            corner_radius=15,
            fg_color=card_bg,
            border_width=1,
            border_color=border_color,
        )
        frame.grid(row=row, column=column, padx=10, pady=10, sticky="nsew")
        frame.grid_columnconfigure(0, weight=1)

        content_container = customtkinter.CTkFrame(frame, fg_color="transparent")
        content_container.grid(row=0, column=0, padx=20, pady=20, sticky="nsew")
        content_container.grid_columnconfigure(0, weight=1)

        # Icon
        icon_image = plugin.get_icon()
        if icon_image:
            icon_label = customtkinter.CTkLabel(
                content_container, image=icon_image, text=""
            )
            icon_label.grid(row=0, column=0, pady=(0, 10))

        # Title
        title_label = customtkinter.CTkLabel(
            content_container,
            text=plugin.get_name(),
            font=customtkinter.CTkFont(size=16, weight="bold"),
            text_color=text_primary,
        )
        title_label.grid(row=1, column=0, pady=(0, 5))

        # Status
        status_container = customtkinter.CTkFrame(
            content_container, fg_color="transparent"
        )
        status_container.grid(row=2, column=0)

        status_dot = customtkinter.CTkFrame(
            status_container,
            width=10,
            height=10,
            corner_radius=5,
            fg_color=accent_green,
        )
        status_dot.pack(side="left", padx=(0, 5))

        status_text = (
            "Protected" if plugin.get_status().lower() == "ok" else plugin.get_status()
        )
        status_label = customtkinter.CTkLabel(
            status_container,
            text=status_text,
            font=customtkinter.CTkFont(size=11),
            text_color=text_primary,
        )
        status_label.pack(side="left")

        # Click Interaction
        def on_click(_event=None):
            # Find App instance
            curr = container_frame
            while curr and not hasattr(curr, "select_frame_by_name"):
                curr = curr.master
            if curr:
                curr.select_frame_by_name(f"frame_{plugin.get_name()}")

        def on_enter(_e):
            frame.configure(border_color=accent_blue, fg_color=hover_bg)

        def on_leave(_e):
            frame.configure(border_color=border_color, fg_color=card_bg)

        # Bind events
        def bind_recursive(widget):
            widget.bind("<Button-1>", on_click)
            widget.bind("<Enter>", on_enter)
            widget.bind("<Leave>", on_leave)
            for child in widget.winfo_children():
                bind_recursive(child)

        bind_recursive(frame)

        return frame

    @staticmethod
    def get_font(key="CTkFont"):
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

    @staticmethod
    def _get_theme_color(widget_type, attribute):
        """Helper to safely get color tuple from ThemeManager."""
        try:
            return ThemeManager.theme[widget_type][attribute]
        except KeyError:
            return None

    @staticmethod
    def calculate_rows_cols(num_plugins):
        cols = math.ceil(math.sqrt(num_plugins))
        rows = math.ceil(num_plugins / cols)
        return tuple(range(rows)), tuple(range(cols))

    @staticmethod
    def create_grid(frame, row, column, plugins, color, sticky="nsew"):
        rows_tuple, cols_tuple = AppUI.calculate_rows_cols(len(plugins))

        container = customtkinter.CTkFrame(frame, corner_radius=0, fg_color=color)
        container.grid(row=row, column=column, sticky=sticky)
        container.grid_columnconfigure(rows_tuple, weight=1)
        container.grid_rowconfigure(cols_tuple, weight=1)

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

        # Plugin List Management (Circular import avoidance)
        if not hasattr(self.__class__, "plugin_list"):
            self.__class__.plugin_list = PluginManager(self).plugins
        else:
            # Refresh if needed (simple count check)
            if len(self.__class__.plugin_list) < len(PluginManager(self).plugins):
                self.__class__.plugin_list = PluginManager(self).plugins
        self.plugin_list = self.__class__.plugin_list
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
                logo_image = customtkinter.CTkImage(
                    light_image=logo_img,
                    dark_image=logo_img,
                    size=(max_width, logo_height),
                )
            except Exception as e:
                print(f"Error loading logo: {e}")

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
                print(f"Error loading plugin button {plugin.get_name()}: {e}")
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

        main_screen = frame.create_main_screen()
        main_screen.grid(row=0, column=1, sticky="nsew")
        main_screen.grid_columnconfigure(0, weight=1)
        main_screen.grid_rowconfigure(0, weight=1)
        self._current_main_screen = main_screen

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
