import os, sys

def resource_path(relative_path: str) -> str:
    """
    Return absolute path to resource bundled by PyInstaller.
    Works in dev and in --onefile builds.
    """
    base_path = getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))
    # When called from code outside utils, go one level up so relative paths match project root
    project_root = os.path.abspath(os.path.join(base_path, "." if "_MEIPASS" in dir(sys) else ".."))
    return os.path.normpath(os.path.join(project_root, relative_path))