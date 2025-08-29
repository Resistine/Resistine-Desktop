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
sys.path.append(os.path.join(os.path.dirname(__file__), 'libraries'))
import platform
from wireguard_install import check_wireguard_installed  # Import the installation check
from utils.keys import ensure_keys_exist, write_demo_config_if_absent
import customtkinter
from PIL import Image
from plugins.plugin_manager import PluginManager
from utils import functions as myfunctions
import re
from tkinterweb import HtmlFrame
import tkinter as tk

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

        self.title("Resistine AI")
        self.iconbitmap(r"C:\Users\Developer_here\Desktop\Windows\Resistine-Desktop\resources\icons\icon.ico")
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
    customtkinter.set_appearance_mode("system")
    customtkinter.set_default_color_theme(os.path.join(os.path.dirname(__file__), "resources", "themes", "custom_theme.json"))
    app = App()
    app.mainloop()

