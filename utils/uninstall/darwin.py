"""
macOS Uninstaller Backend.

Performs full cleanup in order:
0. Stop and remove Wazuh SIEM agent (if installed)
1. Stop VPN tunnel (if running)
2. Deactivate the system extension
3. Remove keychain items
4. Remove app bundle from /Applications
5. Remove WireGuard config files        (late — prevents recreation by running code)
6. Remove app config directory           (late — prevents recreation by settings module)
7. Quit the application

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
    """Execute the full macOS uninstall sequence."""

    def _progress(msg):
        logger.info(f"[UNINSTALL] {msg}")
        if progress_callback:
            try:
                progress_callback(msg)
            except Exception:
                pass

    # Steps run in order; later steps are deliberately last to prevent
    # recreation by code/settings modules still running.
    steps = [
        ("Removing SIEM agent...",         "SIEM agent",            _remove_wazuh_agent),
        ("Stopping VPN tunnel...",         "VPN stop",              _stop_vpn_tunnel),
        ("Deactivating system extension...","Extension deactivation",_deactivate_system_extension),
        ("Removing keychain items...",     "Keychain",              _remove_keychain_items),
        ("Removing application...",        "App bundle",            _remove_app_bundle),
        ("Removing VPN configurations...", "WG configs",            _remove_wireguard_configs),
        ("Removing application data...",   "App config",            _remove_app_config),
    ]

    errors = []
    for message, label, func in steps:
        _progress(message)
        try:
            func()
        except Exception as e:
            logger.error(f"[UNINSTALL] Failed — {label}: {e}")
            errors.append(f"{label}: {e}")

    if errors:
        return (False, f"Completed with errors: {'; '.join(errors)}")
    return (True, "Resistine has been uninstalled successfully.")


# ---------------------------------------------------------------------------
# Cleanup helpers
# ---------------------------------------------------------------------------


def _delete_key_backup(path):
    """Remove the Wazuh client.keys backup file if it exists."""
    try:
        escaped = path.replace("\\", "\\\\").replace('"', '\\"')
        cmd = [
            "osascript", "-e",
            f'do shell script "rm -f \\"{escaped}\\"" with administrator privileges',
        ]
        subprocess.run(cmd, capture_output=True, timeout=15)
        logger.info(f"[UNINSTALL] Removed Wazuh key backup: {path}")
    except Exception as e:
        logger.warning(f"[UNINSTALL] Could not remove key backup: {e}")


def _remove_wazuh_agent():
    """Stop and remove the Wazuh SIEM agent if installed.

    Delegates to the Wazuh plugin's ``remove_agent()`` when available.
    Falls back to an inline script if the plugin module cannot be imported
    (e.g. the plugin was already uninstalled).

    Also removes the client.keys backup — on full uninstall we want a clean
    slate, not a preserved key for a future reinstall.
    """
    try:
        from plugins.wazuh.agent.wazuh_functions_darwin import (
            _KEY_BACKUP,
            remove_agent,
        )
        remove_agent()
        # Delete the key backup so a future install enrolls fresh.
        _delete_key_backup(_KEY_BACKUP)
        return
    except ImportError:
        logger.info("[UNINSTALL] Wazuh plugin not available, using inline removal")

    # Fallback: inline removal when the plugin module is missing
    wazuh_control = "/Library/Ossec/bin/wazuh-control"
    wazuh_plist = "/Library/LaunchDaemons/com.wazuh.agent.plist"
    ossec_dir = "/Library/Ossec"
    key_backup = "/Library/Application Support/Resistine/wazuh_client.keys"

    if not os.path.exists(ossec_dir) and not os.path.exists(wazuh_plist):
        logger.info("[UNINSTALL] Wazuh agent not installed, skipping")
        return

    script = (
        f"'{wazuh_control}' stop 2>/dev/null; "
        f"launchctl bootout system '{wazuh_plist}' 2>/dev/null; "
        f"rm -rf '{ossec_dir}'; "
        f"rm -f '{wazuh_plist}'; "
        f"rm -f '{key_backup}'"
    )
    escaped = script.replace("\\", "\\\\").replace('"', '\\"')
    cmd = [
        "osascript", "-e",
        f'do shell script "{escaped}" with administrator privileges',
    ]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
        if result.returncode == 0:
            logger.info("[UNINSTALL] Wazuh agent removed successfully")
        else:
            logger.warning(f"[UNINSTALL] Wazuh removal returned non-zero: {result.stderr}")
    except subprocess.TimeoutExpired:
        logger.warning("[UNINSTALL] Wazuh removal timed out")
    except Exception as e:
        logger.error(f"[UNINSTALL] Wazuh removal error: {e}")


def _stop_vpn_tunnel():
    """Stop the VPN tunnel via the CLI tool."""
    cli_path = _find_cli_path()
    if not cli_path:
        logger.info("[UNINSTALL] CLI not found, skipping VPN stop")
        return

    try:
        subprocess.run(
            [cli_path, "stop"],
            capture_output=True,
            timeout=10,
        )
        logger.info("[UNINSTALL] VPN tunnel stop command sent")
    except subprocess.TimeoutExpired:
        logger.warning("[UNINSTALL] VPN stop timed out")
    except FileNotFoundError:
        logger.info("[UNINSTALL] CLI binary not found")


def _deactivate_system_extension():
    """Deactivate the network extension via SystemExtensions framework."""
    try:
        from Foundation import NSObject, NSOperationQueue
        from SystemExtensions import (
            OSSystemExtensionManager,
            OSSystemExtensionRequest,
        )

        class _Deactivator(NSObject):
            def request_didFinishWithResult_(self, request, result):
                logger.info(f"[UNINSTALL] Extension deactivation finished: {result}")

            def request_didFailWithError_(self, request, error):
                logger.error(
                    f"[UNINSTALL] Extension deactivation failed: "
                    f"{error.localizedDescription()}"
                )

            def requestNeedsUserApproval_(self, request):
                logger.info("[UNINSTALL] Extension deactivation needs user approval")

            def request_actionForReplacingExtension_withExtension_(
                self, request, existing, extension
            ):
                return 1  # Replace

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
    except ImportError:
        logger.info("[UNINSTALL] SystemExtensions not available (dev mode)")
    except Exception as e:
        logger.error(f"[UNINSTALL] Extension deactivation error: {e}")


def _remove_wireguard_configs():
    """Remove WireGuard configuration directory.

    Group Containers are sandbox-protected on macOS, so ``shutil.rmtree``
    often fails with *Operation not permitted*.  We try ``rm -rf`` first
    and fall back to an admin-privileged removal via ``osascript``.
    """
    wg_dir = os.path.expanduser(
        "~/Library/Group Containers/group.Resistine.WireguardTest"
    )
    if not os.path.exists(wg_dir):
        logger.info("[UNINSTALL] WireGuard config dir not found, skipping")
        return

    # Try unprivileged removal first
    try:
        shutil.rmtree(wg_dir)
        logger.info(f"[UNINSTALL] Removed {wg_dir}")
        return
    except OSError:
        logger.info("[UNINSTALL] shutil.rmtree failed, trying rm -rf")

    # Try rm -rf (handles some sandbox cases shutil cannot)
    subprocess.run(["rm", "-rf", wg_dir], capture_output=True, text=True)
    if not os.path.exists(wg_dir):
        logger.info(f"[UNINSTALL] Removed {wg_dir} via rm -rf")
        return

    # Fall back to admin-privileged removal
    logger.info("[UNINSTALL] rm -rf failed, requesting admin privileges")
    script = f"rm -rf '{wg_dir}'"
    escaped = script.replace("\\", "\\\\").replace('"', '\\"')
    cmd = [
        "osascript", "-e",
        f'do shell script "{escaped}" with administrator privileges',
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
    if result.returncode == 0:
        logger.info(f"[UNINSTALL] Removed {wg_dir} with admin privileges")
    else:
        raise OSError(
            f"Failed to remove WireGuard configs: {result.stderr.strip()}"
        )


def _remove_app_config():
    """Remove the application configuration directory."""
    config_dir = os.path.expanduser("~/Library/Application Support/Resistine")
    if os.path.exists(config_dir):
        shutil.rmtree(config_dir)
        logger.info(f"[UNINSTALL] Removed {config_dir}")
    else:
        logger.info("[UNINSTALL] App config dir not found, skipping")


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

    for service, username in entries:
        try:
            keyring.delete_password(service, username)
            logger.info(f"[UNINSTALL] Removed keychain: {service}/{username}")
        except keyring.errors.PasswordDeleteError:
            logger.info(f"[UNINSTALL] Keychain entry not found: {service}/{username}")
        except Exception as e:
            logger.warning(f"[UNINSTALL] Keychain removal failed: {service}: {e}")


def _remove_app_bundle():
    """Remove the Resistine.app bundle."""
    if not getattr(sys, "frozen", False):
        logger.info("[UNINSTALL] Not a frozen app, skipping bundle removal")
        return

    # sys.executable → .../Resistine.app/Contents/MacOS/Resistine
    from pathlib import Path
    app_bundle = str(Path(sys.executable).parents[2])

    if not app_bundle.endswith(".app"):
        logger.warning(f"[UNINSTALL] Unexpected bundle path: {app_bundle}")
        return

    if os.path.exists(app_bundle):
        shutil.rmtree(app_bundle)
        logger.info(f"[UNINSTALL] Removed {app_bundle}")
    else:
        logger.info("[UNINSTALL] App bundle not found")


def _find_cli_path():
    """Find the resistine-vpn-cli binary."""
    if not getattr(sys, "frozen", False):
        return None

    macos_dir = os.path.dirname(sys.executable)
    cli_path = os.path.join(macos_dir, "resistine-vpn-cli")
    if os.path.exists(cli_path):
        return cli_path
    return None
