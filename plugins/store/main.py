# @file plugins/store/main.py
""" "
Store plugin for the Resistine application.
This plugin allows users to download and install new plugins from the store.
Author: Peres J., P3 and the Resistine Team
Copyright (c) Resistine 2025
Licensed under the GNU General Public License v2 or later
"""

import os
import webbrowser
from io import BytesIO

import customtkinter
from PIL import Image

from plugins.base_plugin import BasePlugin
from plugins.plugin_manager import PluginManager

# Try to import SVG support
try:
    from cairosvg import svg2png
    HAS_SVG = True
    # Test if cairosvg actually works (sometimes it's installed but broken)
    try:
        # Use bytestring instead of url for the test to avoid OSError
        test_data = svg2png(bytestring='<svg xmlns="http://www.w3.org/2000/svg" width="1" height="1"></svg>', output_width=1, output_height=1)
        if not test_data:
            HAS_SVG = False
    except Exception:
        HAS_SVG = False
except ImportError:
    HAS_SVG = False

# DNS Configuration - Change this value to update DNS across the application
DNS_SERVER = "10.49.11.10"


class Plugin(BasePlugin):
    """
    @brief Plugin class for the Store plugin.
    Plugin class for the Store plugin, that allows user install new plugins from the store.
    """

    def __init__(self, app):
        """
        @brief Initialize the Store plugin.
        Initialize the Store plugin with the specified parameters.
        :param app: Main application object.
        """
        super().__init__(
            id="004",
            version="2025.01.01",
            order=1000,
            name="Store",
            status=None,
            description="This plugin allows you to download and install new plugins.",
            supported_systems=["Windows", "Linux", "Mac"],
            translations={"US": "Store", "ES": "Tienda", "FR": "Magasin"},
            icon_light_path=os.path.join(
                os.path.dirname(os.path.realpath(__file__)), "store_light.svg"
            ),
            icon_dark_path=os.path.join(
                os.path.dirname(os.path.realpath(__file__)), "store_dark.svg"
            ),
            uninstall_enabled=False,
        )
        self.app = app
        self.status = self.get_status()

    def create_main_screen(self):
        """
        @brief Create the main screen for the Store plugin.
        """
        self.main_frame = customtkinter.CTkFrame(
            self.app, corner_radius=0, fg_color="transparent"
        )
        self.main_frame.grid_columnconfigure(0, weight=1)
        self.main_frame.grid_rowconfigure(0, weight=1)
        self.main_frame.grid_rowconfigure(1, weight=10)

        # Title frame
        self.title_frame = customtkinter.CTkFrame(
            self.main_frame, corner_radius=0, fg_color="transparent"
        )
        self.title_frame.grid(row=0, column=0, sticky="nsew")
        self.title_frame.grid_columnconfigure(0, weight=1)

        self.title_label = customtkinter.CTkLabel(
            self.title_frame,
            text="Store",
            font=customtkinter.CTkFont(size=30, weight="bold"),
        )
        self.title_label.grid(row=0, column=0, padx=20, pady=(20, 10))

        # --- Plugins grid ---
        manager = self.app.get_plugin_manager()
        installed_plugins = manager.plugins
        all_local_plugins = manager.load_plugins(include_uninstalled=True)
        available_remote = manager.get_available_plugins()
        
        installed_ids = {p.id for p in installed_plugins}
        local_ids = {p.id for p in all_local_plugins}
        
        plugins = list(installed_plugins)
        
        # Add uninstalled local plugins
        for lp in all_local_plugins:
            if lp.id not in installed_ids:
                lp.status = "Uninstalled"
                plugins.append(lp)
        
        # Add remote plugins that aren't local at all
        for rp in available_remote:
            if rp["id"] not in local_ids:
                plugins.append(RemotePluginWrapper(self.app, rp))
        
        # Sort by name for the store
        plugins = sorted(plugins, key=lambda x: x.get_name())
        
        # Store plugins for responsive rebuild
        self._store_plugins = plugins
        
        # Responsive layout: determine max columns based on window width
        screen_width = self.app.winfo_screenwidth()
        window_width = self.app.winfo_width()
        if window_width <= screen_width * 0.6:
            max_cols = 2
            min_cols = None
        elif window_width >= screen_width * 0.9:
            max_cols = None
            min_cols = 4
        else:
            max_cols = None
            min_cols = None
        rows, cols = self.app.calculate_rows_cols(len(plugins), max_cols=max_cols, min_cols=min_cols)
        
        # Store current column count to detect changes
        self._current_cols = len(cols)
        self._current_max_cols = max_cols

        content_frame = customtkinter.CTkScrollableFrame(
            self.main_frame, corner_radius=0, fg_color="transparent"
        )
        content_frame.grid(row=1, column=0, sticky="nsew", padx=15, pady=0)
        content_frame.grid_columnconfigure(0, weight=1)
        
        # Store reference for rebuilding
        self._content_frame = content_frame

        self.grid_frame = self.app.create_grid(
            frame=content_frame,
            row=0,
            column=0,
            plugins=plugins,
            color="transparent",
            sticky="nsew",
            max_cols=max_cols,
            min_cols=min_cols,
        )
        
        # Helper for extra buttons
        def inject_store_buttons(container, p):
            # Info Button
            info_btn = customtkinter.CTkButton(
                container,
                text="Info",
                height=26,
                width=80,
                command=lambda p=p: self.app.show_readme(p) if not isinstance(p, RemotePluginWrapper) else self.show_remote_info(p),
                border_width=0,
                fg_color=("#3B8ED0", "#1F6AA5"),
                hover_color=("#367EBB", "#144870"),
                font=customtkinter.CTkFont(size=12)
            )
            info_btn.grid(row=0, column=0, padx=5, pady=5)

            if isinstance(p, RemotePluginWrapper) or getattr(p, "status", None) == "Uninstalled":
                # Install Button
                install_btn = customtkinter.CTkButton(
                    container,
                    text="Install",
                    height=26,
                    width=80,
                    command=lambda p=p: self.handle_install(p),
                    border_width=0,
                    fg_color=("#2ECC71", "#27AE60"),
                    hover_color=("#27AE60", "#219150"),
                    font=customtkinter.CTkFont(size=12)
                )
                install_btn.grid(row=0, column=1, padx=5, pady=5)
            else:
                # Uninstall Button (if enabled)
                if getattr(p, "uninstall_enabled", True):
                    uninstall_btn = customtkinter.CTkButton(
                        container,
                        text="Uninstall",
                        height=26,
                        width=80,
                        command=lambda p=p: self.handle_uninstall(p),
                        border_width=0,
                        fg_color=("#FF4444", "#C73636"),
                        hover_color=("#C73636", "#9E2A2A"),
                        font=customtkinter.CTkFont(size=12)
                    )
                    uninstall_btn.grid(row=0, column=1, padx=5, pady=5)

        for index, plugin in enumerate(plugins):
            r = index // len(cols)
            c = index % len(cols)
            self.app.create_plugin_card(
                r, c, self.grid_frame, plugin, 
                show_description=True, 
                extra_buttons_func=inject_store_buttons
            )
        
        # Bind resize handler to app window for responsive layout
        self._bind_responsive_resize(inject_store_buttons)

        return self.main_frame
    
    def _bind_responsive_resize(self, inject_store_buttons):
        """Bind a resize handler to rebuild grid when crossing 60% threshold."""
        def on_resize(event=None):
            if not hasattr(self, '_store_plugins') or not hasattr(self, '_content_frame'):
                return
            try:
                if not self._content_frame.winfo_exists():
                    return
            except:
                return
                
            screen_width = self.app.winfo_screenwidth()
            window_width = self.app.winfo_width()
            
            # Determine target columns based on width thresholds
            if window_width <= screen_width * 0.6:
                max_cols = 2
                min_cols = None
            elif window_width >= screen_width * 0.9:
                max_cols = None
                min_cols = 4
            else:
                max_cols = None
                min_cols = None
            
            # Calculate target columns
            target_cols = len(self.app.calculate_rows_cols(len(self._store_plugins), max_cols=max_cols, min_cols=min_cols)[1])
            
            # Only rebuild if column count changed
            current = getattr(self, '_current_cols', None)
            if current == target_cols:
                return
            
            self._rebuild_grid(max_cols, min_cols, inject_store_buttons)
        
        # Debounce: trigger quickly but avoid excessive rebuilds
        self._resize_after_id = None
        self._last_threshold_state = None
        self._cached_screen_width = self.app.winfo_screenwidth()  # Cache screen width
        
        def debounced_resize(event=None):
            # Skip if store is not visible or destroyed
            if not hasattr(self, 'main_frame') or not self.main_frame.winfo_exists() or not self.main_frame.winfo_ismapped():
                return
            
            # Quick check if we crossed the threshold (no debounce for threshold crossing)
            screen_width = self._cached_screen_width
            window_width = self.app.winfo_width()
            # Track state: 0=narrow (<=60%), 1=normal, 2=wide (>=90%)
            if window_width <= screen_width * 0.6:
                threshold_state = 0
            elif window_width >= screen_width * 0.9:
                threshold_state = 2
            else:
                threshold_state = 1
            
            # If threshold state changed, trigger immediately
            if self._last_threshold_state is not None and self._last_threshold_state != threshold_state:
                self._last_threshold_state = threshold_state
                if self._resize_after_id:
                    self.app.after_cancel(self._resize_after_id)
                    self._resize_after_id = None
                on_resize()
                return
            
            self._last_threshold_state = threshold_state
            
            # For other resizes, use debounce to avoid excessive rebuilds
            if self._resize_after_id:
                self.app.after_cancel(self._resize_after_id)
            self._resize_after_id = self.app.after(100, on_resize)
        
        self.app.bind("<Configure>", debounced_resize, add="+")
    
    def _rebuild_grid(self, max_cols, min_cols, inject_store_buttons):
        """Rebuild the plugin grid with new column count."""
        if not hasattr(self, '_store_plugins') or not hasattr(self, '_content_frame'):
            return
        
        plugins = self._store_plugins
        
        # Destroy old grid
        if hasattr(self, 'grid_frame') and self.grid_frame:
            try:
                self.grid_frame.destroy()
            except:
                pass
        
        rows, cols = self.app.calculate_rows_cols(len(plugins), max_cols=max_cols, min_cols=min_cols)
        self._current_cols = len(cols)
        self._current_max_cols = max_cols
        
        self.grid_frame = self.app.create_grid(
            frame=self._content_frame,
            row=0,
            column=0,
            plugins=plugins,
            color="transparent",
            sticky="nsew",
            max_cols=max_cols,
            min_cols=min_cols,
        )
        
        for index, plugin in enumerate(plugins):
            r = index // len(cols)
            c = index % len(cols)
            self.app.create_plugin_card(
                r, c, self.grid_frame, plugin, 
                show_description=True,
                extra_buttons_func=inject_store_buttons
            )

    def handle_install(self, remote_plugin):
        """Handle plugin installation."""
        from utils.logger import logger
        if not isinstance(remote_plugin, RemotePluginWrapper):
            # It's an uninstalled local plugin, just re-enable it
            manager = self.app.get_plugin_manager()
            state = manager._load_state()
            if remote_plugin.id in state.get("uninstalled", []):
                state["uninstalled"].remove(remote_plugin.id)
                manager._save_state(state)
                manager.plugins = manager.load_plugins()
                if hasattr(self.app, "refresh_navigation_menu"):
                    self.app.refresh_navigation_menu()
                self.app.show_notification(f"Plugin {remote_plugin.get_name()} re-enabled.", type="info")
                # Refresh screen
                self.app.select_frame_by_name("frame_Store")
                return

        success, message = self.app.get_plugin_manager().download_plugin(remote_plugin.url, remote_plugin.id, remote_plugin.get_name())
        logger.info(f"Store: Installation result for {remote_plugin.get_name()}: success={success}, msg={message}")
        
        if success:
            if hasattr(self.app, "refresh_navigation_menu"):
                self.app.refresh_navigation_menu()
            self.app.show_notification(message, type="info")
            # Refresh screen
            self.app.select_frame_by_name("frame_Store")
        else:
            self.app.show_notification(message, type="error")

    def show_remote_info(self, remote_plugin):
        """Show info for a remote plugin."""
        from gui.dialogs import show_info
        show_info(self.app, remote_plugin.get_name(), remote_plugin.get_description())

    def handle_uninstall(self, plugin):
        """Handle plugin uninstallation with confirmation."""
        from gui.dialogs import ask_yes_no
        
        def confirm_uninstall(confirmed):
            if confirmed:
                success, res = self.app.get_plugin_manager().uninstall_plugin(plugin)
                if success:
                    self.app.show_notification(res, type="info")
                    # Refresh screen
                    self.app.select_frame_by_name("frame_Store")
                else:
                    self.app.show_notification(res, type="error")

        ask_yes_no(
            self.app, 
            "Uninstall Plugin", 
            f"Are you sure you want to uninstall {plugin.get_name()}?",
            confirm_uninstall
        )

