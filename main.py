## @file main.py
## @namespace main
"""
This script is to run the main window for the Resistine AI EndPoint application.
Author: Petr, Javier, Jackie and the Resistine Team
Copyright (c) Resistine 2025
Licensed under the GNU General Public License v2 or later
"""

import sys
import os
import logging
import subprocess


import customtkinter
from PIL import Image
from plugins.plugin_manager import PluginManager
from utils import functions as myfunctions
from utils import config_manager
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
        #self.debug_window = DebugWindow(self)
        #self.debug_window.create_debug_window()
        
       #Things to run when app is launched
        if sys.platform == 'darwin':
             # Register privileged helper on macOS (only runs once per install)
            from plugins.vpn.wireguard.vpn_functions_darwin import ensure_helper_registered
            ensure_helper_registered()
        
            
        self.title("Resistine")
        screen_width = self.winfo_screenwidth()
        screen_height = self.winfo_screenheight()
        window_width = int(screen_width * 0.75)
        window_height = int(screen_height * 0.8)
        position_right = int(screen_width / 2 - window_width / 2)
        position_down = int(screen_height / 2 - window_height / 2)
        self.geometry(f"{window_width}x{window_height}+{position_right}+{position_down}")

        # Check if already logged in
        if config_manager.is_logged_in():
            print("✅ User already logged in, skipping login screen...")
            self.create_dashboard()
        else:
            # Always show login screen since we're using Odoo authentication
            print("🔐 Creating login screen...")
            self.create_login_screen()
            print("✅ Login screen created")
        
        # Ensure the window is visible
        self.update()



    def create_login_screen(self):
        """
        Create the login screen using the Login plugin.
        """
        # Import the login plugin
        from plugins.login.main import Plugin as LoginPlugin
        
        # Create login plugin instance
        self.login_plugin = LoginPlugin(self)
        
        # Create the login screen
        self.login_frame = self.login_plugin.create_main_screen()
        self.login_frame.grid(row=0, column=0, sticky="nsew")
        
        # Configure grid to ensure login screen takes full window
        self.grid_rowconfigure(0, weight=1)
        self.grid_columnconfigure(0, weight=1)
        
        # Ensure login screen is on top
        self.login_frame.lift()

    def destroy_login_screen(self):
        """
        Destroy the login screen and clean up resources.
        """
        if hasattr(self, 'login_frame'):
            self.login_frame.destroy()
            del self.login_frame
        if hasattr(self, 'login_plugin'):
            del self.login_plugin









    def create_dashboard(self):
        """
        Create the main dashboard of the application, including loading plugins and creating navigation buttons.
        """
        
        for widget in self.winfo_children():
            widget.grid_forget()
        
        # 2. Re-configure the main window (self) for the 2-column dashboard layout
        self.grid_rowconfigure(0, weight=1)  # Only one row needed
        self.grid_columnconfigure(0, weight=0) # Column 0 (Navigation): Weight 0 (only takes necessary width)
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