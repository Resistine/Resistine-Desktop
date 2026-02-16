## @file markdown_viewer.py
## @namespace plugins.help
"""
Markdown viewer for the Help plugin, that provides help documentation.
Author: Petr and the Resistine Team
Copyright (c) Resistine 2025
Licensed under the GNU General Public License v2 or later
"""

import os
import tkinter as tk
import webbrowser

import customtkinter
from customtkinter import ThemeManager
import markdown
from utils.logger import logger

# tkinterweb (Tkhtml) is optional on Tcl/Tk 9; it can fail at import-time or runtime.
try:
    from tkinterweb import HtmlFrame  # type: ignore
except Exception:  # pragma: no cover
    HtmlFrame = None


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

        # HTML frame with link click handler (fallback to plain text if Tkhtml unavailable)
        self._use_html = False
        self.html_frame = None
        self.fallback_text = None

        if HtmlFrame is not None:
            try:
                mode = customtkinter.get_appearance_mode()
                if mode == "System":
                    mode = self._resolve_system_mode()

                bg_color = "#1A1A1C" if mode == "Dark" else "#ffffff"

                self.html_frame = HtmlFrame(
                    self, messages_enabled=False, on_link_click=self.on_link_click
                )
                try:
                    self.html_frame.configure(background=bg_color)
                except Exception:
                    try:
                        self.html_frame.config(bg=bg_color)
                    except Exception:
                        pass

                self.html_frame.pack(fill="both", expand=True, padx=16, pady=(12, 16))
                self._use_html = True
            except Exception as e:
                logger.warning(f"Help: HtmlFrame unavailable, using fallback viewer: {e}")

        if not self._use_html:
            self.fallback_text = customtkinter.CTkTextbox(
                self,
                wrap="word",
                corner_radius=8,
            )
            self.fallback_text.pack(fill="both", expand=True, padx=16, pady=(12, 16))

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
            # Remove forward history if we're not at the end
            if self.current_index < len(self.history) - 1:
                self.history = self.history[: self.current_index + 1]
            self.history.append(file_path)
            self.current_index = len(self.history) - 1
            self.update_nav_buttons()

        if not os.path.exists(file_path):
            self._render_fallback(f"Error\n\nFile not found:\n{file_path}\n")
            return

        # Update dropdown selection
        if hasattr(self, "file_dropdown"):
            filename = os.path.basename(file_path)
            if filename in self.help_files:
                self.file_dropdown.set(filename)

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

            # Set base_url for relative links
            base_url = "file://" + os.path.abspath(self.current_dir) + "/"

            # Post-process HTML to linkify URLs in code blocks
            import re

            code_block_pattern = re.compile(
                r"(<pre><code>)(.*?)(</code></pre>)", re.DOTALL
            )

            def replace_code_block(match):
                prefix = match.group(1)
                content = match.group(2)
                suffix = match.group(3)
                linked_content = self._linkify_text(content, is_escaped=True)
                return f"{prefix}{linked_content}{suffix}"

            html_content = code_block_pattern.sub(replace_code_block, html_content)

            if self._use_html and self.html_frame is not None:
                try:
                    self.html_frame.load_html(css + html_content, base_url=base_url)
                except Exception as e:
                    logger.warning(f"Help: HtmlFrame load failed, using fallback viewer: {e}")
                    self._use_html = False
                    self._render_fallback(md_content)
            else:
                self._render_fallback(md_content)
        elif file_path.endswith(".html") or file_path.endswith(".htm"):
            if self._use_html and self.html_frame is not None:
                try:
                    self.html_frame.load_file(file_path)
                except Exception as e:
                    logger.warning(f"Help: HtmlFrame load failed, using fallback viewer: {e}")
                    self._use_html = False
                    with open(file_path, "r", encoding="utf-8") as f:
                        self._render_fallback(f.read())
            else:
                with open(file_path, "r", encoding="utf-8") as f:
                    self._render_fallback(f.read())
        else:
            # Handle plain text files (LICENSE, etc.)
            with open(file_path, "r", encoding="utf-8") as f:
                text_content = f.read()

            # Linkify URLs (text is not escaped yet)
            text_content = self._linkify_text(text_content, is_escaped=False)

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

            # Wrap in pre tag for preformatted text
            html_content = f"{css}<pre>{text_content}</pre>"

            if self._use_html and self.html_frame is not None:
                try:
                    self.html_frame.load_html(html_content)
                except Exception as e:
                    logger.warning(f"Help: HtmlFrame load failed, using fallback viewer: {e}")
                    self._use_html = False
                    self._render_fallback(text_content)
            else:
                self._render_fallback(text_content)

    def _linkify_text(self, text, is_escaped=False):
        """Convert URLs in text to anchor tags."""
        import re

        url_pattern = re.compile(r"(https?://(?:(?!&lt;|&gt;|[<>]).)+)")

        parts = url_pattern.split(text)
        final_content = []

        for i, part in enumerate(parts):
            if i % 2 == 0:
                if not is_escaped:
                    part = (
                        part.replace("&", "&amp;")
                        .replace("<", "&lt;")
                        .replace(">", "&gt;")
                    )
                final_content.append(part)
            else:
                url = part
                trailing_punct = ""

                if url.endswith("&gt;"):
                    url = url[:-4]
                    trailing_punct = "&gt;" + trailing_punct

                if (
                    url.endswith(".")
                    or url.endswith(",")
                    or url.endswith(";")
                    or url.endswith(")")
                ):
                    trailing_punct = url[-1] + trailing_punct
                    url = url[:-1]

                final_content.append(f'<a href="{url}">{url}</a>{trailing_punct}')

        return "".join(final_content)

    def on_link_click(self, url):
        logger.info(f"Link clicked: {url}")

        # Check if it's a local file
        if "://" not in url:
            # Relative path
            target_path = os.path.join(self.current_dir, url)
            if os.path.exists(target_path):
                self.load_file(target_path)
                return
        elif url.startswith("file://"):
            target_path = url[7:]
            if os.path.exists(target_path):
                self.load_file(target_path)
                return

        # External link - open in browser
        logger.info(f"Opening external link: {url}")
        webbrowser.open(url)

    def _render_fallback(self, text: str):
        """Render plain text/markdown into fallback text widget."""
        if self.fallback_text is None:
            self.fallback_text = customtkinter.CTkTextbox(
                self,
                wrap="word",
                corner_radius=8,
            )
            self.fallback_text.pack(fill="both", expand=True, padx=16, pady=(12, 16))

        try:
            self.fallback_text.configure(state="normal")
            self.fallback_text.delete("1.0", tk.END)
            self.fallback_text.insert("1.0", text)
            self.fallback_text.configure(state="disabled")
        except Exception:
            pass
