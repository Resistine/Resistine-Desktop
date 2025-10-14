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
import logging
import subprocess


import customtkinter
from PIL import Image
from plugins.plugin_manager import PluginManager
from utils import functions as myfunctions
import re

import tkinter as tk
import io


class DebugWindow:
    """Debug window to show print statements and logs in real-time"""
    
    def __init__(self, parent):
        self.parent = parent
        self.debug_window = None
        self.text_widget = None
        self.original_stdout = sys.stdout
        self.original_stderr = sys.stderr
        
    def create_debug_window(self):
        """Create the debug window"""
        self.debug_window = tk.Toplevel(self.parent)
        self.debug_window.title("Resistine Debug Output")
        self.debug_window.geometry("800x600")
        
        # Create text widget WITHOUT scroll
        self.text_widget = tk.Text(self.debug_window, wrap=tk.WORD)
        self.text_widget.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)
        
        # Add buttons
        button_frame = tk.Frame(self.debug_window)
        button_frame.pack(fill=tk.X, padx=10, pady=5)
        
        clear_button = tk.Button(button_frame, text="Clear", command=self.clear_output)
        clear_button.pack(side=tk.LEFT, padx=5)
        
        save_button = tk.Button(button_frame, text="Save Log", command=self.save_log)
        save_button.pack(side=tk.LEFT, padx=5)
        
        # Redirect stdout and stderr
        self.redirect_output()
        
        # Add initial message
        self.log_message("=== RESISTINE DEBUG WINDOW ===\n")
        self.log_message("All print statements and logs will appear here.\n")
        self.log_message("=" * 50 + "\n")
        
    def redirect_output(self):
        """Redirect stdout and stderr to the debug window"""
        class DebugOutput:
            def __init__(self, debug_window):
                self.debug_window = debug_window
                
            def write(self, text):
                if text.strip():  # Only log non-empty text
                    self.debug_window.log_message(text)
                self.debug_window.original_stdout.write(text)
                
            def flush(self):
                self.debug_window.original_stdout.flush()
        
        sys.stdout = DebugOutput(self)
        sys.stderr = DebugOutput(self)
    
    def log_message(self, message):
        """Add a message to the debug window"""
        if self.text_widget:
            self.text_widget.insert(tk.END, message)
            self.text_widget.see(tk.END)  # Auto-scroll to bottom
            self.text_widget.update_idletasks()
    
    def clear_output(self):
        """Clear the debug output"""
        if self.text_widget:
            self.text_widget.delete(1.0, tk.END)
    
    def save_log(self):
        """Save the debug output to a file"""
        if self.text_widget:
            content = self.text_widget.get(1.0, tk.END)
            try:
                import datetime
                timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
                filename = f"resistine_debug_{timestamp}.log"
                
                with open(filename, 'w') as f:
                    f.write(content)
                
                self.log_message(f"Log saved to: {filename}\n")
            except Exception as e:
                self.log_message(f"Error saving log: {e}\n")
    
    def restore_output(self):
        """Restore original stdout and stderr"""
        sys.stdout = self.original_stdout
        sys.stderr = self.original_stderr

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
        #self.debug_window = DebugWindow(self)
        #self.debug_window.create_debug_window()
        
        # Register privileged helper on macOS (only runs once per install)
        if sys.platform == 'darwin':
            self._ensure_darwin_helper_registered()
            
        self.title("Resistine AI")
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

    def is_email_registered(self):
        """
        Check if the email is registered by verifying the existence of the email-settings.txt file.
        
        :return: True if the email is registered, False otherwise.
        """
        return os.path.isfile(os.path.join(os.path.dirname(__file__), "utils", "email-settings.txt"))

    def _ensure_darwin_helper_registered(self):
        """Register the privileged helper on macOS (runs silently on startup)"""
        try:
            from ServiceManagement import SMAppService
            plist_name = "com.resistine.plist"
            
            # Create the service
            try:
                service = SMAppService.daemonServiceWithPlistName_(plist_name)
            except:
                try:
                    service = SMAppService.daemonWithPlistName_(plist_name)
                except:
                    print("⚠️ Could not create SMAppService for helper")
                    return
            
            # Check current status
            status = int(service.status())
            status_map = {0: "notRegistered", 1: "enabled", 2: "requiresApproval", 3: "notFound"}
            status_str = status_map.get(status, "unknown")
            
            if status == 1:  # Already enabled
                print("✅ Helper already enabled")
                return
            
            if status == 2:  # Requires approval
                print("⚠️ Helper registered but requires user approval")
                self._prompt_helper_approval(service)
                return
            
            # Not registered yet (0 or 3), try to register
            print("🔧 Registering privileged helper...")
            error = service.registerAndReturnError_(None)
            
            if error:
                print(f"⚠️ Helper registration error: {error}")
                # Check status again after registration attempt
                new_status = int(service.status())
                if new_status == 2:  # Now requires approval
                    self._prompt_helper_approval(service)
            else:
                print("✅ Helper registered successfully")
                
        except ImportError:
            print("⚠️ ServiceManagement framework not available")
        except Exception as e:
            print(f"⚠️ Helper registration error: {e}")
    
    def _prompt_helper_approval(self, service):
        """Prompt user to approve helper in System Settings"""
        try:
            import tkinter.messagebox as messagebox
            
            response = messagebox.askyesno(
                "Helper Approval Required",
                "Resistine AI needs your approval to install a helper tool for VPN functionality.\n\n"
                "Click 'Yes' to open System Settings where you can enable it in Login Items.",
                icon='info'
            )
            
            if response:
                # Open System Settings → Login Items
                service.openSystemSettingsLoginItems()
                print("📱 Opened System Settings → Login Items")
        except Exception as e:
            print(f"⚠️ Could not prompt for approval: {e}")

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
        shares_folder = os.path.join(os.path.dirname(__file__), "utils")
        if not os.path.exists(shares_folder):
            os.makedirs(shares_folder)
        with open(os.path.join(shares_folder, "email-settings.txt"), "w") as f:
            f.write(email)
        self.registration_frame.destroy()
        self.create_dashboard()

    def create_dashboard(self):
        """
        Create the main dashboard of the application, including loading plugins and creating navigation buttons.
        """
        self.grid_rowconfigure(0, weight=1)
        self.grid_columnconfigure(1, weight=1)
        #Getting the plugin list from the PluginManager located in plugins folder. 
        if not hasattr(App, 'plugin_list'):
            App.plugin_list = PluginManager(self).plugins
        else:
            if len(App.plugin_list) < len(PluginManager(self).plugins):
                App.plugin_list = PluginManager(self).plugins
        self.plugin_list = App.plugin_list
        number_plugins = len(self.plugin_list) + 1

        self.navigation_frame = customtkinter.CTkFrame(self, corner_radius=0)
        self.navigation_frame.grid(row=0, column=0, sticky="nsew")
        self.navigation_frame.grid_rowconfigure(number_plugins, weight=1)

        self.navigation_frame_label = customtkinter.CTkLabel(self.navigation_frame, text="Resistine", image=None,
                                                             compound="left", font=customtkinter.CTkFont(size=15, weight="bold"))
        self.navigation_frame_label.grid(row=0, column=0, padx=20, pady=20)

        self.frames = {}
        row = 1
        for plugin in self.plugin_list:
            frame_name = f'frame_{plugin.get_name()}'
            self.frames[frame_name] = plugin

            try:
                # Create the buttons for each plugin
                plugin.set_button(myfunctions.create_tab_button(
                    self.navigation_frame, 
                    plugin.get_name(), 
                    plugin.get_icon(), 
                    lambda p=plugin: self.select_frame_by_name(f'frame_{p.get_name()}', button = p.get_button()), 
                    row, 
                    0
                ))
            except Exception as e:
                print(f"Error loading plugin button {plugin.get_name()}, Error: {e}")
            row += 1

        self.select_frame_by_name("frame_Dashboard", button = self.frames["frame_Dashboard"].get_button())

    def select_frame_by_name(self, name, button=None):
        """
        Select and display the specified frame, and update the button appearance.
        
        :param name: The name of the frame to display.
        :param button: The button associated with the frame.
        """
        for frame_name, frame in self.frames.items():
            if frame_name == name:
                if button:
                    button.configure(fg_color=("gray75", "gray25"))
                frame.create_main_screen().grid(row=0, column=1, sticky="nsew")
            else:
                if button:
                    button.configure(fg_color="transparent")
                frame.create_main_screen().grid_forget()

if __name__ == "__main__":
    app = App()
    app.mainloop()
