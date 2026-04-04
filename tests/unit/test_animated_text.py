"""Tests for plugins.chat.animated_text — character-by-character animation.

Covers: initialization, start/stop animation, state tracking,
widget type handling, on_complete callback, and edge cases.
"""

from unittest.mock import MagicMock

import pytest

from plugins.chat.animated_text import AnimatedText


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture()
def mock_widget():
    """A mock that simulates a tk.Text widget."""
    w = MagicMock()
    w.after.return_value = 42  # callback ID
    w.index.return_value = "1.0"
    return w


@pytest.fixture()
def anim(mock_widget):
    return AnimatedText(mock_widget, character_delay=0.02, line_delay=0.5)


# ---------------------------------------------------------------------------
# Initialization
# ---------------------------------------------------------------------------

@pytest.mark.unit
class TestInit:
    def test_default_state(self, anim):
        assert anim.full_text == ""
        assert anim.lines == []
        assert anim.displayed_text == ""
        assert anim.current_line_index == 0
        assert anim.current_char_index == 0
        assert anim.scheduled_callbacks == []
        assert anim._last_displayed_length == 0

    def test_custom_delays(self, mock_widget):
        a = AnimatedText(mock_widget, character_delay=0.1, line_delay=1.0)
        assert a.character_delay == 0.1
        assert a.line_delay == 1.0


# ---------------------------------------------------------------------------
# start_animation
# ---------------------------------------------------------------------------

@pytest.mark.unit
class TestStartAnimation:
    def test_sets_full_text(self, anim):
        anim.start_animation("Hello\nWorld")
        assert anim.full_text == "Hello\nWorld"
        assert anim.lines == ["Hello", "World"]

    def test_resets_state(self, anim):
        anim.displayed_text = "old text"
        anim.current_line_index = 5
        anim.current_char_index = 10
        anim._last_displayed_length = 99

        anim.start_animation("new")
        # start_animation calls _animate_next_line(), which advances one char
        assert anim.full_text == "new"
        assert anim.lines == ["new"]
        # char_index is 1 because first char was already animated
        assert anim.current_char_index == 1

    def test_empty_text(self, anim):
        anim.start_animation("")
        # Empty string splits to [""], which has 1 element
        # Animation should still proceed without crashing
        assert anim.lines == [""]

    def test_stops_previous_animation(self, anim):
        anim.scheduled_callbacks = [1, 2, 3]
        anim.start_animation("new text")
        # Previous callbacks should have been cancelled
        anim.widget.after_cancel.assert_called()

    def test_stores_insert_tag(self, anim):
        anim.start_animation("text", insert_tag="my_tag")
        assert anim._insert_tag == "my_tag"

    def test_stores_on_complete(self, anim):
        cb = MagicMock()
        anim.start_animation("text", on_complete=cb)
        assert anim._on_complete is cb


# ---------------------------------------------------------------------------
# _animate_next_line — state progression
# ---------------------------------------------------------------------------

@pytest.mark.unit
class TestAnimateNextLine:
    def test_single_char_progression(self, anim):
        """Each call appends one character to displayed_text."""
        anim.full_text = "AB"
        anim.lines = ["AB"]
        anim.current_line_index = 0
        anim.current_char_index = 0

        anim._animate_next_line()
        assert anim.displayed_text == "A"
        assert anim.current_char_index == 1

        anim._animate_next_line()
        assert anim.displayed_text == "AB"
        assert anim.current_char_index == 2

    def test_line_boundary_adds_newline(self, anim):
        anim.full_text = "A\nB"
        anim.lines = ["A", "B"]
        anim.current_line_index = 0
        anim.current_char_index = 0

        # Animate 'A'
        anim._animate_next_line()
        assert anim.displayed_text == "A"

        # Line complete — adds newline, moves to next line
        anim._animate_next_line()
        assert "\n" in anim.displayed_text
        assert anim.current_line_index == 1
        assert anim.current_char_index == 0

    def test_on_complete_called_at_end(self, anim):
        cb = MagicMock()
        anim.full_text = "X"
        anim.lines = ["X"]
        anim._on_complete = cb

        anim._animate_next_line()  # "X"
        anim._animate_next_line()  # line complete, last line
        anim._animate_next_line()  # past all lines → on_complete

        cb.assert_called_once()

    def test_on_complete_exception_swallowed(self, anim):
        cb = MagicMock(side_effect=RuntimeError("boom"))
        anim.full_text = ""
        anim.lines = []
        anim._on_complete = cb
        anim.current_line_index = 0

        # Should not raise
        anim._animate_next_line()

    def test_schedules_callbacks(self, anim):
        anim.full_text = "AB"
        anim.lines = ["AB"]
        anim._animate_next_line()
        # Should schedule next character via widget.after()
        anim.widget.after.assert_called()
        assert len(anim.scheduled_callbacks) > 0


# ---------------------------------------------------------------------------
# stop_animation
# ---------------------------------------------------------------------------

@pytest.mark.unit
class TestStopAnimation:
    def test_cancels_all_callbacks(self, anim):
        anim.scheduled_callbacks = [10, 20, 30]
        anim.stop_animation()
        assert anim.scheduled_callbacks == []
        assert anim.widget.after_cancel.call_count == 3

    def test_resets_tracking_state(self, anim):
        anim._insert_start_pos = "1.0"
        anim._insert_end_pos = "2.0"
        anim._insert_tag = "tag"
        anim._on_complete = MagicMock()
        anim._last_displayed_length = 42

        anim.stop_animation()

        assert not hasattr(anim, "_insert_start_pos")
        assert not hasattr(anim, "_insert_end_pos")
        assert not hasattr(anim, "_insert_tag")
        assert not hasattr(anim, "_on_complete")
        assert anim._last_displayed_length == 0

    def test_cancel_handles_destroyed_widget(self, anim):
        anim.widget.after_cancel.side_effect = RuntimeError("widget destroyed")
        anim.scheduled_callbacks = [1]
        # Should not raise
        anim.stop_animation()


# ---------------------------------------------------------------------------
# Utility methods
# ---------------------------------------------------------------------------

@pytest.mark.unit
class TestUtilityMethods:
    def test_set_insertion_point(self, anim):
        anim.set_insertion_point("3.5")
        assert anim._explicit_insert_pos == "3.5"

    def test_set_widget(self, anim):
        new_widget = MagicMock()
        anim.scheduled_callbacks = [1, 2]
        anim.set_widget(new_widget)
        assert anim.widget is new_widget
        # Should have stopped animation (cleared callbacks)
        assert anim.scheduled_callbacks == []

    def test_get_displayed_text(self, anim):
        anim.displayed_text = "partial text"
        assert anim.get_displayed_text() == "partial text"

    def test_is_animating_true(self, anim):
        anim.scheduled_callbacks = [1]
        assert anim.is_animating() is True

    def test_is_animating_false(self, anim):
        anim.scheduled_callbacks = []
        assert anim.is_animating() is False
