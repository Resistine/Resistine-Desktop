## @file main.py
## @namespace main
"""
This script is to run the main window for the Resistine AI EndPoint application.
Author: Petr, Javier, Jackie and the Resistine Team
Copyright (c) Resistine 2025
Licensed under the GNU General Public License v2 or later
"""

import argparse
import os
import signal
import sys
import customtkinter

# Apply all platform-specific CTk monkey-patches (Cairo rendering on Linux,
# resize debounce on Windows, cross-platform scroll bugfix, cursor fixes, etc.)
import gui.ctk_patches  # noqa: F401
from gui.ctk_patches import patch_linux_keybindings

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

        # Fix Ctrl+A select-all on Linux (Tk default is cursor-to-start)
        patch_linux_keybindings(self)

        # Theme: fixed Resistine CTk theme; only appearance mode varies (System/Light/Dark)
        customtkinter.set_default_color_theme(resource_path("resources/themes/resistine_ctk.json"))
        customtkinter.set_appearance_mode("System")

        if DEBUG_WINDOW:
            self.debug_window = DebugWindow(self)
            self.debug_window.create_debug_window()

        self.title("Resistine")
        self._set_app_icon()
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
            # Resume any pending Wazuh install
            if sys.platform == "darwin":
                import threading
                from plugins.wazuh.agent.installer_service import check_and_advance
                threading.Thread(target=check_and_advance, daemon=True).start()
            # Resume any pending ClamAV install
            if sys.platform == "darwin":
                from plugins.antivirus.installer_service import check_and_advance as av_advance
                threading.Thread(target=av_advance, daemon=True).start()
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

        # Initialize cross-platform system notifications
        try:
            from utils import notifications

            notifications.init()
        except Exception as e:
            logger.warning(f"Failed to initialize system notifications: {e}")

        self.protocol("WM_DELETE_WINDOW", self._on_closing)

        # Start system tray icon in a background thread (Windows only).
        # In dev mode, run.bat launches tray.py as a separate process, but in
        # the frozen .exe there's no standalone python — so we run it in-process.
        self._tray = None
        if sys.platform.startswith("win"):
            self._start_tray()

    def _set_app_icon(self):
        """Set the window and taskbar icon on Linux and Windows.

        Looks for the icon at resources/icons/app_icon.png (preferred) with
        fallback to .ico on Windows. Handles all required size variants and
        gracefully no-ops if the file is missing or PIL is unavailable.
        """
        icon_path_png = resource_path("resources/icons/app_icon.png")
        icon_path_ico = resource_path("resources/icons/app_icon.ico")

        try:
            if sys.platform.startswith("linux"):
                # Linux: wm_iconphoto requires Tk PhotoImage objects.
                # Provide multiple sizes so the WM can pick the best fit for
                # titlebar, taskbar, Alt-Tab switcher, etc.
                from PIL import Image, ImageTk
                img = Image.open(icon_path_png)
                sizes = [16, 24, 32, 48, 64, 128, 256]
                photos = []
                for size in sizes:
                    resized = img.resize((size, size), Image.LANCZOS)
                    photos.append(ImageTk.PhotoImage(resized))
                # Keep references alive — Tk GC will drop them otherwise
                self._icon_photos = photos
                # True as first arg makes this the default for all future
                # toplevels too (dialogs, popups, etc.)
                self.wm_iconphoto(True, *photos)

            elif sys.platform.startswith("win"):
                # Windows: iconbitmap() wants a .ico which supports multiple
                # embedded sizes natively. Fall back to PNG→ICO conversion if
                # only a PNG is available.
                if os.path.exists(icon_path_ico):
                    self.iconbitmap(icon_path_ico)
                else:
                    # Convert PNG to a temp ICO with standard Windows sizes
                    from PIL import Image
                    import tempfile
                    img = Image.open(icon_path_png)
                    sizes = [(16, 16), (24, 24), (32, 32), (48, 48),
                             (64, 64), (128, 128), (256, 256)]
                    imgs = [img.resize(s, Image.LANCZOS) for s in sizes]
                    tmp = tempfile.NamedTemporaryFile(suffix=".ico", delete=False)
                    tmp.close()
                    imgs[0].save(tmp.name, format="ICO",
                                 sizes=[(i.width, i.height) for i in imgs],
                                 append_images=imgs[1:])
                    self._icon_tmp = tmp.name  # keep ref so we can clean up
                    self.iconbitmap(tmp.name)

        except FileNotFoundError:
            logger.warning("App icon not found — skipping icon setup.")
        except Exception as e:
            logger.warning(f"Failed to set app icon: {e}")

    def on_update_available(self, version, url, description):
        """Handle when an update is available."""
        import webbrowser

        response = self.show_notification(
            f"Update Available: {version}\n\nWould you like to download and install it?",
            type="info",
            buttons=["Download", "Later"]
        )

        if response == "Download":
            webbrowser.open(url)
            self.show_notification("Opening download in your browser...", type="info")

    def _start_tray(self):
        """Launch the system tray icon in a daemon thread."""
        import threading
        try:
            from gui.tray import ResistineTray
            tray = ResistineTray()
            # Override on_open_app to show THIS window instead of spawning a new process
            def _show_window(icon, item):
                self.after(0, self._restore_window)
            tray.on_open_app = _show_window
            # Override on_quit to fully exit the app
            def _quit_app(icon, item):
                icon.stop()
                self.after(0, self._full_quit)
            tray.on_quit = _quit_app
            self._tray = tray
            t = threading.Thread(target=tray.run, daemon=True)
            t.start()
        except Exception as e:
            logger.warning(f"Failed to start system tray: {e}")

    def _restore_window(self):
        """Show and focus the main window (called from tray 'Open Resistine')."""
        self.deiconify()
        self.lift()
        self.focus_force()

    def _on_closing(self):
        """Hide to tray on window close (X button). Use tray → Quit to exit."""
        if self._tray is not None:
            self.withdraw()  # Hide window, keep process alive for tray
        else:
            self._full_quit()

    def _full_quit(self):
        """Actually exit the application (called from tray Quit or if no tray)."""
        try:
            from utils import updates
            updates.shutdown()
        except Exception:
            pass
        if hasattr(self, "_icon_tmp"):
            try:
                os.unlink(self._icon_tmp)
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

    # --- macOS: prevent running from mounted DMG ---
    if functions.is_running_from_dmg():
        from gui.dmg_prompt import prompt_move_to_applications

        action = prompt_move_to_applications()
        if action == "moved":
            # App was copied to /Applications and relaunched from there — exit this instance
            sys.exit(0)
        elif action == "quit":
            sys.exit(0)
        # action == "continue" — user chose to run anyway (shouldn't normally happen)

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

    # Handle Ctrl+C gracefully
    def _handle_sigint(signum, frame):
        """Close the app gracefully on Ctrl+C."""
        try:
            app.destroy()
        except Exception:
            pass
        sys.exit(0)

    signal.signal(signal.SIGINT, _handle_sigint)

    # Bring the window to the front on launch
    app.lift()
    app.attributes("-topmost", True)
    app.after(100, lambda: app.attributes("-topmost", False))
    app.focus_force()

    if sys.platform == "darwin":
        try:
            from Foundation import NSBundle
            bundle = NSBundle.mainBundle()
            info = bundle.localizedInfoDictionary() or bundle.infoDictionary()
            if info:
                info["LSBackgroundOnly"] = "0"
            from AppKit import NSApplication, NSApp
            NSApplication.sharedApplication()
            NSApp.activateIgnoringOtherApps_(True)
        except ImportError:
            # pyobjc not available — fall back to osascript
            import subprocess
            subprocess.Popen([
                "osascript", "-e",
                'tell application "System Events" to set frontmost '
                'of the first process whose unix id is '
                f'{os.getpid()} to true'
            ])

    # Application loop - run!
    app.mainloop()
