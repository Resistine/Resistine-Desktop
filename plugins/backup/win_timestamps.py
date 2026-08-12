## @file win_timestamps.py
## @namespace plugins.backup
"""Windows-only post-restore timestamp repair.

When restic restores a path like ``C:\\Users\\me\\Documents\\x`` into a target,
it recreates the full path scaffolding (``<target>\\C\\Users\\…``) and faithfully
re-applies each source directory's metadata — including the *real* ``C:\\Users``'s
restrictive ACL and read-only flag. Having just locked the directory down, restic
can no longer set its own timestamp and reports
``failed to restore timestamp … Access is denied`` for those system-scaffolding
dirs. The user's actual files restore with correct timestamps; only these shared
system path components are left with the restore-time mtime.

We own those scaffolding directories (restic created them as us), and an owner
always holds ``WRITE_DAC`` — so we can grant ourselves write access on the DACL
(touching only the DACL avoids needing ``SeSecurityPrivilege``), clear the
read-only flag, and set the correct mtime from the snapshot metadata. No admin
required — the same reason any user can set the mtime of a folder they created.

This module is imported unconditionally but only does anything on Windows; the
pywin32 imports are lazy so non-Windows platforms never touch them.

Author: the Resistine Team
Copyright (c) Resistine 2025
Licensed under the GNU General Public License v2 or later
"""

from __future__ import annotations

import os
import stat

from utils.logger import logger


def _grant_self_full_control(path: str) -> None:
    """Add an ACE granting the current user full control on *path*'s DACL.

    Only the DACL is read and written (``DACL_SECURITY_INFORMATION``), so this
    needs just the owner's implicit ``WRITE_DAC`` right — not the privileged
    ``SeSecurityPrivilege`` that touching the SACL would require.
    """
    import ntsecuritycon
    import win32api
    import win32security

    th = win32security.OpenProcessToken(
        win32api.GetCurrentProcess(), win32security.TOKEN_QUERY)
    user_sid = win32security.GetTokenInformation(
        th, win32security.TokenUser)[0]

    sd = win32security.GetFileSecurity(
        path, win32security.DACL_SECURITY_INFORMATION)
    dacl = sd.GetSecurityDescriptorDacl()
    if dacl is None:
        dacl = win32security.ACL()
    dacl.AddAccessAllowedAce(
        win32security.ACL_REVISION, ntsecuritycon.FILE_ALL_ACCESS, user_sid)
    sd.SetSecurityDescriptorDacl(1, dacl, 0)
    win32security.SetFileSecurity(
        path, win32security.DACL_SECURITY_INFORMATION, sd)


def apply_directory_mtimes(fixes: list[tuple[str, float]]) -> tuple[int, int]:
    """Set the modified time on each directory restic couldn't.

    *fixes* is a list of ``(path, mtime_epoch_seconds)``. For each, grant the
    current user access (DACL), clear read-only, then set the time. Returns
    ``(fixed, failed)``. Safe to call off the UI thread.
    """
    fixed = failed = 0
    for path, mtime in fixes:
        try:
            _grant_self_full_control(path)
            # Clear read-only (now permitted), then stamp the correct mtime.
            os.chmod(path, stat.S_IWRITE)
            os.utime(path, (mtime, mtime))
            fixed += 1
        except Exception as e:
            logger.debug(f"win_timestamps: could not fix {path}: {e}")
            failed += 1
    return fixed, failed
