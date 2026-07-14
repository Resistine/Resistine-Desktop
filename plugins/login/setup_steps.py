# -*- coding: utf-8 -*-
# @file plugins/login/setup_steps.py
# Description: Platform glue for the post-login customer setup wizard.
#
# Each SetupStep wraps one capability (VPN, Antivirus, Full Disk Access,
# Endpoint agent) behind a uniform interface the wizard drives without knowing
# any plugin internals:
#
#   is_applicable()  -> should this step appear on this system at all?
#   is_complete()    -> is the capability already set up / permissioned?
#   begin(on_status) -> kick off the work (activation, install, open Settings);
#                       long/blocking work runs on a background thread and
#                       reports progress through on_status(text).
#   check_failed()   -> a user-facing error string if the last attempt failed,
#                       else None (lets the wizard offer "Try Again").
#
# The wizard calls begin() once (when the user clicks the step's primary
# button), then polls is_complete()/check_failed() every couple seconds and
# auto-advances when the capability reports ready. All UI-thread marshalling is
# done by the wizard — steps just call on_status() from wherever they run.
#
# Author: Resistine Team
# Copyright: Resistine (c) 2025
# Licensed under the GNU General Public License v2 or later

import platform
import threading
import webbrowser

from utils.logger import logger

_PLATFORM = platform.system()


class SetupStep:
    """Base class — a single guided setup step. Subclasses override the hooks."""

    key = ""
    icon = "🛡️"
    title = ""
    subtitle = ""          # one-line summary for the welcome checklist
    detail = ""            # longer explanation shown while on the step
    instructions = []      # optional numbered guidance (list[str])
    primary_label = "Enable"
    working_label = "Working…"

    def __init__(self, app):
        self.app = app
        self._failed = None  # user-facing error string, or None
        self._logged_failure = False  # dedupe one-time failure logging
        self._activated = False  # set once the step's service is running
        self._cancel = threading.Event()  # set when the wizard leaves this step

    def cancelled(self) -> bool:
        return self._cancel.is_set()

    # ── Hooks ───────────────────────────────────────────────────────
    def is_applicable(self) -> bool:
        return True

    def is_complete(self) -> bool:
        return False

    def begin(self, on_status):
        """Start the step. on_status(text) reports progress (thread-safe)."""

    def check_failed(self):
        """Return a user-facing failure message, or None if not failed."""
        return self._failed

    # ── Helpers ─────────────────────────────────────────────────────
    def _run_bg(self, fn):
        """Run fn() on a daemon thread, capturing exceptions to _failed."""
        def _worker():
            try:
                fn()
            except Exception as e:  # noqa: BLE001 — surface, never crash the UI
                logger.error(f"[SETUP] Step '{self.key}' failed: {e}")
                self._failed = "Something went wrong. You can try again or skip."
        threading.Thread(target=_worker, daemon=True).start()


# ════════════════════════════════════════════════════════════════════
# VPN — module helpers (import lazily; keep the slow status check off the
# UI thread by only calling it inside worker threads).
# ════════════════════════════════════════════════════════════════════

def _vpn_config():
    """Return (config_name, config_path) for the active tunnel, or (None, None)."""
    try:
        from plugins.vpn.main import _config_manager
        return (_config_manager.get_active_config_name(),
                _config_manager.get_active_config_path())
    except Exception as e:  # noqa: BLE001
        logger.warning(f"[VPN-SETUP] config lookup failed: {e}")
        return None, None


def _vpn_status(name):
    """Return "Running"/"Stopped" for the tunnel. Blocking — worker thread only."""
    try:
        if _PLATFORM == "Windows":
            from plugins.vpn.wireguard.vpn_windows_client import get_status
            return get_status(name).get("state", "Stopped")
        if _PLATFORM == "Linux":
            from plugins.vpn.wireguard.vpn_functions_linux import check_service_status
            return check_service_status(name, None)
        from plugins.vpn.wireguard.vpn_functions_darwin import check_service_status
        return check_service_status(name)
    except Exception as e:  # noqa: BLE001
        logger.warning(f"[VPN-SETUP] status check failed: {e}")
        return "Stopped"


