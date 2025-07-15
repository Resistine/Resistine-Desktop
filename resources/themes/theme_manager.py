"""
This script is used to detect the system theme (dark or light) and update the UI accordingly. 
It uses the customtkinter module to set the theme of the application.
Author: Peres J.
Copyright (c) Resistine 2025
Licensed under the Apache License 2.0
"""


import tkinter as tk
import ctypes
import customtkinter as ctk
import os

#class to detect system theme and update UI (it doesn't work)
class ThemeManager:
    def __init__(self, root):
        self.app = root
        self.system_theme = self.get_system_theme()
        
        # Set initial theme using customtkinter
        self.set_custom_theme(self.system_theme)
        
        # Start periodically checking for theme changes
        flag = self.check_theme_periodically()
        print("System theme:", self.system_theme)
        print("Theme check started:", flag)

    def get_system_theme(self):
        """Detect system theme (dark or light)."""
        try:
            color = ctypes.c_uint()
            ctypes.windll.dwmapi.DwmGetColorizationColor(ctypes.byref(color), ctypes.c_int())
            if color.value & 0xFFFFFF < 0x7F7F7F:
                return "dark"
            else:
                return "light"
        except Exception as e:
            print("Error detecting system theme:", e)
            return "light"

    def set_custom_theme(self, theme):
        """Set the custom theme using customtkinter."""
        theme_path = os.path.join(os.path.dirname(__file__), "custom_theme.json")
        
        if theme == "dark":
            ctk.set_default_color_theme(theme_path)  # Dark theme
        else:
            ctk.set_default_color_theme(theme_path)  # Light theme or other theme path

    def update_ui(self):
        """Update UI elements based on the current theme."""
        current_theme = self.get_system_theme()
        self.set_custom_theme(current_theme)

    def check_theme_periodically(self):
        """Periodically check if the theme has changed."""
        current_theme = self.get_system_theme()
        if current_theme != self.system_theme:
            self.set_custom_theme(current_theme)
            self.system_theme = current_theme
            return True
        self.app.after(1000, self.check_theme_periodically)  # Check every 5 seconds
        return False


