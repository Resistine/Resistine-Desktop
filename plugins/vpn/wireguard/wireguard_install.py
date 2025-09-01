import subprocess
import os
import platform
import urllib.request
import tempfile
import shutil
import time
import ctypes

WIREGUARD_EXE_CANDIDATES = (
    r"C:\Program Files\WireGuard\wg.exe",
    r"C:\Program Files (x86)\WireGuard\wg.exe",
)

def is_wireguard_installed() -> bool:
    """Return True if wg.exe is in PATH or common install locations."""
    if shutil.which("wg") or shutil.which("wg.exe"):
        return True
    return any(os.path.exists(p) for p in WIREGUARD_EXE_CANDIDATES)

def _wg_path() -> str:
    """Return a resolvable path to wg.exe if available."""
    return shutil.which("wg") or shutil.which("wg.exe") or next((p for p in WIREGUARD_EXE_CANDIDATES if os.path.exists(p)), "")

def _launch_elevated(installer_path: str, params: str = "/S") -> bool:
    """Launch installer with elevation (UAC prompt)."""
    try:
        rc = ctypes.windll.shell32.ShellExecuteW(None, "runas", installer_path, params, None, 1)
        if rc <= 32:
            raise OSError(f"ShellExecute failed with code {rc}")
        return True
    except Exception as e:
        print(f"Failed to launch installer elevated: {e}")
        return False

def install_wireguard_windows(timeout_seconds: int = 180) -> bool:
    wireguard_installer_url = "https://download.wireguard.com/windows-client/wireguard-installer.exe"
    installer_path = os.path.join(tempfile.gettempdir(), "wireguard-installer.exe")

    print(f"Downloading WireGuard installer to {installer_path}...")
    urllib.request.urlretrieve(wireguard_installer_url, installer_path)
    print("Launching WireGuard installer (UAC prompt expected)...")
    if not _launch_elevated(installer_path):
        # Fallback: launch without elevation (will likely fail to install drivers)
        os.startfile(installer_path)

    # Wait for installation to complete or timeout
    start = time.time()
    while time.time() - start < timeout_seconds:
        if is_wireguard_installed():
            return True
        time.sleep(3)
    return False

def check_wireguard_installed():
    """Ensure WireGuard is present; install on Windows if missing."""
    if platform.system() != "Windows":
        # Non-Windows: only report status
        if is_wireguard_installed():
            exe = _wg_path() or "wg"
            try:
                out = subprocess.run([exe, "--version"], capture_output=True, text=True)
                print((out.stdout or out.stderr).strip() or "WireGuard is already installed.")
            except Exception:
                print("WireGuard appears installed.")
        else:
            print("WireGuard not detected on this platform.")
        return

    try:
        if is_wireguard_installed():
            exe = _wg_path() or "wg"
            try:
                out = subprocess.run([exe, "--version"], capture_output=True, text=True)
                print((out.stdout or out.stderr).strip() or "WireGuard is already installed.")
            except Exception:
                print("WireGuard is already installed.")
            return

        print("WireGuard is not installed. Installing now...")
        ok = install_wireguard_windows()
        if ok and is_wireguard_installed():
            print("WireGuard installation completed.")
        else:
            print("WireGuard installation may have been cancelled or failed. Please install manually.")
    except Exception as e:
        print(f"WireGuard check/install error: {e}")
