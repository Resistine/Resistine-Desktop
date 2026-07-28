"""Wazuh Overview Plugin (PyQt6).

Second sidebar entry ("Wazuh") — a multi-tab security-posture dashboard for the
caller's device group, driven by the IP-identified /api/v1/me/* API. Ported from
the CustomTkinter design_test2 branch onto the PyQt foundation.

Tabs: Overview, Events, Vulnerabilities, Inventory. The Overview tab paints from
five /me/* endpoints (agent, vulnerabilities-summary, sca, inventory, hotfixes),
each fetched on its own thread and rendered as it lands. Events / Vulnerabilities
add matplotlib charts (Qt backend) and are built lazily on first tab open.

The module-level data layer (constants, response normalizers, the remote-data
cache, and the background preloaders) is framework-agnostic and carries over
from the source almost verbatim; only the UI is a PyQt rewrite. All blocking
work runs on daemon threads and is marshalled back onto the GUI thread via
``self.app.after(0, ...)``.

Author: Resistine Team
Copyright (c) Resistine 2025
Licensed under the GNU General Public License v2 or later
"""

from __future__ import annotations

import os
import platform as _platform
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone

from PyQt6.QtCore import QTimer, Qt
from PyQt6.QtWidgets import (
    QStackedWidget,
    QBoxLayout,
    QComboBox,
    QFrame,
    QGraphicsOpacityEffect,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from gui import theme
from gui.qt_widgets import ResponsiveStack
from gui.qt_widgets import scroll_page
from plugins.base_plugin import BasePlugin
from plugins.wazuh_overview import api_client, charts
from plugins.wazuh_overview.config import EVENTS_WINDOW_HOURS, MAX_PARALLEL_FETCHES
from plugins.wazuh_overview.loading import LoadingScreen, RampProgress
from utils.logger import logger

_PLUGIN_DIR = os.path.dirname(os.path.realpath(__file__))
# Reuse the SIEM-agent plugin's Wazuh iconography for the sidebar entry.
_WAZUH_DIR = os.path.join(os.path.dirname(_PLUGIN_DIR), "wazuh")

# Dev-only refresh button on the Overview modules header. Hardcoded True until
# the debug inspector gate is restored; flip to False when shipping.
_SHOW_DEV_REFRESH_BUTTON = True

_TAB_NAMES = ("Overview", "Events", "Vulnerabilities", "Inventory")
# Tabs that show a circular-progress loading screen. Overview is excluded on
# purpose: it paints a full skeleton immediately and fills it in as endpoints
# land, which beats blocking on a ring.
_LOADING_TABS = ("Events", "Vulnerabilities", "Inventory")
_LEGEND_KEYS = ("critical", "error", "warning", "info")
_SEVERITY_LEVELS = ("critical", "high", "medium", "low")
# Opacity a non-selected severity fades to when a threat level is selected. Shared
# by the Vulnerabilities donut/timeline and the Events chart/header pills so the
# fade looks identical across the whole plugin.
_SEV_DIM_ALPHA = 0.25
# Severity bucket -> displayed badge label. Shared by the Overview cards and the
# (later) Inventory device rows.
_SEV_TO_STATUS = {
    "critical": "CRITICAL",
    "high": "HIGH",
    "medium": "WARNING",
    "low": "OK",
}
# Sort priority for composite threat ranking. Higher is more severe.
_THREAT_RANK = {"critical": 4, "high": 3, "medium": 2, "low": 1, "ok": 0}
_RANK_TO_SEV = {v: k for k, v in _THREAT_RANK.items()}

# Layout constants. The Overview content is a centered column so page elements
# don't stretch edge-to-edge; module tiles sit in a RESPONSIVE grid within it
# whose column count follows the width ladder below (ported from
# endpoint/design_test2's CTk implementation).
_CONTENT_MAX_WIDTH = 1240
_CONTENT_MIN_WIDTH = 320

# Responsive breakpoints (design_test2 parity): the module grid steps
# Overview module grid holds 2 columns until the app window spans this fraction
# of the screen width, then expands to one row (see _ModuleGrid._target_cols).
# Two-up chart/detail rows stack vertically below the stack breakpoint.
_MODULE_GRID_EXPAND_SCREEN_FRAC = 0.8
_STACK_BREAKPOINT = 680
_CARD_MIN_H = 160
_CARD_MAX_H = 300
_RESIZE_DEBOUNCE_MS = 250

# Severity name -> badge theme key.
#   critical -> violet/red   high -> red (error)
#   medium   -> orange       low  -> green (ok)
_SEVERITY_THEME_KEY = {
    "critical": "critical",
    "high": "high",
    "medium": "warning",
    "low": "ok",
}
# Short label shown inside the severity badge in the vulnerabilities table.
_SEVERITY_SHORT = {
    "critical": "CRIT",
    "high": "HIGH",
    "medium": "MED",
    "low": "LOW",
}

# status/severity color key -> a key theme.badge_colors understands. high/medium/
# low are severity aliases the base badge palette doesn't carry, so fold them
# onto the closest error/warning/ok hue.
_BADGE_KEY = {
    "ok": "ok",
    "info": "info",
    "warning": "warning",
    "error": "error",
    "critical": "critical",
    "high": "error",
    "medium": "warning",
    "low": "ok",
    "vuln": "error",
}


def _badge_colors(status):
    """(bg, fg) pill colors for a card status / severity label."""
    key = _BADGE_KEY.get((status or "").lower(), (status or "").lower())
    return theme.badge_colors(key)


def _segment_color(key):
    """Text color for a stat segment. 'muted' -> secondary text; otherwise the
    badge foreground hue for that severity/status key."""
    if key == "muted":
        return theme.color("text_secondary")
    _, fg = theme.badge_colors(_BADGE_KEY.get(key, key))
    return fg


def _wazuh_level_to_severity(level):
    """Map a Wazuh rule.level (0-15) to one of the page's four severity buckets."""
    try:
        n = int(level)
    except (TypeError, ValueError):
        return "low"
    if n >= 14:
        return "critical"
    if n >= 12:
        return "high"
    if n >= 7:
        return "medium"
    return "low"


def _normalize_wazuh_hit(hit):
    """Flatten a Wazuh alert hit into the dict shape the events UI expects.

    Tolerates OpenSearch-shaped hits (``_source`` envelope, nested rule/agent),
    pre-flattened payloads, and the live /me/vulnerabilities/{id}/events shape
    (flat, capitalized ``severity``, ``rule_id``/``rule_level``/``title``).
    Live-shape fields are tried first, then the legacy nested accessors, so a
    future shape change can't blank the UI."""
    import json

    src = hit.get("_source") or hit
    rule = src.get("rule") or {}
    agent = src.get("agent") or {}
    mitre = (rule.get("mitre") or {}).get("id") or []
    if not isinstance(mitre, list):
        mitre = [mitre]

    raw_log = src.get("full_log") or src.get("previous_output") or ""
    if not raw_log:
        data = src.get("data")
        if data:
            try:
                raw_log = json.dumps(data, indent=2)
            except (TypeError, ValueError):
                raw_log = str(data)
        elif src.get("cve"):
            raw_log = json.dumps(
                {
                    "cve": src.get("cve"),
                    "package": src.get("package"),
                    "version": src.get("version"),
                    "title": src.get("title"),
                },
                indent=2,
            )

    cve = src.get("cve")
    severity_str = src.get("severity")
    rule_level = src.get("rule_level")
    if rule_level is None:
        rule_level = rule.get("level")

    return {
        "id": hit.get("_id") or src.get("id") or cve or "",
        "rule_id": src.get("rule_id") or rule.get("id", ""),
        "level": rule_level,
        "severity": (severity_str or "").lower() or _wazuh_level_to_severity(rule_level),
        "description": src.get("title") or rule.get("description", "") or cve or "",
        "timestamp": src.get("timestamp") or "",
        "agent": agent.get("name", ""),
        "host": agent.get("name", ""),
        "ip": agent.get("ip", ""),
        "mitre": mitre,
        "hash": src.get("id", "") or cve or "",
        "raw_log": raw_log,
    }


# ------------------------------------------------------------------------------
#  Inventory multi-device dataset (lazy on first Inventory open)
# ------------------------------------------------------------------------------
_AGENTS = []
_agents_ready = threading.Event()
_agents_loader_started = False
_agents_loader_lock = threading.Lock()


def _shape_inventory_agent(summary, detail):
    """Map a /me/inventory summary device (+ optional /me/inventory/{id} detail)
    into the {basic_info, syscollector, hardware} shape the Inventory tab reads.

    Caller groups are stamped onto basic_info because the API only returns
    devices in the caller's group, so the group-filter dropdown can still show
    the right value. Devices whose detail fetch failed get an empty syscollector
    (Processes/Ports/Network views render 0 counts)."""
    caller_groups = []
    if _remote_agent_ready.is_set() and isinstance(_REMOTE_AGENT, dict):
        g = _REMOTE_AGENT.get("group") or []
        if isinstance(g, list):
            caller_groups = list(g)

    os_info = summary.get("os") or {}
    hw_info = summary.get("hardware") or {}
    last_seen = os_info.get("last_scan") or hw_info.get("last_scan")

    basic_info = {
        "id": summary.get("agent_id"),
        "name": summary.get("agent_name"),
        "ip": summary.get("agent_ip") or "—",
        "status": summary.get("status"),
        "os": os_info,
        "lastKeepAlive": last_seen,
        "group": caller_groups,
    }

    syscollector = {}
    if isinstance(detail, dict):
        processes = detail.get("processes")
        ports = detail.get("ports")
        network = detail.get("network") or {}
        interfaces = network.get("interfaces") if isinstance(network, dict) else None
        packages = detail.get("packages")
        syscollector = {
            "processes": {"affected_items": list(processes or [])},
            "network": {
                "ports": {"affected_items": list(ports or [])},
                "interfaces": {"affected_items": list(interfaces or [])},
            },
            "packages": {"affected_items": list(packages or [])},
        }

    return {
        "basic_info": basic_info,
        "syscollector": syscollector,
        "hardware": hw_info,
    }


def _load_all_agents(devices=None):
    """Fetch the device list + per-device detail IN PARALLEL, returning agent
    dicts in the shape the Inventory tab consumes. Pass ``devices`` to reuse a
    cached inventory list (the preloader caches it under _REMOTE_INVENTORY)."""
    if devices is None:
        devices, err = api_client.fetch_inventory_full()
        if err:
            logger.error(f"Inventory: fetch_inventory_full failed: {err}")
            return []
    if not devices:
        return []

    ided = [(d.get("agent_id"), d) for d in devices]
    fetchable = [(aid, d) for aid, d in ided if aid]
    no_id = [(aid, d) for aid, d in ided if not aid]

    detail_by_aid = {}
    if fetchable:
        workers = min(len(fetchable), MAX_PARALLEL_FETCHES)
        with ThreadPoolExecutor(max_workers=workers) as ex:
            future_to_aid = {
                ex.submit(api_client.fetch_device_inventory, aid): aid
                for aid, _ in fetchable
            }
            for future in as_completed(future_to_aid):
                aid = future_to_aid[future]
                detail, derr = future.result()
                if derr:
                    logger.warning(
                        f"Inventory: fetch_device_inventory({aid}) failed: {derr}"
                    )
                detail_by_aid[aid] = detail

    out = []
    for aid, d in fetchable:
        out.append(_shape_inventory_agent(d, detail_by_aid.get(aid)))
    for _, d in no_id:
        out.append(_shape_inventory_agent(d, None))
    return out


def _load_agents_async():
    global _AGENTS
    try:
        cached = None
        if _remote_inventory_ready.is_set() and isinstance(_REMOTE_INVENTORY, dict):
            items = _REMOTE_INVENTORY.get("items")
            if isinstance(items, list) and items:
                cached = items
        _AGENTS = _load_all_agents(devices=cached)
    finally:
        _agents_ready.set()


def _kick_agents_loader():
    """Start the agents loader thread once (locked one-shot)."""
    global _agents_loader_started
    with _agents_loader_lock:
        if _agents_loader_started:
            return
        _agents_loader_started = True
    threading.Thread(
        target=_load_agents_async,
        name="wazuh-overview-agents-loader",
        daemon=True,
    ).start()


# ------------------------------------------------------------------------------
#  Live /api/v1/me/* remote-data cache. Each slot has its own readiness Event so
#  the Overview poll can rebuild cards as each endpoint lands; a per-slot error
#  string lets cards render "Couldn't load" instead of looping on "Loading…".
# ------------------------------------------------------------------------------
_REMOTE_AGENT = None
_REMOTE_AGENT_ERROR = None
_remote_agent_ready = threading.Event()

_REMOTE_VULNS = []
_REMOTE_VULNS_ERROR = None
_remote_vulns_ready = threading.Event()

# Group-level vulnerability summary (by_severity counts). Lands ~4x faster than
# the per-device fan-out, so the Overview vuln card paints from this.
_REMOTE_VULNS_SUMMARY = None
_REMOTE_VULNS_SUMMARY_ERROR = None
_remote_vulns_summary_ready = threading.Event()

_REMOTE_SCA = []
_REMOTE_SCA_ERROR = None
_remote_sca_ready = threading.Event()

_REMOTE_INVENTORY = {"total": 0, "items": []}
_REMOTE_INVENTORY_ERROR = None
_remote_inventory_ready = threading.Event()

_REMOTE_HOTFIXES = []
_REMOTE_HOTFIXES_ERROR = None
_remote_hotfixes_ready = threading.Event()

# Vulnerability detection events. Two-phase load: phase-1 (local device) fires
# _remote_vuln_events_ready; phase-2 (rest of group) fires _..._complete.
_REMOTE_VULN_EVENTS = []
_REMOTE_VULN_EVENTS_ERROR = None
_remote_vuln_events_ready = threading.Event()
_remote_vuln_events_complete = threading.Event()

# One-shot loader guards.
_overview_early_loader_started = False
_overview_early_loader_lock = threading.Lock()
_vuln_events_phase2_started = False
_vuln_events_phase2_lock = threading.Lock()
_vulns_loader_started = False
_vulns_loader_lock = threading.Lock()


def _wait_for_vpn(poll_interval=2.0, timeout=60.0):
    """Wait (up to ``timeout``) for the VPN tunnel — the /me/* host is only
    reachable through it. Fails SAFE: if VPN state can't be confirmed, proceed
    anyway and let the GETs surface real connectivity errors."""
    try:
        from plugins.vpn.main import is_vpn_connected
    except ImportError:
        logger.warning(
            "[WAZUH-OVERVIEW] VPN plugin unavailable; preloader proceeding without VPN gate"
        )
        return

    if is_vpn_connected():
        return
    logger.info(
        "[WAZUH-OVERVIEW] Preloader waiting for VPN tunnel before fetching /me/* endpoints"
    )
    waited = 0.0
    while not is_vpn_connected():
        if waited >= timeout:
            logger.warning(
                f"[WAZUH-OVERVIEW] VPN not confirmed after {timeout:.0f}s — preloader "
                "proceeding anyway; GETs will surface real connectivity errors if the "
                "tunnel is down"
            )
            return
        time.sleep(poll_interval)
        waited += poll_interval
    logger.info("[WAZUH-OVERVIEW] VPN tunnel up — preloader proceeding")


def _load_overview_early_async():
    """Fetch all /me/* endpoints in parallel, after waiting for the VPN.

    Inventory is fetched once and cached; the summary card is derived from it
    and the cached list is fed into the vuln fan-out so three list calls become
    one. The remaining four endpoints (agent, sca, hotfixes, vulns-summary) fan
    out on a thread pool, each setting its readiness Event on completion so the
    Overview cards paint in arrival order."""
    _wait_for_vpn()

    devices, devices_err = api_client.fetch_inventory_full()

    global _REMOTE_INVENTORY, _REMOTE_INVENTORY_ERROR
    if devices is None:
        _REMOTE_INVENTORY_ERROR = devices_err
    else:
        _REMOTE_INVENTORY = {"total": len(devices), "items": list(devices)}
    _remote_inventory_ready.set()

    def _do_agent():
        global _REMOTE_AGENT, _REMOTE_AGENT_ERROR
        _REMOTE_AGENT, _REMOTE_AGENT_ERROR = api_client.fetch_agent()
        _remote_agent_ready.set()

    def _do_sca():
        global _REMOTE_SCA, _REMOTE_SCA_ERROR
        data, err = api_client.fetch_sca()
        if data is not None:
            _REMOTE_SCA = data
        _REMOTE_SCA_ERROR = err
        _remote_sca_ready.set()

    def _do_hotfixes():
        global _REMOTE_HOTFIXES, _REMOTE_HOTFIXES_ERROR
        data, err = api_client.fetch_hotfixes()
        if data is not None:
            _REMOTE_HOTFIXES = data
        _REMOTE_HOTFIXES_ERROR = err
        _remote_hotfixes_ready.set()

    def _do_vulns_summary():
        global _REMOTE_VULNS_SUMMARY, _REMOTE_VULNS_SUMMARY_ERROR
        data, err = api_client.fetch_vulnerabilities_summary()
        if data is not None:
            _REMOTE_VULNS_SUMMARY = data
        _REMOTE_VULNS_SUMMARY_ERROR = err
        _remote_vulns_summary_ready.set()

    with ThreadPoolExecutor(max_workers=4) as ex:
        futures = [
            ex.submit(_do_agent),
            ex.submit(_do_sca),
            ex.submit(_do_hotfixes),
            ex.submit(_do_vulns_summary),
        ]
        for f in as_completed(futures):
            try:
                f.result()
            except Exception as e:
                logger.error(f"[WAZUH-OVERVIEW] preloader thread crashed: {e}")


def _load_vuln_events_phase1_async():
    """Eager Phase 1: pull the LOCAL device's vuln-detection events, then set
    _remote_vuln_events_ready so the Events tab can render immediately."""
    global _vuln_events_phase2_started, _REMOTE_VULN_EVENTS_ERROR

    _remote_agent_ready.wait()
    local_id = (_REMOTE_AGENT or {}).get("id") if isinstance(_REMOTE_AGENT, dict) else None
    if not local_id:
        logger.warning(
            "[WAZUH-OVERVIEW] No local agent id — skipping vuln-events fetch"
        )
        _REMOTE_VULN_EVENTS_ERROR = "no local agent"
        _remote_vuln_events_ready.set()
        _remote_vuln_events_complete.set()
        with _vuln_events_phase2_lock:
            _vuln_events_phase2_started = True
        return

    global _REMOTE_VULN_EVENTS
    local_events, err = api_client.fetch_device_vulnerability_events(
        local_id, hours=EVENTS_WINDOW_HOURS
    )
    _REMOTE_VULN_EVENTS_ERROR = err
    if err:
        # Without this the tab renders an empty stream that's indistinguishable
        # from a genuine "no events in the window".
        logger.warning(
            f"[WAZUH-OVERVIEW] Vuln-events fetch for local agent {local_id} failed: {err}"
        )
    else:
        normalized = [_normalize_wazuh_hit(h) for h in (local_events or [])]
        normalized.sort(key=lambda e: e.get("timestamp") or "", reverse=True)
        _REMOTE_VULN_EVENTS = normalized
    _remote_vuln_events_ready.set()


def _load_vuln_events_phase2_async():
    """Lazy Phase 2: fan out the rest of the group's devices, merging into
    _REMOTE_VULN_EVENTS by atomic rebind (single coordinator thread, no lock)."""
    global _REMOTE_VULN_EVENTS

    _remote_inventory_ready.wait()
    local_id = (_REMOTE_AGENT or {}).get("id") if isinstance(_REMOTE_AGENT, dict) else None
    items = _REMOTE_INVENTORY.get("items") if isinstance(_REMOTE_INVENTORY, dict) else []
    other_ids = [
        d.get("agent_id")
        for d in (items or [])
        if d.get("agent_id") and d.get("agent_id") != local_id
    ]
    if not other_ids:
        _remote_vuln_events_complete.set()
        return

    workers = min(len(other_ids), MAX_PARALLEL_FETCHES)
    with ThreadPoolExecutor(max_workers=workers) as ex:
        future_to_aid = {
            ex.submit(
                api_client.fetch_device_vulnerability_events,
                aid,
                hours=EVENTS_WINDOW_HOURS,
            ): aid
            for aid in other_ids
        }
        for future in as_completed(future_to_aid):
            aid = future_to_aid[future]
            events, derr = future.result()
            if derr:
                logger.warning(
                    f"[WAZUH-OVERVIEW] Vuln-events fetch for agent {aid} failed: {derr}"
                )
                continue
            new_normalized = [_normalize_wazuh_hit(h) for h in (events or [])]
            if not new_normalized:
                continue
            merged = _REMOTE_VULN_EVENTS + new_normalized
            merged.sort(key=lambda e: e.get("timestamp") or "", reverse=True)
            _REMOTE_VULN_EVENTS = merged

    _remote_vuln_events_complete.set()


def _kick_overview_early_loader():
    """Idempotent: spawn the preloader + Phase-1 events thread at most once."""
    global _overview_early_loader_started
    with _overview_early_loader_lock:
        if _overview_early_loader_started:
            return
        _overview_early_loader_started = True
    threading.Thread(
        target=_load_overview_early_async,
        name="wazuh-overview-preloader",
        daemon=True,
    ).start()
    threading.Thread(
        target=_load_vuln_events_phase1_async,
        name="wazuh-overview-vuln-events-phase1",
        daemon=True,
    ).start()


def _kick_vuln_events_phase2_loader():
    """Idempotent: spawn the Events-tab Phase 2 fan-out at most once."""
    global _vuln_events_phase2_started
    with _vuln_events_phase2_lock:
        if _vuln_events_phase2_started:
            return
        _vuln_events_phase2_started = True
    threading.Thread(
        target=_load_vuln_events_phase2_async,
        name="wazuh-overview-vuln-events-phase2",
        daemon=True,
    ).start()


def _load_vulns_async():
    """Lazy loader for the Vulnerabilities tab's per-device CVE fan-out."""
    global _REMOTE_VULNS, _REMOTE_VULNS_ERROR

    _remote_inventory_ready.wait()
    items = _REMOTE_INVENTORY.get("items") if isinstance(_REMOTE_INVENTORY, dict) else []
    data, err = api_client.fetch_all_vulnerabilities(devices=items)
    if data is not None:
        _REMOTE_VULNS = data
    _REMOTE_VULNS_ERROR = err
    _remote_vulns_ready.set()


def _kick_vulns_loader():
    """Idempotent: spawn the Vulnerabilities-tab CVE fan-out at most once."""
    global _vulns_loader_started
    with _vulns_loader_lock:
        if _vulns_loader_started:
            return
        _vulns_loader_started = True
    threading.Thread(
        target=_load_vulns_async,
        name="wazuh-overview-vulns-loader",
        daemon=True,
    ).start()


def _kick_overview_api_loader():
    """Back-compat alias for tab-entry kicks; delegates to the idempotent kick."""
    _kick_overview_early_loader()


def refresh_all_remote_data():
    """Reset the one-shot loader guards and re-kick every loader. Readiness
    events stay SET and globals stay populated until each rebind, so the UI
    keeps showing stale values (no "Loading…" flash) until fresh data lands."""
    global _overview_early_loader_started, _vulns_loader_started
    global _vuln_events_phase2_started, _agents_loader_started
    global _REMOTE_VULN_EVENTS_ERROR

    _REMOTE_VULN_EVENTS_ERROR = None

    with _overview_early_loader_lock:
        _overview_early_loader_started = False
    with _vulns_loader_lock:
        _vulns_loader_started = False
    with _vuln_events_phase2_lock:
        _vuln_events_phase2_started = False
    with _agents_loader_lock:
        _agents_loader_started = False

    _kick_overview_early_loader()
    _kick_vulns_loader()
    _kick_vuln_events_phase2_loader()
    _kick_agents_loader()


def _ready_mask():
    """Bitmask of which Overview slots have completed (data or error)."""
    return (
        (1 if _remote_agent_ready.is_set() else 0)
        | (2 if _remote_vulns_summary_ready.is_set() else 0)
        | (4 if _remote_sca_ready.is_set() else 0)
        | (8 if _remote_inventory_ready.is_set() else 0)
        | (16 if _remote_hotfixes_ready.is_set() else 0)
        # Phase-1 vuln events back the Security Alerts card. Included so the
        # readiness poll keeps repainting until they land (they arrive after the
        # agent fetch, so they're usually the last slot to complete).
        | (32 if _remote_vuln_events_ready.is_set() else 0)
    )


_READY_ALL = 63  # all 6 slots set


def _overview_has_errors():
    """True if any of the five Overview slots completed with an error."""
    return any(
        (
            _REMOTE_AGENT_ERROR,
            _REMOTE_VULNS_SUMMARY_ERROR,
            _REMOTE_SCA_ERROR,
            _REMOTE_INVENTORY_ERROR,
            _REMOTE_HOTFIXES_ERROR,
        )
    )


def _format_relative(iso_ts):
    """Compact 'X ago' string from an ISO-8601 timestamp."""
    if not iso_ts:
        return "—"
    try:
        dt = datetime.fromisoformat(iso_ts.replace("Z", "+00:00"))
    except ValueError:
        return iso_ts
    now = datetime.now(timezone.utc)
    sec = int((now - dt).total_seconds())
    if sec < 0:
        return "in the future"
    if sec < 60:
        return "just now"
    if sec < 3600:
        return f"{sec // 60}m ago"
    if sec < 86400:
        return f"{sec // 3600}h ago"
    days = sec // 86400
    if days == 1:
        return "1 day ago"
    if days < 30:
        return f"{days} days ago"
    months = days // 30
    if months < 12:
        return f"{months} mo ago"
    return f"{months // 12}y ago"


def _format_timestamp(iso_ts):
    """Format an ISO-8601 timestamp as 'MMM DD HH:MM:SS' in local time.

    Wazuh timestamps are UTC (trailing 'Z'); render them in the viewer's local
    timezone so the displayed date/time matches their wall clock rather than
    reading a few hours (and sometimes a whole calendar day) off."""
    if not iso_ts:
        return "—"
    try:
        dt = datetime.fromisoformat(iso_ts.replace("Z", "+00:00"))
    except ValueError:
        return iso_ts
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone().strftime("%b %d %H:%M:%S")


def _short_benchmark_name(name):
    """Tidy a CIS-style policy name."""
    if not name:
        return ""
    return name.replace("_", " ").replace("Apple ", "")


# ----- module-card state helpers ----------------------------------------------
def _status_card(title, description, stat_text, target_tab=None):
    card = {
        "title": title,
        "status": "INFO",
        "description": description,
        "stats": ((stat_text, "muted"),),
    }
    if target_tab:
        card["target_tab"] = target_tab
    return card


def _unavailable_card(title, description, target_tab=None):
    return _status_card(title, description, "Data unavailable", target_tab)


def _loading_card(title, description, target_tab=None):
    return _status_card(title, description, "Loading…", target_tab)


def _error_card(title, description, target_tab=None):
    return _status_card(title, description, "Couldn't load", target_tab)


def _bucket_by_severity(items):
    counts = {lvl: 0 for lvl in _SEVERITY_LEVELS}
    for it in items:
        sev = (it.get("severity") or "").lower() if isinstance(it, dict) else ""
        if sev in counts:
            counts[sev] += 1
    return counts


def _severity_stats(counts):
    """Render a counts dict into the (text, color_key) tuples the card stats use."""
    stats = []
    for level in _SEVERITY_LEVELS:
        cnt = counts.get(level, 0)
        if not cnt:
            continue
        if stats:
            stats.append(("  ·  ", "muted"))
        stats.append((f"{cnt} {level}", _SEVERITY_THEME_KEY.get(level, "info")))
    return tuple(stats)


def _is_windows_agent():
    """Best-effort: prefer the agent's reported OS; fall back to local platform."""
    if _remote_agent_ready.is_set() and isinstance(_REMOTE_AGENT, dict):
        os_info = _REMOTE_AGENT.get("os") or {}
        platform_name = (os_info.get("platform") or os_info.get("name") or "").lower()
        if platform_name:
            return "windows" in platform_name
    return _platform.system() == "Windows"


# ==============================================================================
#  Small PyQt building blocks
# ==============================================================================
def _clear_layout(layout):
    """Remove and delete every widget/child-layout in ``layout``."""
    while layout.count():
        item = layout.takeAt(0)
        w = item.widget()
        if w is not None:
            w.setParent(None)
            w.deleteLater()
        else:
            child = item.layout()
            if child is not None:
                _clear_layout(child)
                child.deleteLater()


def _label(text, *, size=13, bold=False, color=None, secondary=False, wrap=False):
    """QLabel with inline font/colour styling (severity colours aren't static
    QSS, so inline is the cleanest way to carry them)."""
    lbl = QLabel(str(text))
    lbl.setWordWrap(wrap)
    parts = [f"font-size:{size}px", "background:transparent"]
    if bold:
        parts.append("font-weight:700")
    if color:
        parts.append(f"color:{color}")
    elif secondary:
        parts.append(f"color:{theme.color('text_secondary')}")
    lbl.setStyleSheet("QLabel{" + ";".join(parts) + ";}")
    return lbl


def _pill(text, bg, fg, *, size=11):
    lbl = QLabel(str(text))
    lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
    lbl.setSizePolicy(QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Fixed)
    lbl.setStyleSheet(
        "QLabel{"
        f"background-color:{bg};color:{fg};border-radius:6px;"
        f"padding:3px 10px;font-size:{size}px;font-weight:700;"
        "}"
    )
    return lbl


class _ModuleCard(QFrame):
    """A clickable Overview module card. Emits its target tab on click by
    calling ``on_click`` (a plain callable) — avoids a signal for one consumer."""

    def __init__(self, card_data, on_click=None):
        super().__init__()
        self.setObjectName("Card")
        self._target = card_data.get("target_tab")
        self._on_click = on_click if (self._target and on_click) else None
        if self._on_click:
            self.setCursor(Qt.CursorShape.PointingHandCursor)
        # Stretch to fill each grid half; height follows content with a floor
        # for a uniform tile look.
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        self.setMinimumHeight(140)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(16, 16, 16, 16)
        lay.setSpacing(6)

        # Row 0: title + status badge
        top = QHBoxLayout()
        top.setContentsMargins(0, 0, 0, 0)
        top.addWidget(_label(card_data["title"], size=16, bold=True))
        top.addStretch(1)
        bg, fg = _badge_colors(card_data["status"])
        top.addWidget(_pill(f"●  {card_data['status']}", bg, fg))
        lay.addLayout(top)

        # Row 1: description
        lay.addWidget(_label(card_data["description"], size=12, secondary=True, wrap=True))
        lay.addStretch(1)

        # Row 2: stats + arrow
        bottom = QHBoxLayout()
        bottom.setContentsMargins(0, 0, 0, 0)
        bottom.setSpacing(0)
        for text, color_key in card_data["stats"]:
            bottom.addWidget(
                _label(text, size=13, bold=color_key != "muted",
                       color=_segment_color(color_key))
            )
        bottom.addStretch(1)
        if self._on_click:
            bottom.addWidget(_label("›", size=20, secondary=True))
        lay.addLayout(bottom)

    def mousePressEvent(self, event):  # noqa: N802 - Qt override
        if self._on_click and event.button() == Qt.MouseButton.LeftButton:
            self._on_click(self._target)
        super().mousePressEvent(event)


class _ClickableFrame(QFrame):
    """A QFrame that invokes ``on_click`` when left-clicked. Used for event /
    (later) vuln list rows so the whole row is a hit target."""

    def __init__(self, on_click):
        super().__init__()
        self._on_click = on_click
        self.setCursor(Qt.CursorShape.PointingHandCursor)

    def mousePressEvent(self, event):  # noqa: N802 - Qt override
        if event.button() == Qt.MouseButton.LeftButton:
            self._on_click()
        super().mousePressEvent(event)


class SeveritySelection:
    """Single source of truth for a 'one severity level or none' filter.

    Owned per-tab: the Vulnerabilities donut/timeline and the Events header pills
    each hold an instance and pass an ``on_change`` callback that repaints *their*
    own widgets and re-renders *their* own list. The toggle rule and the row
    predicate live here once, so the three widgets are thin call sites rather than
    three copies of the same logic. Zero-count guarding is the caller's job (it
    mirrors how a zero-height chart bar is naturally unclickable)."""

    def __init__(self, on_change=None):
        self.selected = None            # str | None, lowercase severity level
        self._on_change = on_change

    def toggle(self, level):
        # Clicking the active level clears it; clicking another switches to it.
        self.selected = None if self.selected == level else level
        if self._on_change:
            self._on_change()

    def clear(self):
        # Silent reset (no on_change) — used at pane (re)build time, before the
        # widgets on_change would repaint exist.
        self.selected = None

    def matches(self, severity):
        if self.selected is None:
            return True
        return (severity or "").lower() == self.selected


def _rows_scroll():
    """A vertical QScrollArea + a top-aligned rows container. Returns
    (scroll_area, rows_layout) — clear/repopulate rows_layout to refresh."""
    area = QScrollArea()
    area.setWidgetResizable(True)
    area.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
    host = QWidget()
    host.setObjectName("Transparent")
    lay = QVBoxLayout(host)
    lay.setContentsMargins(4, 4, 4, 4)
    lay.setSpacing(2)
    lay.addStretch(1)  # keeps rows top-aligned; always the last item
    area.setWidget(host)
    return area, lay


# _ResponsiveStack moved to gui.qt_widgets.ResponsiveStack


class _ModuleGrid(QWidget):
    """Holds the module tiles in a responsive grid whose column count follows
    the 1->2->3->4 width ladder, with card row heights driven off the column
    width so tiles stay ~square (160-300px clamp). Ported from
    endpoint/design_test2's _populate_module_grid/_bind_module_aspect_ratio.
    """

    def __init__(self):
        super().__init__()
        self.setObjectName("Transparent")
        self._cards = []
        self._cols = None
        self._grid = QGridLayout(self)
        self._grid.setContentsMargins(0, 0, 0, 0)
        self._grid.setSpacing(16)
        self._debounce = QTimer(self)
        self._debounce.setSingleShot(True)
        self._debounce.setInterval(_RESIZE_DEBOUNCE_MS)
        self._debounce.timeout.connect(self._relayout)

    def resizeEvent(self, event):  # noqa: N802 - Qt override
        super().resizeEvent(event)
        self._debounce.start()

    def set_cards(self, cards):
        # Delete the previous tiles outright — detaching from the layout alone
        # leaves them parented here, painted at their old geometry, so they'd
        # stack behind the new ones on every repaint.
        while self._grid.count():
            item = self._grid.takeAt(0)
            w = item.widget()
            if w is not None:
                w.setParent(None)
                w.deleteLater()
        self._cards = list(cards)
        self._cols = None  # force a fresh layout pass
        self._relayout(force=True)

    def _target_cols(self):
        """Column count for the module grid: 2 columns until the app window spans
        ≥80% of the screen width, then expand so every card shares one row. Gated
        on the screen width (not the grid's own width), mirroring how the timeline
        scales its day-span off the screen."""
        n = len(self._cards)
        if n <= 1:
            return 1
        win = self.window()
        screen = self.screen()
        if win is not None and screen is not None:
            screen_w = screen.availableGeometry().width()
            if screen_w > 0 and win.width() >= _MODULE_GRID_EXPAND_SCREEN_FRAC * screen_w:
                return min(n, 4)
        return 2

    def _relayout(self, force=False):
        if not self._cards:
            return
        cols = max(1, min(self._target_cols(), len(self._cards)))
        if not force and cols == self._cols:
            self._apply_row_heights(cols)
            return
        self._cols = cols

        # Re-grid without destroying the cards (state-preserving relayout).
        while self._grid.count():
            self._grid.takeAt(0)
        for c in range(4):
            self._grid.setColumnStretch(c, 1 if c < cols else 0)
        for i, card in enumerate(self._cards):
            self._grid.addWidget(card, i // cols, i % cols)
        self._apply_row_heights(cols)

    def _apply_row_heights(self, cols):
        # Square-ish tiles: row height tracks column width, clamped.
        col_w = max(1, (self.width() - 16 * (cols - 1)) / cols)
        target_h = max(_CARD_MIN_H, min(_CARD_MAX_H, int(col_w) + 20))
        rows = (len(self._cards) + cols - 1) // cols
        for r in range(rows):
            self._grid.setRowMinimumHeight(r, target_h)


# ==============================================================================
#  Plugin
# ==============================================================================
class Plugin(BasePlugin):
    """Wazuh Overview — multi-tab security-posture dashboard."""

    def __init__(self, app):
        super().__init__(
            id="013",
            version="2026.07.01",
            order=5.5,
            name="Wazuh",
            status=None,
            description="Security posture across your device group.",
            supported_systems=["Darwin", "Linux", "Windows"],
            translations={"US": "Wazuh", "ES": "Wazuh", "FR": "Wazuh"},
            icon_light_path=os.path.join(_WAZUH_DIR, "wazuh_light.png"),
            icon_dark_path=os.path.join(_WAZUH_DIR, "wazuh_dark.png"),
            uninstall_enabled=True,
        )
        self.app = app
        self._tabs = None
        self._tab_stack = None
        self._tab_buttons = {}
        self._tab_built = {name: False for name in _TAB_NAMES}
        self._tab_pages = {}
        # Per-tab synthetic progress ramps for loaders that only signal
        # done/not-done. Created lazily, reset when a tab reloads.
        self._tab_ramps = {}
        # Mounted loading screens, by tab name. Popped when swapped for content.
        self._loading_screens = {}

        # Overview state
        self._overview_ready_mask = -1
        self._overview_poll_token = None
        self._device_holder = None
        self._alert_holder = None
        self._module_grid = None
        self._refresh_button = None

        # Events state
        self._ev_page_widget = None      # the tab page (for loading→content swap)
        self._ev_search = None           # QLineEdit
        self._ev_search_token = None     # debounce handle
        self._ev_count_label = None
        self._ev_pill_labels = {}        # severity -> count QLabel
        self._ev_pill_frames = {}        # severity -> clickable pill QFrame
        self._ev_sev_sel = SeveritySelection(self._on_ev_severity_change)
        self._ev_rows_layout = None      # QVBoxLayout holding event rows
        self._ev_row_frames = {}         # event id -> row QFrame
        self._ev_detail_holder = None    # QWidget wrapping the detail card
        self._ev_pager_holder = None
        self._ev_selected_id = None
        self._ev_selected_bucket = None  # datetime of active hour filter, or None
        self._ev_page = 1
        self._ev_chart_canvas = None
        self._ev_chart_fig = None
        self._ev_chart_ax = None
        self._ev_buckets = []
        self._ev_counts = {}
        self._ev_ready_token = None
        self._ev_last_seen_id = None     # id(_REMOTE_VULN_EVENTS) at last render

        # Vulnerabilities state
        self._vuln_page_widget = None
        self._vuln_search = None
        self._vuln_search_token = None
        self._vuln_count_label = None
        self._vuln_sev_sel = SeveritySelection(self._on_vuln_severity_change)
        self._vuln_donut_fig = None
        self._vuln_donut_canvas = None
        self._vuln_donut_ax = None
        self._vuln_donut_wedges = []     # (wedge_artist, severity) pairs
        self._vuln_cvss_fig = None
        self._vuln_cvss_canvas = None
        self._vuln_cvss_ax = None
        self._vuln_cvss_bars = []        # (bar_container, severity) pairs
        self._vuln_cvss_hover_annot = None  # matplotlib tooltip annotation
        self._vuln_cvss_hover_key = None    # (bucket_idx, severity) under cursor
        self._vuln_cvss_buckets = []        # date per x-index (for the tooltip)
        self._vuln_cvss_counts = {}         # bucket date -> {severity: count}
        self._vuln_rows_layout = None
        self._vuln_row_frames = {}
        self._vuln_detail_holder = None
        self._vuln_pager_holder = None
        self._vuln_selected_key = None
        self._vuln_page = 1
        self._vuln_ready_token = None

        # Inventory state
        self._inv_page_widget = None
        self._inv_view = "Devices"
        self._inv_group = "All groups"
        self._inv_page = 1
        self._inv_count_label = None
        self._inv_rows_layout = None
        self._inv_pager_holder = None
        self._inv_body_holder = None     # column header + list (rebuilt on change)
        self._inv_ready_token = None

    def check_status(self):
        return None

    def on_theme_changed(self):
        """Rebuild the Wazuh Overview screen on theme toggle to re-render charts and colors."""
        if getattr(self, "app", None):
            self.app.update_plugin(self.id)

    # ----- screen scaffold ---------------------------------------------------
    def create_main_screen(self):
        self._cancel_pending_ui_callbacks()
        self._tabs = None
        self._tab_stack = None
        self._tab_buttons = {}
        self._tab_built = {name: False for name in _TAB_NAMES}
        self._tab_pages = {}

        # Global device filter shared by every tab (strip selector). Tracks the
        # scope each built tab was last rendered at so a scope change made on one
        # tab re-applies to the others when they're next shown. Defaults to the
        # local device once the roster lands, unless the user picks something
        # first (_device_scope_user_set guards against overriding their choice).
        self._device_scope = self._DEVICE_ALL
        self._device_scope_user_set = False
        self._device_combo = None
        self._tab_rendered_scope = {}
        self._active_tab = None

        self._tab_ramps = {}
        self._loading_screens = {}

        self._overview_poll_token = None
        self._device_holder = None
        self._alert_holder = None
        self._module_grid = None
        self._refresh_button = None

        self._ev_page_widget = None
        self._ev_search = None
        self._ev_count_label = None
        self._ev_pill_labels = {}
        self._ev_pill_frames = {}
        self._ev_sev_sel = SeveritySelection(self._on_ev_severity_change)
        self._ev_rows_layout = None
        self._ev_row_frames = {}
        self._ev_detail_holder = None
        self._ev_pager_holder = None
        self._ev_chart_canvas = None
        self._ev_chart_fig = None
        self._ev_chart_ax = None

        self._vuln_page_widget = None
        self._vuln_search = None
        self._vuln_count_label = None
        self._vuln_sev_sel = SeveritySelection(self._on_vuln_severity_change)
        self._vuln_donut_fig = None
        self._vuln_donut_canvas = None
        self._vuln_donut_ax = None
        self._vuln_cvss_fig = None
        self._vuln_cvss_canvas = None
        self._vuln_cvss_ax = None
        self._vuln_cvss_bars = []
        self._vuln_cvss_hover_annot = None
        self._vuln_cvss_hover_key = None
        self._vuln_cvss_buckets = []
        self._vuln_cvss_counts = {}
        self._vuln_rows_layout = None
        self._vuln_row_frames = {}
        self._vuln_detail_holder = None
        self._vuln_pager_holder = None

        self._inv_page_widget = None
        self._inv_count_label = None
        self._inv_rows_layout = None
        self._inv_pager_holder = None
        self._inv_body_holder = None

        root = QWidget()
        # Explicit theme background (NOT Transparent): document-mode QTabBar
        # ignores background rules on some styles, so the strip showed the
        # dark ancestor colour as a black band in light mode. Painting the
        # page root guarantees the bar row sits on the theme background.
        root.setObjectName("WazuhOverviewRoot")
        root.setStyleSheet(
            f"#WazuhOverviewRoot{{background:{theme.color('window_bg')};}}")
        outer = QVBoxLayout(root)
        # Breathing room so the tab bar doesn't sit flush against the window
        # title bar (top) or the content edges (sides).
        outer.setContentsMargins(16, 14, 16, 0)
        outer.setSpacing(0)

        # Custom tab strip (plain QPushButtons + accent underline) over a
        # QStackedWidget. QTabBar paints natively on macOS and repeatedly
        # ignored both stylesheet AND palette backgrounds (the persistent
        # black band in light mode) — a hand-rolled strip is fully ours.
        strip = QWidget()
        strip.setObjectName("Transparent")
        strip_lay = QHBoxLayout(strip)
        strip_lay.setContentsMargins(0, 0, 0, 0)
        strip_lay.setSpacing(28)
        self._tab_buttons = {}
        for name in _TAB_NAMES:
            btn = QPushButton(name)
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.setFlat(True)
            btn.clicked.connect(lambda _=False, n=name: self._switch_tab(n))
            strip_lay.addWidget(btn)
            self._tab_buttons[name] = btn
        strip_lay.addStretch(1)

        # Global device selector, pinned top-right of the strip so it's easy to
        # find and applies to every tab (see _on_device_scope_change). Starts with
        # just "All devices" and fills in via _refresh_device_combo as the device
        # roster lands (the strip is built before inventory is ready).
        self._device_combo = QComboBox()
        self._device_combo.setCursor(Qt.CursorShape.PointingHandCursor)
        self._device_combo.setMaximumWidth(240)
        self._device_combo.addItem(self._DEVICE_ALL)
        self._device_combo.setCurrentText(self._device_scope)
        self._device_combo.currentTextChanged.connect(self._on_device_scope_change)
        strip_lay.addWidget(self._device_combo, 0, Qt.AlignmentFlag.AlignVCenter)
        self._refresh_device_combo()

        outer.addWidget(strip)

        hairline = QFrame()
        hairline.setFixedHeight(1)
        hairline.setStyleSheet(f"background:{theme.color('border')};")
        outer.addWidget(hairline)

        self._tab_stack = QStackedWidget()
        for name in _TAB_NAMES:
            page = QWidget()
            page.setObjectName("Transparent")
            lay = QVBoxLayout(page)
            lay.setContentsMargins(0, 0, 0, 0)
            self._tab_pages[name] = page
            self._tab_stack.addWidget(page)
        outer.addWidget(self._tab_stack, 1)
        self._tabs = self._tab_stack  # legacy attr; guarded by _switch_tab
        self._active_tab = None
        self._style_tab_buttons("Overview")

        # Build the default tab now; others build lazily on first activation.
        self._ensure_tab_built("Overview")
        return root

    def _style_tab_buttons(self, active):
        """Underline style, painted by us: accent + bold when active."""
        self._active_tab = active
        for name, btn in self._tab_buttons.items():
            try:
                if name == active:
                    btn.setStyleSheet(
                        "QPushButton{background:transparent;border:none;"
                        f"color:{theme.color('accent')};font-size:14px;"
                        "font-weight:700;padding:9px 2px 7px 2px;"
                        f"border-bottom:2px solid {theme.color('accent')};"
                        "border-radius:0;}")
                else:
                    btn.setStyleSheet(
                        "QPushButton{background:transparent;border:none;"
                        f"color:{theme.color('text_secondary')};font-size:14px;"
                        "padding:9px 2px 9px 2px;border-radius:0;}"
                        "QPushButton:hover{"
                        f"color:{theme.color('text_primary')};}}")
            except RuntimeError:
                pass

    def _ensure_tab_built(self, name):
        if self._tab_built.get(name):
            return
        page = self._tab_pages.get(name)
        if page is None:
            return
        builder = {
            "Overview": self._build_overview_pane,
            "Events": self._build_events_pane,
            "Vulnerabilities": self._build_vulnerabilities_pane,
            "Inventory": self._build_inventory_pane,
        }.get(name)
        if builder is None:
            return
        try:
            builder(page, name)
            self._tab_built[name] = True
            self._tab_rendered_scope[name] = self._device_scope
        except Exception as e:
            logger.error(f"Wazuh Overview: building '{name}' pane failed: {e}")
            self._tab_built[name] = True  # don't retry forever

    def _switch_tab(self, name):
        if name not in _TAB_NAMES or self._tab_stack is None:
            return
        already_built = self._tab_built.get(name, False)
        self._ensure_tab_built(name)
        # A device scope picked while another tab was showing hasn't been applied
        # here yet — re-render this tab at the current scope on the way in.
        scope_changed = (already_built
                         and self._tab_rendered_scope.get(name) != self._device_scope)
        if scope_changed:
            self._apply_scope_to_tab(name)
        # The timeline chart's date window is anchored to "today"; re-render it
        # when revisiting the Vulnerabilities tab so it tracks the current date
        # rather than freezing at the date the pane was first built. (First
        # build already renders it, so only refresh on later visits. A scope
        # rebuild above already re-rendered it, so skip the double draw.)
        elif name == "Vulnerabilities" and already_built and self._vuln_cvss_ax is not None:
            self._render_vuln_cvss()
        self._tab_stack.setCurrentIndex(_TAB_NAMES.index(name))
        self._style_tab_buttons(name)

    # ----- global device selector --------------------------------------------
    def _default_device_scope(self, roster):
        """The scope to select by default: the local device when it's in the
        roster, else 'All devices'."""
        if isinstance(_REMOTE_AGENT, dict):
            local = _REMOTE_AGENT.get("name")
            if local and local in roster:
                return local
        return self._DEVICE_ALL

    def _refresh_device_combo(self):
        """Sync the strip selector's items with the current device roster,
        preserving the selection. Called by the tab pollers as devices land.
        The first time the roster carries real devices, the scope defaults to
        the local device (unless the user has already picked one)."""
        combo = self._device_combo
        if combo is None:
            return
        roster = self._device_roster()
        if not self._device_scope_user_set and self._device_scope == self._DEVICE_ALL:
            default = self._default_device_scope(roster)
            if default != self._device_scope:
                self._device_scope = default
                # Re-render the visible tab so it reflects the resolved default.
                if self._active_tab and self._tab_built.get(self._active_tab):
                    self._apply_scope_to_tab(self._active_tab)
        if self._device_scope not in roster:
            self._device_scope = self._DEVICE_ALL
        current = [combo.itemText(i) for i in range(combo.count())]
        if current == roster and combo.currentText() == self._device_scope:
            return
        combo.blockSignals(True)
        try:
            combo.clear()
            combo.addItems(roster)
            combo.setCurrentText(self._device_scope)
        finally:
            combo.blockSignals(False)

    def _on_device_scope_change(self, name):
        if not name or name == self._device_scope:
            return
        self._device_scope = name
        self._device_scope_user_set = True
        # A narrowed list should start at its first page on every tab.
        self._ev_page = 1
        self._vuln_page = 1
        self._inv_page = 1
        # Re-render the visible tab now; the rest re-render on their next visit
        # (tracked via _tab_rendered_scope in _switch_tab).
        if self._active_tab:
            self._apply_scope_to_tab(self._active_tab)

    def _apply_scope_to_tab(self, name):
        """Re-render tab ``name`` at the current device scope, using each tab's
        cheapest in-place refresh where one exists."""
        if not self._tab_built.get(name):
            return
        page = self._tab_pages.get(name)
        try:
            if name == "Overview":
                self._rebuild_device_card()
                self._rebuild_alert_bar()
                self._populate_module_grid()
            elif name == "Events":
                if self._ev_page_widget is not None and _remote_vuln_events_ready.is_set():
                    self._update_severity_pills()
                    self._ev_buckets, self._ev_counts = self._bucket_events_24h_hourly()
                    self._render_event_chart()
                    self._render_event_list()
            elif name == "Vulnerabilities":
                if page is not None:
                    self._build_vulnerabilities_pane(page)
            elif name == "Inventory":
                if self._inv_body_holder is not None:
                    self._render_inventory_body()
                elif page is not None:
                    self._build_inventory_pane(page)
        except Exception as e:
            logger.error(f"Wazuh Overview: applying scope to '{name}' failed: {e}")
        self._tab_rendered_scope[name] = self._device_scope

    # ----- loading screens ---------------------------------------------------
    def _tab_ramp(self, name, *, restart=False):
        """The synthetic progress ramp for ``name``, created on first use.

        ``restart`` re-zeroes the curve, so a refresh replays the animation
        instead of resuming wherever the previous load left off.
        """
        ramp = self._tab_ramps.get(name)
        if ramp is None:
            ramp = RampProgress()
            self._tab_ramps[name] = ramp
        elif restart:
            ramp.reset()
        return ramp

    def _mount_loading_screen(self, name, page, title, subtitle, done_fn):
        """Make a circular-progress loading screen the page's only content."""
        screen = LoadingScreen(
            title, subtitle, progress_fn=self._tab_ramp(name), done_fn=done_fn
        )
        self._loading_screens[name] = screen
        page.layout().addWidget(screen)
        return screen

    def _finish_loading(self, name, rebuild):
        """Run ``name``'s loading ring to 100%, then swap in the real content.

        Falls straight through to ``rebuild`` when no ring is mounted (the tab
        built its content directly) or when the widget is already gone.
        """
        screen = self._loading_screens.pop(name, None)
        if screen is None:
            rebuild()
            return
        try:
            screen.complete(rebuild)
        except RuntimeError:
            rebuild()  # C++ side already deleted

    # ----- placeholder panes (Events / Vulnerabilities / Inventory) ----------
    def _build_placeholder_pane(self, page, name):
        inner = QWidget()
        inner.setObjectName("Transparent")
        lay = QVBoxLayout(inner)
        lay.setContentsMargins(24, 24, 24, 24)
        lay.addStretch(1)
        lay.addWidget(
            _label(f"{name}", size=20, bold=True), alignment=Qt.AlignmentFlag.AlignCenter
        )
        lay.addWidget(
            _label("Coming soon.", size=13, secondary=True),
            alignment=Qt.AlignmentFlag.AlignCenter,
        )
        lay.addStretch(1)
        page.layout().addWidget(scroll_page(inner))

    # ----- Overview pane -----------------------------------------------------
    def _build_overview_pane(self, page, _name="Overview"):
        # No loading screen here, deliberately: this pane paints its full
        # skeleton immediately (device card, alert bar, module cards all
        # reading "Loading…") and fills each section in as its endpoint lands.
        # A blocking ring would replace a useful page with an empty one and
        # make the same wait feel longer. The other three tabs have no such
        # skeleton to fall back on, so they do get the ring.
        #
        # Centered, max-width column so page elements don't stretch edge-to-edge
        # (which triggered horizontal scroll on this build's wider default size).
        inner = QWidget()
        inner.setObjectName("Transparent")
        row = QHBoxLayout(inner)
        row.setContentsMargins(24, 16, 24, 20)
        row.addStretch(1)
        content = QWidget()
        content.setObjectName("Transparent")
        content.setMaximumWidth(_CONTENT_MAX_WIDTH)
        content.setMinimumWidth(_CONTENT_MIN_WIDTH)
        # Dominant stretch so content claims the width up to its max; the two
        # thin side stretches just center it. Equal weights would let content
        # collapse to a third of the row and squeeze the tiles to one per line.
        row.addWidget(content, 20)
        row.addStretch(1)

        col = QVBoxLayout(content)
        col.setContentsMargins(0, 0, 0, 0)
        col.setSpacing(0)

        # Section holders so the poll can rebuild device card + alert bar in
        # place as endpoints land, without tearing down the whole pane.
        self._device_holder = QWidget()
        self._device_holder.setObjectName("Transparent")
        QVBoxLayout(self._device_holder).setContentsMargins(0, 0, 0, 12)
        col.addWidget(self._device_holder)

        self._alert_holder = QWidget()
        self._alert_holder.setObjectName("Transparent")
        QVBoxLayout(self._alert_holder).setContentsMargins(0, 0, 0, 16)
        col.addWidget(self._alert_holder)

        col.addWidget(self._build_modules_header())

        self._module_grid = _ModuleGrid()
        col.addWidget(self._module_grid)
        col.addStretch(1)

        page.layout().addWidget(scroll_page(inner))

        # Initial paint from whatever is already cached.
        self._overview_ready_mask = _ready_mask()
        self._rebuild_device_card()
        self._rebuild_alert_bar()
        self._populate_module_grid()

        # Kick the loader (idempotent) and poll for readiness.
        _kick_overview_api_loader()
        if _ready_mask() == _READY_ALL and _overview_has_errors():
            logger.info(
                "[WAZUH-OVERVIEW] Cached preload had errors — auto-refreshing on tab open"
            )
            refresh_all_remote_data()
            self._schedule_overview_poll(force=True)
        elif _ready_mask() != _READY_ALL:
            self._schedule_overview_poll()

    def _schedule_overview_poll(self, force=False):
        if self._overview_poll_token is not None and not force:
            return

        def check():
            self._overview_poll_token = None
            if self._module_grid is None:
                return
            self._refresh_device_combo()
            mask = _ready_mask()
            if mask != self._overview_ready_mask:
                self._overview_ready_mask = mask
                self._rebuild_device_card()
                self._rebuild_alert_bar()
                self._populate_module_grid()
            if mask == _READY_ALL:
                return
            self._overview_poll_token = self.app.after(150, check)

        self._overview_poll_token = self.app.after(150, check)

    def request_refresh(self):
        """Dev refresh button: re-fetch every endpoint and repaint as it lands."""
        refresh_all_remote_data()
        # Replay the ring animation from zero rather than resuming the old curve.
        for name in _LOADING_TABS:
            self._tab_ramp(name, restart=True)
        if self._refresh_button is not None:
            self._refresh_button.setEnabled(False)
        # Repaint a few times across the eager (~500ms) + lazy (~2-6s) window.
        for delay in (500, 2000, 6000):
            self.app.after(delay, self._repaint_overview)
        self.app.after(6000, self._restore_refresh_button)

    def _repaint_overview(self):
        if self._module_grid is None:
            return
        self._rebuild_device_card()
        self._rebuild_alert_bar()
        self._populate_module_grid()

    def _restore_refresh_button(self):
        if self._refresh_button is not None:
            try:
                self._refresh_button.setEnabled(True)
            except RuntimeError:
                pass  # button destroyed by a rebuild

    # ----- section 1: device card --------------------------------------------
    def _rebuild_device_card(self):
        holder = self._device_holder
        if holder is None:
            return
        _clear_layout(holder.layout())
        holder.layout().addWidget(self._device_card_widget())

    def _device_card_widget(self):
        card = QFrame()
        card.setObjectName("Card")
        lay = QVBoxLayout(card)
        lay.setContentsMargins(20, 16, 20, 16)
        lay.setSpacing(10)

        bi, loading, error = self._scoped_device_info()
        # "THIS DEVICE" for the local agent; a scoped remote device is labelled
        # "SELECTED DEVICE" so the card never misrepresents someone else's box.
        local = _REMOTE_AGENT.get("name") if isinstance(_REMOTE_AGENT, dict) else None
        card_label = ("THIS DEVICE" if (not self._device_active()
                      or self._device_scope == local) else "SELECTED DEVICE")
        if loading:
            return self._device_placeholder(card, lay, "Loading device info…", card_label)
        if error or not bi:
            return self._device_placeholder(card, lay, "Couldn't load device info", card_label)

        os_info = bi.get("os") or {}
        name = bi.get("name") or "(unknown device)"
        os_name = os_info.get("name") or ""
        os_version = os_info.get("version") or ""
        os_arch = os_info.get("arch") or ""
        agent_id = bi.get("id") or ""
        wazuh_version = (bi.get("version") or "").replace("Wazuh ", "")

        meta_parts = []
        if os_name and os_version:
            meta_parts.append(f"{os_name} {os_version}")
        elif os_name:
            meta_parts.append(os_name)
        if os_arch:
            meta_parts.append(os_arch)
        if agent_id:
            meta_parts.append(f"agent #{agent_id}")
        if wazuh_version:
            meta_parts.append(wazuh_version)
        meta_text = "  ·  ".join(meta_parts)

        is_connected = (bi.get("status") or "").lower() in ("active", "connected")
        connectivity_label = "Connected" if is_connected else "Disconnected"
        state_label = "Online" if is_connected else "Offline"

        facts = [f"Last seen {_format_relative(bi.get('lastKeepAlive'))}", state_label]
        if bi.get("manager"):
            facts.append(f"Manager {bi.get('manager')}")
        if bi.get("ip"):
            facts.append(f"IP {bi.get('ip')}")
        groups = bi.get("group") or []
        if groups:
            facts.append(f"Group {', '.join(groups)}")
        if bi.get("node_name"):
            facts.append(f"Node {bi.get('node_name')}")
        facts_text = "  ·  ".join(facts)

        # Top: label + name + meta | status badge
        top = QHBoxLayout()
        top.setContentsMargins(0, 0, 0, 0)
        left = QVBoxLayout()
        left.setSpacing(2)
        left.addWidget(_label(card_label, size=10, bold=True, secondary=True))
        left.addWidget(_label(name, size=22, bold=True))
        if meta_text:
            left.addWidget(_label(meta_text, size=12, secondary=True))
        top.addLayout(left)
        top.addStretch(1)
        bg, fg = _badge_colors("ok" if is_connected else "error")
        badge = _pill(f"●  {connectivity_label}", bg, fg)
        top.addWidget(badge, alignment=Qt.AlignmentFlag.AlignTop)
        lay.addLayout(top)

        # Divider
        divider = QFrame()
        divider.setFixedHeight(1)
        divider.setObjectName("Divider")
        lay.addWidget(divider)

        # Bottom: facts row
        lay.addWidget(_label(facts_text, size=12, secondary=True, wrap=True))
        return card

    def _device_placeholder(self, card, lay, message, label="THIS DEVICE"):
        lay.addWidget(_label(label, size=10, bold=True, secondary=True))
        lay.addWidget(_label(message, size=14, secondary=True))
        return card

    # ----- section 2: alert bar ----------------------------------------------
    def _rebuild_alert_bar(self):
        holder = self._alert_holder
        if holder is None:
            return
        _clear_layout(holder.layout())
        holder.layout().addWidget(self._alert_bar_widget())

    def _alert_bar_widget(self):
        def bar(bg):
            f = QFrame()
            f.setObjectName("Transparent")
            f.setStyleSheet(f"QFrame{{background-color:{bg};border-radius:8px;}}")
            h = QHBoxLayout(f)
            h.setContentsMargins(14, 10, 12, 10)
            return f, h

        bi, loading, error = self._scoped_device_info()
        if loading or error or not bi:
            muted_bg = theme.color("protect_warn_bg")
            f, h = bar(muted_bg)
            msg = "Loading agent status…" if loading else "Couldn't load agent status."
            h.addWidget(_label(msg, size=13, color=theme.color("text_secondary")))
            h.addStretch(1)
            return f

        local = _REMOTE_AGENT.get("name") if isinstance(_REMOTE_AGENT, dict) else None
        is_local = not self._device_active() or self._device_scope == local
        is_connected = (bi.get("status") or "").lower() in ("active", "connected")
        if is_connected:
            bg, txt = theme.color("protect_ok_bg"), theme.color("protect_ok_text")
            msg = f"●  Agent is connected. Last keep-alive {_format_relative(bi.get('lastKeepAlive'))}."
        else:
            bg, txt = theme.color("protect_warn_bg"), theme.color("protect_warn_text")
            disc_at = _format_relative(bi.get("disconnection_time"))
            msg = (
                f"⚠  Agent is disconnected. Last contact with Wazuh manager was {disc_at}. "
                "Plugin features below reflect the last successful scan."
            )

        f, h = bar(bg)
        h.addWidget(_label(msg, size=12, color=txt, wrap=True))
        h.addStretch(1)
        if not is_connected and is_local:
            btn = QPushButton("Reconnect agent")
            btn.setObjectName("Danger")
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.clicked.connect(self._on_reconnect_click)
            h.addWidget(btn)
        return f

    def _on_reconnect_click(self):
        logger.info("Wazuh Overview: Reconnect clicked (placeholder)")

    # ----- section 3a: modules header ----------------------------------------
    def _build_modules_header(self):
        header = QWidget()
        header.setObjectName("Transparent")
        h = QHBoxLayout(header)
        h.setContentsMargins(0, 0, 0, 8)

        h.addWidget(_label("WAZUH MODULES", size=11, bold=True))
        h.addWidget(_label("status of each plugin on this device", size=11, secondary=True))
        h.addStretch(1)

        for key in _LEGEND_KEYS:
            _, fg = theme.badge_colors(_BADGE_KEY.get(key, key))
            h.addWidget(_label(f"●  {key.capitalize()}", size=11, bold=True, color=fg))

        if _SHOW_DEV_REFRESH_BUTTON:
            btn = QPushButton("↻ Refresh data")
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.clicked.connect(self.request_refresh)
            self._refresh_button = btn
            h.addWidget(btn)
        return header

    # ----- section 3b: module cards ------------------------------------------
    def _populate_module_grid(self):
        if self._module_grid is None:
            return
        cards_data = self._module_cards()
        widgets = [_ModuleCard(cd, on_click=self._switch_tab) for cd in cards_data]
        self._module_grid.set_cards(widgets)

    def _module_cards(self):
        """Compute module-card data from the live /me/* responses."""
        # File Integrity, Rootcheck, Hotfixes, Compliance·SCA and Manager are
        # hidden for now. Their endpoints are still fetched (part of _READY_ALL and
        # the Overview loading progress); only the cards are withheld. Re-add the
        # entries here to bring them back — the card methods are kept below.
        cards = [
            self._security_alerts_card(),
            self._vuln_card(),
            self._inventory_card(),
        ]
        return cards

    def _security_alerts_card(self):
        """Summarise the vuln-detection events (same data the Events tab paints)
        as a severity breakdown, so the Overview card mirrors that tab."""
        title, desc, target = (
            "Security Alerts",
            "Threats and security incidents detected",
            "Events",
        )
        if not _remote_vuln_events_ready.is_set():
            return _loading_card(title, desc, target_tab=target)

        counts = _bucket_by_severity(self._scope_records(_REMOTE_VULN_EVENTS, "agent"))
        total = sum(counts.values())
        if total == 0:
            return {
                "title": title, "status": "OK", "description": desc,
                "stats": (("No alerts", "ok"),), "target_tab": target,
            }
        highest = next((s for s in _SEVERITY_LEVELS if counts.get(s, 0) > 0), "low")
        return {
            "title": title, "status": _SEV_TO_STATUS[highest], "description": desc,
            "stats": _severity_stats(counts), "target_tab": target,
        }

    def _vuln_card(self):
        title, desc, target = "Vulnerabilities", "CVEs across installed packages", "Vulnerabilities"
        if self._device_active():
            # The pre-aggregated summary has no per-device breakdown, so a scoped
            # card must re-bucket the full per-device CVE list instead.
            if not _remote_vulns_ready.is_set():
                return _loading_card(title, desc, target_tab=target)
            if _REMOTE_VULNS_ERROR:
                return _error_card(title, desc, target_tab=target)
            counts = _bucket_by_severity(self._scope_records(_REMOTE_VULNS, "agent_name"))
        else:
            if not _remote_vulns_summary_ready.is_set():
                return _loading_card(title, desc, target_tab=target)
            if _REMOTE_VULNS_SUMMARY_ERROR or not isinstance(_REMOTE_VULNS_SUMMARY, dict):
                return _error_card(title, desc, target_tab=target)
            by_sev = _REMOTE_VULNS_SUMMARY.get("by_severity") or {}
            counts = {
                lvl: int(by_sev.get(lvl.capitalize(), by_sev.get(lvl, 0)) or 0)
                for lvl in _SEVERITY_LEVELS
            }
        total = sum(counts.values())
        if total == 0:
            return {
                "title": title, "status": "OK", "description": desc,
                "stats": (("No vulnerabilities", "ok"),), "target_tab": target,
            }
        highest = next((s for s in _SEVERITY_LEVELS if counts.get(s, 0) > 0), "low")
        return {
            "title": title, "status": _SEV_TO_STATUS[highest], "description": desc,
            "stats": _severity_stats(counts), "target_tab": target,
        }

    def _sca_card(self):
        title = "Compliance · SCA"
        if not _remote_sca_ready.is_set():
            return _loading_card(title, "OS signature checks and benchmarks")
        if _REMOTE_SCA_ERROR:
            return _error_card(title, "OS signature checks and benchmarks")
        if not _REMOTE_SCA:
            return {
                "title": title, "status": "INFO",
                "description": "OS signature checks and benchmarks",
                "stats": (("No scan results", "muted"),),
            }
        sca = _REMOTE_SCA[0]
        score = int(sca.get("score") or 0)
        passed = int(sca.get("pass") or 0)
        failed = int(sca.get("fail") or 0)
        invalid = int(sca.get("invalid") or 0)
        sca_status = "OK" if score >= 80 else ("WARNING" if score >= 50 else "CRITICAL")
        score_color = "ok" if score >= 80 else ("warning" if score >= 50 else "critical")
        desc = _short_benchmark_name(sca.get("name", "")) or "OS configuration benchmark"
        stats = [
            (f"{score}% score", score_color), ("  ·  ", "muted"),
            (f"{passed} pass", "ok"), ("  ·  ", "muted"), (f"{failed} fail", "error"),
        ]
        if invalid:
            stats.extend([("  ·  ", "muted"), (f"{invalid} invalid", "muted")])
        return {"title": title, "status": sca_status, "description": desc, "stats": tuple(stats)}

    def _hotfix_card(self):
        title, desc = "Hotfixes", "Windows KB updates applied"
        if not _remote_hotfixes_ready.is_set():
            return _loading_card(title, desc)
        if _REMOTE_HOTFIXES_ERROR:
            return _error_card(title, desc)
        if not _REMOTE_HOTFIXES:
            if _is_windows_agent():
                return {"title": title, "status": "INFO", "description": desc,
                        "stats": (("No hotfixes reported", "muted"),)}
            return {"title": title, "status": "INFO", "description": desc,
                    "stats": (("Not applicable on this OS", "muted"),)}
        n = len(_REMOTE_HOTFIXES)
        noun = "hotfix" if n == 1 else "hotfixes"
        return {"title": title, "status": "OK", "description": desc,
                "stats": ((f"{n} {noun} installed", "ok"),)}

    def _inventory_card(self):
        title, desc, target = "Inventory", "Devices linked to your account", "Inventory"
        if not _remote_inventory_ready.is_set():
            return _loading_card(title, desc, target_tab=target)
        if _REMOTE_INVENTORY_ERROR:
            return _error_card(title, desc, target_tab=target)
        total = 1 if self._device_active() else int(_REMOTE_INVENTORY.get("total") or 0)
        if total == 0:
            return {"title": title, "status": "INFO", "description": desc,
                    "stats": (("No devices", "muted"),), "target_tab": target}
        noun = "device" if total == 1 else "devices"
        return {"title": title, "status": "OK", "description": desc,
                "stats": ((f"{total} {noun}", "muted"),), "target_tab": target}

    def _agent_health_card(self):
        title, desc = "Agent Health", "Connectivity & configuration"
        if not _remote_agent_ready.is_set():
            return _loading_card(title, desc)
        if _REMOTE_AGENT_ERROR or not _REMOTE_AGENT:
            return _error_card(title, desc)
        bi = _REMOTE_AGENT
        is_connected = (bi.get("status") or "").lower() in ("active", "connected")
        if is_connected:
            return {"title": title, "status": "OK", "description": desc,
                    "stats": ((f"Connected · keep-alive {_format_relative(bi.get('lastKeepAlive'))}", "ok"),)}
        return {"title": title, "status": "ERROR", "description": desc,
                "stats": ((f"Disconnected · {_format_relative(bi.get('disconnection_time'))}", "error"),)}

    def _manager_card(self):
        title, desc = "Manager", "Wazuh cluster reachable by node"
        if not _remote_agent_ready.is_set():
            return _loading_card(title, desc)
        if _REMOTE_AGENT_ERROR or not _REMOTE_AGENT:
            return _error_card(title, desc)
        bi = _REMOTE_AGENT
        manager = bi.get("manager") or ""
        node = bi.get("node_name") or ""
        config_synced = (bi.get("group_config_status") or "").lower() == "synced"
        segments = []
        if manager:
            segments.append((manager, "muted"))
        if node:
            if segments:
                segments.append(("  ·  ", "muted"))
            segments.append((node, "muted"))
        if config_synced:
            if segments:
                segments.append(("  ·  ", "muted"))
            segments.append(("synced", "ok"))
        if not segments:
            segments = [("No data available", "muted")]
        return {"title": title, "status": "OK" if config_synced else "INFO",
                "description": desc, "stats": tuple(segments)}

    # Shared "all devices" sentinel for the global device selector (§ tab strip).
    _DEVICE_ALL = "All devices"

    # ======================================================================
    #  Events pane
    # ======================================================================
    _LIST_PAGE_SIZE = 50

    def _build_events_pane(self, page, _name="Events"):
        # First open kicks the per-device group fan-out (idempotent).
        _kick_vuln_events_phase2_loader()

        _clear_layout(page.layout())
        self._ev_page_widget = page
        # Fresh visit starts unfiltered; silent clear (pills don't exist yet).
        self._ev_sev_sel.clear()

        if not _remote_vuln_events_ready.is_set():
            self._mount_loading_screen(
                "Events",
                page,
                "Loading events…",
                "Collecting security alerts across your devices",
                _remote_vuln_events_ready.is_set,
            )
            self._schedule_events_ready_check()
            return

        inner = QWidget()
        inner.setObjectName("Transparent")
        col = QVBoxLayout(inner)
        col.setContentsMargins(20, 16, 20, 20)
        col.setSpacing(12)

        col.addWidget(self._build_severity_pills())
        col.addWidget(self._build_event_chart())
        col.addWidget(self._build_event_search_header())
        col.addWidget(self._build_event_stream(), 1)

        page.layout().addWidget(inner)

        self._ev_last_seen_id = id(_REMOTE_VULN_EVENTS)
        if _REMOTE_VULN_EVENTS:
            self._ev_selected_id = _REMOTE_VULN_EVENTS[0]["id"]
        self._render_event_list()

        # Keep polling while Phase 2 merges more devices in.
        if not _remote_vuln_events_complete.is_set():
            self._schedule_events_ready_check()

    def _schedule_events_ready_check(self):
        if self._ev_ready_token is not None:
            return

        def check():
            self._ev_ready_token = None
            page = self._ev_page_widget
            if page is None:
                return
            self._refresh_device_combo()
            if not _remote_vuln_events_ready.is_set():
                self._ev_ready_token = self.app.after(120, check)
                return
            current_id = id(_REMOTE_VULN_EVENTS)
            if self._ev_last_seen_id != current_id:
                self._ev_last_seen_id = current_id
                if self._ev_rows_layout is not None:
                    self._refresh_events_content()
                else:
                    # Ring still up — run it to 100%, then build the full pane.
                    self._finish_loading("Events", lambda: self._build_events_pane(page))
                    return
            if _remote_vuln_events_complete.is_set():
                return
            self._ev_ready_token = self.app.after(250, check)

        self._ev_ready_token = self.app.after(120, check)

    def _refresh_events_content(self):
        """In-place update after a Phase 2 rebind: pill counts, chart, list."""
        self._update_severity_pills()
        self._ev_buckets, self._ev_counts = self._bucket_events_24h_hourly()
        self._render_event_chart()
        self._render_event_list()

    # ----- severity pills ----------------------------------------------------
    def _severity_counts(self):
        return _bucket_by_severity(self._scope_records(_REMOTE_VULN_EVENTS, "agent"))

    def _build_severity_pills(self):
        counts = self._severity_counts()
        self._ev_pill_labels = {}
        self._ev_pill_frames = {}
        bar = QWidget()
        bar.setObjectName("Transparent")
        h = QHBoxLayout(bar)
        h.setContentsMargins(0, 0, 0, 0)
        h.setSpacing(8)
        for level in _SEVERITY_LEVELS:
            _bg, fg = theme.badge_colors(_BADGE_KEY.get(level, level))
            # Clickable pill: selecting a threat level filters the events list
            # below, mirroring the Vulnerabilities donut/timeline. Default-arg
            # capture binds `level` per iteration (late-binding closure guard).
            pill = _ClickableFrame(lambda lvl=level: self._on_pill_clicked(lvl))
            # Named so the stylesheet targets only the pill frame. A bare QFrame{}
            # selector would cascade onto the inner labels too (QLabel subclasses
            # QFrame), drawing the border around the title/count/bullet as well.
            pill.setObjectName("SeverityPill")
            ph = QHBoxLayout(pill)
            ph.setContentsMargins(14, 8, 14, 8)
            ph.addWidget(_label("●", size=13, color=fg))
            ph.addWidget(_label(level.upper(), size=11, bold=True, color=fg))
            ph.addStretch(1)
            count_lbl = _label(str(counts[level]), size=20, bold=True, color=fg)
            self._ev_pill_labels[level] = count_lbl
            ph.addWidget(count_lbl)
            self._ev_pill_frames[level] = pill
            h.addWidget(pill, 1)
        # Single styling path for both the initial paint and later updates.
        self._refresh_severity_pills_selection()
        return bar

    def _on_ev_severity_change(self):
        # on_change for the shared SeveritySelection on the Events tab: repaint the
        # pill selection state, reset to page 1, and re-filter the events list.
        self._refresh_severity_pills_selection()
        self._ev_page = 1
        self._render_event_list()

    def _on_pill_clicked(self, level):
        # Zero-count pills are unselectable, mirroring zero-height chart bars. Uses
        # live counts so a pill that fills in after a Phase-2 merge becomes usable.
        if self._severity_counts().get(level, 0) <= 0:
            return
        self._ev_sev_sel.toggle(level)

    def _refresh_severity_pills_selection(self):
        """Paint each pill's selected/dimmed state: the selected pill keeps full
        colour with a coloured outline; the others fade to ~30% opacity. Parity
        with the donut/timeline set_alpha dimming (see _refresh_vuln_donut_alpha)."""
        sel = self._ev_sev_sel.selected
        counts = self._severity_counts()
        for level, pill in self._ev_pill_frames.items():
            try:
                bg, fg = theme.badge_colors(_BADGE_KEY.get(level, level))
                selected = level == sel
                # A 2px border is always present (transparent when unselected) so
                # toggling selection never nudges the pill's geometry.
                border = fg if selected else "transparent"
                # ID selector: styles the pill only, never the inner labels (a
                # bare QFrame{} selector matches QLabel too and borders them).
                pill.setStyleSheet(
                    f"QFrame#SeverityPill{{background-color:{bg};border-radius:10px;"
                    f"border:2px solid {border};}}"
                )
                # Dim the non-selected pills only while a selection is active.
                dim = sel is not None and not selected
                eff = QGraphicsOpacityEffect(pill)
                eff.setOpacity(_SEV_DIM_ALPHA if dim else 1.0)
                pill.setGraphicsEffect(eff)
                # Only offer the hand cursor on selectable (non-zero) pills.
                pill.setCursor(
                    Qt.CursorShape.PointingHandCursor if counts.get(level, 0) > 0
                    else Qt.CursorShape.ArrowCursor
                )
            except RuntimeError:
                pass  # widget torn down mid-refresh

    def _update_severity_pills(self):
        counts = self._severity_counts()
        for level, lbl in self._ev_pill_labels.items():
            try:
                lbl.setText(str(counts[level]))
            except RuntimeError:
                pass
        # If a Phase-2 rebind emptied the selected level, drop the selection so the
        # list doesn't stay filtered to zero rows; then repaint pill selection.
        sel = self._ev_sev_sel.selected
        if sel is not None and counts.get(sel, 0) <= 0:
            self._ev_sev_sel.clear()
        self._refresh_severity_pills_selection()

    # ----- 24h hourly stacked bar chart --------------------------------------
    def _bucket_events_24h_hourly(self):
        """Group events into a fixed 24-slot hourly window ending at the next
        upcoming hour boundary (UTC). Events outside the window are dropped —
        the chart is a rolling 24-hour view by design."""
        from datetime import timedelta

        now = datetime.now(timezone.utc)
        right_edge = now.replace(minute=0, second=0, microsecond=0) + timedelta(hours=1)
        left_edge = right_edge - timedelta(hours=24)
        buckets = [left_edge + timedelta(hours=i) for i in range(24)]
        counts = {b: {lvl: 0 for lvl in _SEVERITY_LEVELS} for b in buckets}
        for ev in self._scope_records(_REMOTE_VULN_EVENTS, "agent"):
            try:
                dt = datetime.fromisoformat((ev["timestamp"]).replace("Z", "+00:00"))
            except (KeyError, ValueError, AttributeError):
                continue
            sev = (ev.get("severity") or "").lower()
            if sev not in _SEVERITY_LEVELS:
                continue
            if dt < left_edge or dt >= right_edge:
                continue
            idx = int((dt - left_edge).total_seconds() // 3600)
            counts[buckets[idx]][sev] += 1
        return buckets, counts

    def _build_event_chart(self):
        ct = charts.chart_theme()
        card = QFrame()
        card.setObjectName("Card")
        cl = QVBoxLayout(card)
        cl.setContentsMargins(8, 8, 8, 8)

        self._ev_buckets, self._ev_counts = self._bucket_events_24h_hourly()
        fig, canvas, ax = charts.make_canvas(card, (8, 1.7), facecolor=ct["bg"])
        # Recompute margins on every draw so labels aren't clipped when the
        # canvas resizes (see _build_vuln_cvss_card for the same rationale).
        fig.set_layout_engine("tight")
        canvas.setMinimumHeight(150)
        canvas.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        canvas.mpl_connect("button_press_event", self._on_chart_click)
        self._ev_chart_fig, self._ev_chart_canvas, self._ev_chart_ax = fig, canvas, ax
        cl.addWidget(canvas)
        self._render_event_chart()
        return card

    def _render_event_chart(self):
        ax = self._ev_chart_ax
        canvas = self._ev_chart_canvas
        if ax is None or canvas is None:
            return
        import matplotlib.colors as mcolors

        ct = charts.chart_theme()
        ax.clear()
        ax.set_facecolor(ct["bg"])
        buckets, counts, sel = self._ev_buckets, self._ev_counts, self._ev_selected_bucket
        x = list(range(24))
        bottoms = [0] * 24
        for level in _SEVERITY_LEVELS:
            heights = [counts[b][level] for b in buckets]
            rgb = mcolors.to_rgb(_segment_color(level))
            colors = [
                (rgb[0], rgb[1], rgb[2], 1.0 if (sel is None or b == sel) else _SEV_DIM_ALPHA)
                for b in buckets
            ]
            ax.bar(x, heights, bottom=bottoms, width=0.9, color=colors,
                   edgecolor="none", label=level.capitalize())
            bottoms = [a + b for a, b in zip(bottoms, heights)]

        ax.set_xlim(-0.5, 23.5)
        ax.set_xticks(x)
        ax.set_xticklabels(
            [buckets[i].strftime("%H:%M") if i % 3 == 0 else "" for i in range(24)],
            fontsize=8, color=ct["text"],
        )
        ax.xaxis.grid(True, color=ct["grid"], linewidth=0.4, alpha=0.5)
        max_h = max(bottoms) if bottoms else 1
        max_h = max(1, max_h)
        ax.set_ylim(0, max_h + 1)
        ax.set_yticks(range(0, max_h + 2, max(1, (max_h + 1) // 4)))
        ax.tick_params(colors=ct["text"], labelsize=8)
        ax.spines["top"].set_visible(False)
        ax.spines["right"].set_visible(False)
        ax.spines["left"].set_color(ct["text"])
        ax.spines["bottom"].set_color(ct["text"])
        ax.yaxis.grid(True, color=ct["grid"], linewidth=0.4, alpha=0.5)
        ax.set_axisbelow(True)
        # Tight layout engine (set in the chart builder) handles margins on draw.
        canvas.draw_idle()

    def _on_chart_click(self, event):
        prev = self._ev_selected_bucket
        new_selection = None
        if event.inaxes is self._ev_chart_ax and event.xdata is not None and self._ev_buckets:
            idx = int(round(event.xdata))
            if 0 <= idx < len(self._ev_buckets):
                bucket = self._ev_buckets[idx]
                if sum(self._ev_counts.get(bucket, {}).values()) > 0:
                    new_selection = None if bucket == prev else bucket
        if new_selection == prev:
            return
        self._ev_selected_bucket = new_selection
        self._render_event_chart()
        self._ev_page = 1
        self._render_event_list()

    # ----- search header -----------------------------------------------------
    def _build_event_search_header(self):
        header = QWidget()
        header.setObjectName("Transparent")
        h = QHBoxLayout(header)
        h.setContentsMargins(0, 0, 0, 0)
        h.addWidget(_label("EVENT SEARCH", size=11, bold=True))
        self._ev_search = QLineEdit()
        self._ev_search.setPlaceholderText("Search rule, IP, description…")
        self._ev_search.textChanged.connect(self._on_event_search_changed)
        h.addWidget(self._ev_search, 1)
        self._ev_count_label = _label(f"{len(_REMOTE_VULN_EVENTS)} events", size=11, secondary=True)
        h.addWidget(self._ev_count_label)
        return header

    def _on_event_search_changed(self, _text):
        # Debounce: filter once the user pauses, not on every keystroke.
        if self._ev_search_token is not None:
            self.app.after_cancel(self._ev_search_token)
        self._ev_search_token = self.app.after(150, self._apply_event_search)

    def _apply_event_search(self):
        self._ev_search_token = None
        self._ev_page = 1
        self._render_event_list()

    # ----- list + detail split -----------------------------------------------
    def _build_event_stream(self):
        split = QWidget()
        split.setObjectName("Transparent")
        h = QHBoxLayout(split)
        h.setContentsMargins(0, 0, 0, 0)
        h.setSpacing(12)

        # Left: list card (header + scroll rows + pager)
        list_card = QFrame()
        list_card.setObjectName("Card")
        lc = QVBoxLayout(list_card)
        lc.setContentsMargins(10, 10, 10, 10)
        lc.setSpacing(4)
        lc.addWidget(self._event_list_header())
        scroll, rows_layout = _rows_scroll()
        self._ev_rows_layout = rows_layout
        lc.addWidget(scroll, 1)
        self._ev_pager_holder = QWidget()
        self._ev_pager_holder.setObjectName("Transparent")
        QHBoxLayout(self._ev_pager_holder).setContentsMargins(0, 0, 0, 0)
        lc.addWidget(self._ev_pager_holder)

        # Right: detail card
        self._ev_detail_holder = QWidget()
        self._ev_detail_holder.setObjectName("Transparent")
        QVBoxLayout(self._ev_detail_holder).setContentsMargins(0, 0, 0, 0)

        h.addWidget(
            ResponsiveStack(
                list_card, self._ev_detail_holder, stretches=(3, 2)), 1)
        return split

    def _event_list_header(self):
        head = QWidget()
        head.setObjectName("Transparent")
        h = QHBoxLayout(head)
        h.setContentsMargins(6, 4, 6, 4)
        # No DESCRIPTION column — it's the headline of the detail card on the
        # right instead. The freed space becomes a stretch so METRIC and WHEN
        # stay right-aligned. Column widths must match _add_event_row.
        for text, stretch in (("", 0), ("RULE", 0), ("", 1), ("METRIC", 0), ("WHEN", 0)):
            lbl = _label(text, size=10, bold=True, secondary=True)
            h.addWidget(lbl, stretch)
            if text == "" and stretch == 0:
                lbl.setFixedWidth(14)
            elif text == "RULE":
                lbl.setFixedWidth(70)
            elif text == "METRIC":
                lbl.setFixedWidth(90)
            elif text == "WHEN":
                lbl.setFixedWidth(110)
        return head

    def _filter_events(self, query):
        sel = self._ev_selected_bucket
        q = (query or "").lower().strip()
        out = []
        for ev in self._scope_records(_REMOTE_VULN_EVENTS, "agent"):
            if sel is not None:
                ts = ev.get("timestamp")
                if not ts:
                    continue
                try:
                    floored = datetime.fromisoformat(
                        ts.replace("Z", "+00:00")
                    ).replace(minute=0, second=0, microsecond=0)
                except ValueError:
                    continue
                if floored != sel:
                    continue
            # AND the header severity selection alongside the hour-bucket + search
            # filters (symmetric with _filter_vulns' device+severity+search).
            if not self._ev_sev_sel.matches(ev.get("severity")):
                continue
            if q and q not in " ".join(str(f) for f in (
                ev.get("rule_id", ""), ev.get("description", ""), ev.get("ip", ""),
                (ev.get("severity") or ""), " ".join(ev.get("mitre", []) or []),
            )).lower():
                continue
            out.append(ev)
        return out

    def _render_event_list(self):
        if self._ev_rows_layout is None:
            return
        from datetime import timedelta

        query = self._ev_search.text() if self._ev_search else ""
        # Clear existing rows (keep the trailing stretch at the end).
        lay = self._ev_rows_layout
        while lay.count() > 1:
            item = lay.takeAt(0)
            w = item.widget()
            if w is not None:
                w.setParent(None)
                w.deleteLater()
        self._ev_row_frames = {}

        events = self._filter_events(query)
        if self._ev_count_label is not None:
            total = len(self._scope_records(_REMOTE_VULN_EVENTS, "agent"))
            shown = len(events)
            text = f"{shown} events" if shown == total else f"{shown}/{total} events"
            if self._ev_selected_bucket is not None:
                end = self._ev_selected_bucket + timedelta(hours=1)
                text += f" · {self._ev_selected_bucket.strftime('%H:%M')}–{end.strftime('%H:%M')}"
            self._ev_count_label.setText(text)

        ids = {ev["id"] for ev in events}
        if events and self._ev_selected_id not in ids:
            self._ev_selected_id = events[0]["id"]

        page_size = self._LIST_PAGE_SIZE
        total_pages = max(1, (len(events) + page_size - 1) // page_size)
        self._ev_page = max(1, min(self._ev_page, total_pages))
        start = (self._ev_page - 1) * page_size
        for ev in events[start:start + page_size]:
            self._add_event_row(ev)
        self._render_pager(self._ev_pager_holder, self._ev_page, total_pages,
                           self._set_event_page)

        if events:
            ev = next((e for e in events if e["id"] == self._ev_selected_id), events[0])
            self._render_event_detail(ev)
        else:
            # Say why the stream is empty. A failed fetch and a genuinely quiet
            # window both render zero rows, and they need different responses.
            if _REMOTE_VULN_EVENTS_ERROR:
                msg = f"Couldn't load events — {_REMOTE_VULN_EVENTS_ERROR}"
            elif _REMOTE_VULN_EVENTS:
                msg = "No events match the current filters"
            else:
                days = EVENTS_WINDOW_HOURS // 24
                msg = f"No security events in the last {days} days"
            empty = _label(msg, size=13, secondary=True)
            empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
            lay.insertWidget(lay.count() - 1, empty)
            self._render_event_detail(None)

    def _set_event_page(self, page):
        page = max(1, int(page))
        if page == self._ev_page:
            return
        self._ev_page = page
        self._render_event_list()

    def _add_event_row(self, ev):
        eid = ev["id"]
        is_selected = eid == self._ev_selected_id
        sev = (ev.get("severity") or "").lower()
        dot = _segment_color(sev)
        active = theme.color("sidebar_active_bg")
        hover = theme.color("sidebar_hover_bg")

        row = _ClickableFrame(lambda e=eid: self._select_event(e))
        row.setObjectName("EvRow")
        bg = active if is_selected else "transparent"
        row.setStyleSheet(
            f"#EvRow{{background:{bg};border-radius:8px;}}"
            + ("" if is_selected else f"#EvRow:hover{{background:{hover};}}")
        )
        h = QHBoxLayout(row)
        h.setContentsMargins(6, 8, 6, 8)
        h.setSpacing(0)
        d = _label("●", size=14, color=dot)
        d.setFixedWidth(14)
        h.addWidget(d)
        rule = _label(str(ev.get("rule_id", "—")), size=12, bold=True)
        rule.setFixedWidth(70)
        h.addWidget(rule)
        # Description lives in the detail card on the right, not in the row.
        h.addStretch(1)
        metric = (ev.get("mitre") or [None])[0] or ev.get("ip") or "—"
        m = _label(metric, size=11, secondary=True)
        m.setFixedWidth(90)
        h.addWidget(m)
        when = _label(_format_timestamp(ev.get("timestamp")), size=11, secondary=True)
        when.setFixedWidth(110)
        h.addWidget(when)

        # Insert before the trailing stretch.
        self._ev_rows_layout.insertWidget(self._ev_rows_layout.count() - 1, row)
        self._ev_row_frames[eid] = row

    def _select_event(self, event_id):
        if event_id == self._ev_selected_id:
            return
        self._ev_selected_id = event_id
        active = theme.color("sidebar_active_bg")
        hover = theme.color("sidebar_hover_bg")
        for eid, rf in list(self._ev_row_frames.items()):
            try:
                selected = eid == event_id
                bg = active if selected else "transparent"
                rf.setStyleSheet(
                    f"#EvRow{{background:{bg};border-radius:8px;}}"
                    + ("" if selected else f"#EvRow:hover{{background:{hover};}}")
                )
            except RuntimeError:
                pass
        ev = next((e for e in _REMOTE_VULN_EVENTS if e["id"] == event_id), None)
        self._render_event_detail(ev)

    def _render_event_detail(self, ev):
        holder = self._ev_detail_holder
        if holder is None:
            return
        _clear_layout(holder.layout())

        card = QFrame()
        card.setObjectName("Card")
        cl = QVBoxLayout(card)
        cl.setContentsMargins(20, 16, 20, 16)
        cl.setSpacing(8)

        if ev is None:
            cl.addStretch(1)
            cl.addWidget(_label("Select an event to see details", size=13, secondary=True),
                         alignment=Qt.AlignmentFlag.AlignCenter)
            cl.addStretch(1)
            holder.layout().addWidget(card)
            return

        sev = (ev.get("severity") or "").lower()
        bg, fg = theme.badge_colors(_BADGE_KEY.get(sev, sev))
        head = QHBoxLayout()
        head.addWidget(_pill(f"●  {sev.upper()}", bg, fg, size=10))
        head.addWidget(_label(f"rule {ev.get('rule_id', '—')}", size=11, bold=True, secondary=True))
        head.addStretch(1)
        head.addWidget(_label(_format_relative(ev.get("timestamp")), size=11, secondary=True))
        cl.addLayout(head)

        cl.addWidget(_label(ev.get("description", "—"), size=18, bold=True, wrap=True))

        meta = QGridLayout()
        meta.setContentsMargins(0, 0, 0, 0)
        meta.setHorizontalSpacing(12)
        meta.setVerticalSpacing(2)
        rows = [
            ("AGENT", ev.get("agent", "—")),
            ("HOST", ev.get("host", "—")),
            ("IP", ev.get("ip", "—")),
            ("MITRE TECHNIQUES", ", ".join(ev.get("mitre", []) or []) or "—"),
            ("HASH", ev.get("hash", "—")),
        ]
        for r, (lbl, value) in enumerate(rows):
            meta.addWidget(_label(lbl, size=10, bold=True, secondary=True), r, 0,
                           alignment=Qt.AlignmentFlag.AlignTop)
            val = _label(str(value), size=12, wrap=True)
            meta.addWidget(val, r, 1)
        meta.setColumnStretch(1, 1)
        cl.addLayout(meta)

        divider = QFrame()
        divider.setFixedHeight(1)
        divider.setObjectName("Divider")
        cl.addWidget(divider)

        cl.addWidget(_label("RAW LOG", size=10, bold=True, secondary=True))
        raw = QPlainTextEdit()
        raw.setPlainText(ev.get("raw_log", ""))
        raw.setReadOnly(True)
        raw.setFixedHeight(90)
        raw.setStyleSheet("font-family:'Courier New',monospace;font-size:11px;")
        cl.addWidget(raw)
        cl.addStretch(1)

        holder.layout().addWidget(card)

    # ======================================================================
    #  Vulnerabilities pane
    # ======================================================================

    def _build_vulnerabilities_pane(self, page, _name="Vulnerabilities"):
        # Drop any prior figures so a rebuild (device switch) doesn't leak.
        for attr in ("_vuln_donut_fig", "_vuln_cvss_fig"):
            fig = getattr(self, attr, None)
            if fig is not None:
                try:
                    fig.clear()
                except Exception:
                    pass
                setattr(self, attr, None)
        _clear_layout(page.layout())
        self._vuln_page_widget = page
        self._vuln_selected_key = None
        self._vuln_row_frames = {}
        self._vuln_detail_holder = None
        self._vuln_sev_sel.clear()
        self._vuln_donut_wedges = []
        self._vuln_cvss_bars = []
        self._vuln_cvss_hover_annot = None
        self._vuln_cvss_hover_key = None

        _kick_overview_api_loader()
        _kick_vulns_loader()

        if not _remote_vulns_ready.is_set():
            self._mount_loading_screen(
                "Vulnerabilities",
                page,
                "Loading vulnerabilities…",
                "Scanning each device for known CVEs",
                _remote_vulns_ready.is_set,
            )
            self._schedule_vuln_ready_check()
            return
        if _REMOTE_VULNS_ERROR:
            self._vuln_centered(page, "Couldn't load vulnerabilities", _REMOTE_VULNS_ERROR)
            return

        inner = QWidget()
        inner.setObjectName("Transparent")
        col = QVBoxLayout(inner)
        col.setContentsMargins(20, 16, 20, 20)
        col.setSpacing(12)
        col.addWidget(self._build_vuln_charts_row())
        col.addWidget(self._build_vuln_table_header())
        col.addWidget(self._build_vuln_table(), 1)
        page.layout().addWidget(inner)
        self._render_vuln_list()

    def _vuln_centered(self, page, text, detail=None):
        msg = QWidget()
        msg.setObjectName("Transparent")
        v = QVBoxLayout(msg)
        v.addStretch(1)
        v.addWidget(_label(text, size=14, bold=detail is not None, secondary=detail is None),
                    alignment=Qt.AlignmentFlag.AlignCenter)
        if detail is not None:
            v.addWidget(_label(str(detail), size=12, secondary=True),
                        alignment=Qt.AlignmentFlag.AlignCenter)
        v.addStretch(1)
        page.layout().addWidget(msg)

    def _schedule_vuln_ready_check(self):
        if self._vuln_ready_token is not None:
            return

        def check():
            self._vuln_ready_token = None
            page = self._vuln_page_widget
            if page is None:
                return
            self._refresh_device_combo()
            if _remote_vulns_ready.is_set():
                self._finish_loading(
                    "Vulnerabilities", lambda: self._build_vulnerabilities_pane(page)
                )
            else:
                self._vuln_ready_token = self.app.after(120, check)

        self._vuln_ready_token = self.app.after(120, check)

    # ----- global device scope (shared by every tab) -------------------------
    def _device_active(self):
        """True when a specific device is selected (i.e. not 'All devices')."""
        return bool(self._device_scope and self._device_scope != self._DEVICE_ALL)

    def _scope_records(self, records, field):
        """Filter a record list to the globally-selected device. Returns the list
        unchanged for 'All devices'. ``field`` is the per-record key holding the
        device/agent name — CVEs use ``agent_name``, events use ``agent``. This is
        the single abstracted filter every tab reuses."""
        if not self._device_active():
            return records
        scope = self._device_scope
        return [r for r in records if r.get(field) == scope]

    def _device_roster(self):
        """The unified device list for the strip selector: 'All devices' + every
        device name known to the account. Sourced from the eagerly-loaded
        inventory summary (``_REMOTE_INVENTORY``); falls back to the fully-shaped
        agents roster, then to whatever names appear in the CVE/event streams,
        so the dropdown is usable before inventory lands."""
        names = set()
        if isinstance(_REMOTE_INVENTORY, dict):
            for it in (_REMOTE_INVENTORY.get("items") or []):
                nm = (it.get("agent_name") or "").strip()
                if nm:
                    names.add(nm)
        if not names:
            for a in _AGENTS:
                nm = ((a.get("basic_info") or {}).get("name") or "").strip()
                if nm:
                    names.add(nm)
        if not names:
            for v in _REMOTE_VULNS:
                nm = (v.get("agent_name") or "").strip()
                if nm:
                    names.add(nm)
            for ev in _REMOTE_VULN_EVENTS:
                nm = (ev.get("agent") or "").strip()
                if nm:
                    names.add(nm)
        return [self._DEVICE_ALL] + sorted(names)

    def _scoped_device_info(self):
        """(basic_info, loading, error) for the Overview device card/alert bar
        under the current scope. Local device (or 'All devices') → the rich
        ``_REMOTE_AGENT`` record; another device → its inventory ``basic_info``
        (identically shaped, minus Wazuh version/manager/node, which render
        absent). ``basic_info`` is None while loading or when unresolved."""
        local = _REMOTE_AGENT.get("name") if isinstance(_REMOTE_AGENT, dict) else None
        if not self._device_active() or self._device_scope == local:
            if not _remote_agent_ready.is_set():
                return None, True, None
            if _REMOTE_AGENT_ERROR or not _REMOTE_AGENT:
                return None, False, (_REMOTE_AGENT_ERROR or "no data")
            return _REMOTE_AGENT, False, None
        # Non-local device: prefer the fully-shaped agents roster, else derive a
        # basic_info from the eagerly-loaded inventory summary.
        for a in _AGENTS:
            bi = a.get("basic_info") or {}
            if bi.get("name") == self._device_scope:
                return bi, False, None
        if isinstance(_REMOTE_INVENTORY, dict):
            for it in (_REMOTE_INVENTORY.get("items") or []):
                if it.get("agent_name") == self._device_scope:
                    return _shape_inventory_agent(it, None)["basic_info"], False, None
        if not _remote_inventory_ready.is_set():
            return None, True, None
        return None, False, "device not found"

    def _vuln_total_for_device(self):
        return len(self._scope_records(_REMOTE_VULNS, "agent_name"))

    def _vuln_severity_counts(self):
        return _bucket_by_severity(self._scope_records(_REMOTE_VULNS, "agent_name"))

    # ----- charts row: donut + CVSS ------------------------------------------
    def _build_vuln_charts_row(self):
        # Two-up above the stack breakpoint; stacked vertically below it
        # (design_test2 parity: graphs stack when the app is too skinny).
        return ResponsiveStack(
            self._build_vuln_donut_card(),
            self._build_vuln_cvss_card(),
            stretches=(1, 1),
        )

    def _build_vuln_donut_card(self):
        card = QFrame()
        card.setObjectName("Card")
        card.setMinimumHeight(210)
        cl = QVBoxLayout(card)
        cl.setContentsMargins(14, 12, 14, 12)
        cl.addWidget(_label("SEVERITY BREAKDOWN", size=11, bold=True, secondary=True))

        counts = self._vuln_severity_counts()
        total = sum(counts.values())

        body = QHBoxLayout()
        ct = charts.chart_theme()
        fig, canvas, ax = charts.make_canvas(card, (2.6, 2.2), facecolor=ct["bg"])
        canvas.setMinimumHeight(160)
        self._vuln_donut_fig, self._vuln_donut_canvas, self._vuln_donut_ax = fig, canvas, ax
        self._render_vuln_donut(counts, total)
        canvas.mpl_connect("button_press_event", self._on_vuln_donut_click)
        body.addWidget(canvas, 1)

        # Legend on the right
        legend = QWidget()
        legend.setObjectName("Transparent")
        lg = QVBoxLayout(legend)
        lg.setContentsMargins(4, 0, 0, 0)
        lg.addStretch(1)
        for lvl in _SEVERITY_LEVELS:
            dot = _segment_color(lvl)
            rowh = QHBoxLayout()
            rowh.addWidget(_label("●", size=14, color=dot))
            rowh.addWidget(_label(lvl.capitalize(), size=12))
            rowh.addStretch(1)
            rowh.addWidget(_label(str(counts[lvl]), size=14, bold=True, color=dot))
            lg.addLayout(rowh)
        lg.addStretch(1)
        body.addWidget(legend)
        cl.addLayout(body, 1)
        return card

    def _render_vuln_donut(self, counts, total):
        import matplotlib.colors as mcolors

        ax = self._vuln_donut_ax
        ct = charts.chart_theme()
        ax.clear()
        ax.set_facecolor(ct["bg"])
        if total <= 0:
            # Empty ring + "No CVEs".
            ax.pie([1], colors=[ct["grid"]], startangle=90, counterclock=False,
                   wedgeprops={"width": 0.32, "edgecolor": ct["bg"]})
            ax.text(0, 0, "No CVEs", ha="center", va="center", color=ct["text"], fontsize=11)
            self._vuln_donut_wedges = []
        else:
            sel = self._vuln_sev_sel.selected
            sizes = [counts[lvl] for lvl in _SEVERITY_LEVELS]
            rgba = []
            for lvl in _SEVERITY_LEVELS:
                rgb = mcolors.to_rgb(_segment_color(lvl))
                alpha = 1.0 if (sel is None or lvl == sel) else _SEV_DIM_ALPHA
                rgba.append((rgb[0], rgb[1], rgb[2], alpha))
            wedges, _t = ax.pie(sizes, colors=rgba, startangle=90, counterclock=False,
                                wedgeprops={"width": 0.32, "edgecolor": ct["bg"]})
            self._vuln_donut_wedges = list(zip(wedges, _SEVERITY_LEVELS))
            ax.text(0, 0.08, str(total), ha="center", va="center",
                    color=ct["text"], fontsize=15, fontweight="bold")
            ax.text(0, -0.20, "CVEs", ha="center", va="center",
                    color=theme.color("text_secondary"), fontsize=9)
        ax.set_aspect("equal")
        self._vuln_donut_canvas.draw_idle()

    def _on_vuln_donut_click(self, event):
        if event.inaxes is None or not self._vuln_donut_wedges:
            return
        for wedge, level in self._vuln_donut_wedges:
            if wedge.theta1 == wedge.theta2:
                continue
            contains, _ = wedge.contains(event)
            if contains:
                self._vuln_sev_sel.toggle(level)
                return

    def _on_vuln_severity_change(self):
        # on_change for the shared SeveritySelection: clicking a level on the donut
        # or the timeline mutates the same state, then this dims the non-selected
        # segments on BOTH charts and re-filters the table. Either chart is a valid
        # entry point; the visual selection and the table stay in lockstep.
        self._refresh_vuln_donut_alpha()
        self._refresh_vuln_cvss_alpha()
        self._vuln_page = 1
        self._render_vuln_list()

    def _refresh_vuln_donut_alpha(self):
        sel = self._vuln_sev_sel.selected
        for wedge, level in self._vuln_donut_wedges:
            try:
                wedge.set_alpha(1.0 if (sel is None or level == sel) else _SEV_DIM_ALPHA)
            except Exception:
                pass
        if self._vuln_donut_canvas is not None:
            self._vuln_donut_canvas.draw_idle()

    def _bucket_vulns_daily(self):
        """Group CVEs into 30 daily buckets ending today (local date) by
        first_detected_at. That field may be unpopulated by the per-device
        endpoint, in which case the chart renders its empty state.

        Both the "today" anchor and each detection are resolved in the viewer's
        local timezone. Anchoring in UTC would put "today" a calendar day ahead
        whenever UTC has already rolled over (evenings in western timezones),
        labelling the newest bucket with a future date."""
        from datetime import timedelta

        today = datetime.now().astimezone().date()
        buckets = [today - timedelta(days=i) for i in range(29, -1, -1)]
        counts = {b: {lvl: 0 for lvl in _SEVERITY_LEVELS} for b in buckets}
        first = buckets[0]
        for v in self._scope_records(_REMOTE_VULNS, "agent_name"):
            ts = v.get("first_detected_at")
            if not ts:
                continue
            try:
                dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
            except (ValueError, AttributeError):
                continue
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            d = dt.astimezone().date()
            if d < first or d > today:
                continue
            sev = (v.get("severity") or "").lower()
            if sev in _SEVERITY_LEVELS:
                counts[d][sev] += 1
        return buckets, counts

    def _build_vuln_cvss_card(self):
        card = QFrame()
        card.setObjectName("Card")
        card.setMinimumHeight(210)
        cl = QVBoxLayout(card)
        cl.setContentsMargins(14, 12, 14, 12)
        cl.addWidget(_label("Recent Detection Timeline", size=11, bold=True, secondary=True))

        ct = charts.chart_theme()
        fig, canvas, ax = charts.make_canvas(card, (5.5, 2.2), facecolor=ct["bg"])
        # Persistent tight layout: recompute margins on every draw so the axis —
        # and the rightmost "today" tick label sitting at the edge — stays fully
        # visible when the canvas resizes to the card's real width/height. A
        # one-shot tight_layout() only fits the initial figsize and then clips
        # once the widget grows or shrinks.
        fig.set_layout_engine("tight")
        canvas.setMinimumHeight(160)
        canvas.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        fig.patch.set_facecolor(ct["bg"])
        ax.set_facecolor(ct["bg"])
        self._vuln_cvss_fig, self._vuln_cvss_canvas, self._vuln_cvss_ax = fig, canvas, ax
        # The visible day-span scales with window width (see _vuln_visible_days),
        # so re-window the x-axis whenever the canvas resizes. Guarded inline in
        # the handler rather than debounced — the Windows modal-resize loop
        # starves QTimer-based debounces (unlike ModuleGrid's grid relayout,
        # this only redraws when the day-count actually crosses a threshold).
        self._vuln_cvss_days = None
        canvas.mpl_connect("resize_event", self._on_vuln_cvss_resize)
        # Clicking a severity segment on the timeline filters the whole tab, exactly
        # like clicking the matching donut wedge (shared self._vuln_sev_sel).
        canvas.mpl_connect("button_press_event", self._on_vuln_cvss_click)
        # Hovering a severity segment shows a small tooltip with its date + count.
        canvas.mpl_connect("motion_notify_event", self._on_vuln_cvss_hover)
        # Add the canvas to the card layout so Qt manages its geometry. Without
        # this the canvas stays an unmanaged child at its native figure size
        # (~550px) pinned top-left: the card clips its right edge (hiding the
        # newest days, incl. today) and it never resizes with the window, so the
        # width-driven day-span never kicks in. Every other chart here does this
        # (events chart, donut card) — this one was missing it.
        cl.addWidget(canvas, 1)
        self._render_vuln_cvss()
        return card

    def _vuln_visible_days(self):
        """Number of trailing days the timeline should show, driven by the app
        window width: 7 days at the app's DEFAULT (native) window width, growing
        linearly to the full 30 days once the window reaches ~2/3 of the screen
        width. Today stays pinned to the right edge; a wider window reveals more
        history on the left. Anchoring on the default size (not the hard minimum)
        means a freshly-opened window shows ~1 week rather than most of the month."""
        canvas = self._vuln_cvss_canvas
        if canvas is None:
            return 30
        win = canvas.window()
        if win is None:
            return 30
        screen = canvas.screen()
        screen_w = screen.availableGeometry().width() if screen is not None else 1920
        # Lower anchor = the app's default window width (the size it opens at),
        # sourced from the shared constant with a 1120 fallback. Lazy import keeps
        # this off the plugin's import path (avoids a startup import cycle).
        try:
            from gui.app_window import DEFAULT_WINDOW_SIZE
            anchor_lo = DEFAULT_WINDOW_SIZE[0]
        except Exception:
            anchor_lo = 1120
        anchor_hi = (2.0 / 3.0) * screen_w
        if anchor_hi <= anchor_lo:
            # Tiny screen: the default window already meets/exceeds the 2/3 mark.
            return 30
        frac = (win.width() - anchor_lo) / (anchor_hi - anchor_lo)
        frac = max(0.0, min(1.0, frac))
        return int(round(7 + frac * (30 - 7)))

    def _on_vuln_cvss_resize(self, _event):
        """Re-window the timeline on canvas resize, but only redraw when the
        computed day-count actually changes (limits redraws to a handful across
        the full width range instead of one per resize pixel)."""
        if self._vuln_visible_days() == self._vuln_cvss_days:
            return
        self._render_vuln_cvss()

    def _render_vuln_cvss(self):
        """Draw (or redraw) the 30-day 'first detected' timeline onto the CVSS
        axis. The date window is anchored to the current day, so this is re-run
        on every tab visit to keep the right edge on today instead of freezing
        at the date the pane was first built."""
        ax = self._vuln_cvss_ax
        if ax is None:
            return
        ct = charts.chart_theme()
        ax.clear()
        ax.set_facecolor(ct["bg"])

        buckets, counts = self._bucket_vulns_daily()
        # Stash for the hover tooltip (maps an x-index → date and its counts). The
        # ax.clear() above dropped any prior annotation, so reset the hover state.
        self._vuln_cvss_buckets, self._vuln_cvss_counts = buckets, counts
        self._vuln_cvss_hover_annot = None
        self._vuln_cvss_hover_key = None
        x = list(range(len(buckets)))
        bottoms = [0] * len(buckets)
        # Right-anchored visible window: today (the last bucket) is always at the
        # right edge; the number of trailing days shown scales with window width.
        n = self._vuln_visible_days()
        self._vuln_cvss_days = n
        start = len(buckets) - n
        ax.set_xlim(start - 0.5, len(buckets) - 0.5)
        has_data = any(sum(counts[b].values()) for b in buckets)
        # (bar_container, severity) pairs, mirroring the donut's wedge tracking so
        # clicks can be hit-tested and the selection dim can be refreshed in place.
        self._vuln_cvss_bars = []
        if has_data:
            sel = self._vuln_sev_sel.selected
            for level in _SEVERITY_LEVELS:
                heights = [counts[b][level] for b in buckets]
                alpha = 1.0 if (sel is None or level == sel) else _SEV_DIM_ALPHA
                bc = ax.bar(x, heights, bottom=bottoms, width=0.85,
                            color=_segment_color(level), edgecolor="none", alpha=alpha)
                self._vuln_cvss_bars.append((bc, level))
                bottoms = [a + b for a, b in zip(bottoms, heights)]
            # Hover tooltip: hidden until the cursor is over a segment. Centered
            # just above the bar top; theme-aware bubble.
            annot = ax.annotate(
                "", xy=(0, 0), xytext=(0, 8), textcoords="offset points",
                ha="center", va="bottom", fontsize=8, color=ct["text"], zorder=10,
                bbox=dict(boxstyle="round,pad=0.4", fc=ct["bg"], ec=ct["grid"], lw=0.8),
            )
            # Pure overlay: exclude it from the figure's tight-layout engine so
            # showing/hiding the tooltip never reflows the axes (it would otherwise
            # reserve/release margin space on each draw and shift the whole graph).
            annot.set_in_layout(False)
            annot.set_visible(False)
            self._vuln_cvss_hover_annot = annot
            # Anchor ticks to the right edge (today) and step backwards within the
            # visible window, so the newest day is always the labelled rightmost tick.
            step = max(1, n // 6)
            ticks = sorted(range(len(buckets) - 1, start - 1, -step))
            ax.set_xticks(ticks)
            ax.set_xticklabels([buckets[i].strftime("%b %d") for i in ticks],
                               fontsize=8, color=ct["text"])
            # Scale the y-axis to the visible window only, so a tall bar scrolled
            # off the left edge doesn't squash the bars actually on screen.
            visible = bottoms[start:]
            max_h = max(visible) if visible else 1
            max_h = max(1, max_h)
            ax.set_ylim(0, max_h + 1)
            ax.set_yticks(range(0, max_h + 2, max(1, (max_h + 1) // 4)))
        else:
            ax.text(0.5, 0.5, "No detections in the last 30 days", transform=ax.transAxes,
                    ha="center", va="center", color=ct["text"], fontsize=11)
            ax.set_xticks([])
            ax.set_yticks([])
        ax.tick_params(colors=ct["text"], labelsize=8)
        ax.spines["top"].set_visible(False)
        ax.spines["right"].set_visible(False)
        ax.spines["left"].set_color(ct["text"])
        ax.spines["bottom"].set_color(ct["text"])
        ax.yaxis.grid(True, color=ct["grid"], linewidth=0.4, alpha=0.5)
        ax.set_axisbelow(True)
        # Margins are recomputed on draw by the figure's tight layout engine
        # (set in _build_vuln_cvss_card), so no one-shot tight_layout() here.
        self._vuln_cvss_canvas.draw_idle()

    def _refresh_vuln_cvss_alpha(self):
        """Dim the non-selected severities on the timeline to match the donut,
        without recomputing buckets or re-windowing — just retint the existing
        bar patches (the donut does the same via _refresh_vuln_donut_alpha)."""
        sel = self._vuln_sev_sel.selected
        for bc, level in self._vuln_cvss_bars:
            alpha = 1.0 if (sel is None or level == sel) else _SEV_DIM_ALPHA
            for patch in bc:
                try:
                    patch.set_alpha(alpha)
                except Exception:
                    pass
        if self._vuln_cvss_canvas is not None:
            self._vuln_cvss_canvas.draw_idle()

    def _on_vuln_cvss_click(self, event):
        if event.inaxes is None or not self._vuln_cvss_bars:
            return
        # Hit-test each severity's stacked segments; zero-height bars can't contain
        # a click, so empty severities are naturally unselectable.
        for bc, level in self._vuln_cvss_bars:
            for patch in bc:
                contains, _ = patch.contains(event)
                if contains:
                    self._vuln_sev_sel.toggle(level)
                    return

    def _on_vuln_cvss_hover(self, event):
        annot = self._vuln_cvss_hover_annot
        canvas = self._vuln_cvss_canvas
        if annot is None or canvas is None:
            return
        # Find the stacked segment under the cursor (zero-height bars can't contain
        # the point, so empty days/severities are naturally skipped).
        hovered = None
        if event.inaxes is self._vuln_cvss_ax:
            for bc, level in self._vuln_cvss_bars:
                for i, patch in enumerate(bc):
                    contains, _ = patch.contains(event)
                    if contains:
                        hovered = (i, level, patch)
                        break
                if hovered is not None:
                    break
        # Motion events fire per pixel; only redraw when the hovered segment
        # actually changes, so mouse movement within one bar doesn't thrash.
        key = (hovered[0], hovered[1]) if hovered is not None else None
        if key == self._vuln_cvss_hover_key:
            return
        self._vuln_cvss_hover_key = key
        if hovered is not None:
            i, level, patch = hovered
            date = self._vuln_cvss_buckets[i]
            count = self._vuln_cvss_counts.get(date, {}).get(level, 0)
            annot.xy = (patch.get_x() + patch.get_width() / 2.0,
                        patch.get_y() + patch.get_height())
            noun = "threat" if count == 1 else "threats"
            annot.set_text(f"{date.strftime('%b %d, %Y')}\n{count} {level} {noun}")
            annot.set_visible(True)
        else:
            annot.set_visible(False)
        canvas.draw_idle()

    # ----- table header + device selector ------------------------------------
    def _build_vuln_table_header(self):
        header = QWidget()
        header.setObjectName("Transparent")
        v = QVBoxLayout(header)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(6)

        top = QHBoxLayout()
        top.addWidget(_label("AFFECTED PACKAGES & CVES", size=11, bold=True))
        self._vuln_search = QLineEdit()
        self._vuln_search.setPlaceholderText("Search CVE, package, severity…")
        self._vuln_search.textChanged.connect(self._on_vuln_search_changed)
        top.addWidget(self._vuln_search, 1)
        self._vuln_count_label = _label(
            f"{self._vuln_total_for_device()} vulnerabilities", size=11, secondary=True)
        top.addWidget(self._vuln_count_label)
        v.addLayout(top)
        # Device filtering now lives in the global selector on the tab strip
        # (see _on_device_scope_change); the old per-tab picker was removed.
        return header

    def _on_vuln_search_changed(self, _text):
        if self._vuln_search_token is not None:
            self.app.after_cancel(self._vuln_search_token)
        self._vuln_search_token = self.app.after(150, self._apply_vuln_search)

    def _apply_vuln_search(self):
        self._vuln_search_token = None
        self._vuln_page = 1
        self._render_vuln_list()

    # ----- table: list + detail ----------------------------------------------
    def _build_vuln_table(self):
        split = QWidget()
        split.setObjectName("Transparent")
        h = QHBoxLayout(split)
        h.setContentsMargins(0, 0, 0, 0)
        h.setSpacing(12)

        list_card = QFrame()
        list_card.setObjectName("Card")
        lc = QVBoxLayout(list_card)
        lc.setContentsMargins(10, 10, 10, 10)
        lc.setSpacing(4)
        lc.addWidget(self._vuln_columns_header())
        scroll, rows_layout = _rows_scroll()
        self._vuln_rows_layout = rows_layout
        lc.addWidget(scroll, 1)
        self._vuln_pager_holder = QWidget()
        self._vuln_pager_holder.setObjectName("Transparent")
        QHBoxLayout(self._vuln_pager_holder).setContentsMargins(0, 0, 0, 0)
        lc.addWidget(self._vuln_pager_holder)

        self._vuln_detail_holder = QWidget()
        self._vuln_detail_holder.setObjectName("Transparent")
        QVBoxLayout(self._vuln_detail_holder).setContentsMargins(0, 0, 0, 0)

        h.addWidget(list_card, 3)
        h.addWidget(self._vuln_detail_holder, 2)
        return split

    def _vuln_columns_header(self):
        head = QWidget()
        head.setObjectName("Transparent")
        h = QHBoxLayout(head)
        h.setContentsMargins(6, 4, 6, 4)
        sev = _label("SEV", size=10, bold=True, secondary=True)
        sev.setFixedWidth(70)
        h.addWidget(sev)
        cve = _label("CVE", size=10, bold=True, secondary=True)
        cve.setFixedWidth(180)
        h.addWidget(cve)
        h.addWidget(_label("AFFECTED PACKAGE", size=10, bold=True, secondary=True), 1)
        return head

    def _filter_vulns(self, query):
        q = (query or "").lower().strip()
        out = []
        for v in self._scope_records(_REMOTE_VULNS, "agent_name"):
            if not self._vuln_sev_sel.matches(v.get("severity")):
                continue
            if q and q not in " ".join(str(f) for f in (
                v.get("id", ""), v.get("package_name", ""), v.get("package_version", ""),
                v.get("severity", ""), v.get("status", ""), v.get("description", ""),
                v.get("agent_name", ""),
            )).lower():
                continue
            out.append(v)
        out.sort(key=lambda x: float(x.get("cvss_score") or 0.0), reverse=True)
        return out

    def _render_vuln_list(self):
        if self._vuln_rows_layout is None:
            return
        query = self._vuln_search.text() if self._vuln_search else ""
        lay = self._vuln_rows_layout
        while lay.count() > 1:
            item = lay.takeAt(0)
            w = item.widget()
            if w is not None:
                w.setParent(None)
                w.deleteLater()
        self._vuln_row_frames = {}

        vulns = self._filter_vulns(query)
        if self._vuln_count_label is not None:
            total = self._vuln_total_for_device()
            shown = len(vulns)
            self._vuln_count_label.setText(
                f"{shown} vulnerabilities" if shown == total
                else f"{shown}/{total} vulnerabilities")

        keys = {self._vuln_key(v) for v in vulns}
        if self._vuln_selected_key not in keys:
            self._vuln_selected_key = None

        page_size = self._LIST_PAGE_SIZE
        total_pages = max(1, (len(vulns) + page_size - 1) // page_size)
        self._vuln_page = max(1, min(self._vuln_page, total_pages))
        start = (self._vuln_page - 1) * page_size
        for v in vulns[start:start + page_size]:
            self._add_vuln_row(v)
        self._render_pager(self._vuln_pager_holder, self._vuln_page, total_pages,
                           self._set_vuln_page)

        if not vulns:
            self._render_vuln_detail(None)
        elif self._vuln_selected_key is None:
            self._select_vuln(self._vuln_key(vulns[0]))
        else:
            self._render_vuln_detail(self._find_vuln_by_key(self._vuln_selected_key))

    def _set_vuln_page(self, page):
        page = max(1, int(page))
        if page == self._vuln_page:
            return
        self._vuln_page = page
        self._render_vuln_list()

    @staticmethod
    def _vuln_key(vuln):
        return f"{vuln.get('agent_id') or ''}::{vuln.get('id') or ''}"

    def _find_vuln_by_key(self, key):
        return next((v for v in _REMOTE_VULNS if self._vuln_key(v) == key), None)

    def _epss_color_key(self, epss):
        try:
            value = float(epss)
        except (TypeError, ValueError):
            return "muted"
        if value >= 0.7:
            return "high"
        if value >= 0.3:
            return "warning"
        return "muted"

    def _add_vuln_row(self, vuln):
        key = self._vuln_key(vuln)
        is_selected = key == self._vuln_selected_key
        sev = (vuln.get("severity") or "").lower()
        sev_bg, sev_fg = theme.badge_colors(_BADGE_KEY.get(sev, sev))
        sev_label = _SEVERITY_SHORT.get(sev, sev.upper() or "—")
        active = theme.color("sidebar_active_bg")
        hover = theme.color("sidebar_hover_bg")

        row = _ClickableFrame(lambda k=key: self._select_vuln(k))
        row.setObjectName("VRow")
        bg = active if is_selected else "transparent"
        row.setStyleSheet(
            f"#VRow{{background:{bg};border-radius:8px;}}"
            + ("" if is_selected else f"#VRow:hover{{background:{hover};}}")
        )
        h = QHBoxLayout(row)
        h.setContentsMargins(6, 6, 6, 6)
        h.setSpacing(0)

        badge = _pill(sev_label, sev_bg, sev_fg, size=10)
        badge_cell = QWidget()
        badge_cell.setObjectName("Transparent")
        badge_cell.setFixedWidth(70)
        bh = QHBoxLayout(badge_cell)
        bh.setContentsMargins(0, 0, 0, 0)
        bh.addWidget(badge)
        bh.addStretch(1)
        h.addWidget(badge_cell)

        cve_cell = QWidget()
        cve_cell.setObjectName("Transparent")
        cve_cell.setFixedWidth(180)
        cv = QVBoxLayout(cve_cell)
        cv.setContentsMargins(0, 0, 0, 0)
        cv.setSpacing(0)
        cv.addWidget(_label(vuln.get("id", "—"), size=12, bold=True))
        cv.addWidget(_label(f"modified {_format_relative(vuln.get('modified_date'))}",
                            size=10, secondary=True))
        h.addWidget(cve_cell)

        pkg_cell = QWidget()
        pkg_cell.setObjectName("Transparent")
        pv = QVBoxLayout(pkg_cell)
        pv.setContentsMargins(0, 0, 0, 0)
        pv.setSpacing(0)
        pv.addWidget(_label(vuln.get("package_name", "—"), size=12, bold=True))
        pv.addWidget(_label(str(vuln.get("package_version", "")), size=10, secondary=True))
        h.addWidget(pkg_cell, 1)

        self._vuln_rows_layout.insertWidget(self._vuln_rows_layout.count() - 1, row)
        self._vuln_row_frames[key] = row

    def _select_vuln(self, key):
        if key == self._vuln_selected_key:
            return
        self._vuln_selected_key = key
        active = theme.color("sidebar_active_bg")
        hover = theme.color("sidebar_hover_bg")
        for k, rf in list(self._vuln_row_frames.items()):
            try:
                selected = k == key
                bg = active if selected else "transparent"
                rf.setStyleSheet(
                    f"#VRow{{background:{bg};border-radius:8px;}}"
                    + ("" if selected else f"#VRow:hover{{background:{hover};}}")
                )
            except RuntimeError:
                pass
        self._render_vuln_detail(self._find_vuln_by_key(key))

    def _render_vuln_detail(self, vuln):
        holder = self._vuln_detail_holder
        if holder is None:
            return
        _clear_layout(holder.layout())

        card = QFrame()
        card.setObjectName("Card")
        card.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Expanding)
        cl = QVBoxLayout(card)
        cl.setContentsMargins(20, 16, 20, 16)
        cl.setSpacing(8)

        if vuln is None:
            cl.addStretch(1)
            cl.addWidget(_label("Select a vulnerability to see details", size=13, secondary=True),
                         alignment=Qt.AlignmentFlag.AlignCenter)
            cl.addStretch(1)
            holder.layout().addWidget(card)
            return

        sev = (vuln.get("severity") or "").lower()
        sev_bg, sev_fg = theme.badge_colors(_BADGE_KEY.get(sev, sev))
        sev_label = _SEVERITY_SHORT.get(sev, sev.upper() or "—")

        head = QHBoxLayout()
        head.addWidget(_pill(sev_label, sev_bg, sev_fg, size=10))
        head.addWidget(_label(vuln.get("id", "—"), size=11, bold=True, secondary=True))
        head.addStretch(1)
        head.addWidget(_label(_format_relative(vuln.get("modified_date")), size=11, secondary=True))
        cl.addLayout(head)

        pkg = f"{vuln.get('package_name') or ''} {vuln.get('package_version') or ''}".strip()
        cl.addWidget(_label(pkg or vuln.get("id") or "—", size=18, bold=True, wrap=True))

        meta = QGridLayout()
        meta.setContentsMargins(0, 0, 0, 0)
        meta.setHorizontalSpacing(12)
        meta.setVerticalSpacing(2)
        rows = []
        try:
            rows.append(("CVSS", f"{float(vuln.get('cvss_score') or 0.0):.1f}", sev_fg))
        except (TypeError, ValueError):
            pass
        epss = vuln.get("epss")
        try:
            epss_key = self._epss_color_key(epss)
            epss_color = None if epss_key == "muted" else _segment_color(epss_key)
            rows.append(("EPSS", f"{float(epss) * 100:.0f}%", epss_color))
        except (TypeError, ValueError):
            pass
        if (vuln.get("status") or "").strip():
            rows.append(("STATUS", vuln.get("status").capitalize(), None))
        if vuln.get("agent_name"):
            rows.append(("DEVICE", vuln.get("agent_name"), None))
        for lbl, k in (("FIRST DETECTED", "first_detected_at"),
                       ("PUBLISHED", "published_date"), ("LAST MODIFIED", "modified_date")):
            if vuln.get(k):
                rows.append((lbl, _format_timestamp(vuln.get(k)), None))
        for r, (lbl, value, vcolor) in enumerate(rows):
            meta.addWidget(_label(lbl, size=10, bold=True, secondary=True), r, 0,
                           alignment=Qt.AlignmentFlag.AlignTop)
            meta.addWidget(_label(str(value), size=12, color=vcolor, wrap=True), r, 1)
        meta.setColumnStretch(1, 1)
        cl.addLayout(meta)

        divider = QFrame()
        divider.setFixedHeight(1)
        divider.setObjectName("Divider")
        cl.addWidget(divider)

        cl.addWidget(_label("DESCRIPTION", size=10, bold=True, secondary=True))
        description = vuln.get("description") or ""
        if description:
            # Expand to fill the space left below the (possibly multi-line)
            # title/meta and scroll internally — so the box bottom stays pinned
            # to the card bottom rather than being pushed off by a long title.
            box = QPlainTextEdit()
            box.setPlainText(description)
            box.setReadOnly(True)
            box.setMinimumHeight(80)
            box.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
            box.setStyleSheet("font-family:'Courier New',monospace;font-size:11px;")
            cl.addWidget(box, 1)
        else:
            cl.addWidget(_label("No description available.", size=12, secondary=True))
            cl.addStretch(1)
        holder.layout().addWidget(card)

    # ======================================================================
    #  Inventory pane
    # ======================================================================
    _INVENTORY_COUNT_FIELDS = {
        "Devices": None,
        "Processes": ("syscollector", "processes"),
        "Ports": ("syscollector", "network", "ports"),
        "Network": ("syscollector", "network", "interfaces"),
    }
    _INVENTORY_LEAD_HEADER = {
        "Devices": "THREAT",
        "Processes": "PROCESSES",
        "Ports": "OPEN PORTS",
        "Network": "INTERFACES",
    }
    _GROUP_ALL = "All groups"
    _GROUP_NONE = "(no group)"
    _INVENTORY_PAGE_SIZE = 20

    def _build_inventory_pane(self, page, _name="Inventory"):
        _clear_layout(page.layout())
        self._inv_page_widget = page
        _kick_agents_loader()

        if not _agents_ready.is_set():
            self._mount_loading_screen(
                "Inventory",
                page,
                "Loading devices…",
                "Gathering hardware and software inventory",
                _agents_ready.is_set,
            )
            self._schedule_inventory_ready_check()
            return

        self._render_inventory_list(page)

    def _schedule_inventory_ready_check(self):
        if self._inv_ready_token is not None:
            return

        def check():
            self._inv_ready_token = None
            page = self._inv_page_widget
            if page is None:
                return
            self._refresh_device_combo()
            if _agents_ready.is_set():
                self._finish_loading("Inventory", lambda: self._build_inventory_pane(page))
            else:
                self._inv_ready_token = self.app.after(120, check)

        self._inv_ready_token = self.app.after(120, check)

    # ----- threat composition (events + vulns) -------------------------------
    def _events_threat_by_agent(self):
        out = {}
        for ev in _REMOTE_VULN_EVENTS:
            name = (ev.get("agent") or "").strip()
            sev = (ev.get("severity") or "").lower()
            if not name or sev not in _THREAT_RANK:
                continue
            prev = out.get(name)
            if prev is None or _THREAT_RANK[sev] > _THREAT_RANK[prev]:
                out[name] = sev
        return out

    def _vulns_threat_for_name(self, target_name):
        if not target_name:
            return None
        best = None
        for v in _REMOTE_VULNS:
            if v.get("agent_name") != target_name:
                continue
            sev = (v.get("severity") or "").lower()
            if sev not in _THREAT_RANK:
                continue
            if best is None or _THREAT_RANK[sev] > _THREAT_RANK[best]:
                best = sev
        return best

    def _device_threat_level(self, agent_name, events_by_agent):
        best_rank = 0
        for sev in (events_by_agent.get(agent_name), self._vulns_threat_for_name(agent_name)):
            if sev and _THREAT_RANK.get(sev, 0) > best_rank:
                best_rank = _THREAT_RANK[sev]
        return _RANK_TO_SEV.get(best_rank, "ok")

    # ----- row data ----------------------------------------------------------
    def _agent_groups(self, bi):
        raw = bi.get("group")
        if isinstance(raw, list):
            return [g for g in raw if g]
        if raw:
            return [raw]
        return []

    def _base_agent_row(self, agent):
        bi = agent.get("basic_info") or {}
        return {
            "name": bi.get("name") or "(unknown)",
            "status": (bi.get("status") or "").lower(),
            "last_keep": bi.get("lastKeepAlive"),
            "agent_id": bi.get("id") or "—",
            "ip": bi.get("ip") or "—",
            "groups": self._agent_groups(bi),
        }

    def _inventory_rows(self):
        events_by_agent = self._events_threat_by_agent()
        rows = []
        for agent in _AGENTS:
            row = self._base_agent_row(agent)
            row["threat"] = self._device_threat_level(row["name"], events_by_agent)
            rows.append(row)
        rows.sort(key=lambda r: (-_THREAT_RANK.get(r["threat"], 0), r["name"].lower()))
        return rows

    def _inventory_counts_rows(self, field_path):
        rows = []
        for agent in _AGENTS:
            node = agent
            for fkey in field_path:
                node = node.get(fkey) if isinstance(node, dict) else None
                if node is None:
                    break
            items = (node or {}).get("affected_items") if isinstance(node, dict) else None
            row = self._base_agent_row(agent)
            row["count"] = len(items) if isinstance(items, list) else 0
            rows.append(row)
        rows.sort(key=lambda r: (-r["count"], r["name"].lower()))
        return rows

    def _inventory_group_values(self):
        seen = set()
        has_empty = False
        for agent in _AGENTS:
            groups = self._agent_groups(agent.get("basic_info") or {})
            if not groups:
                has_empty = True
            else:
                seen.update(groups)
        out = [self._GROUP_ALL] + sorted(seen)
        if has_empty:
            out.append(self._GROUP_NONE)
        return out

    def _row_in_group(self, row, group_filter):
        if group_filter == self._GROUP_ALL:
            return True
        groups = row.get("groups") or []
        if group_filter == self._GROUP_NONE:
            return not groups
        return group_filter in groups

    def _row_in_scope(self, row):
        """Honour the global device selector on the Inventory list too."""
        return not self._device_active() or row.get("name") == self._device_scope

    # ----- render ------------------------------------------------------------
    def _render_inventory_list(self, page):
        card = QFrame()
        card.setObjectName("Card")
        cl = QVBoxLayout(card)
        cl.setContentsMargins(16, 14, 16, 10)
        cl.setSpacing(0)

        # Title bar: category + group dropdowns | pager
        title = QHBoxLayout()
        title.setSpacing(8)
        cat = QComboBox()
        cat.addItems(list(self._INVENTORY_COUNT_FIELDS.keys()))
        cat.setCurrentText(self._inv_view)
        cat.currentTextChanged.connect(self._on_inventory_view_change)
        cat.setMaximumWidth(160)
        title.addWidget(cat)

        group_values = self._inventory_group_values()
        if len(group_values) >= 3:
            if self._inv_group not in group_values:
                self._inv_group = self._GROUP_ALL
            grp = QComboBox()
            grp.addItems(group_values)
            grp.setCurrentText(self._inv_group)
            grp.currentTextChanged.connect(self._on_inventory_group_change)
            grp.setMaximumWidth(200)
            title.addWidget(grp)
        else:
            self._inv_group = self._GROUP_ALL

        title.addStretch(1)
        self._inv_pager_holder = QWidget()
        self._inv_pager_holder.setObjectName("Transparent")
        QHBoxLayout(self._inv_pager_holder).setContentsMargins(0, 0, 0, 0)
        title.addWidget(self._inv_pager_holder)
        cl.addLayout(title)

        self._inv_count_label = _label("", size=11, secondary=True)
        cl.addWidget(self._inv_count_label)

        divider = QFrame()
        divider.setFixedHeight(1)
        divider.setObjectName("Divider")
        cl.addWidget(divider)

        # Body (column header + list) — rebuilt in place on view/group/page change.
        self._inv_body_holder = QWidget()
        self._inv_body_holder.setObjectName("Transparent")
        bl = QVBoxLayout(self._inv_body_holder)
        bl.setContentsMargins(0, 8, 0, 0)
        bl.setSpacing(4)
        cl.addWidget(self._inv_body_holder, 1)

        page.layout().addWidget(card)
        self._render_inventory_body()

    # Column widths shared by the header and each row so they align.
    _INV_COL_WIDTHS = {"lead": 110, "last": 140, "agent": 80, "ip": 140}

    def _inventory_column_header(self):
        head = QWidget()
        head.setObjectName("Transparent")
        h = QHBoxLayout(head)
        h.setContentsMargins(2, 0, 2, 0)
        h.setSpacing(12)
        lead = _label(self._INVENTORY_LEAD_HEADER.get(self._inv_view, "THREAT"),
                      size=10, bold=True, secondary=True)
        lead.setFixedWidth(self._INV_COL_WIDTHS["lead"])
        h.addWidget(lead)
        h.addWidget(_label("DEVICE", size=10, bold=True, secondary=True), 1)
        for name, key in (("LAST SEEN", "last"), ("AGENT ID", "agent"), ("IP", "ip")):
            lbl = _label(name, size=10, bold=True, secondary=True)
            lbl.setFixedWidth(self._INV_COL_WIDTHS[key])
            h.addWidget(lbl)
        return head

    def _render_inventory_body(self):
        holder = self._inv_body_holder
        if holder is None:
            return
        _clear_layout(holder.layout())

        view = self._inv_view
        is_devices = view == "Devices"
        field_path = self._INVENTORY_COUNT_FIELDS.get(view)
        gf = self._inv_group

        if is_devices:
            rows = [r for r in self._inventory_rows()
                    if self._row_in_group(r, gf) and self._row_in_scope(r)]
            count_text = f"{len(rows)} linked · sorted by threat level"
        else:
            rows = [r for r in self._inventory_counts_rows(field_path)
                    if self._row_in_group(r, gf) and self._row_in_scope(r)]
            total = sum(r["count"] for r in rows)
            n_with_data = sum(1 for r in rows if r["count"] > 0)
            word = "interfaces" if view == "Network" else view.lower()
            count_text = f"{n_with_data} devices · {total} {word} total"
        if self._inv_count_label is not None:
            self._inv_count_label.setText(count_text)

        page_size = self._INVENTORY_PAGE_SIZE
        total_pages = max(1, (len(rows) + page_size - 1) // page_size)
        self._inv_page = max(1, min(self._inv_page, total_pages))
        start = (self._inv_page - 1) * page_size
        page_rows = rows[start:start + page_size]

        holder.layout().addWidget(self._inventory_column_header())
        scroll, rows_layout = _rows_scroll()
        self._inv_rows_layout = rows_layout
        holder.layout().addWidget(scroll, 1)
        for dev in page_rows:
            self._add_inventory_row(dev, is_devices)

        self._render_pager(self._inv_pager_holder, self._inv_page, total_pages,
                           self._set_inventory_page)

    def _add_inventory_row(self, dev, is_devices):
        row = QFrame()
        row.setObjectName("InvRow")
        hover = theme.color("sidebar_hover_bg")
        row.setStyleSheet(
            f"#InvRow{{background:transparent;border-radius:6px;}}"
            f"#InvRow:hover{{background:{hover};}}"
        )
        h = QHBoxLayout(row)
        h.setContentsMargins(2, 6, 2, 6)
        h.setSpacing(12)

        # Lead cell — threat badge (Devices) or count (other views).
        lead = QWidget()
        lead.setObjectName("Transparent")
        lead.setFixedWidth(self._INV_COL_WIDTHS["lead"])
        lh = QHBoxLayout(lead)
        lh.setContentsMargins(0, 0, 0, 0)
        if is_devices:
            status_label = _SEV_TO_STATUS.get(dev["threat"], "OK")
            t_bg, t_fg = _badge_colors(status_label)
            lh.addWidget(_pill(f"●  {status_label}", t_bg, t_fg))
        else:
            count = dev["count"]
            lh.addWidget(_label(str(count), size=13, bold=True,
                                secondary=(count == 0)))
        lh.addStretch(1)
        h.addWidget(lead)

        h.addWidget(_label(dev["name"], size=13, bold=True), 1)

        connected = dev["status"] in ("active", "connected")
        last_seen = "Active now" if connected else _format_relative(dev["last_keep"])
        for text, key in ((last_seen, "last"), (str(dev["agent_id"]), "agent"), (dev["ip"], "ip")):
            lbl = _label(text, size=12, secondary=True)
            lbl.setFixedWidth(self._INV_COL_WIDTHS[key])
            h.addWidget(lbl)

        self._inv_rows_layout.insertWidget(self._inv_rows_layout.count() - 1, row)

    def _on_inventory_view_change(self, view_name):
        if view_name not in self._INVENTORY_COUNT_FIELDS or view_name == self._inv_view:
            return
        self._inv_view = view_name
        self._inv_page = 1
        self._render_inventory_body()

    def _on_inventory_group_change(self, group_name):
        if group_name == self._inv_group:
            return
        self._inv_group = group_name
        self._inv_page = 1
        self._render_inventory_body()

    def _set_inventory_page(self, page):
        page = max(1, int(page))
        if page == self._inv_page:
            return
        self._inv_page = page
        self._render_inventory_body()

    # ----- shared pager ------------------------------------------------------
    @staticmethod
    def _pager_button(glyph, enabled, on_click):
        """A single ◀/▶ pager button with explicit enabled/hover/disabled
        styling and a pointer cursor only while it's actionable."""
        btn = QPushButton(glyph)
        btn.setFixedSize(30, 28)
        btn.setEnabled(enabled)
        if enabled:
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.clicked.connect(on_click)
        border = theme.color("border")
        btn.setStyleSheet(
            "QPushButton{"
            f"background:transparent;color:{theme.color('text_secondary')};"
            f"border:1px solid {border};border-radius:6px;font-size:13px;padding:0;}}"
            "QPushButton:hover{"
            f"background:{theme.color('sidebar_hover_bg')};"
            f"color:{theme.color('accent')};border-color:{theme.color('accent')};}}"
            "QPushButton:disabled{"
            f"background:transparent;color:{border};border-color:{border};}}"
        )
        return btn

    def _render_pager(self, holder, current, total_pages, on_set_page):
        """Right-aligned [◀] page X / Y [▶] navigator. Hidden on a single page."""
        if holder is None:
            return
        _clear_layout(holder.layout())
        if total_pages <= 1:
            holder.hide()
            return
        holder.show()
        h = holder.layout()
        h.setSpacing(6)
        h.addStretch(1)
        h.addWidget(self._pager_button("◀", current > 1, lambda: on_set_page(current - 1)))
        h.addWidget(_label(f"{current} / {total_pages}", size=12, secondary=True))
        h.addWidget(self._pager_button("▶", current < total_pages, lambda: on_set_page(current + 1)))

    # ----- lifecycle ---------------------------------------------------------
    def _cancel_pending_ui_callbacks(self):
        for token_attr in ("_overview_poll_token", "_ev_ready_token", "_ev_search_token",
                           "_vuln_ready_token", "_vuln_search_token", "_inv_ready_token"):
            token = getattr(self, token_attr, None)
            if token is not None:
                try:
                    self.app.after_cancel(token)
                except Exception:
                    pass
                setattr(self, token_attr, None)

    def destroy(self):
        self._cancel_pending_ui_callbacks()
