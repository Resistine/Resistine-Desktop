## @file main.py
## @namespace main
"""
This script is to run the main application for Resistine AI.
Author: Peres J.
Copyright (c) Resistine 2025
Licensed under the Apache License 2.0
"""

import sys
import os
from utils.paths import resource_path 
from utils.paths import user_data_dir, user_resource_dir
sys.path.append(resource_path('libraries'))
#sys.path.append(os.path.join(os.path.dirname(__file__), 'libraries'))
import platform
from plugins.vpn.wireguard.wireguard_install import check_wireguard_installed  # Import the installation check
from utils.keys import ensure_keys_exist, write_demo_config_if_absent
import customtkinter
from PIL import Image
from plugins.plugin_manager import PluginManager
from utils import functions as myfunctions
import re
from tkinterweb import HtmlFrame
import tkinter as tk
import importlib
import traceback
import tempfile
import platform


# Generate keys and a demo config (first run)
try:
    ensure_keys_exist()
    write_demo_config_if_absent()
except Exception as e:
    print(f"Key initialization failed: {e}")

# Ensure WireGuard is installed first (before app initialization)
try:
    check_wireguard_installed()
except Exception as e:
    print(f"WireGuard precheck failed: {e}")

class DebugWindow:
    """Debug window to show logs; safe for windowed runs where sys.__stdout__ is None."""
    def __init__(self, master=None):
        self.master = master
        self.top = None
        self.text = None
        self._orig_stdout = getattr(sys, "__stdout__", None)
        self._orig_stderr = getattr(sys, "__stderr__", None)
        self._log_file = None
        # If no console streams, open a log file as fallback
        if self._orig_stdout is None or self._orig_stderr is None:
            try:
                log_dir = os.path.join(os.environ.get("APPDATA", tempfile.gettempdir()), "Resistine AI", "logs")
                os.makedirs(log_dir, exist_ok=True)
                self._log_file = open(os.path.join(log_dir, "app.log"), "a", encoding="utf-8")
            except Exception:
                self._log_file = None

    def open(self):
        if self.top and self.top.winfo_exists():
            return
        self.top = customtkinter.CTkToplevel(self.master) if self.master else tk.Toplevel()
        self.top.title("Logs")
        container = customtkinter.CTkFrame(self.top)
        container.pack(fill="both", expand=True)
        self.text = tk.Text(container, height=18, wrap="word")
        self.text.pack(fill="both", expand=True)

    def write(self, msg: str):
        if not msg:
            return
        try:
            if self.text and self.text.winfo_exists():
                self.text.insert("end", msg)
                self.text.see("end")
            elif self._orig_stdout is not None:
                self._orig_stdout.write(msg)
            elif self._log_file is not None:
                self._log_file.write(msg)
                self._log_file.flush()
            # else: drop silently
        except Exception:
            # Never crash on logging
            try:
                if self._log_file:
                    self._log_file.write(msg)
                    self._log_file.flush()
            except Exception:
                pass

    def flush(self):
        try:
            if self.text and self.text.winfo_exists():
                self.text.update_idletasks()
            elif self._log_file:
                self._log_file.flush()
        except Exception:
            pass

    def close(self):
        try:
            if self._log_file:
                self._log_file.close()
        except Exception:
            pass

# Handle elevated VPN toggle before creating the App/UI
if platform.system() == "Windows" and "--vpn-toggle" in sys.argv:
    try:
        idx = sys.argv.index("--vpn-toggle")
        cfg = sys.argv[idx + 1] if len(sys.argv) > idx + 1 else None
    except Exception:
        cfg = None
    if cfg:
        try:
            from plugins.vpn.wireguard.vpn_functions_windows import (
                check_service_status, start_vpn, stop_vpn
            )
            name = os.path.splitext(os.path.basename(cfg))[0]
            status = check_service_status(name, "10.49.64.53")
            if status == "Running":
                stop_vpn(cfg)
            else:
                start_vpn(cfg)
        except Exception as e:
            print(f"Elevated VPN toggle failed: {e}")
    sys.exit(0)