def _vpn_connect(name, path):
    """Start/connect the tunnel. Blocking — worker thread only."""
    if _PLATFORM == "Windows":
        from plugins.vpn.wireguard.vpn_windows_client import connect
        return connect(name, config_path=path)
    if _PLATFORM == "Linux":
        from plugins.vpn.wireguard.vpn_functions_linux import start_vpn
        return start_vpn(path)
    from plugins.vpn.wireguard.vpn_functions_darwin import start_vpn
    return start_vpn(path)


# ════════════════════════════════════════════════════════════════════
# VPN — steps
# ════════════════════════════════════════════════════════════════════

class _VPNStepBase(SetupStep):
    """Shared VPN step: ensure permission/install, then connect the tunnel.

    Completion means the tunnel is actually up (self._activated), not merely
    that the extension/WireGuard is present — the flow must leave the VPN
    running, not just set up.
    """

    key = "vpn"
    icon = "🔒"

    def is_complete(self) -> bool:
        # Fast checks only (called on the UI thread). _perm_ready() is a quick,
        # cached probe; _activated is a bool set by the worker once the tunnel
        # is confirmed up. The slow status check stays in the worker.
        try:
            return self._perm_ready() and self._activated
        except Exception:  # noqa: BLE001
            return False

    # Subclasses implement these.
    def _perm_ready(self) -> bool:
        raise NotImplementedError

    def _ensure_permission(self, on_status) -> bool:
        """Bring the platform prerequisite (extension/WireGuard) online.
        Return True when ready; set self._failed and return False otherwise."""
        raise NotImplementedError

    def begin(self, on_status):
        self._failed = None

        def _work():
            if not self._ensure_permission(on_status):
                return  # _failed already set
            name, path = _vpn_config()
            if not path:
                self._failed = ("No VPN configuration found. Sign in again, then "
                                "retry.")
                logger.error("[VPN-SETUP] no active config to connect")
                return
            if _vpn_status(name) == "Running":
                logger.info("[VPN-SETUP] tunnel already up")
                self._activated = True
                return
            logger.info(f"[VPN-SETUP] connecting tunnel '{name}'")
            on_status("Connecting to VPN…")
            _vpn_connect(name, path)
            import time
            deadline = time.time() + 40
            while time.time() < deadline:
                if self.cancelled():
                    return
                st = _vpn_status(name)
                if st == "Running":
                    logger.info("[VPN-SETUP] connected")
                    self._activated = True
                    return
                time.sleep(2)
            logger.error(f"[VPN-SETUP] connect timed out (status={_vpn_status(name)})")
            self._failed = "VPN didn't connect. You can try again or skip."

        self._run_bg(_work)


class _VPNStepMac(_VPNStepBase):
    title = "Enable & Connect VPN"
    subtitle = "Secure your connection with a private tunnel"
    detail = (
        "Resistine installs a system network extension, then connects you to a "
        "secure VPN. Approving the extension is a one-time step in System "
        "Settings."
    )
    primary_label = "Enable VPN"
    working_label = "Setting up VPN…"

    def __init__(self, app):
        super().__init__(app)
        self.instructions = self._mac_instructions()

    def _perm_ready(self) -> bool:
        from plugins.vpn.wireguard.vpn_functions_darwin import is_extension_enabled
        return bool(is_extension_enabled())

    def _ensure_permission(self, on_status) -> bool:
        from plugins.vpn.wireguard.vpn_functions_darwin import (
            VPNHelper,
            is_extension_enabled,
        )
        if is_extension_enabled():
            return True
        logger.info("[VPN-SETUP] requesting extension activation")
        try:
            VPNHelper.activate_extension()
        except Exception as e:  # noqa: BLE001
            logger.warning(f"[VPN-SETUP] activate_extension failed: {e}")
        self._open_settings()
        on_status("Approve the Resistine extension in System Settings — this "
                  "continues automatically once enabled.")
        import time
        deadline = time.time() + 300
        while time.time() < deadline:
            if self.cancelled():
                return False
            if is_extension_enabled():
                logger.info("[VPN-SETUP] extension approved")
                return True
            time.sleep(2)
        logger.error("[VPN-SETUP] extension approval timed out")
        self._failed = ("VPN extension wasn't approved. You can try again or skip.")
        return False

    def _open_settings(self):
        import subprocess
        try:
            subprocess.Popen([
                "open",
                "x-apple.systempreferences:com.apple.LoginItems-Settings.extension",
            ])
        except Exception as e:  # noqa: BLE001
            logger.error(f"[VPN-SETUP] Failed to open System Settings: {e}")

    @staticmethod
    def _mac_instructions():
        try:
            major = int(platform.mac_ver()[0].split(".")[0] or "0")
        except ValueError:
            major = 0
        if major >= 15:
            where = "Open General ▸ Login Items & Extensions ▸ Network Extensions"
        else:
            where = "Open Privacy & Security and scroll to Security"
        return [
            "A macOS dialog appears — click “Open System Settings”.",
            where,
            "Enable the Resistine extension and click Allow.",
        ]


