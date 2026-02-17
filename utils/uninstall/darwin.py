"""
macOS Uninstaller Backend.

Performs full cleanup in order:
1. Stop VPN tunnel (if running)
2. Deactivate the system extension
3. Remove WireGuard config files
4. Remove app config directory
5. Remove keychain items
6. Remove app bundle from /Applications
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

    errors = []

    # --- Step 1: Stop VPN tunnel ---
    _progress("Stopping VPN tunnel...")
    try:
        _stop_vpn_tunnel()
    except Exception as e:
        logger.error(f"[UNINSTALL] Failed to stop VPN: {e}")
        errors.append(f"VPN stop: {e}")

    # --- Step 2: Deactivate system extension ---
    _progress("Deactivating system extension...")
    try:
        _deactivate_system_extension()
    except Exception as e:
        logger.error(f"[UNINSTALL] Failed to deactivate extension: {e}")
        errors.append(f"Extension deactivation: {e}")

    # --- Step 3: Remove WireGuard configs ---
    _progress("Removing VPN configurations...")
    try:
        _remove_wireguard_configs()
    except Exception as e:
        logger.error(f"[UNINSTALL] Failed to remove WG configs: {e}")
        errors.append(f"WG configs: {e}")

    # --- Step 4: Remove app config directory ---
    _progress("Removing application data...")
    try:
        _remove_app_config()
    except Exception as e:
        logger.error(f"[UNINSTALL] Failed to remove app config: {e}")
        errors.append(f"App config: {e}")

    # --- Step 5: Remove keychain items ---
    _progress("Removing keychain items...")
    try:
        _remove_keychain_items()
    except Exception as e:
        logger.error(f"[UNINSTALL] Failed to remove keychain items: {e}")
        errors.append(f"Keychain: {e}")

    # --- Step 6: Remove app bundle ---
    _progress("Removing application...")
    try:
        _remove_app_bundle()
    except Exception as e:
        logger.error(f"[UNINSTALL] Failed to remove app bundle: {e}")
        errors.append(f"App bundle: {e}")

    if errors:
        return (False, f"Completed with errors: {'; '.join(errors)}")
    return (True, "Resistine has been uninstalled successfully.")


# ---------------------------------------------------------------------------
# Cleanup helpers
# ---------------------------------------------------------------------------


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
    """Remove WireGuard configuration directory."""
    wg_dir = os.path.expanduser(
        "~/Library/Group Containers/group.Resistine.WireguardTest"
    )
    if os.path.exists(wg_dir):
        shutil.rmtree(wg_dir)
        logger.info(f"[UNINSTALL] Removed {wg_dir}")
    else:
        logger.info("[UNINSTALL] WireGuard config dir not found, skipping")


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

    # sys.executable = /Applications/Resistine.app/Contents/MacOS/Resistine
    app_bundle = os.path.dirname(
        os.path.dirname(os.path.dirname(sys.executable))
    )

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
