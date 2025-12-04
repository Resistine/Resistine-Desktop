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
        self.nav_frame = customtkinter.CTkFrame(self, height=40, fg_color="transparent")
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
        """Get list of help files from docs directory and root."""
        files = []

        # Add root files
        if self.docs_dir:
            project_root = os.path.dirname(self.docs_dir)
            root_files = ["README.md", "LICENSE"]
            for f in root_files:
                if os.path.exists(os.path.join(project_root, f)):
                    files.append(f)

        # Add docs files
        if self.docs_dir and os.path.exists(self.docs_dir):
            for file in os.listdir(self.docs_dir):
                if file.endswith(".md"):
                    files.append(file)

        return sorted(files)

    def navigate_to_file(self, filename):
        """Navigate to a help file from dropdown."""
        if self.docs_dir:
            # Check if it's a root file
            project_root = os.path.dirname(self.docs_dir)
            root_path = os.path.join(project_root, filename)

            if os.path.exists(root_path):
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
            self.html_frame.load_html(
                f"<h1>Error</h1><p>File not found: {file_path}</p>"
            )
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
            # Find <pre><code>...</code></pre> blocks
            import re

            code_block_pattern = re.compile(
                r"(<pre><code>)(.*?)(</code></pre>)", re.DOTALL
            )

            def replace_code_block(match):
                prefix = match.group(1)
                content = match.group(2)
                suffix = match.group(3)
                # Content is already HTML escaped by markdown
                linked_content = self._linkify_text(content, is_escaped=True)
                return f"{prefix}{linked_content}{suffix}"

            html_content = code_block_pattern.sub(replace_code_block, html_content)

            self.html_frame.load_html(css + html_content, base_url=base_url)
        elif file_path.endswith(".html") or file_path.endswith(".htm"):
            self.html_frame.load_file(file_path)
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

            self.html_frame.load_html(html_content)

    def _linkify_text(self, text, is_escaped=False):
        """Convert URLs in text to anchor tags."""
        import re

        # Regex to match URLs, excluding < and > and escaped &lt; &gt;
        # We look for http/https URLs
        # This regex stops at whitespace, <, >, or &lt; or &gt;
        url_pattern = re.compile(r"(https?://(?:(?!&lt;|&gt;|[<>]).)+)")

        parts = url_pattern.split(text)
        final_content = []

        for i, part in enumerate(parts):
            if i % 2 == 0:
                # This is text
                if not is_escaped:
                    # Escape it if not already escaped
                    part = (
                        part.replace("&", "&amp;")
                        .replace("<", "&lt;")
                        .replace(">", "&gt;")
                    )
                final_content.append(part)
            else:
                # This is a URL, make it a link
                # Check if the URL ends with punctuation that should be stripped
                url = part
                trailing_punct = ""

                # Handle trailing &gt; if it somehow got included
                if url.endswith("&gt;"):
                    url = url[:-4]
                    trailing_punct = "&gt;" + trailing_punct

                # Common trailing punctuation
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
        print(f"Link clicked: {url}")
        # print(f"Current dir: {self.current_dir}")

        # Check if it's a local file
        if "://" not in url:
            # Relative path
            target_path = os.path.join(self.current_dir, url)
            if os.path.exists(target_path):
                self.load_file(target_path)
                return  # Don't call default handler
        elif url.startswith("file://"):
            target_path = url[7:]
            if os.path.exists(target_path):
                self.load_file(target_path)
                return  # Don't call default handler

        # External link - open in browser
        print(f"Opening external link: {url}")
        webbrowser.open(url)