class _VPNStepWindows(_VPNStepBase):
    title = "Set Up & Connect VPN"
    subtitle = "Install WireGuard to secure your connection"
    detail = (
        "Resistine's VPN is powered by WireGuard. Install it once and Resistine "
        "connects and manages the secure tunnel for you."
    )
    instructions = [
        "Click “Download WireGuard” to open the installer page.",
        "Run the WireGuard installer and accept the prompts.",
        "This step continues and connects automatically once installed.",
    ]
    primary_label = "Download WireGuard"
    working_label = "Setting up VPN…"

    def _perm_ready(self) -> bool:
        from plugins.vpn.wireguard.vpn_functions_windows import check_wireguard_installed
        return bool(check_wireguard_installed())

    def _ensure_permission(self, on_status) -> bool:
        from plugins.vpn.wireguard.vpn_functions_windows import check_wireguard_installed
        if check_wireguard_installed():
            return True
        webbrowser.open("https://www.wireguard.com/install/")
        on_status("Install WireGuard — this continues automatically once done.")
        import time
        deadline = time.time() + 300
        while time.time() < deadline:
            if check_wireguard_installed():
                return True
            time.sleep(3)
        self._failed = "WireGuard wasn't installed. You can try again or skip."
        return False


class _VPNStepLinux(_VPNStepBase):
    title = "Set Up & Connect VPN"
    subtitle = "Install WireGuard to secure your connection"
    detail = (
        "Resistine's VPN is powered by WireGuard. We'll install the tools and "
        "connect you — you may be asked for your password."
    )
    primary_label = "Set Up VPN"
    working_label = "Setting up VPN…"

    def _perm_ready(self) -> bool:
        from plugins.vpn.wireguard.vpn_functions_linux import check_wireguard_installed
        return bool(check_wireguard_installed())

    def _ensure_permission(self, on_status) -> bool:
        from plugins.vpn.wireguard.vpn_functions_linux import (
            check_wireguard_installed,
            run_installer_as_admin,
        )
        if check_wireguard_installed():
            return True
        on_status("Installing WireGuard — you may be prompted for your password…")
        run_installer_as_admin("")
        if check_wireguard_installed():
            return True
        self._failed = "WireGuard didn't install. You can try again or skip."
        return False


# ════════════════════════════════════════════════════════════════════
# Antivirus
# ════════════════════════════════════════════════════════════════════

