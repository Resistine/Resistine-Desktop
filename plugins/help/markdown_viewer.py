## @file markdown_viewer.py
## @namespace plugins.help
"""
Markdown viewer for the Help plugin, that provides help documentation.
Author: Petr and the Resistine Team
Copyright (c) Resistine 2025
Licensed under the GNU General Public License v2 or later
"""

import os
import webbrowser

import customtkinter
from customtkinter import ThemeManager
from utils.logger import logger


class MarkdownViewer(customtkinter.CTkFrame):

    # Root files to add to the dropdown
    root_files = ["README.md", "LICENSE.md"]

    def __init__(self, master, docs_dir=None, **kwargs):
        corner_radius = ThemeManager.theme.get("Theme", {}).get("corner_radius", 12)
        super().__init__(master, corner_radius=corner_radius, **kwargs)

        # Navigation history
        self.history = []
        self.current_index = -1
        self.docs_dir = docs_dir

        # Navigation bar — styled as a card header
        self.nav_frame = customtkinter.CTkFrame(self, fg_color="transparent")
        self.nav_frame.pack(fill="x", padx=16, pady=(14, 0))

        # Back button
        self.back_button = customtkinter.CTkButton(
            self.nav_frame,
            text="\u2190  Back",
            width=80,
            height=32,
            corner_radius=8,
            font=customtkinter.CTkFont(size=13),
            fg_color="transparent",
            border_width=1,
            border_color=("#E5E7EB", "#2A2A2C"),
            text_color=("#000000", "#ffffff"),
            hover_color=("#F0F0F5", "#1F1F22"),
            command=self.go_back,
            state="disabled",
        )
        self.back_button.pack(side="left", padx=(0, 6))

        # Home button
        self.home_button = customtkinter.CTkButton(
            self.nav_frame,
            text="\u2302  Home",
            width=80,
            height=32,
            corner_radius=8,
            font=customtkinter.CTkFont(size=13),
            fg_color="transparent",
            border_width=1,
            border_color=("#E5E7EB", "#2A2A2C"),
            text_color=("#000000", "#ffffff"),
            hover_color=("#F0F0F5", "#1F1F22"),
            command=self.go_home,
        )
        self.home_button.pack(side="left", padx=(0, 12))

        # Help files dropdown
        if self.docs_dir:
            self.help_files = self.get_help_files()
            self.file_dropdown = customtkinter.CTkOptionMenu(
                self.nav_frame,
                values=self.help_files,
                command=self.navigate_to_file,
                width=180,
                height=32,
                corner_radius=8,
                font=customtkinter.CTkFont(size=13),
            )
            self.file_dropdown.pack(side="left")

        # Divider
        divider_color = ThemeManager.theme.get("Theme", {}).get(
            "divider_color", ["#E5E7EB", "#2A2A2A"]
        )
        divider = customtkinter.CTkFrame(self, height=1, fg_color=divider_color)
        divider.pack(fill="x", padx=16, pady=(12, 0))

        # Content area — uses MarkdownBubble's native renderer
        self._content_frame = customtkinter.CTkFrame(self, fg_color="transparent")
        self._content_frame.pack(fill="both", expand=True, padx=16, pady=(12, 16))
        self._content_widget = None

        self.home_file = None

    @staticmethod
    def _resolve_system_mode() -> str:
        """Resolve 'System' appearance to 'Dark' or 'Light'."""
        import sys as _sys

        if _sys.platform == "darwin":
            try:
                import subprocess

                res = subprocess.run(
                    ["defaults", "read", "-g", "AppleInterfaceStyle"],
                    capture_output=True,
                    text=True,
                )
                if res.returncode == 0 and "Dark" in res.stdout:
                    return "Dark"
            except Exception:
                pass
        return "Light"

    def get_help_files(self):
        """Get list of help files from docs directory and root."""
        files = []

        # Add root files (README, LICENSE) from the parent of docs_dir
        if self.docs_dir:
            project_root = os.path.dirname(os.path.abspath(self.docs_dir))
            for f in self.root_files:
                if os.path.exists(os.path.join(project_root, f)):
                    files.append(f)

        # Add markdown files from docs_dir
        if self.docs_dir and os.path.exists(self.docs_dir):
            for file in os.listdir(self.docs_dir):
                if file.endswith(".md"):
                    files.append(file)

        return sorted(list(set(files)))

    def navigate_to_file(self, filename):
        """Navigate to a help file from dropdown."""
        if self.docs_dir:
            # Check if it's a root file (parent of docs_dir)
            project_root = os.path.dirname(os.path.abspath(self.docs_dir))
            root_path = os.path.join(project_root, filename)

            if os.path.exists(root_path) and filename in self.root_files:
                self.load_file(root_path)
            else:
                # Check docs dir
                file_path = os.path.join(self.docs_dir, filename)
                if os.path.exists(file_path):
                    self.load_file(file_path)

    def go_home(self):
        """Navigate back to home file."""
        if self.home_file and os.path.exists(self.home_file):
            self.load_file(self.home_file, add_to_history=True)

    def go_back(self):
        """Navigate to previous page in history."""
        if self.current_index > 0:
            self.current_index -= 1
            file_path = self.history[self.current_index]
            self.load_file(file_path, add_to_history=False)
            self.update_nav_buttons()

    def update_nav_buttons(self):
        """Update navigation button states."""
        if self.current_index > 0:
            self.back_button.configure(state="normal")
        else:
            self.back_button.configure(state="disabled")

    def load_file(self, file_path, add_to_history=True):
        self.current_dir = os.path.dirname(os.path.abspath(file_path))

        # Store home file
        if self.home_file is None:
            self.home_file = file_path

        # Add to history
        if add_to_history:
            if self.current_index < len(self.history) - 1:
                self.history = self.history[: self.current_index + 1]
            self.history.append(file_path)
            self.current_index = len(self.history) - 1
            self.update_nav_buttons()

        if not os.path.exists(file_path):
            self._render_content(f"**Error**\n\nFile not found:\n`{file_path}`\n")
            return

        # Update dropdown selection
        if hasattr(self, "file_dropdown"):
            filename = os.path.basename(file_path)
            if filename in self.help_files:
                self.file_dropdown.set(filename)

        with open(file_path, "r", encoding="utf-8") as f:
            content = f.read()

        if file_path.endswith(".md"):
            self._render_content(content)
        else:
            # Wrap plain text in a code fence so it renders as a code block
            self._render_content(f"```\n{content}\n```")

    def _render_content(self, md_content):
        """Render markdown content using the chat plugin's MarkdownBubble."""
        from plugins.chat.markdown_bubble import MarkdownBubble

        # Clear previous content
        if self._content_widget is not None:
            self._content_widget.destroy()
            self._content_widget = None

        self._content_widget = MarkdownBubble(
            self._content_frame, md_content,
        )
        self._content_widget.pack(fill="both", expand=True)

    def on_link_click(self, url):
        """Handle link clicks — local files navigate, external URLs open in browser."""
        logger.info(f"Link clicked: {url}")

        if "://" not in url:
            target_path = os.path.join(self.current_dir, url)
            if os.path.exists(target_path):
                self.load_file(target_path)
                return
        elif url.startswith("file://"):
            target_path = url[7:]
            if os.path.exists(target_path):
                self.load_file(target_path)
                return

        webbrowser.open(url)
