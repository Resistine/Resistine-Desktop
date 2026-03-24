"""
AnimatedText - Character-by-character and line-by-line text animation for Tkinter.

This module provides an AnimatedText class that animates text display similar to iOS AnimatedText component.
Text appears character-by-character, line-by-line, with configurable delays.

Author: Peres J. and the Resistine Team
Copyright (c) Resistine 2025
Licensed under the GNU General Public License v2 or later
"""

import tkinter as tk
from typing import Optional


class AnimatedText:
    """
    A class that animates text display in a Tkinter widget.
    
    Text appears character-by-character, line-by-line, with configurable delays
    between characters and lines. Uses Tkinter's after() method for timing.
    """
    
    def __init__(self, widget, character_delay: float = 0.02, line_delay: float = 0.5):
        """
        Initialize the AnimatedText instance.
        
        :param widget: Tkinter widget to update (e.g., tk.Text, tk.Label, customtkinter.CTkTextbox)
        :param character_delay: Delay in seconds between each character (default: 0.02)
        :param line_delay: Delay in seconds between lines (default: 0.5)
        """
        self.widget = widget
        self.character_delay = character_delay
        self.line_delay = line_delay
        
        # State tracking
        self.full_text = ""
        self.lines = []
        self.displayed_text = ""
        self.current_line_index = 0
        self.current_char_index = 0
        
        # Store scheduled callback IDs for cancellation
        self.scheduled_callbacks = []
        
        # Optional explicit insertion point (if set, will use this instead of "end")
        self._explicit_insert_pos = None
        
        # Track how many characters we've displayed (for append-only updates)
        self._last_displayed_length = 0
    
    def set_insertion_point(self, position: str):
        """
        Set an explicit insertion point for the animation.
        This is useful when you want to insert at a specific position rather than "end".
        
        :param position: Tkinter index string (e.g., "end", "1.0", "2.5")
        """
        self._explicit_insert_pos = position
    
    def start_animation(self, full_text: str, insert_tag: Optional[str] = None, on_complete: Optional[callable] = None):
        """
        Initialize and start the animation with new text.
        
        :param full_text: The complete text to animate (can contain newlines)
        :param insert_tag: Optional tag to apply when inserting text (for CTkTextbox styling)
        :param on_complete: Optional callback function to call when animation completes
        """
        # Stop any ongoing animation
        self.stop_animation()
        
        # Reset state
        self.full_text = full_text
        self.displayed_text = ""
        self.current_line_index = 0
        self.current_char_index = 0
        self._insert_tag = insert_tag
        self._on_complete = on_complete
        
        # Reset insertion position tracking (will be set on first update)
        if hasattr(self, '_insert_start_pos'):
            delattr(self, '_insert_start_pos')
        if hasattr(self, '_insert_end_pos'):
            delattr(self, '_insert_end_pos')
        
        # Reset displayed length counter
        self._last_displayed_length = 0
        
        # Split text into lines
        self.lines = full_text.split('\n')
        
        # Handle edge cases
        if not self.lines:
            return
        
        # Start animating the first line
        self._animate_next_line()
    
    def _animate_next_line(self):
        """
        Process the current line character by character.
        After completing a line, wait for line delay, then move to next line.
        """
        # Check if we've processed all lines
        if self.current_line_index >= len(self.lines):
            # Animation complete - call completion callback if provided
            if hasattr(self, '_on_complete') and self._on_complete:
                try:
                    self._on_complete()
                except:
                    pass
            return
        
        current_line = self.lines[self.current_line_index]
        
        # Check if we've displayed all characters in the current line
        if self.current_char_index >= len(current_line):
            # Line complete - add newline and move to next line
            if self.current_line_index < len(self.lines) - 1:
                # Add newline (except for the last line)
                self.displayed_text += '\n'
                self._update_widget()
            
            # Move to next line
            self.current_line_index += 1
            self.current_char_index = 0
            
            # If there are more lines, wait for line delay before starting next line
            if self.current_line_index < len(self.lines):
                callback_id = self.widget.after(
                    int(self.line_delay * 1000),
                    self._animate_next_line
                )
                self.scheduled_callbacks.append(callback_id)
            return
        
        # Add next character to displayed text
        self.displayed_text += current_line[self.current_char_index]
        self.current_char_index += 1
        
        # Update the widget
        self._update_widget()
        
        # Schedule next character update
        callback_id = self.widget.after(
            int(self.character_delay * 1000),
            self._animate_next_line
        )
        self.scheduled_callbacks.append(callback_id)
    
    def _update_widget(self):
        """
        Update the widget with the current displayed text.
        Handles different widget types (tk.Text, tk.Label, customtkinter.CTkTextbox).
        """
        try:
            # Check if it's a tk.Text widget or customtkinter.CTkTextbox
            if isinstance(self.widget, tk.Text):
                # IMPORTANT (chat plugin): we animate into a real tk.Text (CTkTextbox's internal _textbox).
                # So this MUST be append-only; never delete/replace the whole widget.

                # Track where we started inserting
                if not hasattr(self, "_insert_start_pos"):
                    if self._explicit_insert_pos is not None:
                        self._insert_start_pos = self.widget.index(self._explicit_insert_pos)
                        self._explicit_insert_pos = None
                    else:
                        self._insert_start_pos = self.widget.index("end")

                    self._insert_end_pos = self._insert_start_pos
                    self._last_displayed_length = 0

                # Append only the new characters we haven't shown yet
                current_displayed_length = len(self.displayed_text)
                chars_to_add = current_displayed_length - self._last_displayed_length

                if chars_to_add > 0:
                    new_chars = self.displayed_text[self._last_displayed_length:]

                    if hasattr(self, "_insert_end_pos") and self._insert_end_pos:
                        insert_pos = self._insert_end_pos
                    else:
                        insert_pos = self._insert_start_pos

                    if hasattr(self, "_insert_tag") and self._insert_tag:
                        self.widget.insert(insert_pos, new_chars, self._insert_tag)
                    else:
                        self.widget.insert(insert_pos, new_chars)

                    self._last_displayed_length = current_displayed_length
                    self._insert_end_pos = self.widget.index("end")
            elif hasattr(self.widget, '_textbox'):
                # For customtkinter.CTkTextbox, use the internal _textbox
                # NEVER delete existing content - only append new characters
                # Track where we started inserting
                if not hasattr(self, '_insert_start_pos'):
                    # First update - mark the start position (where we'll insert the animated text)
                    # Use explicit position if set, otherwise use "end"
                    if self._explicit_insert_pos is not None:
                        self._insert_start_pos = self.widget._textbox.index(self._explicit_insert_pos)
                        # Clear explicit position after first use
                        self._explicit_insert_pos = None
                    else:
                        self._insert_start_pos = self.widget._textbox.index("end")
                    # Mark the end position for tracking (initially same as start)
                    self._insert_end_pos = self._insert_start_pos
                    self._last_displayed_length = 0
                
                # Calculate what NEW text to add (only characters we haven't displayed yet)
                # We track displayed length, so we only add characters beyond what we've already shown
                current_displayed_length = len(self.displayed_text)
                chars_to_add = current_displayed_length - self._last_displayed_length
                
                if chars_to_add > 0:
                    # Add only the new characters that haven't been displayed yet
                    new_chars = self.displayed_text[self._last_displayed_length:]
                    
                    # CRITICAL: Use the stored insertion end position for subsequent inserts
                    # On first insert, we insert at _insert_start_pos (which is set to the position after user message)
                    # For subsequent inserts, we insert at _insert_end_pos (where our last insert ended)
                    # This ensures we always append sequentially after the user message, never before it
                    if hasattr(self, '_insert_end_pos') and self._insert_end_pos:
                        # Use the end position from our last insert (this is where we continue appending)
                        insert_pos = self._insert_end_pos
                    elif hasattr(self, '_insert_start_pos') and self._insert_start_pos:
                        # First insert - use the start position (after user message)
                        insert_pos = self._insert_start_pos
                    else:
                        # Fallback: should not happen, but use current end as last resort
                        insert_pos = self.widget._textbox.index("end")
                    
                    if hasattr(self, '_insert_tag') and self._insert_tag:
                        self.widget._textbox.insert(insert_pos, new_chars, self._insert_tag)
                    else:
                        self.widget._textbox.insert(insert_pos, new_chars)
                    
                    # Update the displayed length counter
                    self._last_displayed_length = current_displayed_length
                    # Update the end position marker to where we just inserted (for next append)
                    self._insert_end_pos = self.widget._textbox.index("end")
                
                # Scroll to show the latest text (but don't force if user scrolled up)
                try:
                    # Only scroll if we're near the bottom
                    first_visible = float(self.widget._textbox.index("@0,0").split('.')[0])
                    total_lines = float(self.widget._textbox.index("end-1c").split('.')[0])
                    if total_lines > 0:
                        scroll_ratio = first_visible / total_lines
                        # If user is viewing bottom 90%, auto-scroll
                        if scroll_ratio >= 0.9 or (total_lines - first_visible) < 5:
                            self.widget._textbox.see("end")
                except:
                    # If scroll check fails, just scroll to end
                    self.widget._textbox.see("end")
            elif hasattr(self.widget, 'configure'):
                # For tk.Label or similar widgets with text/stringvar
                if hasattr(self.widget, 'config'):
                    self.widget.config(text=self.displayed_text)
                elif hasattr(self.widget, 'configure'):
                    self.widget.configure(text=self.displayed_text)
        except Exception as e:
            # Silently handle errors (widget might be destroyed)
            pass
    
    def stop_animation(self):
        """
        Cancel any ongoing animation by canceling scheduled callbacks.
        """
        for callback_id in self.scheduled_callbacks:
            try:
                self.widget.after_cancel(callback_id)
            except:
                pass
        
        self.scheduled_callbacks.clear()
        
        # Reset insert position tracking if it exists
        if hasattr(self, '_insert_start_pos'):
            delattr(self, '_insert_start_pos')
        if hasattr(self, '_insert_end_pos'):
            delattr(self, '_insert_end_pos')
        # Reset append-only tracking
        self._last_displayed_length = 0
        if hasattr(self, '_insert_tag'):
            delattr(self, '_insert_tag')
        if hasattr(self, '_on_complete'):
            delattr(self, '_on_complete')
        # Don't reset _explicit_insert_pos here - it should persist until used
    
    def set_widget(self, widget):
        """
        Change the widget that displays the animated text.
        
        :param widget: New Tkinter widget to use
        """
        self.stop_animation()
        self.widget = widget
    
    def get_displayed_text(self) -> str:
        """
        Get the currently displayed text (partial during animation).
        
        :return: The text that has been displayed so far
        """
        return self.displayed_text
    
    def is_animating(self) -> bool:
        """
        Check if animation is currently in progress.
        
        :return: True if animation is active, False otherwise
        """
        return len(self.scheduled_callbacks) > 0

