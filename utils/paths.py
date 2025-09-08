import os, sys, platform

''''
def resource_path(relative_path: str) -> str:
    """
    Return absolute path to resource bundled by PyInstaller.
    Works in dev and in --onefile builds.
    """
    base_path = getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))
    # When called from code outside utils, go one level up so relative paths match project root
    project_root = os.path.abspath(os.path.join(base_path, "." if "_MEIPASS" in dir(sys) else ".."))
    return os.path.normpath(os.path.join(project_root, relative_path))
'''
def resource_path(*parts):
    """Path to packaged read-only resources (MEIPASS when frozen)."""
    if getattr(sys, 'frozen', False):
        base = sys._MEIPASS  # noqa
    else:
        base = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(base, *parts)

def user_data_dir():
    """Writable, persistent per-user data dir."""
    if platform.system() == "Windows":
        root = os.environ.get("APPDATA", os.path.expanduser("~"))
        return os.path.join(root, "Resistine AI")
    elif platform.system() == "Darwin":
        return os.path.join(os.path.expanduser("~"), "Library", "Application Support", "Resistine AI")
    else:
        return os.path.join(os.path.expanduser("~"), ".config", "resistine-ai")

def user_resource_dir(subdir):
    """Create/get a subdir under the user data dir."""
    p = os.path.join(user_data_dir(), subdir)
    os.makedirs(p, exist_ok=True)
    return p