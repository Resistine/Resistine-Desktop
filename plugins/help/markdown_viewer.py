import os
import webbrowser

import customtkinter
import markdown
from tkinterweb import HtmlFrame


class MarkdownViewer(customtkinter.CTkFrame):
    def __init__(self, master, docs_dir=None, **kwargs):
        super().__init__(master, **kwargs)

        # Navigation history
        self.history = []
        self.current_index = -1
        self.docs_dir = docs_dir

        # Navigation bar
        self.nav_frame = customtkinter.CTkFrame(self, height=40)
        self.nav_frame.pack(fill="x", padx=10, pady=(10, 0))
        self.nav_frame.pack_propagate(False)

        # Back button
        self.back_button = customtkinter.CTkButton(
            self.nav_frame,
            text="← Back",
            width=80,
            command=self.go_back,
            state="disabled",
        )
        self.back_button.pack(side="left", padx=5, pady=5)

        # Home button
        self.home_button = customtkinter.CTkButton(
            self.nav_frame, text="🏠 Home", width=80, command=self.go_home
        )
        self.home_button.pack(side="left", padx=5, pady=5)

        # Help files dropdown
        if self.docs_dir:
            self.nav_label = customtkinter.CTkLabel(self.nav_frame, text="Navigate: ")
            self.nav_label.pack(side="left", padx=(10, 5), pady=5)

            self.help_files = self.get_help_files()
            self.file_dropdown = customtkinter.CTkOptionMenu(
                self.nav_frame,
                values=self.help_files,
                command=self.navigate_to_file,
                width=150,
            )
            self.file_dropdown.pack(side="left", padx=5, pady=5)

        # HTML frame with link click handler
        self.html_frame = HtmlFrame(
            self, messages_enabled=False, on_link_click=self.on_link_click
        )
        self.html_frame.pack(fill="both", expand=True, padx=10, pady=10)

        self.home_file = None

    def get_help_files(self):
        """Get list of help files from docs directory."""
        if not self.docs_dir or not os.path.exists(self.docs_dir):
            return []

        files = []
        for file in os.listdir(self.docs_dir):
            if file.endswith(".md"):
                files.append(file)
        return sorted(files)

    def navigate_to_file(self, filename):
        """Navigate to a help file from dropdown."""
        if self.docs_dir:
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
            # Remove forward history if we're not at the end
            if self.current_index < len(self.history) - 1:
                self.history = self.history[: self.current_index + 1]
            self.history.append(file_path)
            self.current_index = len(self.history) - 1
            self.update_nav_buttons()

        if not os.path.exists(file_path):
            self.html_frame.load_html(
                f"<h1>Error</h1><p>File not found: {file_path}</p>"
            )
            return

        if file_path.endswith(".md"):
            with open(file_path, "r", encoding="utf-8") as f:
                md_content = f.read()
            html_content = markdown.markdown(md_content)

            # Get current appearance mode
            appearance_mode = customtkinter.get_appearance_mode()

            # Load CSS from external file
            plugin_dir = os.path.dirname(os.path.abspath(__file__))
            if appearance_mode == "Dark":
                css_file = os.path.join(plugin_dir, "styles_dark.css")
            else:
                css_file = os.path.join(plugin_dir, "styles_light.css")

            with open(css_file, "r", encoding="utf-8") as f:
                css_content = f.read()

            css = f"<style>{css_content}</style>"

            self.html_frame.load_html(css + html_content)
        else:
            self.html_frame.load_file(file_path)

    def on_link_click(self, url):
        print(f"Link clicked: {url}")
        print(f"Current dir: {self.current_dir}")

        # Check if it's a local file
        if "://" not in url:
            # Relative path
            target_path = os.path.join(self.current_dir, url)
            print(f"Checking relative path: {target_path}")
            if os.path.exists(target_path):
                print(f"Loading file: {target_path}")
                self.load_file(target_path)
                return  # Don't call default handler
        elif url.startswith("file://"):
            target_path = url[7:]
            print(f"Checking file:// path: {target_path}")
            if os.path.exists(target_path):
                print(f"Loading file: {target_path}")
                self.load_file(target_path)
                return  # Don't call default handler

        # External link - open in browser
        print(f"Opening external link: {url}")
        webbrowser.open(url)