class _AntivirusStepMac(SetupStep):
    key = "antivirus"
    icon = "🛡️"
    title = "Turn On Antivirus"
    subtitle = "Real-time malware scanning with ClamAV"
    detail = (
        "Resistine downloads virus definitions and installs the ClamAV scanning "
        "service. You'll be asked once for your administrator password to enable "
        "system-wide protection."
    )
    instructions = [
        "Click “Enable Antivirus” and enter your administrator password.",
        "If asked, enable the ClamAV items under System Settings ▸ General ▸ "
        "Login Items & Extensions.",
        "Protection turns on automatically once approved.",
    ]
    primary_label = "Enable Antivirus"
    working_label = "Setting up antivirus…"

    def is_complete(self) -> bool:
        # STATE_COMPLETED means the admin install ran — but on macOS 13+ the
        # daemons still sit in "Approval Required" until the user enables them
        # in Login Items & Extensions. Only treat the step as done once the
        # daemons are actually running (healthy/degraded), or once they're
        # approved and only Full Disk Access remains (handled by the next step).
        from plugins.antivirus.installer_service import (
            STATE_COMPLETED,
            get_runtime_state,
            get_setup_state,
        )
        if get_setup_state() != STATE_COMPLETED:
            return False
        return get_runtime_state() in ("healthy", "degraded", "fda_required")

    def check_failed(self):
        if self._failed:
            return self._failed
        from plugins.antivirus.installer_service import (
            STATE_INSTALL_FAILED,
            STATE_SEED_FAILED,
            get_setup_state,
        )
        if get_setup_state() in (STATE_SEED_FAILED, STATE_INSTALL_FAILED):
            return self._fail_msg("Antivirus setup didn't finish.")
        return None

    def _fail_msg(self, prefix):
        """Build a user-facing failure message that includes the installer's
        recorded reason, and log the full reason+detail once for diagnosis."""
        from plugins.antivirus.installer_service import (
            get_failure_detail,
            get_failure_reason,
            get_setup_state,
        )
        reason = get_failure_reason() or "unknown"
        detail = get_failure_detail() or ""
        if not self._logged_failure:
            self._logged_failure = True
            logger.error(
                f"[AV-SETUP] FAILED state={get_setup_state()} "
                f"reason={reason} detail={detail!r}"
            )
        return f"{prefix} ({reason}) You can try again or skip."

    def begin(self, on_status):
        import time
        from plugins.antivirus import installer_service as av

        self._logged_failure = False
        state0 = av.get_setup_state()
        logger.info(
            f"[AV-SETUP] begin: setup_state={state0} "
            f"runtime_state={self._safe_runtime()} "
            f"prior_reason={av.get_failure_reason()!r} "
            f"prior_detail={av.get_failure_detail()!r}"
        )

        # A prior failed attempt leaves the state machine parked — reset it so
        # this run starts cleanly.
        if state0 in (av.STATE_SEED_FAILED, av.STATE_INSTALL_FAILED):
            logger.info(f"[AV-SETUP] resetting parked state {state0} via retry()")
            av.retry()
        self._failed = None

        def _work():
            # Phase 1: virus definitions (seeded at login; wait for it).
            logger.info("[AV-SETUP] phase 1: ensure_db_seed_started()")
            av.ensure_db_seed_started()
            on_status("Downloading virus definitions…")
            deadline = time.time() + 180
            last = None
            while time.time() < deadline:
                state = av.get_setup_state()
                if state != last:
                    logger.info(f"[AV-SETUP] phase 1 state -> {state}")
                    last = state
                if state == av.STATE_DB_READY:
                    break
                if state == av.STATE_COMPLETED:
                    logger.info("[AV-SETUP] already completed; nothing to do")
                    return  # already fully set up
                if state == av.STATE_SEED_FAILED:
                    self._failed = self._fail_msg("Couldn't download virus definitions.")
                    return
                time.sleep(2)
            else:
                logger.error("[AV-SETUP] phase 1 TIMED OUT waiting for DB_READY "
                             f"(last state={last})")
                self._failed = "Downloading definitions timed out. You can try again or skip."
                return

            # Phase 2: system install (admin prompt).
            logger.info("[AV-SETUP] phase 2: trigger_system_setup() (admin prompt)")
            on_status("Approve the administrator prompt to enable protection…")
            launched = av.trigger_system_setup()
            logger.info(f"[AV-SETUP] trigger_system_setup() -> {launched}")
            if not launched:
                self._failed = self._fail_msg("Antivirus setup couldn't start.")
                return

            # Phase 3: watch the install to completion.
            _STEPS = {
                "install_files": "Installing ClamAV…",
                "seed_db": "Preparing definitions…",
                "register_daemons": "Registering protection service…",
                "start_daemons": "Starting real-time protection…",
            }
            logger.info("[AV-SETUP] phase 3: polling install progress")
            last_step = None
            while True:
                result = av.poll_setup_progress()
                step = result.get("step", "")
                if step and step != last_step:
                    logger.info(f"[AV-SETUP] install step -> {step}")
                    last_step = step
                    on_status(_STEPS.get(step, "Setting up antivirus…"))
                if result.get("finished"):
                    logger.info(f"[AV-SETUP] install finished: {result}")
                    if result.get("success"):
                        logger.info("[AV-SETUP] admin install OK")
                    else:
                        # The admin postinstall can report failure while the
                        # daemons are merely awaiting Login Items approval —
                        # don't hard-fail if that's the real blocker.
                        rt = self._safe_runtime()
                        logger.warning(
                            f"[AV-SETUP] install poll not success; runtime={rt}")
                        if rt != av.RUNTIME_APPROVAL_REQUIRED:
                            self._failed = self._fail_msg("Antivirus setup didn't finish.")
                            return
                    break
                time.sleep(2)

            # Phase 4: Login Items & Extensions approval (macOS 13+). After the
            # admin install the ClamAV daemons are registered but sit in
            # "Approval Required" until the user enables them. Open the pane and
            # wait — this is the step the flow was missing.
            logger.info("[AV-SETUP] phase 4: daemon approval")
            opened = False
            start = time.time()
            deadline = start + 300
            while time.time() < deadline:
                if self.cancelled():
                    logger.info("[AV-SETUP] phase 4 cancelled (step left)")
                    return
                rt = self._safe_runtime()
                elapsed = int(time.time() - start)
                if rt in ("healthy", "degraded", "fda_required"):
                    logger.info(f"[AV-SETUP] SUCCESS — protection active (runtime={rt})")
                    return
                if rt == av.RUNTIME_APPROVAL_REQUIRED:
                    if not opened:
                        logger.info("[AV-SETUP] opening Login Items & Extensions "
                                    "for daemon approval")
                        try:
                            from plugins.antivirus import clamav
                            clamav.open_login_items_settings()
                        except Exception as e:  # noqa: BLE001
                            logger.error(f"[AV-SETUP] open_login_items failed: {e}")
                        opened = True
                    # Live heartbeat so the user sees it's actively checking, and
                    # remind them that ALL the ClamAV items must be enabled.
                    on_status("Enable all the ClamAV items under System Settings ▸ "
                              "Login Items & Extensions — still checking… "
                              f"({elapsed}s)")
                else:  # offline — actively (re)start the daemons
                    logger.info(f"[AV-SETUP] runtime={rt}; activate_system_daemons()")
                    try:
                        from plugins.antivirus import clamav
                        ok, msg = clamav.activate_system_daemons()
                        logger.info(f"[AV-SETUP] activate_system_daemons -> {ok} ({msg})")
                    except Exception as e:  # noqa: BLE001
                        logger.error(f"[AV-SETUP] activate_system_daemons failed: {e}")
                    on_status(f"Starting real-time protection… ({elapsed}s)")
                time.sleep(2)

            logger.error("[AV-SETUP] phase 4 TIMED OUT (runtime="
                         f"{self._safe_runtime()})")
            self._failed = ("Protection is installed but waiting for approval in "
                            "Login Items & Extensions. You can finish this from the "
                            "Antivirus page, or skip.")

        self._run_bg(_work)

    @staticmethod
    def _safe_runtime():
        try:
            from plugins.antivirus.installer_service import get_runtime_state
            return get_runtime_state()
        except Exception as e:  # noqa: BLE001
            return f"<err:{e}>"


