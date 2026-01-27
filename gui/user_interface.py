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
        Create a plugin card with theme-aware colors and a clean split layout.
        """
        card_bg = cls._get_theme_color("CTkFrame", "fg_color")
        border_color = cls._get_theme_color("CTkFrame", "border_color")
        text_primary = cls._get_theme_color("CTkLabel", "text_color")
        hover_bg = cls._get_theme_color("CTkButton", "hover_color")
        accent_blue = cls._get_theme_color("CTkButton", "border_color")
        corner_radius = cls._get_theme_corner_radius()
        divider_color = ThemeManager.theme.get("Theme", {}).get(
            "divider_color", ("#E5E7EB", "#2A2A2A")
        )

        frame = customtkinter.CTkFrame(
            container_frame,
            corner_radius=corner_radius,
            fg_color=card_bg,
            border_width=0,  # Start with no border, show on hover
            border_color=border_color,
        )
        # Mark so create_grid() can enforce consistent sizing/aspect ratio on resize
        frame._resistine_plugin_card = True
        
        # PRE-ALLOCATION: If container already knows the target height, use it immediately
        # to prevent the "clunky" iteration on load.
        # Ratio of card width (usually 0.6 of col width in dashboard layout)
        initial_h = getattr(container_frame, "_resistine_target_height", 200)
        num_cols = getattr(container_frame, "_resistine_num_cols", 1)
        
        # Calculate approximate width based on container width or hint
        cont_w = container_frame.winfo_width()
        if cont_w <= 1:
            # Try to get hint from AppUI
            hint = None
            parent = container_frame.master
            while parent:
                if hasattr(parent, "_content_width_hint") and parent._content_width_hint:
                    hint = parent._content_width_hint
                    break
                parent = getattr(parent, "master", None)
            cont_w = hint if hint else 800
            
        initial_w = int(cont_w / num_cols) - 20
        
        try:
            frame.configure(width=initial_w, height=initial_h)
            frame.grid_propagate(False)
        except Exception:
            pass
        frame.grid(row=row, column=column, padx=10, pady=10, sticky="nsew")
        frame.grid_columnconfigure(0, weight=1)
        
        # Structure rows: Content (~70%), Divider, Status/Buttons (~30%)
        # Buttons are 26px height + padding, so minsize needs to be at least 50px
        frame.grid_rowconfigure(0, weight=7, minsize=90)
        frame.grid_rowconfigure(1, weight=0) # h_div
        frame.grid_rowconfigure(2, weight=3, minsize=55)

        # --- Top content row: icon panel | divider | text panel ---
        # Add top padding to respect rounded corners (prevents child frames from covering rounded top corners)
        # Use corner_radius + border_width to ensure rounded border is fully visible
        top_padding = max(corner_radius + 2, 15)  # At least corner_radius + border_width, minimum 15px
        top_row = customtkinter.CTkFrame(frame, fg_color="transparent")
        top_row.grid(row=0, column=0, sticky="nsew", padx=2, pady=(top_padding, 0))
        top_row.grid_rowconfigure(0, weight=1)
        top_row.grid_columnconfigure(0, weight=32, uniform="top")
        top_row.grid_columnconfigure(1, weight=0, minsize=1)
        top_row.grid_columnconfigure(2, weight=68, uniform="top")

        # Icon Panel
        icon_panel = customtkinter.CTkFrame(top_row, fg_color="transparent")
        icon_panel.grid(row=0, column=0, sticky="nsew", padx=(12, 0), pady=10)
        icon_panel.grid_rowconfigure(0, weight=1)
        icon_panel.grid_columnconfigure(0, weight=1)

        icon_image = plugin.get_icon_large() if hasattr(plugin, 'get_icon_large') else plugin.get_icon()
        if icon_image:
            icon_label = customtkinter.CTkLabel(icon_panel, image=icon_image, text="")
            icon_label.grid(row=0, column=0, sticky="nsew")

        # Text Panel (Title + Desc)
        text_panel = customtkinter.CTkFrame(top_row, fg_color="transparent")
        text_panel.grid(row=0, column=2, sticky="nsew", padx=12, pady=10)
        text_panel.grid_columnconfigure(0, weight=1)
        text_panel.grid_rowconfigure(2, weight=1) # spacer/expand

        title_label = customtkinter.CTkLabel(
            text_panel,
            text=plugin.get_name(),
            font=customtkinter.CTkFont(size=17, weight="bold"),
            text_color=text_primary,
            anchor="w"
        )
        title_label.grid(row=0, column=0, sticky="ew", pady=(0, 4))

        if show_description:
            description = plugin.get_description()
            if truncate and len(description) > 60:
                description = description[:57] + "..."
            
            desc_label = customtkinter.CTkLabel(
                text_panel,
                text=description,
                font=customtkinter.CTkFont(size=13),
                text_color=text_primary,
                wraplength=200,
                justify="left",
                anchor="nw"
            )
            desc_label.grid(row=2, column=0, sticky="nsew", pady=(8, 0))

            # Register description label for centralized wraplength updates from create_grid
            if hasattr(container_frame, "_resistine_desc_labels"):
                container_frame._resistine_desc_labels.append(desc_label)
                # Apply initial wraplength if possible
                w = container_frame.winfo_width()
                if w > 1:
                    num_cols = getattr(container_frame, "_resistine_num_cols", 1)
                    col_width = w / num_cols
                    desc_label.configure(wraplength=max(100, int((col_width - 20) * 0.6) - 24))

        # --- Bottom Status Bar ---
        # Add bottom padding to respect rounded corners
        # Use corner_radius + border_width to ensure rounded border is fully visible
        bottom_padding = max(corner_radius + 2, 15)  # At least corner_radius + border_width, minimum 15px
        status_row = customtkinter.CTkFrame(frame, fg_color="transparent")
        status_row.grid(row=2, column=0, sticky="nsew", padx=12, pady=(0, bottom_padding))
        status_row.grid_columnconfigure(0, weight=1)

        # --- Optional extra buttons (Store only) - replaces status ---
        if extra_buttons_func:
            # Center the buttons, no status indicator
            buttons_container = customtkinter.CTkFrame(status_row, fg_color="transparent")
            buttons_container.pack(expand=True, anchor="center")
            extra_buttons_func(buttons_container, plugin)
        else:
            # Dashboard/other pages: show status indicator (centered)
            # Always render a status slot so the bottom section stays consistent,
            # even for plugins that return no status (None).
            current_status = plugin.get_status()
            status_container = customtkinter.CTkFrame(status_row, fg_color="transparent")
            status_container.pack(expand=True, anchor="center")

            if current_status is None or str(current_status).strip() == "":
                status_dot_color = "#808080"
                status_text = "Status: N/A"
                status_text_color = ("#666666", "#aaaaaa")
            else:
                status_dot_color = cls.status_colors.get(str(current_status).lower(), "#808080")
                status_text = f"Status: {str(current_status).title()}"
                status_text_color = text_primary

            status_dot = customtkinter.CTkFrame(
                status_container, width=10, height=10, corner_radius=5, fg_color=status_dot_color
            )
            status_dot.pack(side="left", padx=(0, 8))

            status_label = customtkinter.CTkLabel(
                status_container,
                text=status_text,
                font=customtkinter.CTkFont(size=13),
                text_color=status_text_color,
            )
            status_label.pack(side="left")

        # Interaction
        def on_click(_e=None):
            curr = container_frame
            while curr and not hasattr(curr, "select_frame_by_name"):
                curr = curr.master
            if curr: curr.select_frame_by_name(f"frame_{plugin.get_name()}")

        def on_enter(_e): 
            try:
                if frame.winfo_exists():
                    # Preserve corner_radius when applying border
                    frame.configure(
                        border_width=2, 
                        border_color=accent_blue, 
                        fg_color=hover_bg,
                        corner_radius=corner_radius  # Explicitly maintain rounded corners
                    )
            except (tk.TclError, AttributeError, RuntimeError):
                pass
        def on_leave(_e): 
            try:
                if frame.winfo_exists():
                    # Preserve corner_radius when removing border
                    frame.configure(
                        border_width=0, 
                        border_color=border_color, 
                        fg_color=card_bg,
                        corner_radius=corner_radius  # Explicitly maintain rounded corners
                    )
            except (tk.TclError, AttributeError, RuntimeError):
                pass

        def bind_recursive(widget):
            try:
                if isinstance(widget, customtkinter.CTkButton): return
                if not widget.winfo_exists():
                    return
                widget.bind("<Button-1>", on_click)
                widget.bind("<Enter>", on_enter)
                widget.bind("<Leave>", on_leave)
                for child in widget.winfo_children(): 
                    bind_recursive(child)
            except (tk.TclError, AttributeError, RuntimeError):
                # Widget destroyed or error - skip
                pass
        
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
    def calculate_rows_cols(cls, num_plugins, max_cols=None, min_cols=None):
        """Calculate rows and columns for a grid layout.
        
        Args:
            num_plugins: Number of plugins to display
            max_cols: Optional maximum number of columns (for responsive layouts)
            min_cols: Optional minimum number of columns (for responsive layouts)
        """
        cols = math.ceil(math.sqrt(num_plugins))
        if max_cols is not None and cols > max_cols:
            cols = max_cols
        if min_cols is not None and cols < min_cols:
            cols = min_cols
        rows = math.ceil(num_plugins / cols) if cols > 0 else 1
        return tuple(range(rows)), tuple(range(cols))


    @classmethod
    def create_grid(cls, frame, row, column, plugins, color, sticky="nsew", aspect_ratio=1.3, max_cols=None, min_cols=None):
        """Create a mathematically uniform grid layout for plugins with a consistent aspect ratio.
        
        Args:
            max_cols: Optional maximum number of columns (for responsive layouts)
            min_cols: Optional minimum number of columns (for responsive layouts)
        """
        rows_tuple, cols_tuple = cls.calculate_rows_cols(len(plugins), max_cols=max_cols, min_cols=min_cols)

        container = customtkinter.CTkFrame(frame, corner_radius=0, fg_color=color)
        container.grid(row=row, column=column, sticky=sticky)
        
        # Force uniform sizing for columns; weight=1 makes them expand/shrink together
        container.grid_columnconfigure(cols_tuple, weight=1, uniform="plugin_grid")

        # Optimization properties
        container._resistine_last_w = -1
        container._resistine_desc_labels = [] # Centralized wraplength updates
        container._resistine_num_cols = len(cols_tuple)
        container._resistine_screen_width = None  # Cached screen width for performance
        container._resistine_resize_job = None  # For debouncing

        def update_aspect_ratio(event=None, force_width=None):
            # Debounce resize events (skip if another update is pending)
            if event and not force_width:
                if container._resistine_resize_job:
                    try:
                        container.after_cancel(container._resistine_resize_job)
                    except:
                        pass
                container._resistine_resize_job = container.after(16, lambda: _do_update_aspect_ratio(force_width=None))
                return
            _do_update_aspect_ratio(force_width=force_width)
        
        def _do_update_aspect_ratio(force_width=None):
            container._resistine_resize_job = None
            try:
                if not container.winfo_exists():
                    return
                
                # Calculate column width directly from force_width or winfo
                total_width = force_width if force_width else container.winfo_width()
                if total_width <= 1:
                    return
                
                # RECURSION & NOISE CHECK: Skip if width hasn't changed meaningfully
                # Small changes (1-3px) often happen as window settles or scrollbars appear.
                if container._resistine_last_w != -1 and abs(total_width - container._resistine_last_w) < 4:
                    return
                container._resistine_last_w = total_width
                
                num_cols = container._resistine_num_cols
                if num_cols == 0:
                    return
                    
                col_width = total_width / num_cols
                
                # Height = Width / ratio
                # Card width is col_width minus padding (10px on each side)
                card_width = max(1, col_width - 20)
                target_height = int(card_width / aspect_ratio) + 20 # add padding back
                
                # Ensure minimum height for content
                target_height = max(target_height, 160)
                
                # Cap maximum height based on number of columns
                # Shorter cards when in 2-column layout
                if num_cols == 2:
                    max_height = 250
                    target_height = min(target_height, max_height)
                elif num_cols >= 4:
                    # For 4+ columns, set minimum height to match what cards would be at 90% width with 3 cols
                    # Store screen width for performance
                    if container._resistine_screen_width is None:
                        container._resistine_screen_width = container.winfo_screenwidth()
                    screen_w = container._resistine_screen_width
                    # Estimate content width at 90% (minus sidebar ~200, minus padding ~40)
                    content_at_90 = screen_w * 0.9 - 240
                    col_w_at_90 = content_at_90 / 3
                    card_w_at_90 = col_w_at_90 - 20
                    min_height_4col = int(card_w_at_90 / aspect_ratio) + 20
                    target_height = max(target_height, min_height_4col)
                else:
                    max_height = 900
                    target_height = min(target_height, max_height)
                
                # Store for cards created later (pre-allocation)
                container._resistine_target_height = target_height

                # Update row minsize to maintain aspect ratio perfectly
                for r in rows_tuple:
                    container.grid_rowconfigure(r, minsize=target_height)

                # Centralized wraplength update (efficiently loops through registered labels)
                wrap_val = max(100, int(card_width * 0.6) - 24) # Approx description panel width
                for label in container._resistine_desc_labels:
                    try:
                        if label.winfo_exists():
                            label.configure(wraplength=wrap_val)
                    except: pass

            except (tk.TclError, AttributeError, RuntimeError):
                pass

        container.bind("<Configure>", update_aspect_ratio)
        
        # INSTANT-READY LAYOUT:
        # Check for width hint from AppUI to perform the VERY FIRST layout pass synchronously.
        # This ensures row minsize and target_height are set before child cards are even created.
        hint = None
        parent = container.master
        while parent:
            if hasattr(parent, "_content_width_hint") and parent._content_width_hint:
                hint = parent._content_width_hint
                break
            parent = getattr(parent, "master", None)
            
        if hint and hint > 1:
            update_aspect_ratio(force_width=hint)
        elif container.winfo_width() > 1:
            update_aspect_ratio()
        else:
            # Fallback for unexpected cases where hint is missing
            container.after(10, lambda: update_aspect_ratio())

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

        # Precompute content width hint for smooth initial plugin rendering.
        try:
            total_w = self.winfo_width()
            if total_w > 1:
                # Use actual navigation sidebar width if available, fallback to 200
                nav_w = self.navigation_frame.winfo_width() if hasattr(self, "navigation_frame") else 200
                if nav_w < 100: nav_w = 200 # Fallback for unmapped frame
                
                # Precise subtraction: window width - sidebar - margins/scrollbar padding
                # (40px accounts for main frame padx(20)*2 + scrollbar allowance)
                self._content_width_hint = total_w - nav_w - 40
        except:
            self._content_width_hint = None

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
            # Attach smooth scrolling + auto-hide scrollbars for any CTkScrollableFrames in this screen
            try:
                self._install_scroll_behaviors(main_screen)
            except Exception:
                pass
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

    # ----------------------------
    # Scroll behavior improvements
    # ----------------------------
    def _install_scroll_behaviors(self, root_widget):
        """Recursively attach smooth scroll + auto-hide scrollbar to any CTkScrollableFrame widgets."""
        try:
            if isinstance(root_widget, customtkinter.CTkScrollableFrame):
                self._enable_smooth_scroll_and_autohide(root_widget)
        except Exception:
            pass

        try:
            for child in root_widget.winfo_children():
                self._install_scroll_behaviors(child)
        except Exception:
            pass

    def _enable_smooth_scroll_and_autohide(self, scrollable: customtkinter.CTkScrollableFrame):
        """
        Make scrolling feel smoother and hide the scrollbar when the content fits.
        Works by targeting CTkScrollableFrame internals when available.
        """
        # Avoid double-install
        if getattr(scrollable, "_resistine_scroll_installed", False):
            return
        scrollable._resistine_scroll_installed = True

        canvas = getattr(scrollable, "_parent_canvas", None)
        scrollbar = getattr(scrollable, "_scrollbar", None)
        if canvas is None:
            return

        # ---- Smooth scrolling (mouse wheel) ----
        state = {"vel": 0.0, "job": None}

        def _normalized_delta(event) -> float:
            # Windows/Linux: event.delta is usually 120/-120 per notch
            # macOS: can be much smaller, especially for trackpads
            d = getattr(event, "delta", 0) or 0
            if d == 0:
                return 0.0
            if abs(d) >= 120:
                return float(d) / 120.0
            # trackpad-ish deltas
            return float(d) / 40.0

        def _step():
            try:
                if not canvas.winfo_exists():
                    return
                v = state["vel"]
                if abs(v) < 0.01:
                    state["vel"] = 0.0
                    state["job"] = None
                    return

                # Scroll by a fraction of the canvas height for smoothness
                cur_top, _ = canvas.yview()
                # 0.06 is a "feel" constant (smaller = smoother/slower)
                new_top = cur_top - (v * 0.06)
                new_top = max(0.0, min(1.0, new_top))
                canvas.yview_moveto(new_top)

                # Decay velocity (inertia)
                state["vel"] *= 0.82
                state["job"] = canvas.after(12, _step)
            except Exception:
                state["job"] = None

        def _on_mousewheel(event):
            try:
                # Negative delta scrolls down on many systems; invert to match natural expectation
                d = _normalized_delta(event)
                if d == 0:
                    return "break"

                state["vel"] += d
                # Clamp velocity so huge trackpad swipes don't go crazy
                state["vel"] = max(-8.0, min(8.0, state["vel"]))

                if state["job"] is None:
                    state["job"] = canvas.after(1, _step)
            except Exception:
                pass
            return "break"

        def _on_linux_scroll_up(_e):
            state["vel"] = max(-8.0, min(8.0, state["vel"] + 1.0))
            if state["job"] is None:
                state["job"] = canvas.after(1, _step)
            return "break"

        def _on_linux_scroll_down(_e):
            state["vel"] = max(-8.0, min(8.0, state["vel"] - 1.0))
            if state["job"] is None:
                state["job"] = canvas.after(1, _step)
            return "break"

        # Bind on the canvas + scrollable itself so it works regardless of focus
        for w in (canvas, scrollable):
            try:
                w.bind("<MouseWheel>", _on_mousewheel, add="+")
                w.bind("<Button-4>", _on_linux_scroll_up, add="+")
                w.bind("<Button-5>", _on_linux_scroll_down, add="+")
            except Exception:
                pass

        # ---- Auto-hide scrollbar when not needed ----
        # IMPORTANT: never change layout width (that causes visible shifting).
        # Instead, keep the scrollbar in place and make it fully transparent when "hidden".
        sb_theme = ThemeManager.theme.get("CTkScrollbar", {}) if "ThemeManager" in globals() else {}
        if scrollbar is not None and not hasattr(scrollable, "_resistine_scrollbar_colors"):
            try:
                scrollable._resistine_scrollbar_colors = {
                    "fg_color": scrollbar.cget("fg_color"),
                    "button_color": scrollbar.cget("button_color"),
                    "button_hover_color": scrollbar.cget("button_hover_color"),
                }
            except Exception:
                # fall back to theme defaults if cget isn't available
                scrollable._resistine_scrollbar_colors = {
                    "fg_color": sb_theme.get("fg_color", ("#F0F0F0", "#2B2B2B")),
                    "button_color": sb_theme.get("button_color", ("#C7C7C7", "#5A5A5A")),
                    "button_hover_color": sb_theme.get("button_hover_color", ("#B0B0B0", "#6A6A6A")),
                }

        hide_state = {"job": None, "hidden": False}

        def _update_scrollbar_visibility():
            try:
                if scrollbar is None or not scrollbar.winfo_exists() or not canvas.winfo_exists():
                    return

                # Determine if content exceeds viewport height
                bbox = canvas.bbox("all")
                content_h = 0 if bbox is None else (bbox[3] - bbox[1])
                viewport_h = canvas.winfo_height()

                # Hysteresis to avoid flicker during resize
                if hide_state["hidden"]:
                    should_hide = content_h <= (viewport_h + 16)
                else:
                    should_hide = content_h <= (viewport_h - 16)

                if should_hide and not hide_state["hidden"]:
                    hide_state["hidden"] = True
                    try:
                        scrollbar.configure(
                            fg_color="transparent",
                            button_color="transparent",
                            button_hover_color="transparent",
                        )
                    except Exception:
                        pass
                elif (not should_hide) and hide_state["hidden"]:
                    hide_state["hidden"] = False
                    try:
                        colors = getattr(scrollable, "_resistine_scrollbar_colors", None) or {}
                        scrollbar.configure(
                            fg_color=colors.get("fg_color", ("#F0F0F0", "#2B2B2B")),
                            button_color=colors.get("button_color", ("#C7C7C7", "#5A5A5A")),
                            button_hover_color=colors.get("button_hover_color", ("#B0B0B0", "#6A6A6A")),
                        )
                    except Exception:
                        pass
            except Exception:
                pass

        def _schedule_visibility_check(_e=None):
            if hide_state["job"] is not None:
                try:
                    canvas.after_cancel(hide_state["job"])
                except Exception:
                    pass
            hide_state["job"] = canvas.after(60, _update_scrollbar_visibility)

        try:
            canvas.bind("<Configure>", _schedule_visibility_check, add="+")
            scrollable.bind("<Configure>", _schedule_visibility_check, add="+")
        except Exception:
            pass

        # Kick it once after layout
        try:
            canvas.after(120, _update_scrollbar_visibility)
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
