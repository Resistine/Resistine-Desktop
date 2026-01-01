import os
import sys


def is_running_in_ide():
    """
    Check if the application is running within an IDE (VS Code, PyCharm, etc.)
    or if a debugger is attached.

    :return: True if running in an IDE or debugger, False otherwise.
    """
    # 1. Check for Cursor (Check before VS Code as Cursor is based on VS Code)
    if (
        os.environ.get("TERM_PROGRAM") == "Cursor"
        or "CURSOR_VERSION" in os.environ
        or "CURSOR_PID" in os.environ
    ):
        return "Cursor"

    # 2. Check for VS Code
    if (
        os.environ.get("TERM_PROGRAM") == "vscode"
        or "VSCODE_PID" in os.environ
        or "VSCODE_CWD" in os.environ
    ):
        return "VSCode"

    # 3. Check for PyCharm / JetBrains
    if "PYCHARM_HOSTED" in os.environ or "JETBRAINS_IDE" in os.environ:
        return "JetBrains"

    # 4. Check for general debugger attachment
    if sys.gettrace() is not None:
        return "Debugger"

    return None