class _AntivirusStepDefender(SetupStep):
    """Windows/Linux antivirus via the clamav facade (Defender / ClamAV)."""

    key = "antivirus"
    icon = "🛡️"
    title = "Turn On Antivirus"
    subtitle = "Enable real-time malware protection"
    detail = (
        "Resistine turns on real-time antivirus protection. You may be asked to "
        "approve an administrator prompt."
    )
    primary_label = "Enable Antivirus"
    working_label = "Turning on protection…"

    def __init__(self, app):
        super().__init__(app)
        if _PLATFORM == "Windows":
            self.detail = (
                "Resistine enables Microsoft Defender real-time protection. "
                "Approve the Windows prompt to continue."
            )
        else:
            self.detail = (
                "Resistine installs and starts the ClamAV scanning service. "
                "You may be asked for your password."
            )

    def is_complete(self) -> bool:
        from plugins.antivirus import clamav
        try:
            state = clamav.get_realtime_status().get("runtime_state", "")
        except Exception:  # noqa: BLE001
            return False
        return state in ("healthy", "degraded")

    def begin(self, on_status):
        on_status(self.working_label)

        def _work():
            from plugins.antivirus import clamav
            ok, msg = clamav.activate_system_daemons()
            if not ok:
                self._failed = "Couldn't turn on antivirus. You can try again or skip."
                logger.warning(f"[SETUP] activate_system_daemons: {msg}")
        self._run_bg(_work)


