##@file plugins/chat/markdown_bubble.py
"""
Markdown Bubble
This file contains the MarkdownBubble class, which is used to display markdown content in a bubble.
Author: P3 and the Resistine Team
Copyright (c) Resistine 2025
Licensed under the GNU General Public License v2 or later
"""

import os
import sys
import tkinter as tk

import customtkinter
import markdown

from utils.logger import logger

try:
    from tkinterweb import HtmlFrame
except ImportError:
    HtmlFrame = None


class MarkdownBubble(customtkinter.CTkFrame):
    def __init__(self, master, markdown_content, **kwargs):
        super().__init__(master, fg_color="transparent", **kwargs)

        self.markdown_content = markdown_content
        self.html_frame = None

        # Check if HtmlFrame is available
        if HtmlFrame is None:
            if not hasattr(MarkdownBubble, '_warned_tkhtml'):
                logger.warning("Tkhtml not available - using plain text fallback for markdown rendering")
                MarkdownBubble._warned_tkhtml = True
            self._render_fallback()
            return

        # Determine appearance mode and colors
        appearance_mode = customtkinter.get_appearance_mode()
        if appearance_mode == "System":
            if sys.platform == "darwin":
                try:
                    import subprocess

                    res = subprocess.run(
                        ["defaults", "read", "-g", "AppleInterfaceStyle"],
                        capture_output=True,
                        text=True,
                    )
                    appearance_mode = (
                        "Dark"
                        if res.returncode == 0 and "Dark" in res.stdout
                        else "Light"
                    )
                except Exception:
                    appearance_mode = "Light"
            else:
                appearance_mode = "Light"  # Default fallback

        try:
            # Initialize HtmlFrame
            # messages_enabled=False suppresses javascript/css logs
            self.html_frame = HtmlFrame(
                self,
                messages_enabled=False,
                vertical_scrollbar=False,
                horizontal_scrollbar=False,
            )

            # Convert Markdown to HTML
            html_content = markdown.markdown(
                markdown_content,
                extensions=["fenced_code", "tables", "nl2br", "sane_lists"],
            )

            # Load CSS from chat-specific files
            chat_plugin_dir = os.path.dirname(os.path.abspath(__file__))
            chat_css_file = (
                "chat_dark.css" if appearance_mode == "Dark" else "chat_light.css"
            )
            chat_css_path = os.path.join(chat_plugin_dir, chat_css_file)

            css_style = ""
            if os.path.exists(chat_css_path):
                with open(chat_css_path, "r", encoding="utf-8") as f:
                    css_style = f.read()

            # Wrap in a div we can target for sizing
            full_html = f"<style>{css_style}</style><div id='bubble_content'>{html_content}</div>"

            # Load HTML content
            self.html_frame.load_html(full_html)

            # Pack with fill
            self.html_frame.pack(fill="both", expand=True)

            # Schedule initial resize
            self.after(100, self._resize_to_fit)

            # Bind configure event for responsive resizing
            # We must listen to the PARENT (Text widget) resize to update our fixed width constraint.
            # Only then will the inner HTML reflow and height calculation activate correctly.

            # Find the text widget ancestor
            self.text_widget = None
            parent = self.master
            while parent:
                if isinstance(parent, customtkinter.CTkTextbox):
                    self.text_widget = parent._textbox
                    break
                if isinstance(
                    parent, (tk.Text, customtkinter.CTkTextbox)
                ):  # or plain tk.Text
                    self.text_widget = parent
                    break
                parent = parent.master

            if not self.text_widget and hasattr(self.master, "_textbox"):
                self.text_widget = self.master._textbox

            if self.text_widget:
                self.text_widget.bind("<Configure>", self.on_parent_configure, add="+")
                # Trigger initial width set
                self.after(
                    10, lambda: self.update_width(self.text_widget.winfo_width())
                )
            else:
                # Fallback: bind to own configure if we can't find parent (unlikely)
                self.bind("<Configure>", self.on_configure)

            self.last_width = 0
            self.resize_timer = None

        except Exception as e:
            # Only log detailed error once
            if not hasattr(MarkdownBubble, '_warned_render_error'):
                logger.warning(f"MarkdownBubble rendering failed, using fallback: {e}")
                MarkdownBubble._warned_render_error = True
            self._render_fallback()

    def on_parent_configure(self, event):
        """Handle parent Text widget resize."""
        self.update_width(event.width)

    def update_width(self, available_width):
        """Update bubble width and trigger height resize."""
        if available_width <= 1:
            return

        # Use most of the available width so tables and code blocks aren't squeezed
        target_width = int(available_width * 0.92)

        if target_width != self.last_width:
            self.last_width = target_width
            self.configure(width=target_width)

            # Debounce height recalculation
            if self.resize_timer:
                self.after_cancel(self.resize_timer)
            self.resize_timer = self.after(50, self._resize_to_fit)

    def on_configure(self, event):
        # Deprecated in favor of on_parent_configure, but kept as fallback
        pass

    def _resize_to_fit(self):
        """Adjust the height of the bubble to fit the content."""
        if not self.html_frame:
            return

        try:
            # Attempt to find the content div
            # .html is the underlying Tkhtml3 widget
            widget = self.html_frame.html

            # TkinterWeb/Tkhtml3 usually supports searching by CSS selector
            # Note: This API availability depends on the specific bindings, but widely supported in wrappers
            node = None

            # Method 1: search selector
            if hasattr(widget, "search"):
                nodes = widget.search("#bubble_content")
                if nodes:
                    node = nodes[0]

            # Method 2: Fallback to body if search fails or not found
            if not node and hasattr(widget, "node"):
                # Try to get body - heuristic
                pass

            if node:
                # Get bounding box: x1, y1, x2, y2
                bbox = widget.bbox(node)
                if bbox:
                    # Height is y2
                    content_height = bbox[3]

                    # Add a little padding for safety
                    msg_height = content_height + 20

                    # Update the containing frame height
                    self.configure(height=msg_height)

                    # Update html frame height if needed (though it expands)
                    self.html_frame.configure(height=msg_height)
        except Exception as e:
            logger.warning(f"MarkdownBubble resize failed: {e}")

    def _render_fallback(self):
        # Fallback to simple label
        label = customtkinter.CTkLabel(
            self,
            text=self.markdown_content,
            anchor="w",
            justify="left",
            wraplength=700,
        )
        label.pack(fill="both", expand=True, padx=10, pady=10)
