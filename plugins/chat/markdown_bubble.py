##@file plugins/chat/markdown_bubble.py
"""
Markdown Bubble — Native Renderer
Renders markdown content using a native CTkTextbox with text tags,
avoiding the blurriness of HtmlFrame/tkhtml3 on macOS Retina displays.

Author: P3 and the Resistine Team
Copyright (c) Resistine 2025
Licensed under the GNU General Public License v2 or later
"""

import re
import sys
import tkinter as tk

import customtkinter

from utils.logger import logger

try:
    from pygments import highlight
    from pygments.lexers import get_lexer_by_name, guess_lexer
    from pygments.formatters import TerminalFormatter
    PYGMENTS_AVAILABLE = True
except ImportError:
    PYGMENTS_AVAILABLE = False
    logger.warning("Pygments not available, syntax highlighting disabled")


class MarkdownBubble(customtkinter.CTkFrame):
    """Renders markdown as crisp native text using CTkTextbox + text tags."""

    # Inline formatting regex — order matters (bold before italic)
    _INLINE_RE = re.compile(
        r'(\*\*(?:(?!\*\*).)+?\*\*'   # **bold**
        r'|`(?:(?!`).)+?`'             # `code`
        r'|\*(?:(?!\*).)+?\*'          # *italic*
        r')'
    )

    def __init__(self, master, markdown_content, **kwargs):
        # --- Detect appearance mode ---
        appearance_mode = customtkinter.get_appearance_mode()
        if appearance_mode == "System":
            if sys.platform == "darwin":
                try:
                    import subprocess
                    res = subprocess.run(
                        ["defaults", "read", "-g", "AppleInterfaceStyle"],
                        capture_output=True, text=True,
                    )
                    appearance_mode = (
                        "Dark"
                        if res.returncode == 0 and "Dark" in res.stdout
                        else "Light"
                    )
                except Exception:
                    appearance_mode = "Light"
            else:
                appearance_mode = "Light"

        is_dark = appearance_mode == "Dark"

        # --- Color palette — transparent bg like ChatGPT / Claude ---
        if is_dark:
            bubble_bg    = "transparent"
            text_color   = "#E8E8E8"
            heading_clr  = "#FFFFFF"
            code_bg      = "#1A1A1C"
            code_fg      = "#D4D4D8"
            quote_clr    = "#9CA3AF"
            link_clr     = "#60A5FA"
            table_header_bg = "#252528"
            table_row_bg    = "#1E1E20"
            table_border    = "#3A3A3C"
        else:
            bubble_bg    = "transparent"
            text_color   = "#1F2937"
            heading_clr  = "#111827"
            code_bg      = "#F0F0F2"
            code_fg      = "#1F2937"
            quote_clr    = "#6B7280"
            link_clr     = "#0D5394"
            table_header_bg = "#E8E8EA"
            table_row_bg    = "#F5F5F7"
            table_border    = "#D4D4D8"

        super().__init__(master, fg_color="transparent", corner_radius=0, **kwargs)

        self.markdown_content = markdown_content
        self._bubble_bg = bubble_bg
        self._table_header_bg = table_header_bg
        self._table_row_bg = table_row_bg
        self._table_border = table_border

        self._tables = []
        try:
            self._build_native(bubble_bg, text_color, heading_clr,
                               code_bg, code_fg, quote_clr, link_clr, is_dark)
        except Exception as e:
            logger.warning(f"MarkdownBubble native render failed, using fallback: {e}")
            self._render_fallback()

    # ------------------------------------------------------------------
    # Native renderer
    # ------------------------------------------------------------------

    def _build_native(self, bubble_bg, text_color, heading_clr,
                      code_bg, code_fg, quote_clr, link_clr, is_dark):
        """Build and populate the native text-based renderer."""

        self.text_widget = customtkinter.CTkTextbox(
            self,
            wrap="word",
            fg_color="transparent",
            text_color=text_color,
            font=customtkinter.CTkFont(family="Inter", size=15, weight="normal"),
            border_width=0,
            corner_radius=0,
            activate_scrollbars=False,
        )
        self.text_widget.pack(fill="both", expand=True, padx=16, pady=8)

        # Store colors for later use
        self._colors = {
            'bubble_bg': bubble_bg,
            'text_color': text_color,
            'heading_clr': heading_clr,
            'code_bg': code_bg,
            'code_fg': code_fg,
            'quote_clr': quote_clr,
            'link_clr': link_clr,
            'is_dark': is_dark,
            'table_header_bg': self._table_header_bg,
            'table_row_bg': self._table_row_bg,
            'table_border': self._table_border,
        }

        tw = self.text_widget._textbox
        tw.configure(padx=8, pady=4, wrap="word")
        # Prevent horizontal scrolling
        tw.configure(xscrollcommand=lambda *args: None)
        # Redirect scroll events so the outer chat container scrolls, not this bubble
        self._bind_scroll_redirect(tw)

        # Prevent the frame from shrinking to the child's requested size
        self.pack_propagate(False)

        # --- Text tags ---
        mono = ("SF Mono", 13) if sys.platform == "darwin" else ("Consolas", 13)

        tw.tag_configure("bold", font=("Inter", 15, "bold"))
        tw.tag_configure("italic", font=("Inter", 15, "italic"))
        tw.tag_configure("code_inline",
                         font=mono, foreground=code_fg, background=code_bg,
                         borderwidth=0, relief="flat")
        tw.tag_configure("code_block",
                         font=mono, foreground=code_fg, background=code_bg,
                         lmargin1=0, lmargin2=0, rmargin=0,
                         spacing1=5, spacing3=5)
        tw.tag_configure("h1", font=("Inter", 20, "bold"),
                         foreground=heading_clr, spacing1=10, spacing3=6)
        tw.tag_configure("h2", font=("Inter", 18, "bold"),
                         foreground=heading_clr, spacing1=8, spacing3=5)
        tw.tag_configure("h3", font=("Inter", 16, "bold"),
                         foreground=heading_clr, spacing1=7, spacing3=4)
        tw.tag_configure("bullet", lmargin1=20, lmargin2=36,
                         spacing1=2, spacing3=2)
        tw.tag_configure("numbered", lmargin1=20, lmargin2=36,
                         spacing1=2, spacing3=2)
        tw.tag_configure("blockquote", lmargin1=16, lmargin2=16,
                         foreground=quote_clr, spacing1=5, spacing3=5,
                         borderwidth=0, relief="flat")
        tw.tag_configure("link", foreground=link_clr, underline=True)
        tw.tag_configure("table_header", font=("Inter", 14, "bold"),
                         foreground=heading_clr)
        tw.tag_configure("table_cell", font=mono, lmargin1=12, lmargin2=12)
        tw.tag_configure("paragraph", spacing1=3, spacing3=3)

        # --- Parse & render ---
        self._render_markdown(self.markdown_content, tw)
        self.text_widget.configure(state="disabled")

        # --- Responsive resize ---
        self._tw = tw
        self.last_width = 0
        self.resize_timer = None

        self._parent_tw = None
        parent = self.master
        while parent:
            if isinstance(parent, customtkinter.CTkTextbox):
                self._parent_tw = parent._textbox
                break
            if isinstance(parent, tk.Text):
                self._parent_tw = parent
                break
            parent = parent.master

        if not self._parent_tw and hasattr(self.master, "_textbox"):
            self._parent_tw = self.master._textbox

        if self._parent_tw:
            self._parent_tw.bind("<Configure>", self._on_parent_cfg, add="+")
            self.after(10, lambda: self._update_width(
                self._parent_tw.winfo_width()))

        self.after(100, self._resize_to_fit)

    # ------------------------------------------------------------------
    # Markdown parsing
    # ------------------------------------------------------------------

    def _render_markdown(self, content, tw):
        """Parse markdown and insert into the Text widget with tags."""
        lines = content.split("\n")
        in_code_block = False
        code_lines = []
        code_language = None
        first = True
        i = 0

        while i < len(lines):
            line = lines[i]

            # --- Code fences ---
            if line.strip().startswith("```"):
                if in_code_block:
                    in_code_block = False
                    if not first:
                        tw.insert("end", "\n")
                    self._render_code_block(tw, code_lines, code_language)
                    tw.insert("end", "\n")
                    code_lines = []
                    code_language = None
                    first = False
                else:
                    in_code_block = True
                    code_lines = []
                    # Extract language identifier
                    lang_match = line.strip()[3:].strip()
                    code_language = lang_match if lang_match else None
                i += 1
                continue

            if in_code_block:
                code_lines.append(line)
                i += 1
                continue

            stripped = line.strip()

            if not stripped:
                i += 1
                continue

            if not first:
                tw.insert("end", "\n")
            first = False

            # --- Headings ---
            if stripped.startswith("### "):
                self._insert_inline(tw, stripped[4:], ("h3",))
                tw.insert("end", "\n")
            elif stripped.startswith("## "):
                self._insert_inline(tw, stripped[3:], ("h2",))
                tw.insert("end", "\n")
            elif stripped.startswith("# "):
                self._insert_inline(tw, stripped[2:], ("h1",))
                tw.insert("end", "\n")

            # --- Bullet list ---
            elif stripped.startswith("- ") or stripped.startswith("* "):
                tw.insert("end", "  •  ", "bullet")
                self._insert_inline(tw, stripped[2:], ("bullet",))
                tw.insert("end", "\n")

            # --- Numbered list ---
            elif re.match(r'^\d+\.\s', stripped):
                m = re.match(r'^(\d+\.)\s(.*)', stripped)
                if m:
                    tw.insert("end", f"  {m.group(1)}  ", ("numbered", "bold"))
                    self._insert_inline(tw, m.group(2), ("numbered",))
                    tw.insert("end", "\n")

            # --- Blockquote ---
            elif stripped.startswith("> "):
                self._insert_inline(tw, stripped[2:], ("blockquote",))
                tw.insert("end", "\n")

            # --- Table ---
            elif stripped.startswith("|"):
                table_lines = []
                while i < len(lines) and lines[i].strip().startswith("|"):
                    table_lines.append(lines[i].strip())
                    i += 1
                self._render_table(tw, table_lines)
                continue  # i already advanced

            # --- Paragraph ---
            else:
                self._insert_inline(tw, stripped, ("paragraph",))
                tw.insert("end", "\n")

            i += 1

        # Unclosed code block
        if in_code_block and code_lines:
            if not first:
                tw.insert("end", "\n")
            self._render_code_block(tw, code_lines, code_language)
            tw.insert("end", "\n")

    def _bind_scroll_redirect(self, widget):
        """Redirect mouse-wheel events on an inner widget to the outer chat container."""
        parent = self.master
        chat_tw = parent._textbox if hasattr(parent, "_textbox") else parent

        # Smooth inertia scrolling for chat bubbles
        bstate = {"vel": 0.0, "job": None}

        def _bstep():
            try:
                if not chat_tw.winfo_exists():
                    bstate["job"] = None
                    return
                v = bstate["vel"]
                if abs(v) < 0.05:
                    bstate["vel"] = 0.0
                    bstate["job"] = None
                    return
                before = chat_tw.yview()
                chat_tw.yview_scroll(int(round(v)) or (1 if v > 0 else -1), "pixels")
                after = chat_tw.yview()
                if abs(after[0] - before[0]) < 0.0001:
                    bstate["vel"] = 0.0
                    bstate["job"] = None
                    return
                bstate["vel"] *= 0.88
                bstate["job"] = chat_tw.after(8, _bstep)
            except Exception:
                bstate["job"] = None

        def _badd(delta):
            bstate["vel"] += delta
            bstate["vel"] = max(-20.0, min(20.0, bstate["vel"]))
            if bstate["job"] is None:
                bstate["job"] = chat_tw.after(1, _bstep)

        def on_wheel(event):
            if sys.platform == "darwin":
                _badd(-1 * event.delta * 0.4)
            else:
                _badd(-1 * (event.delta / 120) * 0.4)
            return "break"

        widget.bind("<MouseWheel>", on_wheel, add="+")
        if sys.platform != "darwin":
            widget.bind("<Button-4>", lambda e: (_badd(-0.5), "break")[-1], add="+")
            widget.bind("<Button-5>", lambda e: (_badd(0.5), "break")[-1], add="+")

    def _render_code_block(self, tw, code_lines, language=None):
        """Render a code block with copy button and optional syntax highlighting."""
        if not code_lines:
            return

        code_text = "\n".join(code_lines)

        # Create a frame to hold the code block with header
        insert_idx = tw.index("insert")

        # Insert language label and copy button frame
        code_frame = customtkinter.CTkFrame(
            tw,
            fg_color=self._colors['code_bg'],
            corner_radius=10
        )

        # Header with language label and copy button
        header_frame = customtkinter.CTkFrame(
            code_frame,
            fg_color="transparent"
        )
        header_frame.pack(fill="x", padx=14, pady=(10, 0))

        # Language label
        if language:
            lang_label = customtkinter.CTkLabel(
                header_frame,
                text=language.lower(),
                font=customtkinter.CTkFont(family="Inter", size=11, weight="bold"),
                text_color=self._colors['quote_clr'],
                anchor="w"
            )
            lang_label.pack(side="left")

        # Copy button
        copy_btn = customtkinter.CTkButton(
            header_frame,
            text="Copy",
            width=70,
            height=26,
            font=customtkinter.CTkFont(family="Inter", size=11),
            fg_color="#0D5394" if not self._colors['is_dark'] else "#1565B0",
            hover_color="#1565B0" if not self._colors['is_dark'] else "#0D5394",
            text_color="#FFFFFF",
            corner_radius=6,
            command=lambda: self._copy_to_clipboard(code_text, copy_btn)
        )
        copy_btn.pack(side="right")

        # Code text widget with horizontal scrollbar for long lines
        code_widget = tk.Text(
            code_frame,
            wrap="char",
            bg=self._colors['code_bg'],
            fg=self._colors['code_fg'],
            font=("SF Mono" if sys.platform == "darwin" else "Consolas", 13),
            borderwidth=0,
            padx=14,
            pady=10,
            highlightthickness=0,
            relief="flat",
            insertwidth=0  # Hide cursor
        )
        code_widget.pack(fill="both", expand=True, padx=0, pady=(6, 10))
        code_widget.insert("1.0", code_text)

        # Calculate appropriate height
        line_count = len(code_lines)
        widget_height = min(25, max(3, line_count + 1))
        code_widget.configure(state="disabled", height=widget_height)
        # Redirect scroll from all code block sub-widgets to the chat container
        for w in (code_frame, header_frame, code_widget):
            self._bind_scroll_redirect(w)
        for child in header_frame.winfo_children():
            self._bind_scroll_redirect(child)

        # Embed the frame
        tw.window_create("end", window=code_frame, padx=0, pady=10, stretch=1)

    def _copy_to_clipboard(self, text, button):
        """Copy text to clipboard and show feedback."""
        try:
            self.clipboard_clear()
            self.clipboard_append(text)
            button.configure(text="Copied!")
            self.after(1500, lambda: button.configure(text="Copy"))
        except Exception as e:
            logger.warning(f"Failed to copy to clipboard: {e}")
            button.configure(text="Failed")
            self.after(1500, lambda: button.configure(text="Copy"))

    def _insert_inline(self, tw, text, base_tags=()):
        """Insert text with inline bold / italic / code formatting and clickable links."""
        parts = self._INLINE_RE.split(text)
        for part in parts:
            if not part:
                continue
            if part.startswith("**") and part.endswith("**"):
                self._insert_with_links(tw, part[2:-2], base_tags + ("bold",))
            elif part.startswith("*") and part.endswith("*") and len(part) > 2:
                self._insert_with_links(tw, part[1:-1], base_tags + ("italic",))
            elif part.startswith("`") and part.endswith("`"):
                tw.insert("end", part[1:-1], base_tags + ("code_inline",))
            else:
                self._insert_with_links(tw, part, base_tags)

    def _insert_with_links(self, tw, text, tags=()):
        """Insert text and make URLs clickable."""
        # URL regex pattern
        url_pattern = re.compile(
            r'(https?://[^\s<>"{}|\\^`\[\]]+|www\.[^\s<>"{}|\\^`\[\]]+)'
        )

        parts = url_pattern.split(text)
        for i, part in enumerate(parts):
            if not part:
                continue
            # Odd indices are URLs (captured groups)
            if i % 2 == 1:
                # Create a unique tag for this URL
                tag_name = f"url_{id(part)}"
                tw.insert("end", part, tags + ("link", tag_name))
                tw.tag_bind(tag_name, "<Button-1>", lambda e, url=part: self._open_url(url))
                tw.tag_bind(tag_name, "<Enter>", lambda e: tw.configure(cursor="hand2"))
                tw.tag_bind(tag_name, "<Leave>", lambda e: tw.configure(cursor=""))
            else:
                tw.insert("end", part, tags)

    def _open_url(self, url):
        """Open URL in the default browser."""
        import webbrowser
        if not url.startswith(('http://', 'https://')):
            url = 'https://' + url
        try:
            webbrowser.open(url)
        except Exception as e:
            logger.warning(f"Failed to open URL {url}: {e}")

    def _render_table(self, tw, table_lines):
        """Render a markdown table as a proper embedded widget grid."""
        if not table_lines:
            return

        # Parse table rows (skip separator lines)
        rows = []
        for line in table_lines:
            inner = line.strip("|").strip()
            if re.match(r'^[\s\-:|]+$', inner):
                continue
            cells = [c.strip() for c in inner.split("|")]
            rows.append(cells)

        if not rows:
            return

        num_cols = max(len(r) for r in rows) if rows else 0

        # Outer frame = border color (1px gaps between cells reveal it)
        table_frame = customtkinter.CTkFrame(
            tw,
            fg_color=self._colors['table_border'],
            corner_radius=10,
        )
        for j in range(num_cols):
            table_frame.grid_columnconfigure(j, weight=1, uniform="col")

        for idx, row in enumerate(rows):
            while len(row) < num_cols:
                row.append("")

            is_header = idx == 0
            for j, cell in enumerate(row):
                bg = (self._colors['table_header_bg'] if is_header
                      else self._colors['table_row_bg'])

                # Frame per cell for proper internal padding
                cell_frame = customtkinter.CTkFrame(
                    table_frame, fg_color=bg, corner_radius=0,
                )
                cell_frame.grid(
                    row=idx, column=j, sticky="nsew",
                    padx=(1 if j > 0 else 0, 0),
                    pady=(1 if idx > 0 else 0, 0),
                )

                cell_label = customtkinter.CTkLabel(
                    cell_frame,
                    text=cell,
                    fg_color="transparent",
                    font=customtkinter.CTkFont(
                        family="Inter", size=13,
                        weight="bold" if is_header else "normal",
                    ),
                    text_color=(self._colors['heading_clr'] if is_header
                                else self._colors['text_color']),
                    anchor="w",
                )
                cell_label.pack(padx=14, pady=8, fill="x")

        self._tables.append((table_frame, num_cols))

        # Redirect scroll events from all table sub-widgets to the chat container
        self._bind_scroll_redirect(table_frame)
        for child in table_frame.winfo_children():
            self._bind_scroll_redirect(child)
            for grandchild in child.winfo_children():
                self._bind_scroll_redirect(grandchild)

        tw.insert("end", "\n")
        tw.window_create("end", window=table_frame, padx=0, pady=8, stretch=1)

    # ------------------------------------------------------------------
    # Responsive resize
    # ------------------------------------------------------------------

    def _on_parent_cfg(self, event):
        self._update_width(event.width)

    def _update_width(self, available_width):
        if available_width <= 1:
            return
        # Account for parent textbox internal padding
        padx = 0
        if self._parent_tw:
            try:
                padx = int(str(self._parent_tw.cget("padx") or 0))
            except (ValueError, tk.TclError):
                padx = 0
        usable = available_width - padx * 2
        # Use 95% of usable width for a clean chat look
        target = max(int(usable * 0.95), 300)
        if target != self.last_width:
            self.last_width = target
            self.configure(width=target)
            
            # Force the inner textbox to update its width for correct wrapping
            if self.text_widget:
                self.text_widget.configure(width=target - 32)
            
            # Update table cell wrapping
            self._update_tables(target)
                
            if self.resize_timer:
                self.after_cancel(self.resize_timer)
            self.resize_timer = self.after(50, self._resize_to_fit)

    def _update_tables(self, width):
        """Update wraplength of table cells based on available width and column count."""
        if width <= 0:
            return
            
        # Reduced width due to padding/margins
        usable_width = width - 40
        
        for table_frame, num_cols in self._tables:
            if num_cols == 0:
                continue
            
            # Approximate width per column (minus cell padding)
            col_width = max(int(usable_width / num_cols) - 30, 50)
            
            try:
                # Iterate through cell frames inside the table frame
                for child in table_frame.winfo_children():
                    # Each child is a cell frame containing a label
                    for grandchild in child.winfo_children():
                        if isinstance(grandchild, customtkinter.CTkLabel):
                            grandchild.configure(wraplength=col_width)
            except Exception:
                pass

    def _update_tables(self, width):
        """Update wraplength of table cells based on available width and column count."""
        if width <= 0:
            return
            
        # Reduced width due to padding/margins
        usable_width = width - 40
        
        for table_frame, num_cols in self._tables:
            if num_cols == 0:
                continue
            
            # Approximate width per column (minus cell padding)
            col_width = max(int(usable_width / num_cols) - 30, 50)
            
            try:
                # Iterate through table frame children (cell frames)
                for child in table_frame.winfo_children():
                    # Each child is a cell frame containing a label
                    for grandchild in child.winfo_children():
                        if isinstance(grandchild, customtkinter.CTkLabel):
                            grandchild.configure(wraplength=col_width)
            except Exception:
                pass

    def _resize_to_fit(self):
        """Adjust height to fit the rendered text content (incl. embedded tables)."""
        try:
            tw = self._tw
            tw.update_idletasks()

            # count(…, "ypixels") gives the total pixel height of all content
            # including embedded windows (tables, code blocks). Much more
            # reliable than dlineinfo which only measures one display line.
            h = None
            try:
                result = tw.count("1.0", "end", "ypixels")
                if result is not None:
                    val = result[0] if isinstance(result, (list, tuple)) else result
                    h = int(val) + 24
            except (tk.TclError, TypeError, ValueError):
                pass

            if h is None:
                info = tw.dlineinfo("end-1c")
                if info:
                    h = info[1] + info[3] + 24
                else:
                    return

            self.configure(height=h)
            self.text_widget.configure(height=h)
        except Exception as e:
            logger.warning(f"MarkdownBubble resize failed: {e}")

    # ------------------------------------------------------------------
    # Fallback — plain label (always crisp, no formatting)
    # ------------------------------------------------------------------

    def _render_fallback(self):
        label = customtkinter.CTkLabel(
            self,
            text=self.markdown_content,
            anchor="w",
            justify="left",
            wraplength=600,
        )
        label.pack(fill="both", expand=True, padx=16, pady=12)