class _FullDiskAccessStepMac(SetupStep):
    key = "full_disk_access"
    icon = "📁"
    title = "Grant Full Disk Access"
    subtitle = "Let the scanner protect every folder"
    detail = (
        "macOS restricts which files apps can read. Grant Resistine Full Disk "
        "Access so the antivirus can scan your whole system, including Mail and "
        "protected folders."
    )
    instructions = [
        "Click “Open System Settings”.",
        "In Privacy & Security ▸ Full Disk Access, enable Resistine.",
        "This step continues automatically once access is granted.",
    ]
    primary_label = "Open System Settings"
    working_label = "Waiting for Full Disk Access…"

    def is_applicable(self) -> bool:
        # Only meaningful for the packaged app (dev builds report access via a
        # different path and don't have the bundled daemons to protect).
        from plugins.antivirus import clamav
        try:
            return bool(clamav.is_app_bundle())
        except Exception:  # noqa: BLE001
            return False

    def is_complete(self) -> bool:
        from plugins.antivirus import clamav
        try:
            return bool(clamav.has_full_disk_access())
        except Exception:  # noqa: BLE001
            return True

    def begin(self, on_status):
        from plugins.antivirus import clamav
        try:
            clamav.open_fda_settings()
        except Exception as e:  # noqa: BLE001
            logger.error(f"[SETUP] Failed to open FDA settings: {e}")
        on_status("Enable Resistine under Full Disk Access, then this continues "
                  "automatically.")


# ════════════════════════════════════════════════════════════════════
# Endpoint / SIEM agent
# ════════════════════════════════════════════════════════════════════

def _wazuh_mod():
    if _PLATFORM == "Darwin":
        from plugins.wazuh.agent import wazuh_functions_darwin as m
    elif _PLATFORM == "Linux":
        from plugins.wazuh.agent import wazuh_functions_linux as m
    elif _PLATFORM == "Windows":
        from plugins.wazuh.agent import wazuh_functions_windows as m
    else:
        return None
    return m


def _wazuh_installed() -> bool:
    try:
        m = _wazuh_mod()
        return bool(m and m.is_agent_installed())
    except Exception:  # noqa: BLE001
        return False


def _wazuh_running() -> bool:
    try:
        m = _wazuh_mod()
        return bool(m and m.get_agent_status() == "Running")
    except Exception:  # noqa: BLE001
        return False


def _wazuh_start() -> bool:
    """Start the agent service (admin/UAC/password prompt). Worker thread only."""
    try:
        m = _wazuh_mod()
        return bool(m and m.start_agent())
    except Exception as e:  # noqa: BLE001
        logger.error(f"[EP-SETUP] start_agent failed: {e}")
        return False


# Human-readable messages for Wazuh installer failure reasons. Mirrors the
# mapping the Endpoint plugin's own UI uses (plugins/wazuh/main.py) so the
# wizard explains failures the same clear way instead of "didn't finish".
_WZ_REASON_MSG = {
    "user_canceled": "The install was cancelled.",
    "script_failed": "The installer hit an error. You can try again or skip.",
    "pkg_corrupted": "The downloaded package was corrupted. Try again to re-download.",
    "no_status_file": "The install was interrupted. Try again.",
    "dns_failed": "Couldn't reach the download server. Check your connection and try again.",
    "network_timeout": "The download timed out. Check your connection and try again.",
    "signature_invalid": "The package failed signature verification. Try again to re-download.",
    "duplicate_name": (
        "This device is already registered on the monitoring server. "
        "Try again to enroll under a new identifier."
    ),
    "manager_unreachable": (
        "Couldn't reach the monitoring server. Make sure the VPN is connected, "
        "then try again."
    ),
    "enroll_failed": (
        "Enrollment with the monitoring server failed. Make sure the VPN is "
        "connected, then try again."
    ),
}


