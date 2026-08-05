## @file restic_installer.py
## @namespace plugins.backup
"""Cross-platform Restic binary installer.

Restic publishes a single self-contained binary per platform on GitHub
Releases: ``restic_<ver>_<os>_<arch>.bz2`` for Linux/macOS and
``restic_<ver>_windows_<arch>.zip`` for Windows, alongside a signed
``SHA256SUMS`` manifest. This module resolves the right asset for the current
host, downloads it, **verifies its SHA-256** against the manifest, unpacks it,
and drops the executable into the per-user bin dir where ``ResticService``
already looks.

No Qt here — the plugin owns threading and progress display. ``install`` takes
an optional ``on_progress(fraction, message)`` callback.

Author: the Resistine Team
Copyright (c) Resistine 2025
Licensed under the GNU General Public License v2 or later
"""

from __future__ import annotations

import bz2
import hashlib
import io
import os
import platform
import stat
import zipfile
from typing import Callable, Optional

import requests

from utils.logger import logger
from utils.settings import get_config_dir

_LATEST_API = "https://api.github.com/repos/restic/restic/releases/latest"
_IS_WINDOWS = platform.system() == "Windows"

ProgressCb = Callable[[float, str], None]


def _user_bin_dir() -> str:
    return os.path.join(get_config_dir(), "bin")


def _os_token() -> Optional[str]:
    return {"Windows": "windows", "Darwin": "darwin",
            "Linux": "linux"}.get(platform.system())


def _arch_token() -> Optional[str]:
    m = platform.machine().lower()
    if m in ("amd64", "x86_64", "x64"):
        return "amd64"
    if m in ("arm64", "aarch64"):
        return "arm64"
    if m in ("i386", "i686", "x86"):
        return "386"
    if m.startswith("arm"):
        return "arm"
    return None


def _report(cb: Optional[ProgressCb], frac: float, msg: str) -> None:
    if cb is not None:
        try:
            cb(frac, msg)
        except Exception as e:  # a UI callback must never abort the install
            logger.error(f"restic installer progress callback error: {e}")


def is_supported_platform() -> bool:
    return _os_token() is not None and _arch_token() is not None


def install(on_progress: Optional[ProgressCb] = None,
            *, timeout: int = 60) -> tuple[bool, str]:
    """Download, verify and install restic for the current host.

    Returns ``(ok, message)``. On success the message is the installed path.
    Safe to call off the UI thread.
    """
    os_tok, arch_tok = _os_token(), _arch_token()
    if not os_tok or not arch_tok:
        return False, (f"Unsupported platform: {platform.system()} "
                       f"/ {platform.machine()}")

    try:
        _report(on_progress, 0.02, "Finding the latest Restic release…")
        rel = requests.get(_LATEST_API, timeout=timeout,
                           headers={"Accept": "application/vnd.github+json"})
        rel.raise_for_status()
        data = rel.json()
        version = data.get("tag_name", "").lstrip("v")
        if not version:
            return False, "Could not determine the latest Restic version."

        ext = "zip" if _IS_WINDOWS else "bz2"
        asset_name = f"restic_{version}_{os_tok}_{arch_tok}.{ext}"
        assets = {a["name"]: a["browser_download_url"]
                  for a in data.get("assets", [])}
        if asset_name not in assets:
            return False, f"No Restic build published for this host ({asset_name})."
        sums_url = assets.get("SHA256SUMS")

        # --- download the binary asset ------------------------------------
        _report(on_progress, 0.1, f"Downloading Restic {version}…")
        blob = _download(assets[asset_name], on_progress, lo=0.1, hi=0.8,
                         timeout=timeout)

        # --- verify SHA-256 against the published manifest ----------------
        if sums_url:
            _report(on_progress, 0.82, "Verifying checksum…")
            expected = _sha_for(sums_url, asset_name, timeout=timeout)
            if expected:
                actual = hashlib.sha256(blob).hexdigest()
                if actual.lower() != expected.lower():
                    return False, ("Checksum mismatch — refusing to install a "
                                   "possibly corrupted or tampered binary.")
            else:
                logger.warning("restic installer: asset not found in SHA256SUMS; "
                               "proceeding without verification")
        else:
            logger.warning("restic installer: no SHA256SUMS asset; "
                           "proceeding without verification")

        # --- unpack -------------------------------------------------------
        _report(on_progress, 0.9, "Unpacking…")
        binary = _unpack(blob, is_zip=_IS_WINDOWS)

        # --- place + mark executable --------------------------------------
        dest_dir = _user_bin_dir()
        os.makedirs(dest_dir, exist_ok=True)
        dest = os.path.join(dest_dir, "restic.exe" if _IS_WINDOWS else "restic")
        with open(dest, "wb") as f:
            f.write(binary)
        if not _IS_WINDOWS:
            os.chmod(dest, os.stat(dest).st_mode | stat.S_IEXEC | stat.S_IXGRP
                     | stat.S_IXOTH)

        _report(on_progress, 1.0, "Restic installed.")
        logger.info(f"restic installer: installed {version} at {dest}")
        return True, dest

    except requests.RequestException as e:
        logger.error(f"restic installer download failed: {e}")
        return False, f"Download failed: {e}"
    except Exception as e:
        logger.error(f"restic installer error: {e}")
        return False, f"Installation error: {e}"


def _download(url: str, cb: Optional[ProgressCb], *, lo: float, hi: float,
              timeout: int) -> bytes:
    """Stream ``url`` into memory, mapping download progress to [lo, hi]."""
    with requests.get(url, stream=True, timeout=timeout) as r:
        r.raise_for_status()
        total = int(r.headers.get("Content-Length", 0))
        buf = io.BytesIO()
        got = 0
        for chunk in r.iter_content(chunk_size=64 * 1024):
            if not chunk:
                continue
            buf.write(chunk)
            got += len(chunk)
            if total:
                _report(cb, lo + (hi - lo) * (got / total),
                        f"Downloading… {got // 1024}/{total // 1024} KB")
        return buf.getvalue()


def _sha_for(sums_url: str, asset_name: str, *, timeout: int) -> Optional[str]:
    """Fetch SHA256SUMS and return the hex digest listed for ``asset_name``."""
    r = requests.get(sums_url, timeout=timeout)
    r.raise_for_status()
    for line in r.text.splitlines():
        parts = line.split()
        if len(parts) == 2 and parts[1].lstrip("*") == asset_name:
            return parts[0]
    return None


def _unpack(blob: bytes, *, is_zip: bool) -> bytes:
    """Return the raw restic executable bytes from a .zip or .bz2 asset."""
    if is_zip:
        with zipfile.ZipFile(io.BytesIO(blob)) as z:
            # The Windows archive contains a single restic_*.exe.
            exe = next((n for n in z.namelist() if n.lower().endswith(".exe")),
                       None)
            if not exe:
                raise ValueError("no .exe inside the Restic zip")
            return z.read(exe)
    return bz2.decompress(blob)
