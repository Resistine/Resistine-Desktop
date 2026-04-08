"""
macOS Uninstaller Backend.

Performs full cleanup in three phases:

Phase 1 — Non-privileged work (no admin prompt):
  - Unregister ClamAV daemons via SMAppService
  - Stop VPN tunnel
  - Deactivate system extension (waits up to 15s)
  - Remove keychain items
  - Remove WireGuard config files
  - Remove user-level app config

Phase 2 — Privileged work (single admin prompt):
  - Stop/remove Wazuh agent (fallback path)
  - Kill and clean up ClamAV daemons/plists/data
  - Remove system-level app config
  - Remove Wazuh key backup

Phase 3 — App bundle removal (privileged if needed):
  - Remove the .app bundle from /Applications (admin rm -rf)

Author: Resistine Team
Copyright (c) Resistine 2025
Licensed under the GNU General Public License v2 or later
"""

import os
import shutil
import subprocess
import sys

from utils.logger import logger

_EXTENSION_BUNDLE_ID = "com.resistine.desktop.network-extension"


def is_available():
    """Uninstall is always available on macOS."""
    return True


def run_uninstall(app, progress_callback=None):
    """Execute the full macOS uninstall sequence.

    Collects all commands that need admin privileges and runs them in a
    single ``osascript`` call so the user only sees one password prompt.
    """

    def _progress(msg):
        logger.info(f"[UNINSTALL] {msg}")
        if progress_callback:
            try:
                progress_callback(msg)
            except Exception as e:
                logger.debug(f"[UNINSTALL] Progress callback failed: {e}")

    errors = []
    admin_cmds = []  # Shell commands that require admin privileges

    # -- Phase 1: Non-privileged work + collect admin commands ---------------

    # Wazuh — plugin path triggers its own admin prompt (unavoidable);
    # fallback path adds commands to admin_cmds instead.
    _progress("Removing SIEM agent...")
    try:
        _remove_wazuh_agent(admin_cmds)
    except Exception as e:
        logger.error(f"[UNINSTALL] Failed — SIEM agent: {e}")
        errors.append(f"SIEM agent: {e}")

    # ClamAV — SMAppService (no admin), then collect admin commands
    _progress("Stopping ClamAV daemons...")
    try:
        _remove_clamav_daemons(admin_cmds)
    except Exception as e:
        logger.error(f"[UNINSTALL] Failed — ClamAV daemons: {e}")
        errors.append(f"ClamAV daemons: {e}")

    # Non-privileged steps
    non_privileged_steps = [
        ("Stopping VPN tunnel...",             "VPN stop",
         _stop_vpn_tunnel),
        ("Deactivating system extension...",   "Extension deactivation",
         _deactivate_system_extension),
        ("Removing keychain items...",         "Keychain",
         _remove_keychain_items),
        ("Removing VPN configurations...",     "WG configs",
         _remove_wireguard_configs),
    ]
    for message, label, func in non_privileged_steps:
        _progress(message)
        try:
            func()
        except Exception as e:
            logger.error(f"[UNINSTALL] Failed — {label}: {e}")
            errors.append(f"{label}: {e}")

    # App config — user-level (no admin), system-level (admin)
    _progress("Removing application data...")
    try:
        _remove_app_config(admin_cmds)
    except Exception as e:
        logger.error(f"[UNINSTALL] Failed — App config: {e}")
        errors.append(f"App config: {e}")

    # -- Phase 2: Run all privileged commands in one admin prompt -------------

    if admin_cmds:
        _progress("Running privileged cleanup...")
        try:
            _run_privileged(admin_cmds)
        except Exception as e:
            logger.error(f"[UNINSTALL] Failed — Privileged cleanup: {e}")
            errors.append(f"Privileged cleanup: {e}")

    # -- Phase 3: Remove app bundle (may need its own admin prompt) ----------
    _progress("Removing application...")
    try:
        _remove_app_bundle()
    except Exception as e:
        logger.error(f"[UNINSTALL] Failed — App bundle: {e}")
        errors.append(f"App bundle: {e}")

    if errors:
        return (False, f"Completed with errors: {'; '.join(errors)}")
    return (True, "Resistine has been uninstalled successfully.")


# ---------------------------------------------------------------------------
# Privileged command runner
# ---------------------------------------------------------------------------