def _wazuh_reason_message(reason) -> str:
    """Turn a Wazuh installer failure_reason into a clear, actionable message."""
    if reason and reason.startswith("enroll_rc_"):
        rc = reason[len("enroll_rc_"):]
        return (f"Enrollment with the monitoring server failed (code {rc}). "
                "Make sure the VPN is connected, then try again.")
    if reason in _WZ_REASON_MSG:
        return _WZ_REASON_MSG[reason]
    if reason:
        return f"Endpoint setup didn't finish ({reason}). You can try again or skip."
    return "Endpoint setup didn't finish. You can try again or skip."


def _maybe_forward_clamav(on_status):
    """Best-effort: once the agent is running, forward ClamAV logs to it if
    ClamAV is also set up. Never fails the endpoint step."""
    try:
        from plugins.wazuh.agent.log_forwarding import ensure_clamav_log_forwarding
        ensure_clamav_log_forwarding(on_status)
    except Exception as e:  # noqa: BLE001
        logger.warning(f"[EP-SETUP] ClamAV forwarding skipped: {e}")


def _wazuh_activate(on_status, cancelled=None):
    """After install, ensure the agent is actually Running. Worker thread only."""
    import time
    if _wazuh_running():
        logger.info("[EP-SETUP] agent already running")
        return True
    logger.info("[EP-SETUP] starting agent")
    on_status("Starting endpoint monitoring…")
    _wazuh_start()
    deadline = time.time() + 60
    while time.time() < deadline:
        if cancelled and cancelled():
            return False
        if _wazuh_running():
            logger.info("[EP-SETUP] agent running")
            return True
        time.sleep(2)
    logger.warning("[EP-SETUP] agent did not reach Running state")
    return False


class _EndpointStepMac(SetupStep):
    key = "endpoint"
    icon = "📡"
    title = "Install Endpoint Monitoring"
    subtitle = "Detect threats with the SIEM agent"
    detail = (
        "The Resistine endpoint agent watches your device for suspicious "
        "activity and reports it securely. You'll be asked once for your "
        "administrator password."
    )
    instructions = [
        "Click “Install Endpoint Agent”.",
        "Enter your administrator password when macOS asks.",
        "The agent installs and enrolls automatically.",
    ]
    primary_label = "Install Endpoint Agent"
    working_label = "Installing endpoint agent…"

    def is_complete(self) -> bool:
        # Must be installed AND running — the flow leaves monitoring active.
        return _wazuh_installed() and _wazuh_running()

    def check_failed(self):
        if self._failed:
            return self._failed
        from plugins.wazuh.agent.installer_service import (
            STATE_DOWNLOAD_FAILED,
            STATE_ENROLL_FAILED,
            STATE_INSTALL_FAILED,
            get_failure_reason,
            get_install_state,
        )
        state = get_install_state()
        if state in (
            STATE_DOWNLOAD_FAILED, STATE_INSTALL_FAILED, STATE_ENROLL_FAILED,
        ):
            reason = get_failure_reason()
            if not self._logged_failure:
                self._logged_failure = True
                logger.error(f"[EP-SETUP] FAILED state={state} reason={reason!r}")
            return _wazuh_reason_message(reason)
        return None

    def begin(self, on_status):
        import time
        from plugins.wazuh.agent import installer_service as wz

        if wz.get_install_state() in (
            wz.STATE_DOWNLOAD_FAILED, wz.STATE_INSTALL_FAILED, wz.STATE_ENROLL_FAILED,
        ):
            wz.retry()
        self._failed = None

        def _work():
            # Phase 1: package download (kicked off at login; wait for it).
            if not _wazuh_installed():
                wz.ensure_download_started()
                on_status("Downloading endpoint agent…")
                deadline = time.time() + 180
                while time.time() < deadline:
                    state = wz.get_install_state()
                    if state == wz.STATE_DOWNLOADED:
                        break
                    if state in (wz.STATE_INSTALLED, wz.STATE_READY):
                        break
                    if state == wz.STATE_DOWNLOAD_FAILED:
                        self._failed = _wazuh_reason_message(
                            wz.get_failure_reason() or "dns_failed")
                        return
                    time.sleep(2)
                else:
                    self._failed = "Download timed out. You can try again or skip."
                    return

            # Phase 2 + 3: install (admin prompt) + watch to completion, unless
            # the agent is already on disk.
            if not _wazuh_installed():
                on_status("Approve the administrator prompt to install…")
                if not wz.trigger_install(self.app):
                    self._failed = _wazuh_reason_message(
                        wz.get_failure_reason() or "user_canceled")
                    return
                _STEPS = {
                    "install_pkg": "Installing package…",
                    "patch_config": "Configuring agent…",
                    "enrollment": "Enrolling agent…",
                    "key_backup": "Backing up keys…",
                    "launchd": "Starting agent service…",
                    "done": "Finishing up…",
                }
                while True:
                    result = wz.poll_install_progress()
                    step = result.get("step", "")
                    if step:
                        on_status(_STEPS.get(step, "Installing…"))
                    if result.get("finished"):
                        if not result.get("success"):
                            reason = wz.get_failure_reason()
                            logger.error(f"[EP-SETUP] install failed reason={reason!r} "
                                         f"result={result}")
                            self._failed = _wazuh_reason_message(reason)
                            return
                        break
                    time.sleep(2)

            # Phase 4: make sure the agent is actually running.
            if not _wazuh_activate(on_status, self.cancelled):
                self._failed = ("Endpoint agent installed but isn't running yet. "
                                "You can start it from the Endpoint page, or skip.")
                return
            # Phase 5: link ClamAV → Wazuh if antivirus is also set up.
            _maybe_forward_clamav(on_status)

        self._run_bg(_work)


