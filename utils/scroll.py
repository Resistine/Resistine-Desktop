"""
Per-platform scroll speed constants.

Centralises every tuneable so that adjusting scroll feel is a single-file change.
"""

import sys

_IS_MAC = sys.platform == "darwin"
_IS_LINUX = sys.platform.startswith("linux")

# -- Chat / bubble text-widget scrolling (yview_scroll in pixels) -----------

# Velocity added per discrete scroll notch (Button-4 / Button-5 on Linux).
CHAT_SCROLL_DELTA = 16.0 if _IS_LINUX else 0.5

# Multiplier applied to MouseWheel event.delta.
# macOS trackpad sends raw small deltas; Linux/Windows sends ±120 per notch.
CHAT_WHEEL_SCALE = 0.4 if _IS_MAC else 16.0

# Velocity is clamped to ±CHAT_VEL_CLAMP after every input event.
CHAT_VEL_CLAMP = 20.0

# Velocity below this threshold stops the animation.
CHAT_VEL_THRESHOLD = 0.5

# Multiply velocity by this each 8 ms step (lower = faster deceleration).
CHAT_VEL_DECAY = 0.88

# -- Dashboard / CTkScrollableFrame scrolling (fractional via yview_moveto) ----

# Velocity added per discrete scroll notch (Button-4 / Button-5 on Linux).
FRAME_SCROLL_DELTA = 0.125

# "Feel" constant: velocity is multiplied by this to get the fractional
# yview_moveto offset each step.  Lower = slower scroll.
FRAME_FEEL = 0.01125 if _IS_LINUX else 0.1125

# Velocity is clamped to ±FRAME_VEL_CLAMP.
FRAME_VEL_CLAMP = 8.0

# Velocity below this threshold stops the animation.
FRAME_VEL_THRESHOLD = 0.01

# Decay factor applied each 8 ms step.
FRAME_VEL_DECAY = 0.88