def _run_privileged(cmds):
    """Run a list of shell commands in a single admin osascript prompt."""
    script = "; ".join(cmds)
    escaped = script.replace("\\", "\\\\").replace('"', '\\"')
    cmd = [
        "osascript", "-e",
        f'do shell script "{escaped}" with administrator privileges',
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
    if result.returncode == 0:
        logger.info("[UNINSTALL] Privileged cleanup completed")
    else:
        raise OSError(
            f"Privileged cleanup failed: {result.stderr.strip()}"
        )


# ---------------------------------------------------------------------------
# Cleanup helpers
# ---------------------------------------------------------------------------


def _remove_clamav_daemons(admin_cmds):
    """Unregister ClamAV daemons and collect admin commands for cleanup."""
    _SYSTEM_CLAMAV_DIR = "/Library/Application Support/Resistine/clamav"

    # 1. SMAppService unregistration (no admin needed)
    _smappservice_plist_names = [
        "com.resistine.desktop.clamonacc.plist",
        "com.resistine.desktop.clamd.plist",
    ]
    try:
        from ServiceManagement import SMAppService

        for plist_name in _smappservice_plist_names:
            try:
                service = SMAppService.daemonServiceWithPlistName_(plist_name)
                status = int(service.status())
                if status in (1, 2):  # enabled or requiresApproval
                    success, err = service.unregisterAndReturnError_(None)
                    if not success:
                        logger.warning(
                            f"[UNINSTALL] SMAppService unregister error "
                            f"({plist_name}): {err}",
                        )
                    else:
                        logger.info(
                            f"[UNINSTALL] Unregistered {plist_name} via SMAppService",
                        )
            except Exception as e:
                logger.warning(
                    f"[UNINSTALL] SMAppService unregister failed ({plist_name}): {e}",
                )
    except ImportError:
        logger.debug("[UNINSTALL] ServiceManagement not available")

    # 2. Collect admin commands for legacy plist cleanup + process kill + data
    legacy_plists = [
        "/Library/LaunchDaemons/com.resistine.clamonacc.plist",
        "/Library/LaunchDaemons/com.resistine.clamd.plist",
        "/Library/LaunchDaemons/com.resistine.desktop.clamonacc.plist",
        "/Library/LaunchDaemons/com.resistine.desktop.clamd.plist",
    ]
    for plist in legacy_plists:
        if os.path.exists(plist):
            admin_cmds.append(f"launchctl bootout system '{plist}' 2>/dev/null || true")
            admin_cmds.append(f"rm -f '{plist}'")

    # Bootout by label in case plists are gone but daemons still loaded
    for label in (
        "com.resistine.desktop.clamd",
        "com.resistine.desktop.clamonacc",
    ):
        admin_cmds.append(
            f"launchctl bootout system/{label} 2>/dev/null || true",
        )

    # Kill running ClamAV processes (root-owned, needs admin)
    admin_cmds.append("pkill -x clamonacc 2>/dev/null || true")
    admin_cmds.append("pkill -x clamd 2>/dev/null || true")

    # Remove system-level ClamAV data (signatures, configs, logs)
    if os.path.exists(_SYSTEM_CLAMAV_DIR):
        admin_cmds.append(f"rm -rf '{_SYSTEM_CLAMAV_DIR}'")


def _remove_wazuh_agent(admin_cmds):
    """Stop and remove the Wazuh SIEM agent if installed.

    When the Wazuh plugin is available, delegates to its ``remove_agent()``
    (which triggers its own admin prompt — unavoidable).  The key backup
    deletion is added to ``admin_cmds`` so it runs in the batched prompt.

    When the plugin is unavailable, all commands go into ``admin_cmds``.
    """
    try:
        from plugins.wazuh.agent.wazuh_functions_darwin import (
            _KEY_BACKUP,
            remove_agent,
        )
        remove_agent()
        # Batch key backup deletion with the other admin commands
        if os.path.exists(_KEY_BACKUP):
            escaped = _KEY_BACKUP.replace("'", "'\\''")
            admin_cmds.append(f"rm -f '{escaped}'")
        return
    except ImportError:
        logger.info("[UNINSTALL] Wazuh plugin not available, using inline removal")

    # Fallback: collect inline removal commands
    wazuh_control = "/Library/Ossec/bin/wazuh-control"
    wazuh_plist = "/Library/LaunchDaemons/com.wazuh.agent.plist"
    ossec_dir = "/Library/Ossec"
    key_backup = "/Library/Application Support/Resistine/wazuh_client.keys"

    if not os.path.exists(ossec_dir) and not os.path.exists(wazuh_plist):
        logger.info("[UNINSTALL] Wazuh agent not installed, skipping")
        return

    admin_cmds.append(f"'{wazuh_control}' stop 2>/dev/null || true")
    admin_cmds.append(
        f"launchctl bootout system '{wazuh_plist}' 2>/dev/null || true",
    )
    admin_cmds.append(f"rm -rf '{ossec_dir}'")
    admin_cmds.append(f"rm -f '{wazuh_plist}'")
    admin_cmds.append(f"rm -f '{key_backup}'")


def _stop_vpn_tunnel():
    """Stop the VPN tunnel via the CLI tool."""
    cli_path = _find_cli_path()
    if not cli_path:
        logger.info("[UNINSTALL] CLI not found, skipping VPN stop")
        return

    result = subprocess.run(
        [cli_path, "stop"],
        capture_output=True,
        text=True,
        timeout=10,
    )
    if result.returncode == 0:
        logger.info("[UNINSTALL] VPN tunnel stopped")
    else:
        logger.warning(
            f"[UNINSTALL] VPN stop returned non-zero "
            f"(may already be stopped): {result.stderr.strip()}"
        )


def _deactivate_system_extension():
    """Deactivate the network extension via SystemExtensions framework.

    Blocks up to 15 seconds for the delegate callback, so the uninstall
    doesn't remove the app bundle while deactivation is still in flight.
    """
    try:
        from Foundation import NSObject, NSOperationQueue
        from SystemExtensions import (
            OSSystemExtensionManager,
            OSSystemExtensionRequest,
        )
    except ImportError:
        logger.info("[UNINSTALL] SystemExtensions not available (dev mode)")
        return

    import threading
    done_event = threading.Event()
    deactivation_error = []

    class _Deactivator(NSObject):
        def request_didFinishWithResult_(self, request, result):
            logger.info(f"[UNINSTALL] Extension deactivation finished: {result}")
            done_event.set()

        def request_didFailWithError_(self, request, error):
            msg = error.localizedDescription()
            logger.error(f"[UNINSTALL] Extension deactivation failed: {msg}")
            deactivation_error.append(msg)
            done_event.set()

        def requestNeedsUserApproval_(self, request):
            logger.info("[UNINSTALL] Extension deactivation needs user approval")

        def request_actionForReplacingExtension_withExtension_(
            self, request, existing, extension
        ):
            return 1  # Replace

    try:
        deactivator = _Deactivator.alloc().init()
        queue = NSOperationQueue.mainQueue().underlyingQueue()
        request = (
            OSSystemExtensionRequest.deactivationRequestForExtension_queue_(
                _EXTENSION_BUNDLE_ID, queue
            )
        )
        request.setDelegate_(deactivator)
        OSSystemExtensionManager.sharedManager().submitRequest_(request)

        # Store reference to prevent GC
        _deactivate_system_extension._ref = deactivator
        logger.info("[UNINSTALL] Extension deactivation request submitted")

        if not done_event.wait(timeout=15):
            logger.warning(
                "[UNINSTALL] Extension deactivation timed out after 15s "
                "— continuing anyway"
            )
        elif deactivation_error:
            raise OSError(
                f"Extension deactivation failed: {deactivation_error[0]}"
            )
    except OSError:
        raise
    except Exception as e:
        raise OSError(f"Extension deactivation error: {e}") from e


def _remove_wireguard_configs():
    """Remove WireGuard configuration files.

    macOS SIP protects the Group Container directory itself — even admin
    ``rm -rf`` cannot delete it.  We remove the *contents* instead and
    tolerate the empty directory remaining (the OS cleans it up when the
    app is fully removed).
    """
    wg_dir = os.path.expanduser(
        "~/Library/Group Containers/group.Resistine.WireguardTest"
    )
    if not os.path.exists(wg_dir):
        logger.info("[UNINSTALL] WireGuard config dir not found, skipping")
        return

    # Remove contents, not the container directory itself
    try:
        entries = os.listdir(wg_dir)
    except PermissionError:
        logger.info(
            f"[UNINSTALL] Cannot access {wg_dir} (SIP-protected) — "
            f"macOS will clean it up when the app is removed"
        )
        return
    if not entries:
        logger.info("[UNINSTALL] WireGuard config dir already empty")
        return

    removed = 0
    failed = []
    for entry in entries:
        entry_path = os.path.join(wg_dir, entry)
        try:
            if os.path.isdir(entry_path):
                shutil.rmtree(entry_path)
            else:
                os.remove(entry_path)
            removed += 1
        except OSError as e:
            logger.warning(f"[UNINSTALL] Could not remove {entry_path}: {e}")
            failed.append(entry_path)

    # Try to remove the now-empty directory (may fail due to SIP — that's OK)
    try:
        os.rmdir(wg_dir)
        logger.info(f"[UNINSTALL] Removed {wg_dir} ({removed} item(s))")
    except OSError:
        logger.info(
            f"[UNINSTALL] Cleared {removed} item(s) from {wg_dir} "
            f"(directory kept by macOS)"
        )

    if failed and removed == 0:
        raise OSError(
            f"Failed to remove any WireGuard config files "
            f"({len(failed)} failures)"
        )


def _remove_app_config(admin_cmds):
    """Remove application configuration directories (user + system level)."""
    # User-level config (no admin needed)
    config_dir = os.path.expanduser("~/Library/Application Support/Resistine")
    if os.path.exists(config_dir):
        shutil.rmtree(config_dir)
        logger.info(f"[UNINSTALL] Removed {config_dir}")
    else:
        logger.info("[UNINSTALL] User config dir not found, skipping")

    # System-level directory — batch with other admin commands
    sys_dir = "/Library/Application Support/Resistine"
    if os.path.exists(sys_dir):
        admin_cmds.append(f"rm -rf '{sys_dir}'")


def _remove_keychain_items():
    """Remove keychain entries created by Resistine."""
    try:
        import keyring
    except ImportError:
        logger.info("[UNINSTALL] keyring not available, skipping")
        return

    entries = [
        ("resistine-master-key", "master-key"),
    ]

    failed = []
    for service, username in entries:
        try:
            keyring.delete_password(service, username)
            logger.info(f"[UNINSTALL] Removed keychain: {service}/{username}")
        except keyring.errors.PasswordDeleteError:
            logger.info(f"[UNINSTALL] Keychain entry not found: {service}/{username}")
        except Exception as e:
            logger.error(f"[UNINSTALL] Keychain removal failed: {service}: {e}")
            failed.append(f"{service}: {e}")

    if failed:
        raise OSError(
            f"Keychain removal failed: {'; '.join(failed)}"
        )


def _remove_app_bundle():
    """Remove the Resistine.app bundle.

    The bundle in /Applications is typically root-owned, so we use an
    admin ``osascript`` prompt.  macOS allows deleting files that are in
    use — the kernel keeps the data until the last file descriptor closes,
    so the running process won't crash.
    """
    if not getattr(sys, "frozen", False):
        logger.info("[UNINSTALL] Not a frozen app, skipping bundle removal")
        return

    # sys.executable → .../Resistine.app/Contents/MacOS/Resistine
    from pathlib import Path
    app_bundle = str(Path(sys.executable).parents[2])

    if not app_bundle.endswith(".app"):
        logger.warning(f"[UNINSTALL] Unexpected bundle path: {app_bundle}")
        return

    if not os.path.exists(app_bundle):
        logger.info("[UNINSTALL] App bundle not found")
        return

    escaped = app_bundle.replace("'", "'\\''")

    # Try non-privileged first (works if user-owned)
    try:
        shutil.rmtree(app_bundle)
        logger.info(f"[UNINSTALL] Removed {app_bundle}")
        return
    except PermissionError:
        logger.debug("[UNINSTALL] App bundle requires admin to remove")

    # Fall back to admin removal
    cmd = [
        "osascript", "-e",
        f"do shell script \"rm -rf '{escaped}'\" "
        f"with administrator privileges",
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
    if result.returncode == 0:
        logger.info(f"[UNINSTALL] Removed {app_bundle} (admin)")
    else:
        raise OSError(
            f"App bundle removal failed: {result.stderr.strip()}"
        )


def _find_cli_path():
    """Find the resistine-vpn-cli binary."""
    if not getattr(sys, "frozen", False):
        return None

    macos_dir = os.path.dirname(sys.executable)
    cli_path = os.path.join(macos_dir, "resistine-vpn-cli")
    if os.path.exists(cli_path):
        return cli_path
    return None
