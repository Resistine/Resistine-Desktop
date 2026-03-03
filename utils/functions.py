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


def get_resource_path(relative_path: str) -> str:
    """
    Get absolute path to resource, works for both dev and PyInstaller bundled app.

    When running from source, returns path relative to the project root.
    When running from a PyInstaller bundle, returns path relative to the
    temporary extraction directory (sys._MEIPASS).
    """
    if hasattr(sys, '_MEIPASS'):
        # Running in PyInstaller bundle
        return os.path.join(sys._MEIPASS, relative_path)
    else:
        # Running from source - assume we are in utils/ and the root is one level up
        # However, for consistency with main.py, let's make it smarter or relative to the actual project root.
        # If we invoke it from anywhere, we want the project root.
        # Let's use the directory of this file as a reference.
        root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        return os.path.join(root, relative_path)
