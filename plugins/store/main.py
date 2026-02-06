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
        self.main_frame = customtkinter.CTkScrollableFrame(
            self.app, corner_radius=0, fg_color="transparent"
        )
        self.main_frame.grid_columnconfigure(0, weight=1)

        # Get theme colors
        accent_blue = customtkinter.ThemeManager.theme["CTkButton"]["border_color"]
        card_bg = customtkinter.ThemeManager.theme["CTkFrame"]["fg_color"]
        corner_radius = customtkinter.ThemeManager.theme["CTkFrame"]["corner_radius"]

        # Add a top spacer to move content down and away from the window title bar/header
        top_margin_spacer = customtkinter.CTkLabel(self.main_frame, text="", height=30)
        top_margin_spacer.grid(row=0, column=0, sticky="ew")

        # Container for centered title panel
        title_container = customtkinter.CTkFrame(self.main_frame, fg_color="transparent", height=80)
        title_container.grid(row=1, column=0, sticky="ew", padx=20, pady=(0, 20))
        title_container.grid_columnconfigure(0, weight=1)
        title_container.grid_propagate(False)
        
        # Title panel with background frame (max width 50%)
        title_frame = customtkinter.CTkFrame(
            title_container,
            fg_color=card_bg,
            corner_radius=corner_radius
        )
        title_frame.place(relx=0.5, rely=0.5, anchor="center", relwidth=0.5, relheight=1.0)
        
        self.title_label = customtkinter.CTkLabel(
            title_frame,
            text="Store",
            font=customtkinter.CTkFont(family="Inter", size=30, weight="bold"),
            text_color=accent_blue,
            justify="center",
            anchor="center",
        )
        self.title_label.pack(expand=True, fill="both", padx=20, pady=20)

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
        
        # Store remote data for restoration after uninstall
        self.remote_data_map = {rp["id"]: rp for rp in available_remote}
        
        # Sort by name for the store
        plugins = sorted(plugins, key=lambda x: x.get_name())
        
        # Deduplicate list by ID to be absolutely safe
        unique_plugins = []
        seen_store_ids = set()
        for p in plugins:
            if p.id not in seen_store_ids:
                unique_plugins.append(p)
                seen_store_ids.add(p.id)
        plugins = unique_plugins
        
        # Store plugins for responsive rebuild
        self._store_plugins = plugins
        
        from utils.logger import logger
        logger.info(f"Store: Rendering {len(plugins)} cards. IDs: {[p.id for p in plugins]}")
        
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

        content_frame = customtkinter.CTkFrame(
            self.main_frame, corner_radius=0, fg_color="transparent"
        )
        content_frame.grid(row=2, column=0, sticky="new", padx=15, pady=0)
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
        
        # Helper for extra buttons - now uses class method
        inject_store_buttons = self._inject_store_buttons

        # Track cards for surgical updates
        self.plugin_cards = {}  # ID -> frame map

        for index, plugin in enumerate(plugins):
            r = index // len(cols)
            c = index % len(cols)
            card = self.app.create_plugin_card(
                r, c, self.grid_frame, plugin, 
                show_description=True, 
                extra_buttons_func=inject_store_buttons
            )
            self.plugin_cards[plugin.id] = card
        
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
            if not hasattr(self, 'main_frame'):
                return
            try:
                if not self.main_frame.winfo_exists() or not self.main_frame.winfo_ismapped():
                    return
            except Exception:
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
        
        # LEAK PREVENTION: Unbind any existing global handler before adding a new one.
        # This is critical because create_main_screen() is called on every tab switch.
        if hasattr(self, '_resize_handler_id') and self._resize_handler_id:
            try:
                self.app.unbind("<Configure>", self._resize_handler_id)
            except:
                pass
        
        self._resize_handler_id = self.app.bind("<Configure>", debounced_resize, add="+")
    
    def destroy(self):
        """Cleanup handler for uninstallation."""
        if hasattr(self, '_resize_after_id') and self._resize_after_id:
            try:
                self.app.after_cancel(self._resize_after_id)
            except:
                pass
        
        if hasattr(self, '_resize_handler_id') and self._resize_handler_id:
            try:
                self.app.unbind("<Configure>", self._resize_handler_id)
            except:
                pass
        
        super().destroy()
    
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
        
        self.plugin_cards = {}
        for index, plugin in enumerate(plugins):
            r = index // len(cols)
            c = index % len(cols)
            card = self.app.create_plugin_card(
                r, c, self.grid_frame, plugin, 
                show_description=True,
                extra_buttons_func=inject_store_buttons
            )
            self.plugin_cards[plugin.id] = card

    def _inject_store_buttons(self, container, p):
        """Helper to inject buttons with inline confirmation for uninstall."""
        # Track button state for confirmation UI
        container._button_state = "normal"  # "normal" or "confirming"
        
        def show_normal_buttons():
            """Show the default Info + (Install/Uninstall) buttons."""
            # Clear container
            for widget in container.winfo_children():
                widget.destroy()
            
            # Info Button
            customtkinter.CTkButton(
                container,
                text="Info",
                height=26,
                width=80,
                command=lambda p=p: self.app.show_readme(p) if not isinstance(p, RemotePluginWrapper) else self.show_remote_info(p),
                border_width=0,
                fg_color=("#3B8ED0", "#1F6AA5"),
                hover_color=("#367EBB", "#144870"),
                font=customtkinter.CTkFont(size=12)
            ).grid(row=0, column=0, padx=5, pady=5)

            if isinstance(p, RemotePluginWrapper) or getattr(p, "status", None) == "Uninstalled":
                # Install Button
                customtkinter.CTkButton(
                    container,
                    text="Install",
                    height=26,
                    width=80,
                    command=lambda p=p: self.handle_install(p),
                    border_width=0,
                    fg_color=("#2ECC71", "#27AE60"),
                    hover_color=("#27AE60", "#219150"),
                    font=customtkinter.CTkFont(size=12)
                ).grid(row=0, column=1, padx=5, pady=5)
            else:
                # Uninstall Button (if enabled)
                if getattr(p, "uninstall_enabled", True):
                    customtkinter.CTkButton(
                        container,
                        text="Uninstall",
                        height=26,
                        width=80,
                        command=show_confirm_buttons,
                        border_width=0,
                        fg_color=("#FF4444", "#C73636"),
                        hover_color=("#C73636", "#9E2A2A"),
                        font=customtkinter.CTkFont(size=12)
                    ).grid(row=0, column=1, padx=5, pady=5)
            
            container._button_state = "normal"
        
        def show_confirm_buttons():
            """Show Confirm + Cancel buttons for uninstall confirmation."""
            # Clear container
            for widget in container.winfo_children():
                widget.destroy()
            
            # Cancel Button
            customtkinter.CTkButton(
                container,
                text="Cancel",
                height=26,
                width=80,
                command=show_normal_buttons,
                border_width=0,
                fg_color=("#808080", "#606060"),
                hover_color=("#707070", "#505050"),
                font=customtkinter.CTkFont(size=12)
            ).grid(row=0, column=0, padx=5, pady=5)
            
            # Confirm Button
            customtkinter.CTkButton(
                container,
                text="Confirm",
                height=26,
                width=80,
                command=confirm_uninstall,
                border_width=0,
                fg_color=("#FF4444", "#C73636"),
                hover_color=("#C73636", "#9E2A2A"),
                font=customtkinter.CTkFont(size=12)
            ).grid(row=0, column=1, padx=5, pady=5)
            
            container._button_state = "confirming"
        
        def confirm_uninstall():
            """Execute the uninstall action."""
            success, res = self.app.get_plugin_manager().uninstall_plugin(p)
            if success:
                self.app.show_notification(res, type="info")
                
                # Surgical update: Swap with RemotePluginWrapper if available
                new_obj = p
                if hasattr(self, 'remote_data_map') and p.id in self.remote_data_map:
                    new_obj = RemotePluginWrapper(self.app, self.remote_data_map[p.id])
                else:
                    # Fallback for local-only plugins
                    p.status = "Uninstalled"
                
                self._replace_card(p.id, new_obj)
                
                if hasattr(self.app, "refresh_navigation"):
                    self.app.refresh_navigation()
                elif hasattr(self.app, "refresh_navigation_menu"):
                    self.app.refresh_navigation_menu()
            else:
                self.app.show_notification(res, type="error")
                # Revert to normal buttons on error
                show_normal_buttons()
        
        # Initialize with normal buttons
        show_normal_buttons()

    def _replace_card(self, old_plugin_id, new_plugin):
        """Surgically replace a card in the grid."""
        if old_plugin_id not in self.plugin_cards:
            return
            
        old_card = self.plugin_cards[old_plugin_id]
        if not old_card.winfo_exists():
            return
            
        # Get grid position
        grid_info = old_card.grid_info()
        row = grid_info.get("row")
        col = grid_info.get("column")
        
        # Destroy and recreate
        old_card.destroy()
        
        new_card = self.app.create_plugin_card(
            row, col, self.grid_frame, new_plugin,
            show_description=True,
            extra_buttons_func=self._inject_store_buttons
        )
        self.plugin_cards[new_plugin.id] = new_card
        
        # Update internal list for responsiveness
        plugin_found = False
        for i, p in enumerate(self._store_plugins):
            if p.id == old_plugin_id:
                self._store_plugins[i] = new_plugin
                plugin_found = True
                break
                
        # If not found (should be impossible if card exists), try to find by ID if it changed?
        # But for now, ensure we don't have duplicates or missing updates.
        if not plugin_found:
            # Fallback: trigger full reload to correct state
            from utils.logger import logger
            logger.warning(f"Store: Could not find plugin {old_plugin_id} in list during swap. Triggering full reload.")
            self.app.after(10, lambda: self.app.select_frame_by_name("frame_Store"))

    def handle_install(self, remote_plugin):
        """Handle plugin installation."""
        from utils.logger import logger
        
        # Common success handler
        def on_success(new_plugin_obj, msg):
            if hasattr(self.app, "refresh_navigation"):
                self.app.refresh_navigation()
            elif hasattr(self.app, "refresh_navigation_menu"):
                self.app.refresh_navigation_menu()
            
            self.app.show_notification(msg, type="info")
            
            # Surgical UI update
            self._replace_card(remote_plugin.id, new_plugin_obj)

        if not isinstance(remote_plugin, RemotePluginWrapper):
            # It's an uninstalled local plugin.
            # Check if files actually exist before trying to re-enable
            manager = self.app.get_plugin_manager()
            
            # We need to guess the folder name or check if the plugin object has a path?
            # BasePlugin doesn't store path directly usually, but PluginManager knows.
            # Simpler: check if load_plugins finds it? No, that's heavy.
            # Let's check typical user path.
            # Or better: Try to re-enable, if load_plugins fails to find it, it means files are gone.
            
            state = manager._load_state()
            if remote_plugin.id in state.get("uninstalled", []):
                # 1. Optimistically un-mark uninstalled
                state["uninstalled"].remove(remote_plugin.id)
                manager._save_state(state)
                
                # 2. Reload plugins
                manager.plugins = sorted(manager.load_plugins(), key=lambda x: x.order)
                
                # 3. Check if it appeared
                new_instance = next((p for p in manager.plugins if p.id == remote_plugin.id), None)
                
                if new_instance:
                    # Success: Files were there, just re-enabled
                    # Update status manually if needed (likely "Stopped" or "OK")
                    new_instance.status = "Stopped" 
                    on_success(new_instance, f"Plugin {remote_plugin.get_name()} re-enabled.")
                    
                    # Auto-navigate if refreshed
                    frame_name = f"frame_{new_instance.get_name()}"
                    # Ensure frames are refreshed before navigating
                    if hasattr(self.app, "frames"):
                        self.app.after(200, lambda: self.app.select_frame_by_name(frame_name))
                    return
                else:
                    # Failure: Files are missing! We must download it.
                    # Revert state change only if download fails? Or just proceed.
                    logger.warning(f"Store: Plugin {remote_plugin.get_name()} marked as re-enabled but files missing. Attempting redownload.")
                    
                    # Try to find URL in remote_data_map
                    url = None
                    if hasattr(self, 'remote_data_map') and remote_plugin.id in self.remote_data_map:
                         url = self.remote_data_map[remote_plugin.id].get("url")
                    
                    if not url:
                        # Try to fetch fresh if map is empty/stale?
                        # For now, just error if we can't find it.
                        self.app.show_notification(f"Cannot reinstall {remote_plugin.get_name()}: Files missing and remote source unknown.", type="error")
                        
                        # Re-add to uninstalled list to be consistent with missing files
                        state["uninstalled"].append(remote_plugin.id)
                        manager._save_state(state)
                        return

                    # Fall through to download logic below...
            else:
                # Not in uninstalled list? Already installed?
                logger.info(f"Store: Plugin {remote_plugin.get_name()} is local and not in uninstalled list. Refreshing...")
                manager.plugins = sorted(manager.load_plugins(), key=lambda x: x.order)
                new_instance = next((p for p in manager.plugins if p.id == remote_plugin.id), remote_plugin)
                on_success(new_instance, "Plugin refreshed.")
                
                # Auto-navigate if refreshed
                frame_name = f"frame_{new_instance.get_name()}"
                if hasattr(self.app, "frames") and frame_name in self.app.frames:
                    self.app.after(100, lambda: self.app.select_frame_by_name(frame_name))
                return

        success, message = self.app.get_plugin_manager().download_plugin(remote_plugin.url, remote_plugin.id, remote_plugin.get_name())
        logger.info(f"Store: Installation result for {remote_plugin.get_name()}: success={success}, msg={message}")
        
        if success:
            # Find the newly installed plugin instance
            manager = self.app.get_plugin_manager()
            # Explicitly reload to ensure we have the new class loaded
            manager.plugins = sorted(manager.load_plugins(), key=lambda x: x.order)
            
            new_instance = next((p for p in manager.plugins if p.id == remote_plugin.id), None)
            if new_instance:
                on_success(new_instance, message)
                
                # Auto-navigate to the new plugin page
                frame_name = f"frame_{new_instance.get_name()}"
                # We need to wait slightly for the UI refresh (triggered by download_plugin) to register the frame
                # Although download_plugin calls refresh_navigation, the frame creation happens in AppUI.select_frame_by_name or init?
                # Actually, refresh_navigation updates buttons. Frames are lazy loaded?
                # AppUI.select_frame_by_name handles creation if missing.
                # So we can just call it safely.
                self.app.after(200, lambda: self.app.select_frame_by_name(frame_name))
            else:
                # Fallback if strange error
                self.app.show_notification("Plugin installed but not found in memory.", type="warning")
                self.app.select_frame_by_name("frame_Store")
        else:
            self.app.show_notification(message, type="error")

    def show_remote_info(self, remote_plugin):
        """Show info for a remote plugin."""
        from gui.dialogs import show_info
        show_info(self.app, remote_plugin.get_name(), remote_plugin.get_description())



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