class RemotePluginWrapper:
    """Wrapper to make remote plugin dicts compatible with AppUI.create_plugin_card."""
    def __init__(self, app, data):
        self.app = app
        self.id = data["id"]
        self.name = data["name"]
        self.description = data["description"]
        self.url = data["url"]
        self.order = data.get("order", 99)
        self.status = "Available"
        
    def get_name(self): return self.name
    def get_description(self): return self.description
    def get_status(self): return self.status

    def _load_icon_safe(self, path, size):
        """
        Safely load an icon, supporting both SVG and PNG formats.
        Uses the same logic as BasePlugin.create_icon but with extra error handling.
        """
        from utils.logger import logger
        
        # Check if SVG version exists (even if path ends with .png)
        if path.lower().endswith('.png'):
            svg_path = path[:-4] + '.svg'
            if os.path.exists(svg_path) and HAS_SVG:
                try:
                    # Validate size parameters to prevent crashes
                    if size[0] <= 0 or size[1] <= 0:
                        logger.warning(f"⚠️ Invalid size for SVG: {size}, using PNG")
                        if os.path.exists(path):
                            return Image.open(path)
                        raise ValueError(f"Invalid size: {size}")
                    png_data = svg2png(url=svg_path, output_width=size[0], output_height=size[1])
                    if not png_data:
                        raise ValueError("svg2png returned empty data")
                    return Image.open(BytesIO(png_data))
                except (OSError, ValueError, MemoryError, AttributeError) as e:
                    logger.warning(f"⚠️ SVG loading failed for {os.path.basename(svg_path)}: {e}, using PNG")
                    if os.path.exists(path):
                        return Image.open(path)
                    # If PNG doesn't exist either, try SVG path (will fail gracefully)
                    if os.path.exists(svg_path):
                        try:
                            return Image.open(svg_path)
                        except Exception:
                            pass
                except Exception as e:
                    logger.error(f"❌ Unexpected error loading SVG {os.path.basename(svg_path)}: {e}")
                    if os.path.exists(path):
                        return Image.open(path)
                    # Return blank image as last resort
                    return Image.new('RGBA', size, (255, 255, 255, 0))
            else:
                # No SVG found or no SVG support, use PNG
                if os.path.exists(path):
                    return Image.open(path)
                # Try SVG as fallback only if supported
                if os.path.exists(svg_path) and HAS_SVG:
                    try:
                        png_data = svg2png(url=svg_path, output_width=size[0], output_height=size[1])
                        return Image.open(BytesIO(png_data))
                    except:
                        pass
                
                # Last resort
                return Image.new('RGBA', size, (0, 0, 0, 0))
        
        # Path already ends with .svg
        elif path.lower().endswith('.svg'):
            if HAS_SVG:
                try:
                    # Validate size parameters to prevent crashes
                    if size[0] <= 0 or size[1] <= 0:
                        logger.warning(f"⚠️ Invalid size for SVG: {size}, trying PNG fallback")
                        png_path = path[:-4] + '.png'
                        if os.path.exists(png_path):
                            return Image.open(png_path)
                        raise ValueError(f"Invalid size: {size}")
                    png_data = svg2png(url=path, output_width=size[0], output_height=size[1])
                    if not png_data:
                        raise ValueError("svg2png returned empty data")
                    return Image.open(BytesIO(png_data))
                except (OSError, ValueError, MemoryError, AttributeError) as e:
                    logger.warning(f"⚠️ SVG loading failed for {os.path.basename(path)}: {e}")
                    # Try PNG fallback
                    png_path = path[:-4] + '.png'
                    if os.path.exists(png_path):
                        logger.info(f"📄 Using PNG fallback: {os.path.basename(png_path)}")
                        return Image.open(png_path)
                    # If PNG doesn't exist, try to return SVG as-is (will fail gracefully)
                    try:
                        return Image.open(path)
                    except Exception:
                        pass
                except Exception as e:
                    logger.error(f"❌ Unexpected error loading SVG {os.path.basename(path)}: {e}")
                    # Try PNG fallback
                    png_path = path[:-4] + '.png'
                    if os.path.exists(png_path):
                        return Image.open(png_path)
            else:
                # No SVG support, try PNG fallback
                png_path = path[:-4] + '.png'
                if os.path.exists(png_path):
                    logger.info(f"📄 Using PNG fallback: {os.path.basename(png_path)}")
                    return Image.open(png_path)
                
                # Cannot open SVG without cairosvg
                logger.error(f"❌ Cannot open SVG without SVG support: {path}")
                return Image.new('RGBA', size, (0, 0, 0, 0))
        
        # Default: try to open as-is
        if os.path.exists(path):
            try:
                return Image.open(path)
            except Exception as e:
                logger.error(f"❌ Failed to open image {path}: {e}")
        
        # Last resort: return a blank image
        logger.error(f"❌ Could not load icon: {path}")
        return Image.new('RGBA', size, (255, 255, 255, 0))

    def get_icon(self):
        # Return default store icon for remote plugins (20x20 for sidebar)
        # Note: icon_light contains dark icon (for light backgrounds)
        #       icon_dark contains light/white icon (for dark backgrounds)
        # So we need to swap them for CTkImage (same as base_plugin.py does)
        icons_path = os.path.dirname(os.path.realpath(__file__))
        light_path = os.path.join(icons_path, "store_light.svg")
        dark_path = os.path.join(icons_path, "store_dark.svg")
        
        try:
            light_image = self._load_icon_safe(light_path, (20, 20))
            dark_image = self._load_icon_safe(dark_path, (20, 20))
            return customtkinter.CTkImage(
                light_image=dark_image,  # Use dark icon (white) for light mode
                dark_image=light_image,  # Use light icon (dark) for dark mode
                size=(20, 20)  # Sidebar icon size
            )
        except Exception as e:
            from utils.logger import logger
            logger.error(f"Error loading store icon: {e}")
            # Return a blank image as fallback
            blank = Image.new('RGBA', (20, 20), (255, 255, 255, 0))
            return customtkinter.CTkImage(light_image=blank, dark_image=blank, size=(20, 20))
    
    def get_icon_large(self):
        # Return larger icon for dashboard/store cards (50x50)
        icons_path = os.path.dirname(os.path.realpath(__file__))
        light_path = os.path.join(icons_path, "store_light.svg")
        dark_path = os.path.join(icons_path, "store_dark.svg")
        
        try:
            light_image = self._load_icon_safe(light_path, (50, 50))
            dark_image = self._load_icon_safe(dark_path, (50, 50))
            return customtkinter.CTkImage(
                light_image=dark_image,  # Use dark icon (white) for light mode
                dark_image=light_image,  # Use light icon (dark) for dark mode
                size=(50, 50)  # Card icon size
            )
        except Exception as e:
            from utils.logger import logger
            logger.error(f"Error loading store icon (large): {e}")
            # Return a blank image as fallback
            blank = Image.new('RGBA', (50, 50), (255, 255, 255, 0))
            return customtkinter.CTkImage(light_image=blank, dark_image=blank, size=(50, 50))
