"""AssistantBubble widget for AI response rendering."""
from __future__ import annotations

import itertools
import tkinter as tk

import customtkinter

from plugins.chat.fonts import _BASE_SIZE, RESISTINE_BLUE, get_theme_colors, ui_family
from plugins.chat.markdown_renderer import MarkdownRenderer
from utils.logger import logger

# Animated thinking indicator: Braille spinner sequence. Smoother than the
# old dot-cycle ("Thinking", "Thinking.", "Thinking..", "Thinking...") and
# only changes one glyph per frame, so each tick is a single configure()
# rather than re-computing wraplength against a growing string.
_THINK_SPINNER = ("⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏")
_THINK_FRAME_MS = 80


class AssistantBubble(customtkinter.CTkFrame):
    """Left-aligned bubble for assistant responses.

    Two modes:
    - **Streaming:** ``set_streaming_text()`` updates a plain label.
    - **Finalized:** ``finalize_markdown()`` swaps the placeholder for
      a full MarkdownRenderer (or MarkdownBubble fallback).
    """

    _CORNER_RADIUS = 14

    def __init__(
        self, master: object,
        is_dark: bool = False, max_width: int = 700,
        **kwargs: object,
    ) -> None:
        colors = get_theme_colors(is_dark)
        self._bubble_bg = colors["bubble_bg"]
        self._bubble_fg = colors["bubble_fg"]

        kwargs.setdefault("fg_color", "transparent")
        kwargs.setdefault("corner_radius", 0)
        super().__init__(master, **kwargs)
        self.pack(side="left", fill="x", expand=True, padx=(12, 48))

        self._is_dark = is_dark
        self._max_width = max_width
        self._streaming_text: tk.Text | None = None
        self._renderer: MarkdownRenderer | None = None
        self._thinking_label: customtkinter.CTkLabel | None = None
        self._thinking_iter = itertools.cycle(_THINK_SPINNER)
        self._thinking_after_id: str | None = None

        self._build_thinking_indicator()

    # -- thinking indicator -------------------------------------------------

    def _build_thinking_indicator(self) -> None:
        """Show a subtle animated braille spinner before the response arrives."""
        fg = "#9CA3AF" if self._is_dark else "#6B7280"
        self._thinking_label = customtkinter.CTkLabel(
            self, text=f"Thinking  {next(self._thinking_iter)}",
            fg_color="transparent", text_color=fg,
            font=customtkinter.CTkFont(
                family=ui_family(), size=14, slant="italic"),
            justify="left", anchor="w",
        )
        self._thinking_label.pack(
            fill="x", padx=16, pady=(10, 10), anchor="w")
        self._animate_thinking()

    def _animate_thinking(self) -> None:
        # Defensive: bubble may be destroyed mid-stream by a chat rebuild.
        # winfo_exists short-circuits avoid TclError from a dead widget.
        if self._thinking_label is None:
            return
        try:
            if not self._thinking_label.winfo_exists():
                return
            self._thinking_label.configure(
                text=f"Thinking  {next(self._thinking_iter)}")
            self._thinking_after_id = self.after(
                _THINK_FRAME_MS, self._animate_thinking)
        except tk.TclError:
            self._thinking_after_id = None
            self._thinking_label = None

    def _stop_thinking(self) -> None:
        if self._thinking_after_id is not None:
            try:
                self.after_cancel(self._thinking_after_id)
            except Exception:
                pass
            self._thinking_after_id = None
        if self._thinking_label is not None:
            try:
                self._thinking_label.destroy()
            except Exception:
                pass
            self._thinking_label = None

    # -- streaming ----------------------------------------------------------

    def _build_streaming_widget(self) -> None:
        """Use a tk.Text for the streaming placeholder so each new chunk
        is an O(len(delta)) append instead of an O(len(accumulated))
        relayout. CTkLabel.configure(text=...) replaces the full string,
        rewrapping every token boundary every time — the total cost over
        N chunks is O(N^2). tk.Text supports incremental insert(end, ...)
        without re-measuring earlier content.
        """
        is_dark = self._is_dark
        bg = "#1a1a1a" if is_dark else "#FFFFFF"
        self._streaming_text = tk.Text(
            self, bg=bg, fg=self._bubble_fg, wrap="word",
            font=(ui_family(), _BASE_SIZE),
            borderwidth=0, highlightthickness=0,
            insertwidth=0, cursor="arrow",
            padx=16, pady=8, height=1,
        )
        # Disable cursor + edit while still allowing tk.Text to autosize
        # via configure(state="normal") around inserts.
        self._streaming_text.bind("<Key>", lambda _e: "break")
        # Force width to the bubble's max so wrap calculations are stable
        # while chunks stream in.
        self._streaming_text.configure(width=1)  # let pack() control width
        self._streaming_text.pack(
            fill="x", expand=True, padx=0, pady=0, anchor="w")
        # Pin yview to top so a tall response doesn't auto-scroll itself
        # out of view inside the bubble.
        self._streaming_text["yscrollcommand"] = lambda *_a: None

    def append_streaming_chunk(self, delta: str) -> None:
        """Append a single delta to the streaming widget.

        Constant-time per call regardless of accumulated length. Called
        once per stream tick by StreamController after chunk-batching.
        """
        if self._thinking_label is not None:
            self._stop_thinking()
            self._build_streaming_widget()
        tw = self._streaming_text
        if tw is None or not delta:
            return
        try:
            tw.configure(state="normal")
            tw.insert("end", delta)
            tw.configure(state="disabled")
            # Auto-grow the widget to fit the rendered line count. Must
            # use DISPLAYLINES (wrapped lines visible to the user), not
            # the logical line count from index("end-1c"). A streamed
            # single-paragraph answer typically has no newlines until
            # finalize, so the logical count would stick at 1 and the
            # widget would clip to one row — only the most recently
            # streamed text would be visible, the rest scrolled out of
            # view inside the tk.Text. Cap at 60 to bound bubble height;
            # past that the chat-scroll takes over.
            try:
                dl = tw.count("1.0", "end-1c", "displaylines")
                lines = (dl[0] if isinstance(dl, (list, tuple)) else dl) or 1
            except Exception:
                lines = int(tw.index("end-1c").split(".")[0])
            tw.configure(height=max(1, min(int(lines), 60)))
        except tk.TclError:
            self._streaming_text = None

    # Back-compat for callers that still pass full accumulated text.
    def set_streaming_text(self, text: str) -> None:
        """Replace the streaming placeholder with the full accumulated text.

        Kept for compatibility with the error path that wants to show
        "Error: ..." in place of streamed content. Performance-sensitive
        chunk paths should use append_streaming_chunk() instead.
        """
        if self._thinking_label is not None:
            self._stop_thinking()
            self._build_streaming_widget()
        tw = self._streaming_text
        if tw is None:
            return
        try:
            tw.configure(state="normal")
            tw.delete("1.0", "end")
            tw.insert("1.0", text)
            tw.configure(state="disabled")
            try:
                dl = tw.count("1.0", "end-1c", "displaylines")
                lines = (dl[0] if isinstance(dl, (list, tuple)) else dl) or 1
            except Exception:
                lines = int(tw.index("end-1c").split(".")[0])
            tw.configure(height=max(1, min(int(lines), 60)))
        except tk.TclError:
            self._streaming_text = None

    # -- finalize -----------------------------------------------------------

    def finalize_markdown(self, markdown_text: str) -> None:
        """Replace the streaming placeholder with rendered markdown."""
        # Idempotent: ignore a second finalize (e.g. a stop/done race) so we
        # don't stack a duplicate response + Copy button.
        if getattr(self, "_renderer", None) is not None:
            return
        self._stop_thinking()
        if self._streaming_text is not None:
            try:
                self._streaming_text.destroy()
            except Exception:
                pass
            self._streaming_text = None
        # Keep the raw response so the whole thing (prose + tables + code) can
        # be copied in one click. Selecting across embedded table/code widgets
        # isn't possible in Tk (each is its own widget), so the Copy button is
        # the way to grab the entire response at once.
        self._markdown_text = markdown_text
        # The renderer calls pack_propagate(False) on its parent and freezes
        # that parent's height to exactly the content. Give it an inner frame
        # to own, so THIS bubble can still auto-size to (content + Copy button)
        # — otherwise the button would be clipped.
        self._content_frame = customtkinter.CTkFrame(
            self, fg_color="transparent")
        self._content_frame.pack(fill="x", expand=True)
        try:
            self._renderer = MarkdownRenderer(
                self._content_frame, markdown_text,
                self._is_dark, self._max_width)
        except Exception as exc:
            logger.warning(
                f"MarkdownRenderer failed, using fallback: {exc}")
            from plugins.chat.markdown_bubble import MarkdownBubble
            self._renderer = MarkdownBubble(
                self._content_frame, markdown_text, width=self._max_width)
            self._renderer.pack(fill="x", expand=True)
        self._build_copy_button()

    # -- copy whole response ------------------------------------------------

    def _build_copy_button(self) -> None:
        """'Copy' affordance below the response that copies the entire message
        (body text, tables and code) to the clipboard at once. Uses the app's
        blue (RESISTINE_BLUE) so it's clearly visible and on-brand."""
        self._copy_btn = customtkinter.CTkButton(
            self, text="Copy", width=58, height=24, corner_radius=6,
            fg_color=RESISTINE_BLUE, hover_color="#1565B0", text_color="#FFFFFF",
            font=customtkinter.CTkFont(family=ui_family(), size=12),
            command=self._copy_response,
        )
        self._copy_btn.pack(anchor="w", padx=14, pady=(2, 4))

    def _copy_response(self) -> None:
        try:
            self.clipboard_clear()
            self.clipboard_append(getattr(self, "_markdown_text", "") or "")
            self._copy_btn.configure(text="Copied!")

            def _restore():
                try:
                    if self._copy_btn.winfo_exists():
                        self._copy_btn.configure(text="Copy")
                except Exception:
                    pass
            self.after(1200, _restore)
        except Exception:
            logger.debug("Copy response to clipboard failed")

    # -- lifecycle ---------------------------------------------------------

    def destroy(self) -> None:
        # Cancel the thinking-spinner timer before our widget tree goes
        # away — Tk usually swallows after() callbacks on dead widgets,
        # but CTk's configure can raise on destroyed CTkLabels.
        if self._thinking_after_id is not None:
            try:
                self.after_cancel(self._thinking_after_id)
            except Exception:
                pass
            self._thinking_after_id = None
        super().destroy()

    # -- public API ---------------------------------------------------------

    def set_width(self, max_width: int) -> None:
        """Update content width on resize.

        ``_on_resize`` fires on every chat_scroll <Configure> -- including
        scroll-triggered ones where the width hasn't actually changed.
        Re-asserting widths on embedded tables/code blocks causes a
        single-frame reflow on each scroll tick, so short-circuit when
        the width is unchanged. UserBubble has the same guard.
        """
        if max_width == self._max_width:
            return
        self._max_width = max_width
        # Streaming text widget wraps via pack(fill="x", expand=True), so its
        # wrap width follows the bubble width automatically — no per-resize
        # configure needed (which used to trigger a full re-measure).
        if self._renderer is not None \
                and hasattr(self._renderer, "_update_width"):
            self._renderer._update_width(max_width)