class App(customtkinter.CTk):
    """
    @brief Main application class for Resistine AI.
    Main application class for Resistine AI.
    """
    def __init__(self):
        """
        @brief Initialize the main application window.
        Initialize the main application window, set its title, size, and position.
        Check if the email is registered and create the appropriate screen.
        """
        super().__init__()
        #self.debug = DebugWindow(self)

        #sys.stdout = self.debug
        #sys.stderr = self.debug

        self.title("Resistine AI")
        icon_path = resource_path(r"resources\icons\icon.ico")
        try:
            self.iconbitmap(icon_path)
        except Exception as e:
            print(f"Icon load failed: {e}")
        screen_width = self.winfo_screenwidth()
        screen_height = self.winfo_screenheight()
        window_width = int(screen_width * 0.75)
        window_height = int(screen_height * 0.8)
        position_right = int(screen_width / 2 - window_width / 2)
        position_down = int(screen_height / 2 - window_height / 2)
        self.geometry(f"{window_width}x{window_height}+{position_right}+{position_down}")

        if not self.is_email_registered():
            self.create_registration_screen()
        else:
            self.create_dashboard()

    #def is_email_registered(self):
        """
        Check if the email is registered by verifying the existence of the email-settings.txt file.
        
        :return: True if the email is registered, False otherwise.
        """
        #return os.path.isfile(os.path.join(resource_path("utils"), "email-settings.txt"))
        #return os.path.isfile(os.path.join(os.path.dirname(__file__), "utils", "email-settings.txt"))
    
    def is_email_registered(self):
        """
        Check if the email is registered by verifying the existence of the email-settings.txt file.
        """
        email_path = os.path.join(user_data_dir(), "utils", "email-settings.txt")
        return os.path.isfile(email_path)

    def create_registration_screen(self):
        """
        Create the registration screen where the user can enter their email to register.
        """
        self.grid_rowconfigure(0, weight=1)
        self.grid_columnconfigure(0, weight=1)

        self.registration_frame = customtkinter.CTkFrame(self, corner_radius=0, fg_color=self.cget("fg_color"))
        self.registration_frame.grid(row=0, column=0, sticky="nsew")

        for i in range(6):
            self.registration_frame.grid_rowconfigure(i, weight=1)
        for i in range(3):
            self.registration_frame.grid_columnconfigure(i, weight=1)

        self.welcome_label = customtkinter.CTkLabel(self.registration_frame, text="Welcome to Resistine", font=("Arial", 24))
        self.welcome_label.grid(row=1, column=1, padx=20, pady=20, sticky="nsew")
        self.registration_frame.grid_rowconfigure(0, weight=1)
        self.subtitle_label = customtkinter.CTkLabel(self.registration_frame, text="Please register to have access to our product", font=("Arial", 16))
        self.subtitle_label.grid(row=2, column=1, padx=20, pady=10, sticky="ew")
        self.registration_frame.grid_rowconfigure(1, weight=5)
        self.email_entry = customtkinter.CTkEntry(self.registration_frame, placeholder_text="Enter your email")
        self.email_entry.grid(row=3, column=1, padx=20, pady=20, sticky="ew")

        self.register_button = customtkinter.CTkButton(self.registration_frame, text="Register", command=self.register_email)
        self.register_button.grid(row=4, column=1, padx=20, pady=20, sticky="nsew")

    def register_email(self):
        """
        Register the user's email by validating the input and saving it to a file.
        If the email is invalid or empty, display an error message.
        """
        email = self.email_entry.get()
        email_regex = r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$'
        if not email:
            if hasattr(self, 'error_label'):
                self.error_label.destroy()
            self.error_label = customtkinter.CTkLabel(self.registration_frame, text="Email cannot be empty", font=("Arial", 12), text_color="red")
            self.error_label.grid(row=5, column=1, padx=20, pady=10, sticky="ew")
            return
        elif not re.match(email_regex, email):
            if hasattr(self, 'error_label'):
                self.error_label.destroy()
            self.error_label = customtkinter.CTkLabel(self.registration_frame, text="Invalid email format", font=("Arial", 12), text_color="red")
            self.error_label.grid(row=5, column=1, padx=20, pady=10, sticky="ew")
            return
        if hasattr(self, 'error_label'):
            self.error_label.destroy()
        #shares_folder = os.path.join(os.path.dirname(__file__), "utils")
        #if not os.path.exists(shares_folder):
            #os.makedirs(shares_folder)
        #with open(os.path.join(shares_folder, "email-settings.txt"), "w") as f:
            #f.write(email)
        shares_folder = resource_path("utils")
        #if not os.path.exists(shares_folder):
            #os.makedirs(shares_folder, exist_ok=True)
        with open(os.path.join(shares_folder, "email-settings.txt"), "w", encoding="utf-8") as f:
            f.write(email)
        self.registration_frame.destroy()
        self.create_dashboard()

    def create_dashboard(self):
        """
        Create the main dashboard of the application, including loading plugins and creating navigation buttons.
        """
        self.grid_rowconfigure(0, weight=1)
        self.grid_columnconfigure(1, weight=1)

        # Get plugin list once, refresh if new ones appear
        if not hasattr(App, 'plugin_list'):
            App.plugin_list = PluginManager(self).plugins
        else:
            current = PluginManager(self).plugins
            if len(App.plugin_list) < len(current):
                App.plugin_list = current

        self.plugin_list = App.plugin_list

        if not self.plugin_list:
            print("No plugins loaded. Check plugins folder and dependencies.")
            # Show a minimal placeholder while user fixes setup
            placeholder = customtkinter.CTkLabel(self, text="No plugins loaded")
            placeholder.grid(row=0, column=1, sticky="nsew")
            return

        number_plugins = len(self.plugin_list) + 1

        self.navigation_frame = customtkinter.CTkFrame(self, corner_radius=0)
        self.navigation_frame.grid(row=0, column=0, sticky="nsew")
        self.navigation_frame.grid_rowconfigure(number_plugins, weight=1)

        self.navigation_frame_label = customtkinter.CTkLabel(
            self.navigation_frame, text="Resistine", image=None,
            compound="left", font=customtkinter.CTkFont(size=15, weight="bold")
        )
        self.navigation_frame_label.grid(row=0, column=0, padx=20, pady=20)

        self.frames = {}
        row = 1
        for plugin in self.plugin_list:
            frame_name = f'frame_{plugin.get_name()}'
            self.frames[frame_name] = plugin
            try:
                plugin.set_button(myfunctions.create_tab_button(
                    self.navigation_frame,
                    plugin.get_name(),
                    plugin.get_icon(),
                    lambda p=plugin: self.select_frame_by_name(f'frame_{p.get_name()}', button=p.get_button()),
                    row,
                    0
                ))
            except Exception as e:
                print(f"Error loading plugin button {plugin.get_name()}, Error: {e}")
            row += 1

        # Choose default frame: Dashboard if present, else first plugin
        default_plugin = next(
            (p for p in self.plugin_list if str(p.get_name()).strip().lower() == "dashboard"),
            self.plugin_list[0]
        )
        default_frame_name = f'frame_{default_plugin.get_name()}'
        default_button = getattr(default_plugin, "get_button", lambda: None)()

        self.select_frame_by_name(default_frame_name, button=default_button)

    def select_frame_by_name(self, name, button=None):
        """
        Select and display the specified frame, and update the button appearance.
        """
        if name not in self.frames:
            # Fallback to first available frame to avoid KeyError
            first = next(iter(self.frames), None)
            if not first:
                print("select_frame_by_name called with no frames available.")
                return
            name = first
            button = getattr(self.frames[name], "get_button", lambda: None)()

        for frame_name, frame in self.frames.items():
            try:
                if frame_name == name:
                    if button:
                        button.configure(fg_color=("gray75", "gray25"))
                    frame.create_main_screen().grid(row=0, column=1, sticky="nsew")
                else:
                    # Don't toggle other plugin buttons here; each button callback will set itself active
                    view = frame.create_main_screen()
                    try:
                        view.grid_forget()
                    except Exception:
                        pass
            except Exception as e:
                print(f"Failed to render frame {frame_name}: {e}")

    # On close, restore stdio
    def on_closing(self):
        # Restore stdio and close logger
        try:
            sys.stdout = sys.__stdout__
        except Exception:
            sys.stdout = None
        try:
            sys.stderr = sys.__stderr__
        except Exception:
            sys.stderr = None
        try:
            #self.debug.close()
            if hasattr(self, "debug") and self.debug:
                self.debug.close()
        finally:
            self.destroy()


if __name__ == "__main__":
    customtkinter.set_appearance_mode("system")
    theme_path = resource_path(r"resources\themes\custom_theme.json")
    try:
        customtkinter.set_default_color_theme(theme_path)
    except Exception as e:
        print(f"Theme load failed: {e}")
    app = App()
    app.protocol("WM_DELETE_WINDOW", app.on_closing)
    app.mainloop()

