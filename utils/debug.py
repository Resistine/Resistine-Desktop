"""Central debug-mode gate.

All runtime instrumentation (render diagnostics, navigation timing, widget
counts) must be gated behind ``is_debug()`` so it costs nothing in normal use.

Debug mode is enabled by any of:
  * the ``-d`` / ``--debug`` command-line flag,
  * running inside an IDE / under a debugger (``utils.functions.is_running_in_ide``),
  * the ``RESISTINE_DEBUG=1`` environment variable.

``main.py`` exports ``RESISTINE_DEBUG`` once the debug state is resolved so that
modules imported *after* startup get a cheap env-var check. The argv / IDE
fallbacks below cover code that runs *before* that export (e.g. import-time
monkey-patches in ``gui.ctk_patches``).
"""

import os
import sys

_ENV_KEY = "RESISTINE_DEBUG"


def set_debug(enabled: bool) -> None:
    """Record the resolved debug state for later cheap lookups."""
    os.environ[_ENV_KEY] = "1" if enabled else "0"


def is_debug() -> bool:
    """Return True when the app is running in debug mode."""
    env = os.environ.get(_ENV_KEY)
    if env is not None:
        return env == "1"

    # Fallbacks for code running before main.py resolves the flag.
    if any(arg in ("-d", "--debug") for arg in sys.argv):
        return True
    try:
        from utils.functions import is_running_in_ide

        return bool(is_running_in_ide())
    except Exception:
        return False
