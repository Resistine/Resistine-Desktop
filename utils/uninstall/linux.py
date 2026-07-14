"""
Linux Uninstaller Backend.

Removes Resistine's runtime footprint on Linux by delegating to each plugin's
existing (tested) teardown code and then clearing the app's own state:

  1. VPN        — bring down the WireGuard interface + remove its config/keys
  2. SIEM agent — stop/remove the Wazuh agent with a full identity wipe
  3. Antivirus  — deactivate the system ClamAV daemons (packages left in place)
  4. Secrets    — delete the keyring master key
  5. App data   — remove the config dir (~/.config/resistine): settings, secrets,
                  VPN keys, and the Wazuh key backup all live here

Each privileged step is guarded by a presence/active check so a component that
was never set up doesn't trigger a needless pkexec/sudo prompt.

Running from source (run.sh) there is no installed binary or .desktop entry to
remove.  A packaged build should extend this with artifact removal.

Author: Resistine Team
Copyright (c) Resistine 2025
Licensed under the GNU General Public License v2 or later
"""

import os
import shutil

from utils.logger import logger


def is_available():
    """Uninstall is supported on Linux."""
    return True


def run_uninstall(app, progress_callback=None):
    """Execute the full Linux uninstall sequence.

    Returns (success, message).  Individual step failures are collected and
    reported rather than aborting the whole teardown, so a failure in one
    component still lets the rest clean up.
    """

    def _progress(msg):
        logger.info(f"[UNINSTALL-LINUX] {msg}")
        if progress_callback:
            try:
                progress_callback(msg)
            except Exception as e:
                logger.debug(f"[UNINSTALL-LINUX] Progress callback failed: {e}")

    errors = []

    steps = [
        ("Stopping VPN...",            "VPN",         _teardown_vpn),
        ("Removing SIEM agent...",     "SIEM agent",  _remove_wazuh_agent),
        ("Deactivating antivirus...",  "Antivirus",   _deactivate_clamav),
        ("Removing stored secrets...", "Secrets",     _remove_keyring_master_key),
        ("Removing application data...", "App data",   _remove_app_config),
    ]
    for message, label, func in steps:
        _progress(message)
        try:
            func()
        except Exception as e:
            logger.error(f"[UNINSTALL-LINUX] Failed — {label}: {e}")
            errors.append(f"{label}: {e}")

    if errors:
        return (False, f"Completed with errors: {'; '.join(errors)}")
    return (True, "Resistine has been uninstalled successfully.")


# ---------------------------------------------------------------------------
# Cleanup helpers
# ---------------------------------------------------------------------------


def _teardown_vpn():
    """Bring down any WireGuard interface and remove its config + keys.

    Guarded on the presence of a stored config so an un-configured VPN doesn't
    prompt for privileges.
    """
    try:
        from plugins.vpn.wireguard import vpn_functions_linux as vpn
    except ImportError:
        logger.info("[UNINSTALL-LINUX] VPN plugin not present, skipping")
        return

    from utils.settings import get_config_dir

    wg_dir = os.path.join(get_config_dir(), "wireguard")
    confs = []
    if os.path.isdir(wg_dir):
        confs = [
            os.path.join(wg_dir, fn)
            for fn in os.listdir(wg_dir)
            if fn.endswith(".conf")
        ]

    if not confs:
        logger.info("[UNINSTALL-LINUX] No WireGuard config found, skipping VPN teardown")
    else:
        for conf in confs:
            try:
                vpn.stop_vpn(conf)  # wg-quick down + removes the /etc/wireguard copy
            except Exception as e:
                logger.warning(f"[UNINSTALL-LINUX] stop_vpn failed for {conf}: {e}")

    # Local key file is also removed with the config dir, but be explicit.
    try:
        vpn.delete_wireguard_keys()
    except Exception as e:
        logger.warning(f"[UNINSTALL-LINUX] delete_wireguard_keys failed: {e}")


def _remove_wazuh_agent():
    """Stop and remove the Wazuh agent with a full identity wipe.

    remove_agent(wipe_keys=True) self-guards: it returns without prompting for
    privileges when the agent isn't installed and no key backup exists.
    """
    try:
        from plugins.wazuh.agent import wazuh_functions_linux as wazuh
    except ImportError:
        logger.info("[UNINSTALL-LINUX] Wazuh plugin not present, skipping")
        return

    if not wazuh.remove_agent(wipe_keys=True):
        raise OSError("Wazuh agent removal reported failure")


def _deactivate_clamav():
    """Deactivate system ClamAV daemons, guarded on any being active."""
    try:
        from plugins.antivirus import clamav_platform_linux as clamav
    except ImportError:
        logger.info("[UNINSTALL-LINUX] Antivirus plugin not present, skipping")
        return

    # Only touch systemd (and prompt) if one of our services is actually active.
    try:
        services = clamav._service_names()
        any_active = any(clamav._systemctl_is_active(s) for s in services)
    except Exception:
        any_active = False

    if not any_active:
        logger.info("[UNINSTALL-LINUX] No active ClamAV services, skipping")
        return

    ok, msg = clamav.deactivate_system_daemons()
    if not ok:
        raise OSError(msg or "ClamAV deactivation failed")


def _remove_keyring_master_key():
    """Delete the encryption master key from the system keyring."""
    try:
        import keyring
    except ImportError:
        logger.info("[UNINSTALL-LINUX] keyring not available, skipping")
        return

    from utils.settings import MASTER_KEY_SERVICE, MASTER_KEY_USERNAME

    try:
        keyring.delete_password(MASTER_KEY_SERVICE, MASTER_KEY_USERNAME)
        logger.info("[UNINSTALL-LINUX] Removed keyring master key")
    except keyring.errors.PasswordDeleteError:
        logger.info("[UNINSTALL-LINUX] Keyring master key not found")


def _remove_app_config():
    """Remove the user config directory (settings, secrets, VPN/Wazuh keys)."""
    from utils.settings import get_config_dir

    config_dir = get_config_dir()
    if os.path.exists(config_dir):
        shutil.rmtree(config_dir, ignore_errors=True)
        logger.info(f"[UNINSTALL-LINUX] Removed {config_dir}")
    else:
        logger.info("[UNINSTALL-LINUX] Config dir not found, skipping")
