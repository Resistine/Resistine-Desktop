# @file utils/emoji_entry.py
"""
Drop-in CTkEntry replacement that renders emoji as inline images on Linux.

On non-Linux platforms the class is just an alias for CTkEntry.

Emoji are rendered as inline images via cairosvg. A mapping from image
position to emoji codepoint is maintained so that copy/cut can reconstruct
the real unicode text. No elided/hidden characters are used.

Provides the same API surface used by the chat plugin:
    .get(), .delete(0, "end"), .insert(0, text), .configure(state=...),
    .bind(...), .grid(...), .focus_set(), .configure(placeholder_text=...)
"""

import sys
import customtkinter

_USE_EMOJI_ENTRY = sys.platform == "linux"

if _USE_EMOJI_ENTRY:
    try:
        from plugins.chat.markdown_bubble import (
            _EMOJI_RE, _EMOJI_RENDER, MarkdownBubble,
        )
        if not _EMOJI_RENDER:
            _USE_EMOJI_ENTRY = False
    except ImportError:
        _USE_EMOJI_ENTRY = False

if not _USE_EMOJI_ENTRY:
    EmojiEntry = customtkinter.CTkEntry
else:
    import tkinter as tk

    class EmojiEntry(customtkinter.CTkTextbox):
        """Single-line text input with inline colour emoji on Linux."""

        def __init__(self, master, placeholder_text="", corner_radius=0,
                     border_width=0, height=44, font=None, fg_color=None,
                     text_color=None, placeholder_text_color=None, **kw):
            super().__init__(
                master,
                height=height,
                corner_radius=corner_radius,
                border_width=border_width,
                font=font,
                fg_color=fg_color,
                text_color=text_color,
                wrap="none",
                activate_scrollbars=False,
                **kw,
            )

            # CTkTextbox's grid layout doesn't let the text widget fill the
            # full frame height. Switch from grid to place() so we can
            # position the text widget with exact pixel control, matching
            # how CTkEntry vertically centers its tk.Entry.
            self._textbox.grid_forget()

            def _place_centered():
                try:
                    import tkinter.font as tkfont
                    tw = self._textbox
                    tw.configure(bd=0, highlightthickness=0, pady=0)
                    self.update_idletasks()
                    outer_h = self.winfo_height()
                    outer_w = self.winfo_width()
                    f = tkfont.Font(font=tw.cget("font"))
                    line_h = f.metrics("linespace")
                    # Vertical: center the line in the frame
                    y = max((outer_h - line_h) // 2, 0)
                    # Horizontal: inset by corner_radius (like CTkEntry)
                    x = min(corner_radius, outer_h // 2)
                    tw.place(x=x, y=y, relwidth=1.0, height=line_h,
                             width=-x * 2)
                except Exception:
                    pass
            self.after(50, _place_centered)

            self._placeholder_text = placeholder_text
            self._placeholder_color = placeholder_text_color or "#888888"
            self._text_color = text_color
            self._font = font
            self._showing_placeholder = False
            self._state = "normal"

            # Map: tk image name -> emoji string
            self._image_to_emoji: dict[str, str] = {}

            # Manual undo/redo stacks (Tk's built-in undo can't track images)
            self._undo_stack: list[str] = []
            self._redo_stack: list[str] = []
            self._undo_last = ""

            tw = self._textbox
            tw.configure(undo=False)

            # Block newlines
            tw.bind("<Return>", lambda e: "break")
            tw.bind("<Shift-Return>", lambda e: "break")

            # Intercept all character input
            tw.bind("<Key>", self._on_char_input)

            # Copy/cut/paste
            tw.bind("<<Copy>>", self._on_copy)
            tw.bind("<<Cut>>", self._on_cut)
            tw.bind("<<Paste>>", self._on_paste)

            # Undo/redo (override class-level Text bindings)
            tw.bind("<Control-z>", self._on_undo)
            tw.bind("<Control-y>", self._on_redo)

            # Ctrl+A
            tw.bind("<Control-a>", self._select_all)

            # Ctrl+Backspace word delete
            tw.bind("<Control-BackSpace>", self._on_ctrl_backspace)

            # Backspace/Delete
            tw.bind("<BackSpace>", self._on_backspace)
            tw.bind("<Delete>", self._on_delete)

            # Placeholder
            tw.bind("<FocusIn>", self._on_focus_in)
            tw.bind("<FocusOut>", self._on_focus_out)

            self.after(50, self._show_placeholder)

        # ---- CTkEntry-compatible API ----------------------------------

        def get(self, *args):
            """Return the full text with emoji codepoints restored."""
            if self._showing_placeholder:
                return ""
            return self._get_real_text("1.0", "end-1c")

        def delete(self, from_idx, to_idx=None):
            """Clear all text."""
            self.configure(state="normal")
            self._textbox.delete("1.0", "end")
            self._image_to_emoji.clear()
            self._show_placeholder()

        def insert(self, idx, text):
            """Replace content with text."""
            self._clear_placeholder()
            self.configure(state="normal")
            self._textbox.delete("1.0", "end")
            self._image_to_emoji.clear()
            self._textbox.mark_set("insert", "1.0")
            self._insert_with_emoji(text)

        def focus_set(self):
            self._textbox.focus_set()

        def bind(self, sequence, func=None, add=None):
            if sequence == "<Return>":
                def _handler(e, f=func):
                    if self._state == "disabled":
                        return "break"
                    f(e)
                    return "break"
                self._textbox.bind(sequence, _handler, add)
            else:
                self._textbox.bind(sequence, func, add)

        def configure(self, **kw):
            state = kw.pop("state", None)
            placeholder = kw.pop("placeholder_text", None)

            if placeholder is not None:
                self._placeholder_text = placeholder
                if self._showing_placeholder or not self.get():
                    self._show_placeholder()

            if state is not None:
                self._state = state
                if state == "disabled":
                    self._textbox.configure(state="disabled")
                else:
                    self._textbox.configure(state="normal")

            if kw:
                super().configure(**kw)

        # ---- Placeholder ----------------------------------------------

        def _show_placeholder(self):
            if self.get() and not self._showing_placeholder:
                return
            self._showing_placeholder = True
            self._textbox.configure(state="normal")
            self._textbox.delete("1.0", "end")
            self._image_to_emoji.clear()
            self._textbox.insert("1.0", self._placeholder_text)
            self._textbox.configure(
                foreground=self._placeholder_color if isinstance(
                    self._placeholder_color, str
                ) else "#888888"
            )
            if self._state == "disabled":
                self._textbox.configure(state="disabled")

        def _clear_placeholder(self):
            if self._showing_placeholder:
                self._showing_placeholder = False
                self._textbox.configure(state="normal")
                self._textbox.delete("1.0", "end")
                self._image_to_emoji.clear()
                try:
                    color = self._text_color or ""
                    if color:
                        self._textbox.configure(foreground=color)
                except Exception:
                    pass

        def _on_focus_in(self, event):
            if self._showing_placeholder:
                self._clear_placeholder()

        def _on_focus_out(self, event):
            if not self.get().strip():
                self._show_placeholder()

        # ---- Text reconstruction (images -> real emoji) ---------------

        def _get_real_text(self, start, end):
            """Walk the widget content and reconstruct real text,
            replacing image positions with their emoji codepoints."""
            tw = self._textbox
            result = []
            dump = tw.dump(start, end)
            for kind, val, _idx in dump:
                if kind == "text":
                    result.append(val)
                elif kind == "image":
                    emoji = self._image_to_emoji.get(val, "")
                    result.append(emoji)
            return "".join(result)

        # ---- Copy / Cut -----------------------------------------------

        def _on_copy(self, event=None):
            """Copy selection with emoji codepoints restored."""
            tw = self._textbox
            try:
                sel_start = tw.index("sel.first")
                sel_end = tw.index("sel.last")
            except Exception:
                return "break"
            text = self._get_real_text(sel_start, sel_end)
            tw.clipboard_clear()
            tw.clipboard_append(text)
            return "break"

        def _on_cut(self, event=None):
            """Cut selection with emoji codepoints restored."""
            self._on_copy(event)
            tw = self._textbox
            try:
                tw.delete("sel.first", "sel.last")
            except Exception:
                pass
            self._snapshot()
            return "break"

        # ---- Paste ----------------------------------------------------

        def _on_paste(self, event=None):
            if self._state == "disabled":
                return "break"
            self._clear_placeholder()
            try:
                clip = self._textbox.clipboard_get()
            except Exception:
                return "break"
            # Delete any selection first
            try:
                self._textbox.delete("sel.first", "sel.last")
            except Exception:
                pass
            self._insert_with_emoji(clip)
            self._textbox.see("insert")
            self._snapshot()
            return "break"

        # ---- Undo / Redo ------------------------------------------------

        def _snapshot(self):
            """Save current content to undo stack."""
            current = self.get()
            if current != self._undo_last:
                self._undo_stack.append(self._undo_last)
                self._redo_stack.clear()
                self._undo_last = current

        def _on_undo(self, event=None):
            if not self._undo_stack:
                return "break"
            current = self.get()
            self._redo_stack.append(current)
            prev = self._undo_stack.pop()
            self._undo_last = prev
            self._restore(prev)
            return "break"

        def _on_redo(self, event=None):
            if not self._redo_stack:
                return "break"
            current = self.get()
            self._undo_stack.append(current)
            nxt = self._redo_stack.pop()
            self._undo_last = nxt
            self._restore(nxt)
            return "break"

        def _restore(self, text):
            """Clear the widget and re-insert text with emoji rendering."""
            self._textbox.delete("1.0", "end")
            self._image_to_emoji.clear()
            self._textbox.mark_set("insert", "1.0")
            self._insert_with_emoji(text)
            self._textbox.see("insert")

        # ---- Keyboard input -------------------------------------------

        def _select_all(self, event=None):
            self._textbox.tag_add("sel", "1.0", "end-1c")
            self._textbox.mark_set("insert", "end-1c")
            return "break"

        def _on_ctrl_backspace(self, event=None):
            """Delete the word before the cursor."""
            if self._state == "disabled":
                return "break"
            tw = self._textbox
            pos = tw.index("insert")
            if pos == "1.0":
                return "break"
            # Move back past spaces, then past the word
            prev = tw.index(f"{pos}-1c")
            while prev != "1.0" and tw.get(prev) == " ":
                prev = tw.index(f"{prev}-1c")
            word_start = tw.index(f"{prev} wordstart")
            tw.delete(word_start, pos)
            tw.see("insert")
            self._snapshot()
            return "break"

        def _on_char_input(self, event):
            """Intercept all printable character input."""
            if self._showing_placeholder or self._state == "disabled":
                return
            ch = event.char
            if not ch or ord(ch[0]) < 32:
                return  # control character, let specific bindings handle
            self._clear_placeholder()
            tw = self._textbox
            # Replace selected text if any
            try:
                tw.delete("sel.first", "sel.last")
            except Exception:
                pass
            if _EMOJI_RE and _EMOJI_RE.fullmatch(ch):
                photo = MarkdownBubble._render_emoji(ch)
                if photo:
                    img_name = tw.image_create("insert", image=photo, padx=1)
                    self._image_to_emoji[img_name] = ch
                else:
                    tw.insert("insert", ch)
            else:
                tw.insert("insert", ch, ())
            tw.see("insert")
            self._snapshot()
            return "break"

        def _on_backspace(self, event=None):
            if self._state == "disabled":
                return "break"
            tw = self._textbox
            # Selection delete
            try:
                tw.delete("sel.first", "sel.last")
                tw.see("insert")
                self._snapshot()
                return "break"
            except Exception:
                pass
            pos = tw.index("insert")
            if pos == "1.0":
                return "break"
            prev = tw.index(f"{pos}-1c")
            tw.delete(prev, pos)
            tw.see("insert")
            self._snapshot()
            return "break"

        def _on_delete(self, event=None):
            if self._state == "disabled":
                return "break"
            tw = self._textbox
            # Selection delete
            try:
                tw.delete("sel.first", "sel.last")
                self._snapshot()
                return "break"
            except Exception:
                pass
            pos = tw.index("insert")
            end = tw.index("end-1c")
            if pos == end:
                return "break"
            tw.delete(pos, f"{pos}+1c")
            self._snapshot()
            return "break"

        # ---- Insert with emoji rendering ------------------------------

        def _insert_with_emoji(self, text):
            """Insert text at cursor, rendering emoji as inline images."""
            tw = self._textbox
            if not _EMOJI_RE:
                tw.insert("insert", text)
                return
            parts = _EMOJI_RE.split(text)
            for i, part in enumerate(parts):
                if not part:
                    continue
                if i % 2 == 1:
                    for ch in MarkdownBubble._split_emoji_chars(part):
                        photo = MarkdownBubble._render_emoji(ch)
                        if photo:
                            img_name = tw.image_create(
                                "insert", image=photo, padx=1)
                            self._image_to_emoji[img_name] = ch
                        else:
                            tw.insert("insert", ch)
                else:
                    tw.insert("insert", part)