class _EndpointStepDirect(SetupStep):
    """Windows/Linux endpoint install via full_install() on a worker thread."""

    key = "endpoint"
    icon = "📡"
    title = "Install Endpoint Monitoring"
    subtitle = "Detect threats with the SIEM agent"
    detail = (
        "The Resistine endpoint agent watches your device for suspicious "
        "activity and reports it securely. You may be asked to approve an "
        "administrator prompt."
    )
    primary_label = "Install Endpoint Agent"
    working_label = "Installing endpoint agent…"

    def is_complete(self) -> bool:
        # Must be installed AND running — the flow leaves monitoring active.
        return _wazuh_installed() and _wazuh_running()

    def begin(self, on_status):
        def _work():
            if not _wazuh_installed():
                if _PLATFORM == "Linux":
                    from plugins.wazuh.agent.wazuh_functions_linux import full_install
                else:
                    from plugins.wazuh.agent.wazuh_functions_windows import full_install

                def _progress(msg):
                    on_status(str(msg))

                ok = full_install(progress_callback=_progress)
                if not ok and not _wazuh_installed():
                    self._failed = "Endpoint setup didn't finish. You can try again or skip."
                    return

            # Ensure the agent is actually running (full_install usually starts
            # it; this covers the already-installed-but-stopped case too).
            if not _wazuh_activate(on_status, self.cancelled):
                self._failed = ("Endpoint agent installed but isn't running yet. "
                                "You can start it from the Endpoint page, or skip.")
                return
            # Link ClamAV → Wazuh if antivirus is also set up.
            _maybe_forward_clamav(on_status)
        self._run_bg(_work)


# ════════════════════════════════════════════════════════════════════
# Factory
# ════════════════════════════════════════════════════════════════════

def build_steps(app):
    """Return the ordered list of applicable SetupSteps for this platform.

    Steps whose plugin fails to import (or whose is_applicable() raises) are
    dropped so a single unavailable capability never blocks the wizard.
    """
    if _PLATFORM == "Darwin":
        candidates = [
            _VPNStepMac,
            _AntivirusStepMac,
            _FullDiskAccessStepMac,
            _EndpointStepMac,
        ]
    elif _PLATFORM == "Windows":
        candidates = [
            _AntivirusStepDefender,
            _VPNStepWindows,
            _EndpointStepDirect,
        ]
    elif _PLATFORM == "Linux":
        candidates = [
            _AntivirusStepDefender,
            _VPNStepLinux,
            _EndpointStepDirect,
        ]
    else:
        candidates = []

    steps = []
    for cls in candidates:
        try:
            step = cls(app)
            if step.is_applicable():
                steps.append(step)
        except Exception as e:  # noqa: BLE001
            logger.warning(f"[SETUP] Skipping step {cls.__name__}: {e}")
    return steps
