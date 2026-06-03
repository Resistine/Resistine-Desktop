"""
Endpoint 2 Plugin (placeholder)
A second Endpoint sidebar entry, used as a starting point for a redesigned
endpoint-page architecture. The Overview tab renders content derived from the
sample data file at plugins/endpoint2/data/agent.013.json. Sections without a
data source in the sample (vulnerabilities, syscheck, MITRE, etc.) render as
"No data available" rather than fabricating numbers.
Author: Resistine Team
Copyright (c) Resistine 2025
Licensed under the GNU General Public License v2 or later
"""

import json
import os
import platform as _platform
import threading
import time
import tkinter as tk
from datetime import datetime, timedelta, timezone

import customtkinter
from customtkinter import ThemeManager

from plugins.base_plugin import BasePlugin
from plugins.wazuh_overview import api_client
from utils.logger import logger

# matplotlib is imported lazily via _ensure_matplotlib() — see below. Pulling it
# at module load adds ~200–500 ms to plugin discovery on the first run of the
# app; deferring it means the Vulnerabilities/Events charts only pay that cost
# the first time they're built. _ensure_matplotlib() also keeps pyplot out of
# the import graph entirely and pins font.sans-serif to the bundled DejaVu Sans
# so findfont skips the system-font scoring loop on every render.
_Figure = None
_FigureCanvasTkAgg = None


def _ensure_matplotlib():
    """Lazy-import matplotlib with the minimum footprint we can get away with.

    Two deliberate omissions:

    1. ``matplotlib.pyplot`` is never imported. pyplot is ~200KB of helpers
       built around a global figure registry (``Gcf``) that this app doesn't
       use — every chart is built via ``Figure(...)`` directly. Cleanup paths
       call ``fig.clear()`` instead of ``pyplot.close()``.
    2. ``font.sans-serif`` is pinned to the single bundled DejaVu Sans entry
       so ``font_manager.findfont()`` returns on the first candidate. The
       default sans-serif chain is ~10 fonts long, and findfont scores every
       one of them against the system font cache on every render.

    Don't undo either without re-measuring — the first-chart-render path
    benefits from both."""
    global _Figure, _FigureCanvasTkAgg
    if _Figure is None:
        import logging as _logging
        # matplotlib's font_manager emits a DEBUG line per font candidate it
        # scores, and that loop runs on every figure render. With Loguru
        # intercepting stdlib logging at DEBUG (e.g. main.py -d debug mode),
        # opening the Overview tab spams thousands of "findfont: score(...)"
        # entries. Drop matplotlib's DEBUG/INFO at the source — useful warns
        # and errors still flow through.
        _logging.getLogger("matplotlib").setLevel(_logging.WARNING)
        import matplotlib
        matplotlib.use("TkAgg")
        # Pin the font config before any Figure is constructed. DejaVu Sans
        # ships with matplotlib, so findfont resolves on the first candidate
        # without iterating the system font cache on each render. usetex is
        # explicit so any conditional LaTeX-backend probe short-circuits.
        matplotlib.rcParams["font.family"] = ["sans-serif"]
        matplotlib.rcParams["font.sans-serif"] = ["DejaVu Sans"]
        matplotlib.rcParams["text.usetex"] = False
        from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg as _FCA
        from matplotlib.figure import Figure as _F
        _Figure, _FigureCanvasTkAgg = _F, _FCA
    return _Figure, _FigureCanvasTkAgg

_PLUGIN_DIR = os.path.dirname(os.path.realpath(__file__))
_WAZUH_DIR = os.path.join(os.path.dirname(_PLUGIN_DIR), "wazuh")
_DATA_FILE = os.path.join(_PLUGIN_DIR, "data", "agent.013.json")
_EVENTS_FILE = os.path.join(_PLUGIN_DIR, "data", "log_events.json")
_VULNS_FILE = os.path.join(_PLUGIN_DIR, "data", "vulnerabilities.json")

_TAB_NAMES = ("Overview", "Events", "Vulnerabilities", "Inventory")
_LEGEND_KEYS = ("critical", "error", "warning", "info")
_SEVERITY_LEVELS = ("critical", "high", "medium", "low")
# Severity bucket → displayed badge label. The label is also the theme key
# used by _badge_colors (lowercased), so the badge color follows automatically.
# Shared by the Overview Security Alerts card and the Inventory device rows.
_SEV_TO_STATUS = {
    "critical": "CRITICAL",
    "high": "HIGH",
    "medium": "WARNING",
    "low": "OK",
}
# Sort priority for composite threat ranking. Higher is more severe.
_THREAT_RANK = {"critical": 4, "high": 3, "medium": 2, "low": 1, "ok": 0}
# Severity name → status_badge_* theme key.
# Color scheme:
#   critical  → violet
#   high      → red       (alias of "error")
#   medium    → orange    (alias of "warning")
#   low       → green     (alias of "ok")
#   info/unknown → blue   (alias of "info")
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

# Maps vuln status strings to a theme key recognized by _badge_colors.
# "detected" is not a status_badge_* key in the theme JSON; without this
# mapping the badge falls back to the muted default and the color reads
# as a missed lookup. Aliasing it to "warning" gives the orange severity
# treatment from the image.
_VULN_STATUS_BADGE = {
    "detected": "warning",
    "fixed": "ok",
    "mitigated": "info",
}


def _load_agent_data():
    try:
        with open(_DATA_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        logger.error(f"Endpoint 2: failed to load sample data ({_DATA_FILE}): {e}")
        return {}


# Agent + vuln data are loaded on first use rather than at module import so
# plugin discovery doesn't pay the JSON-parse cost when the user never opens
# the Wazuh plugin (or opens it but never visits Vulnerabilities/Overview).
_AGENT_DATA_CACHE = None


def _get_agent_data():
    global _AGENT_DATA_CACHE
    if _AGENT_DATA_CACHE is None:
        _AGENT_DATA_CACHE = _load_agent_data()
    return _AGENT_DATA_CACHE


def _load_vulns():
    try:
        with open(_VULNS_FILE, "r", encoding="utf-8") as f:
            payload = json.load(f) or {}
        return list(payload.get("cves") or [])
    except Exception as e:
        logger.error(f"Endpoint 2: failed to load vulns sample ({_VULNS_FILE}): {e}")
        return []


_VULNS_CACHE = None


def _get_vulns():
    global _VULNS_CACHE
    if _VULNS_CACHE is None:
        _VULNS_CACHE = _load_vulns()
    return _VULNS_CACHE


def _wazuh_level_to_severity(level):
    """Map a Wazuh rule.level (0–15) to one of the page's four severity buckets."""
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
    """Flatten an OpenSearch hit into the dict shape the events UI expects."""
    src = hit.get("_source") or {}
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

    return {
        "id": hit.get("_id") or src.get("id") or "",
        "rule_id": rule.get("id", ""),
        "level": rule.get("level"),
        "severity": _wazuh_level_to_severity(rule.get("level")),
        "description": rule.get("description", ""),
        "timestamp": src.get("timestamp") or "",
        "agent": agent.get("name", ""),
        "host": agent.get("name", ""),
        "ip": agent.get("ip", ""),
        "mitre": mitre,
        "hash": src.get("id", ""),
        "raw_log": raw_log,
    }


def _load_events_data():
    try:
        with open(_EVENTS_FILE, "r", encoding="utf-8") as f:
            payload = json.load(f)
        hits = ((payload.get("hits") or {}).get("hits") or []) if isinstance(payload, dict) else []
        events = [_normalize_wazuh_hit(h) for h in hits]
        # Sort newest first by timestamp; events without a timestamp sort to the end.
        events.sort(
            key=lambda e: e.get("timestamp") or "",
            reverse=True,
        )
        return events
    except Exception as e:
        logger.error(f"Endpoint 2: failed to load events sample ({_EVENTS_FILE}): {e}")
        return []


# Populated by the background loader below. The Events pane gates on
# _events_ready and shows a loading placeholder until the thread finishes,
# so the JSON parse + per-hit normalization stays off the import path and off
# the UI thread when the Wazuh page is first opened.
_EVENTS = []
_events_ready = threading.Event()


def _load_events_async():
    global _EVENTS
    try:
        _EVENTS = _load_events_data()
    finally:
        _events_ready.set()


threading.Thread(
    target=_load_events_async,
    name="endpoint2-events-loader",
    daemon=True,
).start()


# Inventory's multi-device dataset. Kicked off lazily on first Inventory-tab
# open rather than at import time, so users who never visit Inventory don't
# pay the tar-extraction + 47-JSON parse cost on plugin discovery.
_AGENTS = []
_agents_ready = threading.Event()
_agents_loader_started = False
_agents_loader_lock = threading.Lock()


def _shape_inventory_agent(summary, detail):
    """Map a /me/inventory summary device (and its optional /me/inventory/{id}
    detail) into the legacy {basic_info, syscollector, hardware} shape the
    Inventory tab's row builders read.

    Caller groups are stamped onto each device's basic_info because the API
    only returns devices in the caller's group, so the group-filter dropdown
    can still show the right value. Devices whose detail fetch failed get an
    empty syscollector — the Processes/Ports/Network views correctly render 0
    counts in that case."""
    caller_groups = []
    if _remote_agent_ready.is_set() and isinstance(_REMOTE_AGENT, dict):
        g = _REMOTE_AGENT.get("group") or []
        if isinstance(g, list):
            caller_groups = list(g)

    os_info = summary.get("os") or {}
    hw_info = summary.get("hardware") or {}
    # The /me/inventory summary carries no keep-alive field; the most recent
    # syscollector scan time is the best "last seen" signal available, so map
    # it onto lastKeepAlive (what the row renderers read). Fall back to the
    # hardware scan time if the OS scan is missing.
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


def _load_all_agents():
    """Fetch the device list from /api/v1/me/inventory and per-device detail
    from /api/v1/me/inventory/{id}, returning agent dicts in the legacy shape
    the Inventory tab consumes. Sequential per-device fetches — fine for the
    small group sizes this API serves (typical: 1–10 devices)."""
    devices, err = api_client.fetch_inventory_full()
    if err:
        logger.error(f"Inventory: fetch_inventory_full failed: {err}")
        return []
    if not devices:
        return []

    out = []
    for d in devices:
        agent_id = d.get("agent_id")
        detail = None
        if agent_id:
            detail, derr = api_client.fetch_device_inventory(agent_id)
            if derr:
                logger.warning(
                    f"Inventory: fetch_device_inventory({agent_id}) failed: {derr}"
                )
        out.append(_shape_inventory_agent(d, detail))
    return out


def _load_agents_async():
    global _AGENTS
    try:
        _AGENTS = _load_all_agents()
    finally:
        _agents_ready.set()


def _kick_agents_loader():
    """Start the agents loader thread once. Safe to call from the UI thread
    on every Inventory open — locked guard makes repeat calls a no-op."""
    global _agents_loader_started
    with _agents_loader_lock:
        if _agents_loader_started:
            return
        _agents_loader_started = True
    threading.Thread(
        target=_load_agents_async,
        name="endpoint2-agents-loader",
        daemon=True,
    ).start()


# Live data fetched from the /api/v1/me/* endpoints. Each slot gets its own
# threading.Event so the Overview tab's polling refresh can rebuild cards
# incrementally as each endpoint arrives, rather than waiting on the slowest.
# A per-slot error string captures failures so cards render "Couldn't load"
# instead of looping on "Loading…".
_REMOTE_AGENT = None
_REMOTE_AGENT_ERROR = None
_remote_agent_ready = threading.Event()

_REMOTE_VULNS = []
_REMOTE_VULNS_ERROR = None
_remote_vulns_ready = threading.Event()

_REMOTE_SCA = []
_REMOTE_SCA_ERROR = None
_remote_sca_ready = threading.Event()

_REMOTE_INVENTORY = {"total": 0, "items": []}
_REMOTE_INVENTORY_ERROR = None
_remote_inventory_ready = threading.Event()

_REMOTE_HOTFIXES = []
_REMOTE_HOTFIXES_ERROR = None
_remote_hotfixes_ready = threading.Event()

# Overview preloader. Fires from the Dashboard's first-build completion hook
# (see plugins/dashboard/main.py:_kick_overview_early_endpoints) to pre-warm
# every /me/* endpoint the Wazuh tab depends on, so subsequent tab opens have
# data already in hand. Idempotent via the locked started-flag, so the Wazuh
# tab's _kick_overview_api_loader call on tab entry is safe — it's a no-op
# whenever Dashboard already kicked things off.
_overview_early_loader_started = False
_overview_early_loader_lock = threading.Lock()


def _wait_for_vpn(poll_interval=2.0):
    """Block until the VPN tunnel reports connected. The /api/v1/me/* host
    is only reachable through the tunnel, so the preloader has to wait —
    otherwise every GET errors out and the Overview cards land in their
    "Couldn't load" state until something refreshes them.

    Lazy-imports `is_vpn_connected` so this module stays usable in stripped
    builds where the VPN plugin isn't shipped (the gate degrades to a no-op).
    plugins.vpn.main exposes no event/observer for state changes, so polling
    is the only option available today. Runs on the daemon preloader thread,
    so an indefinite wait is bounded by process lifetime."""
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
    while not is_vpn_connected():
        time.sleep(poll_interval)
    logger.info("[WAZUH-OVERVIEW] VPN tunnel up — preloader proceeding")


def _load_overview_early_async():
    """Sequentially fetch all five /me/* endpoints in the user-requested
    pre-warm order: agent → sca → hotfixes → vulnerabilities → inventory
    summary. Each sets its readiness event as it completes so cards on the
    Wazuh Overview tab can paint incrementally if the user navigates there
    while this is still running.

    Gated on VPN connectivity — the /me/* API is only reachable through the
    tunnel, so the thread parks at _wait_for_vpn() until the user has the
    VPN running."""
    _wait_for_vpn()

    global _REMOTE_AGENT, _REMOTE_AGENT_ERROR
    _REMOTE_AGENT, _REMOTE_AGENT_ERROR = api_client.fetch_agent()
    _remote_agent_ready.set()

    global _REMOTE_SCA, _REMOTE_SCA_ERROR
    data, err = api_client.fetch_sca()
    if data is not None:
        _REMOTE_SCA = data
    _REMOTE_SCA_ERROR = err
    _remote_sca_ready.set()

    global _REMOTE_HOTFIXES, _REMOTE_HOTFIXES_ERROR
    data, err = api_client.fetch_hotfixes()
    if data is not None:
        _REMOTE_HOTFIXES = data
    _REMOTE_HOTFIXES_ERROR = err
    _remote_hotfixes_ready.set()

    global _REMOTE_VULNS, _REMOTE_VULNS_ERROR
    # fetch_all_vulnerabilities loops fetch_inventory_full → fetch_vulnerabilities
    # per device, stamping agent_id + agent_name on every CVE so the
    # Vulnerabilities pane can attribute rows per-device. Sequential N+1 GETs;
    # acceptable cost for typical device counts.
    data, err = api_client.fetch_all_vulnerabilities()
    if data is not None:
        _REMOTE_VULNS = data
    _REMOTE_VULNS_ERROR = err
    _remote_vulns_ready.set()

    global _REMOTE_INVENTORY, _REMOTE_INVENTORY_ERROR
    data, err = api_client.fetch_inventory_summary()
    if data is not None:
        _REMOTE_INVENTORY = data
    _REMOTE_INVENTORY_ERROR = err
    _remote_inventory_ready.set()


def _kick_overview_early_loader():
    """Idempotent: spawn the preloader thread at most once per process."""
    global _overview_early_loader_started
    with _overview_early_loader_lock:
        if _overview_early_loader_started:
            return
        _overview_early_loader_started = True
    threading.Thread(
        target=_load_overview_early_async,
        name="endpoint2-overview-preloader",
        daemon=True,
    ).start()


def _kick_overview_api_loader():
    """Back-compat alias for the Wazuh Overview + Vulnerabilities panes' tab-
    entry kicks. Delegates to the preloader's idempotent kick — a no-op when
    the Dashboard's end-of-build hook already started the fetch. A future
    "Refresh" button can reset _overview_early_loader_started + the readiness
    events to force a fresh fetch."""
    _kick_overview_early_loader()


def _ready_mask():
    """Bitmask of which remote slots have completed (any state: data or error).
    Used by the refresh poll to detect transitions without re-rendering on
    every 100 ms tick."""
    return (
        (1 if _remote_agent_ready.is_set() else 0)
        | (2 if _remote_vulns_ready.is_set() else 0)
        | (4 if _remote_sca_ready.is_set() else 0)
        | (8 if _remote_inventory_ready.is_set() else 0)
        | (16 if _remote_hotfixes_ready.is_set() else 0)
    )


_READY_ALL = 31  # all 5 slots set


def _format_relative(iso_ts):
    """Return a compact 'X ago' string from an ISO-8601 timestamp."""
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
    """Format an ISO-8601 timestamp as 'MMM DD HH:MM:SS' (e.g. 'Apr 29 15:55:00')."""
    if not iso_ts:
        return "—"
    try:
        dt = datetime.fromisoformat(iso_ts.replace("Z", "+00:00"))
    except ValueError:
        return iso_ts
    return dt.strftime("%b %d %H:%M:%S")


def _short_benchmark_name(name):
    """Tidy a CIS-style policy name like CIS_Apple_macOS_15.0_Sequoia_Benchmark_v1.0.0."""
    if not name:
        return ""
    cleaned = name.replace("_", " ").replace("Apple ", "")
    return cleaned


# ----- module-card state helpers -----------------------------------------
# Module cards on the Overview pane reach one of four states: loading, error,
# unavailable (no backing endpoint), or loaded. The first three share enough
# chrome to factor into small builders so each card's branch in _module_cards
# only writes the loaded-state shape.


def _unavailable_card(title, description, target_tab=None):
    """Card stub for modules that have no /me/* endpoint yet."""
    card = {
        "title": title,
        "status": "INFO",
        "description": description,
        "stats": (("Data unavailable", "muted"),),
    }
    if target_tab:
        card["target_tab"] = target_tab
    return card


def _loading_card(title, description, target_tab=None):
    card = {
        "title": title,
        "status": "INFO",
        "description": description,
        "stats": (("Loading…", "muted"),),
    }
    if target_tab:
        card["target_tab"] = target_tab
    return card


def _error_card(title, description, target_tab=None):
    card = {
        "title": title,
        "status": "INFO",
        "description": description,
        "stats": (("Couldn't load", "muted"),),
    }
    if target_tab:
        card["target_tab"] = target_tab
    return card


def _bucket_by_severity(items):
    """Count items by their `severity` field across the four canonical buckets."""
    counts = {lvl: 0 for lvl in _SEVERITY_LEVELS}
    for it in items:
        sev = (it.get("severity") or "").lower() if isinstance(it, dict) else ""
        if sev in counts:
            counts[sev] += 1
    return counts


def _severity_stats(counts):
    """Render a counts dict into the (text, theme_key) tuples the card stats line uses."""
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
    """Best-effort check: prefer the agent's OS info from /me/agent so the
    "Not applicable" text matches what the Wazuh server actually reports for
    this machine; fall back to local platform.system() if the agent endpoint
    is still loading or errored."""
    if _remote_agent_ready.is_set() and isinstance(_REMOTE_AGENT, dict):
        os_info = _REMOTE_AGENT.get("os") or {}
        platform_name = (os_info.get("platform") or os_info.get("name") or "").lower()
        if platform_name:
            return "windows" in platform_name
    return _platform.system() == "Windows"


class Plugin(BasePlugin):
    """Endpoint 2 plugin — second sidebar entry, redesigned-architecture skeleton."""

    # Tell gui/user_interface.py to grid_forget our screen on navigation rather
    # than destroy it. Returning to Wazuh then reuses the cached widget tree
    # via create_main_screen() instead of rebuilding all panes from scratch.
    preserve_screen = True

    def __init__(self, app):
        super().__init__(
            id="013",
            version="2026.01.04-alpha",
            order=5.5,
            name="Wazuh",
            status=None,
            description="Placeholder for the redesigned endpoint page.",
            supported_systems=["Darwin", "Linux", "Windows"],
            translations={"US": "Wazuh", "ES": "Wazuh", "FR": "Wazuh"},
            icon_light_path=os.path.join(_WAZUH_DIR, "add_user_light.png"),
            icon_dark_path=os.path.join(_WAZUH_DIR, "add_user_dark.png"),
            uninstall_enabled=True,
        )
        self.app = app
        self._active_tab = None
        self._tab_buttons = {}
        self._tab_panes = {}
        self._module_grid_frame = None
        self._module_current_cols = None
        self._module_resize_after_id = None
        self._module_resize_handler_id = None
        self._padding_offset = 60 if _platform.system() == "Windows" else 40
        # Tracks which panes have been lazily built. _switch_tab consults this
        # so each pane pays its construction cost on first activation, not at
        # plugin open.
        self._tab_built = {name: False for name in _TAB_NAMES}
        # Appearance mode the cached widget tree was built under. create_main_screen
        # compares this to the current mode and rebuilds if the theme switched
        # while the plugin was off-screen (preserved widgets don't auto-refresh
        # matplotlib facecolors and other build-time-resolved hex strings).
        self._cached_appearance_mode = None
        # Per-instance caches populated lazily on first use. Reset implicitly
        # when the Plugin instance is recreated (e.g. plugin reload), or
        # explicitly when the underlying data identity changes (see the
        # aggregation memoization in _severity_counts etc).
        self._fonts_cache = None
        self._theme_cache = {}
        self._severity_counts_cache = None  # (id(_EVENTS), result) or None
        self._bucket_events_cache = None    # (id(_EVENTS), result) or None
        self._vuln_severity_cache = None    # (id(vulns), result) or None
        self._bucket_vulns_cache = None     # (id(vulns), result) or None
        # Events pane state
        self._selected_event_id = None
        self._event_list_frame = None
        self._event_detail_frame = None
        self._event_row_frames = {}
        self._event_search_var = None
        self._event_count_label = None
        self._event_chart_canvas = None
        self._event_chart_figure = None
        self._chart_ax = None
        self._chart_buckets = []
        self._chart_counts = {}
        self._selected_bucket = None  # datetime of the active 30-min bucket filter, or None
        self._events_ready_after_id = None  # poll handle for the background events loader
        self._prebuild_after_id = None  # handle for the inactive-tab pre-build chain
        self._overview_events_after_id = None  # poll handle for the Overview's API-data refresh
        self._overview_ready_mask = -1  # last-seen _ready_mask(); -1 == no render yet
        self._overview_parent = None  # parent of the Overview pane (for re-grid on refresh)
        self._device_card_frame = None  # top device widget; destroyed + rebuilt on data arrival
        self._alert_bar_frame = None  # alert bar; destroyed + rebuilt on data arrival
        self._inventory_after_id = None  # poll handle for the Inventory agents loader
        self._inventory_pane_parent = None  # reference for swapping loading → list
        # Active category in the Inventory tab's dropdown. One of:
        # "Devices" | "Processes" | "Ports" | "Network". Persists across
        # plugin re-entries via preserve_screen=True, and across the
        # loading→ready transition so a user who switched views before data
        # arrived sees their choice when the list paints.
        self._inventory_view = "Devices"
        # Active group filter. Default "All groups" shows every device;
        # otherwise the value matches one of the agent group names parsed
        # from basic_info.group across the loaded agents, or "(no group)"
        # for agents whose group field is missing/empty.
        self._inventory_group = "All groups"
        # Active page in the inventory list. 1-based. Resets to 1 whenever
        # the category or group filter changes (otherwise a stale page index
        # could land out of range when the filtered row count shrinks).
        self._inventory_page = 1
        self._inventory_wrapper = None  # outer bordered card; dropdown callback re-renders into it
        self._inventory_count_label = None  # secondary label under the dropdown
        self._inventory_pagination_frame = None  # right-aligned pager; rebuilt on each body render
        # Vulnerabilities pane state
        self._vuln_search_var = None
        self._vuln_count_label = None
        self._vuln_list_frame = None
        self._vuln_donut_figure = None
        self._vuln_donut_canvas = None
        self._vuln_cvss_figure = None
        self._vuln_cvss_canvas = None
        self._vuln_after_id = None  # poll handle for the Vulnerabilities readiness check
        self._vuln_pane_parent = None  # reference for swapping loading -> table
        # Active device filter on the Vulnerabilities table dropdown. Resolved
        # lazily by _default_vuln_device() once _REMOTE_VULNS arrives.
        self._vuln_device = None
        # Vulnerabilities row selection — mirrors the Events pane's pattern.
        # Composite key f"{agent_id}::{cve_id}" so the same CVE on different
        # devices ("All devices" view) doesn't collide.
        self._selected_vuln_key = None
        self._vuln_row_frames = {}
        self._vuln_detail_frame = None
        # Donut-driven severity filter. None = show every severity; otherwise
        # one of _SEVERITY_LEVELS. Set by clicking a donut slice; clicking
        # the active slice again clears it (toggle).
        self._vuln_severity_filter = None
        # (wedge_artist, severity_level) pairs for the active donut. Used by
        # the click handler to match a click to a slice and to re-skin alpha
        # without rebuilding the chart.
        self._vuln_donut_wedges = []

    def check_status(self):
        return None

    # ----- screen scaffold ---------------------------------------------------

    def create_main_screen(self):
        # Reuse the preserved widget tree from a prior visit when possible.
        # Skip the cache if the appearance mode changed while we were
        # off-screen — matplotlib facecolors and a few other hex strings are
        # resolved at build time and won't auto-refresh.
        current_mode = customtkinter.get_appearance_mode()
        cached = getattr(self, "main_container", None)
        if (
            cached is not None
            and cached.winfo_exists()
            and self._cached_appearance_mode == current_mode
        ):
            return cached
        # Stale cache (theme changed): tear down before rebuilding.
        if cached is not None:
            try:
                if cached.winfo_exists():
                    cached.destroy()
            except Exception:
                pass
        self._cached_appearance_mode = current_mode

        # Outer frame is what select_frame_by_name grids; it forces row 0 weight=1
        # on the returned widget, so we use an inner layout frame for our own
        # multi-row structure (tab strip + content).
        self.main_container = customtkinter.CTkFrame(
            self.app, corner_radius=0, fg_color=["gray92", "gray14"]
        )
        self.main_container.grid_columnconfigure(0, weight=1)
        self.main_container.grid_rowconfigure(0, weight=1)

        self._page = customtkinter.CTkFrame(self.main_container, fg_color="transparent")
        self._page.grid(row=0, column=0, sticky="nsew")
        self._page.grid_columnconfigure(0, weight=1)
        self._page.grid_rowconfigure(0, weight=0)  # tab strip — fixed height
        self._page.grid_rowconfigure(1, weight=1)  # content — takes remaining space

        # _build_tab_strip / _build_content_area replaced the widgets in
        # _tab_buttons and _tab_panes with fresh instances. Reset _active_tab
        # so _switch_tab doesn't short-circuit on the stale "previous session"
        # value and skip gridding the Overview pane.
        self._active_tab = None
        # Drop any stale chart filter — the rebuilt chart computes fresh
        # bucket datetimes; an old _selected_bucket might no longer match.
        self._selected_bucket = None
        self._build_tab_strip()
        self._build_content_area()
        self._switch_tab("Overview")
        # Kick off background pre-build of the inactive tabs once Overview is
        # active, so the user's first click on Events/Vulnerabilities is instant.
        self._schedule_prebuild()

        return self.main_container

    def _schedule_prebuild(self):
        """Queue background pre-build of any unbuilt panes. Idempotent — a
        pending schedule is replaced rather than stacked."""
        pending = self._prebuild_after_id
        if pending is not None:
            try:
                self.app.after_cancel(pending)
            except Exception:
                pass
        # Delay slightly so the Overview pane gets a chance to paint before the
        # heavy prebuild work steals the UI thread.
        self._prebuild_after_id = self.app.after(100, self._run_prebuild)

    def _run_prebuild(self):
        """One chunk of inactive-tab pre-build. Builds Vulnerabilities first
        (no async deps), then Events when its background loader is ready.
        Yields to the event loop between chunks so user input can interleave."""
        self._prebuild_after_id = None
        container = getattr(self, "main_container", None)
        if container is None or not container.winfo_exists():
            return

        # Step A — Vulnerabilities. No async dependency; always buildable.
        if not self._tab_built.get("Vulnerabilities", False):
            pane = self._tab_panes.get("Vulnerabilities")
            if pane is not None and pane.winfo_exists():
                try:
                    self._build_vulnerabilities_pane(pane)
                    self._tab_built["Vulnerabilities"] = True
                except Exception as e:
                    logger.error(f"Wazuh: vulnerabilities prebuild failed: {e}")
                    self._tab_built["Vulnerabilities"] = True  # don't retry forever
            # Yield so any pending user input can fire before the Events chunk.
            self._prebuild_after_id = self.app.after(0, self._run_prebuild)
            return

        # Step B — Events. Only build when the loader thread has finished,
        # otherwise the on-click polling chain in _schedule_events_ready_check
        # would race with us.
        if not self._tab_built.get("Events", False):
            if _events_ready.is_set():
                pane = self._tab_panes.get("Events")
                if pane is not None and pane.winfo_exists():
                    try:
                        self._build_events_pane(pane)
                        self._tab_built["Events"] = True
                    except Exception as e:
                        logger.error(f"Wazuh: events prebuild failed: {e}")
                        self._tab_built["Events"] = True
            else:
                # Events data not ready yet; recheck periodically until it is or
                # the user clicks Events themselves (which sets _tab_built).
                self._prebuild_after_id = self.app.after(200, self._run_prebuild)

    def _build_tab_strip(self):
        text_color = ThemeManager.theme.get("CTkLabel", {}).get(
            "text_color", ["#000000", "#FFFFFF"]
        )
        hover_bg = ThemeManager.theme.get("Theme", {}).get(
            "sidebar_hover_bg", ["#F0F0F5", "#1F1F22"]
        )
        accent = ThemeManager.theme.get("Theme", {}).get(
            "sidebar_active_text", ["#0D5394", "#60A5FA"]
        )
        self._accent_color = accent
        self._text_color = text_color
        self._hover_bg = hover_bg

        self._tab_strip = customtkinter.CTkFrame(self._page, fg_color="transparent")
        self._tab_strip.grid(row=0, column=0, sticky="new", padx=20, pady=(0, 0))
        for col in range(len(_TAB_NAMES)):
            self._tab_strip.grid_columnconfigure(col, weight=0)
        self._tab_strip.grid_columnconfigure(len(_TAB_NAMES), weight=1)

        for i, name in enumerate(_TAB_NAMES):
            btn = customtkinter.CTkButton(
                self._tab_strip,
                text=name,
                fg_color="transparent",
                hover_color=hover_bg,
                text_color=text_color,
                corner_radius=0,
                border_width=0,
                width=0,
                height=30,
                font=customtkinter.CTkFont(size=14, weight="normal"),
                command=lambda n=name: self._on_tab_click(n),
            )
            btn.grid(row=0, column=i, sticky="w", padx=(0, 24), pady=(4, 4))
            self._tab_buttons[name] = btn

        self._tab_underline = customtkinter.CTkFrame(
            self._tab_strip, height=2, fg_color=accent, corner_radius=1
        )

        divider_color = ThemeManager.theme.get("Theme", {}).get(
            "divider_color", ["#E5E7EB", "#2A2A2A"]
        )
        self._tab_separator = customtkinter.CTkFrame(
            self._page, height=1, fg_color=divider_color, corner_radius=0
        )
        self._tab_separator.grid(row=0, column=0, sticky="sew", padx=20)

    def _build_content_area(self):
        self._tab_content_holder = customtkinter.CTkFrame(self._page, fg_color="transparent")
        self._tab_content_holder.grid(
            row=1, column=0, sticky="nsew", padx=20, pady=(8, 12)
        )
        self._tab_content_holder.grid_columnconfigure(0, weight=1)
        self._tab_content_holder.grid_rowconfigure(0, weight=1)

        for name in _TAB_NAMES:
            if name == "Overview":
                # Overview can overflow vertically (3x3 grid + top card + alerts);
                # use a scrollable frame so the content stays accessible at small
                # window heights. AppUI._install_scroll_behaviors picks this up
                # automatically and adds smooth-scroll + auto-hide scrollbar.
                pane = customtkinter.CTkScrollableFrame(
                    self._tab_content_holder, fg_color="transparent"
                )
            else:
                pane = customtkinter.CTkFrame(
                    self._tab_content_holder, fg_color="transparent"
                )
            pane.grid_columnconfigure(0, weight=1)
            pane.grid_rowconfigure(0, weight=1)
            self._tab_panes[name] = pane

        # Pane frames above are freshly created on each create_main_screen call,
        # so reset the lazy-build flags to match. _switch_tab will populate each
        # pane the first time it's shown.
        self._tab_built = {name: False for name in _TAB_NAMES}

    def _switch_tab(self, name):
        if name not in self._tab_panes:
            return
        if self._active_tab == name:
            return

        if self._active_tab and self._active_tab in self._tab_panes:
            self._tab_panes[self._active_tab].grid_remove()
            old_btn = self._tab_buttons.get(self._active_tab)
            if old_btn:
                old_btn.configure(
                    text_color=self._text_color,
                    font=customtkinter.CTkFont(size=14, weight="normal"),
                )

        self._active_tab = name
        pane = self._tab_panes[name]
        # Build the pane on first activation so plugin open only pays for the
        # default (Overview) tab; other panes build when the user clicks them.
        if not self._tab_built.get(name, False):
            builder = {
                "Overview": self._build_overview_pane,
                "Events": self._build_events_pane,
                "Vulnerabilities": self._build_vulnerabilities_pane,
                "Inventory": self._build_inventory_pane,
            }.get(name)
            if builder is not None:
                builder(pane)
                self._tab_built[name] = True
        pane.grid(row=0, column=0, sticky="nsew")

        new_btn = self._tab_buttons[name]
        new_btn.configure(
            text_color=self._accent_color,
            font=customtkinter.CTkFont(size=14, weight="bold"),
        )
        col = _TAB_NAMES.index(name)
        self._tab_underline.grid(row=1, column=col, sticky="ew", padx=(0, 24), pady=(0, 0))

        # Record the active tab as page state. record_page_state checks
        # _nav_suppress internally so back/forward replays are a no-op, and it
        # promotes a stateless landing entry (e.g. (Wazuh, None) from a sidebar
        # click) in place rather than appending a duplicate.
        if hasattr(self.app, "record_page_state"):
            self.app.record_page_state(name)

    def _on_tab_click(self, name):
        self._switch_tab(name)

    def apply_state(self, state):
        target = state if state in _TAB_NAMES else "Overview"
        self._switch_tab(target)

    # ----- theme helpers -----------------------------------------------------

    def _theme(self, *keys, default=None):
        # Memoize hits — the row builders call this dozens of times per render,
        # multiplied by 250+ rows, and ThemeManager.theme dict walks aren't free.
        # Don't cache misses so different defaults still work for unknown keys.
        cached = self._theme_cache.get(keys)
        if cached is not None:
            return cached
        node = ThemeManager.theme.get("Theme", {})
        for k in keys:
            if not isinstance(node, dict):
                return default
            node = node.get(k)
            if node is None:
                return default
        self._theme_cache[keys] = node
        return node

    def _ensure_fonts(self):
        """Return a registry of CTkFont instances shared across row builders.
        Constructing CTkFont per row was ~1,250 instantiations for the events
        list; reusing a handful of fonts drops that to a one-time build."""
        if self._fonts_cache is not None:
            return self._fonts_cache
        self._fonts_cache = {
            "dot_14": customtkinter.CTkFont(size=14),
            "inter_bold_12": customtkinter.CTkFont(family="Inter", size=12, weight="bold"),
            "size_12": customtkinter.CTkFont(size=12),
            "size_11": customtkinter.CTkFont(size=11),
            "bold_10": customtkinter.CTkFont(size=10, weight="bold"),
            "size_10": customtkinter.CTkFont(size=10),
            "inter_bold_14": customtkinter.CTkFont(family="Inter", size=14, weight="bold"),
            "inter_bold_13": customtkinter.CTkFont(family="Inter", size=13, weight="bold"),
        }
        return self._fonts_cache

    def _segment_color(self, key):
        if key == "muted":
            return self._theme("text_secondary", default=["#6B7280", "#9CA3AF"])
        return self._theme("status_badge_text", key, default=["#6B7280", "#9CA3AF"])

    def _badge_colors(self, status):
        key = status.lower()
        if key == "vuln":
            key = "error"
        bg = self._theme("status_badge_bg", key, default=["#F3F4F6", "#1F2937"])
        fg = self._theme("status_badge_text", key, default=["#6B7280", "#9CA3AF"])
        return bg, fg

    # ----- Overview pane -----------------------------------------------------

    def _build_overview_pane(self, parent):
        # Inside a scrollable frame: keep all rows weight=0 so each section
        # takes its natural height and overflow drives the scrollbar.
        parent.grid_columnconfigure(0, weight=1)
        for r in range(4):
            parent.grid_rowconfigure(r, weight=0)

        self._overview_parent = parent
        self._overview_ready_mask = _ready_mask()

        self._build_top_device_widget(parent, row=0)
        self._build_alert_bar(parent, row=1)
        self._build_modules_header(parent, row=2)
        self._build_module_grid(parent, row=3)

        # Live data comes from /api/v1/me/*. Kick the loader (idempotent —
        # repeat calls short-circuit on the locked guard) and poll for
        # readiness; the device card, alert bar, and module grid all read
        # from the per-endpoint module globals via accessor helpers and
        # render "Loading…" until each event fires.
        _kick_overview_api_loader()
        if _ready_mask() != _READY_ALL:
            self._schedule_overview_data_refresh()

    def _schedule_overview_data_refresh(self):
        if self._overview_events_after_id is not None:
            return  # already polling

        def check():
            self._overview_events_after_id = None
            wrapper = self._module_wrapper
            if wrapper is None or not wrapper.winfo_exists():
                return

            mask = _ready_mask()
            if mask != self._overview_ready_mask:
                self._overview_ready_mask = mask
                self._refresh_overview_section()

            if mask == _READY_ALL:
                return
            self._overview_events_after_id = self.app.after(100, check)

        self._overview_events_after_id = self.app.after(100, check)

    def _refresh_overview_section(self):
        """Rebuild the device card, alert bar, and module grid against the
        current snapshot of the remote-data globals. Called from the polling
        callback each time a new endpoint completes; safe to call repeatedly."""
        parent = self._overview_parent
        if parent is None or not parent.winfo_exists():
            return

        for attr in ("_device_card_frame", "_alert_bar_frame"):
            frame = getattr(self, attr, None)
            if frame is not None:
                try:
                    if frame.winfo_exists():
                        frame.destroy()
                except Exception:
                    pass
                setattr(self, attr, None)

        self._build_top_device_widget(parent, row=0)
        self._build_alert_bar(parent, row=1)
        self._populate_module_grid()

    # ----- section 1: top device widget --------------------------------------

    def _build_top_device_widget(self, parent, row):
        text_secondary = self._theme("text_secondary", default=["#6B7280", "#9CA3AF"])
        divider_color = self._theme("divider_color", default=["#E5E7EB", "#2A2A2A"])

        # Card frame is created regardless of data state so the grid row stays
        # occupied; inner content diverges per state below.
        card = customtkinter.CTkFrame(parent, corner_radius=12, border_width=1)
        card.grid(row=row, column=0, sticky="ew", pady=(0, 12))
        card.grid_columnconfigure(0, weight=1)
        self._device_card_frame = card

        # Loading / error states: render a compact placeholder and return.
        # Once _remote_agent_ready fires, _refresh_overview_section destroys
        # this frame and rebuilds with the loaded path below.
        if not _remote_agent_ready.is_set():
            self._device_placeholder(card, "Loading device info…", text_secondary)
            return
        if _REMOTE_AGENT_ERROR or not _REMOTE_AGENT:
            self._device_placeholder(
                card, "Couldn't load device info", text_secondary
            )
            return

        bi = _REMOTE_AGENT
        os_info = bi.get("os") or {}
        name = bi.get("name") or "(unknown device)"
        os_name = os_info.get("name") or ""
        os_version = os_info.get("version") or ""
        os_arch = os_info.get("arch") or ""
        agent_id = bi.get("id") or ""
        wazuh_version_full = bi.get("version") or ""
        wazuh_version = wazuh_version_full.replace("Wazuh ", "") if wazuh_version_full else ""

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

        last_seen = _format_relative(bi.get("lastKeepAlive"))
        state_label = "Online" if is_connected else "Offline"
        manager = bi.get("manager") or ""
        ip = bi.get("ip") or ""
        groups = bi.get("group") or []
        group_text = ", ".join(groups) if groups else ""
        node = bi.get("node_name") or ""

        facts = [f"Last seen {last_seen}", state_label]
        if manager:
            facts.append(f"Manager {manager}")
        if ip:
            facts.append(f"IP {ip}")
        if group_text:
            facts.append(f"Group {group_text}")
        if node:
            facts.append(f"Node {node}")
        facts_text = "  ·  ".join(facts)

        # Top: name + meta + status badge
        top = customtkinter.CTkFrame(card, fg_color="transparent")
        top.grid(row=0, column=0, sticky="ew", padx=20, pady=(16, 10))
        top.grid_columnconfigure(0, weight=1)
        top.grid_columnconfigure(1, weight=0)

        left = customtkinter.CTkFrame(top, fg_color="transparent")
        left.grid(row=0, column=0, sticky="w")

        customtkinter.CTkLabel(
            left,
            text="THIS DEVICE",
            text_color=text_secondary,
            font=customtkinter.CTkFont(size=10, weight="bold"),
        ).grid(row=0, column=0, sticky="w", pady=(0, 4))

        customtkinter.CTkLabel(
            left,
            text=name,
            font=customtkinter.CTkFont(family="Inter", size=22, weight="bold"),
        ).grid(row=1, column=0, sticky="w")

        if meta_text:
            customtkinter.CTkLabel(
                left,
                text=meta_text,
                text_color=text_secondary,
                font=customtkinter.CTkFont(size=12),
            ).grid(row=2, column=0, sticky="w", pady=(4, 0))

        badge_status = "ok" if is_connected else "error"
        bg = self._theme("status_badge_bg", badge_status, default=["#FEE2E2", "#7F1D1D"])
        fg = self._theme("status_badge_text", badge_status, default=["#DC2626", "#F87171"])
        customtkinter.CTkLabel(
            top,
            text=f"  ●  {connectivity_label}  ",
            fg_color=bg,
            text_color=fg,
            corner_radius=6,
            font=customtkinter.CTkFont(size=11, weight="bold"),
        ).grid(row=0, column=1, sticky="ne")

        # Divider
        customtkinter.CTkFrame(card, height=1, fg_color=divider_color, corner_radius=0).grid(
            row=1, column=0, sticky="ew", padx=20
        )

        # Bottom: facts row + Config opened
        bot = customtkinter.CTkFrame(card, fg_color="transparent")
        bot.grid(row=2, column=0, sticky="ew", padx=20, pady=(10, 16))
        bot.grid_columnconfigure(0, weight=1)
        bot.grid_columnconfigure(1, weight=0)

        customtkinter.CTkLabel(
            bot,
            text=facts_text,
            text_color=text_secondary,
            font=customtkinter.CTkFont(size=12),
            anchor="w",
            justify="left",
        ).grid(row=0, column=0, sticky="w")

        customtkinter.CTkButton(
            bot,
            text="Config opened",
            fg_color="transparent",
            text_color=text_secondary,
            hover_color=self._hover_bg,
            corner_radius=6,
            width=0,
            height=24,
            font=customtkinter.CTkFont(size=12),
            command=self._on_config_click,
        ).grid(row=0, column=1, sticky="e", padx=(8, 0))

    def _on_config_click(self):
        logger.info("Endpoint 2: Config opened (placeholder)")

    def _device_placeholder(self, card, message, text_secondary):
        """Render the THIS DEVICE label + a single muted line inside the card.
        Used for Loading / Couldn't-load states so the row keeps its shape."""
        customtkinter.CTkLabel(
            card,
            text="THIS DEVICE",
            text_color=text_secondary,
            font=customtkinter.CTkFont(size=10, weight="bold"),
        ).grid(row=0, column=0, sticky="w", padx=20, pady=(16, 4))
        customtkinter.CTkLabel(
            card,
            text=message,
            text_color=text_secondary,
            font=customtkinter.CTkFont(size=14),
        ).grid(row=1, column=0, sticky="w", padx=20, pady=(0, 16))

    # ----- section 2: alert bar ----------------------------------------------

    def _build_alert_bar(self, parent, row):
        warn_bg = self._theme("protection_bg_warn", default=["#FEF3C7", "#2D1F05"])
        warn_text = self._theme("protection_text_warn", default=["#B45309", "#FBBF24"])
        ok_bg = self._theme("protection_bg_ok", default=["#DCFCE7", "#0A2F1A"])
        ok_text = self._theme("protection_text_ok", default=["#15803D", "#4ADE80"])
        muted_bg = self._theme("protection_bg_warn", default=["#F3F4F6", "#1F2937"])
        muted_text = self._theme("text_secondary", default=["#6B7280", "#9CA3AF"])
        # Reconnect-button colors come from the "error" theme key (red), not the
        # severity scheme. Buttons should never inherit severity colors —
        # Reconnect is an error-fix action, not a "critical-severity" indicator.
        err_bg = self._theme("status_badge_bg", "error", default=["#FEE2E2", "#7F1D1D"])
        err_text = self._theme("status_badge_text", "error", default=["#DC2626", "#F87171"])

        # Loading / error: render a single muted bar so the row keeps its
        # shape; the polling refresh will swap in the real bar once the
        # agent endpoint completes.
        if not _remote_agent_ready.is_set() or _REMOTE_AGENT_ERROR or not _REMOTE_AGENT:
            bar = customtkinter.CTkFrame(parent, fg_color=muted_bg, corner_radius=8)
            bar.grid(row=row, column=0, sticky="ew", pady=(0, 16))
            bar.grid_columnconfigure(0, weight=1)
            msg = (
                "Loading agent status…"
                if not _remote_agent_ready.is_set()
                else "Couldn't load agent status."
            )
            customtkinter.CTkLabel(
                bar,
                text=msg,
                text_color=muted_text,
                font=customtkinter.CTkFont(size=13),
            ).grid(row=0, column=0, sticky="w", padx=16, pady=12)
            self._alert_bar_frame = bar
            return

        bi = _REMOTE_AGENT
        is_connected = (bi.get("status") or "").lower() in ("active", "connected")
        last_keep = _format_relative(bi.get("lastKeepAlive"))
        disc_at = _format_relative(bi.get("disconnection_time"))

        if is_connected:
            bg, txt = ok_bg, ok_text
            icon = "●"
            msg = f"Agent is connected. Last keep-alive {last_keep}."
        else:
            bg, txt = warn_bg, warn_text
            icon = "⚠"
            msg = (
                f"Agent is disconnected. Last contact with Wazuh manager was "
                f"{disc_at}. Plugin features below reflect the last successful scan."
            )

        bar = customtkinter.CTkFrame(parent, fg_color=bg, corner_radius=8)
        bar.grid(row=row, column=0, sticky="ew", pady=(0, 16))
        bar.grid_columnconfigure(0, weight=1)
        bar.grid_columnconfigure(1, weight=0)
        bar.grid_columnconfigure(2, weight=0)
        self._alert_bar_frame = bar

        customtkinter.CTkLabel(
            bar,
            text=f"{icon}  {msg}",
            text_color=txt,
            font=customtkinter.CTkFont(size=12),
            anchor="w",
            justify="left",
            wraplength=720,
        ).grid(row=0, column=0, sticky="w", padx=(14, 12), pady=10)

        # The severity color legend lives in the modules header (directly above
        # the colored cards), so it's intentionally not repeated here.

        if not is_connected:
            customtkinter.CTkButton(
                bar,
                text="Reconnect agent",
                fg_color=err_text,
                hover_color=err_bg,
                text_color=["#FFFFFF", "#FFFFFF"],
                width=140,
                height=32,
                corner_radius=8,
                font=customtkinter.CTkFont(size=12, weight="bold"),
                command=self._on_reconnect_click,
            ).grid(row=0, column=2, sticky="e", padx=(0, 12), pady=8)

    def _on_reconnect_click(self):
        logger.info("Endpoint 2: Reconnect clicked (placeholder)")

    # ----- section 3 (a): modules section header -----------------------------

    def _build_modules_header(self, parent, row):
        text_secondary = self._theme("text_secondary", default=["#6B7280", "#9CA3AF"])

        header = customtkinter.CTkFrame(parent, fg_color="transparent")
        header.grid(row=row, column=0, sticky="ew", pady=(0, 8))
        header.grid_columnconfigure(0, weight=1)
        header.grid_columnconfigure(1, weight=0)

        title_row = customtkinter.CTkFrame(header, fg_color="transparent")
        title_row.grid(row=0, column=0, sticky="w")

        customtkinter.CTkLabel(
            title_row,
            text="WAZUH MODULES",
            font=customtkinter.CTkFont(size=11, weight="bold"),
        ).grid(row=0, column=0, sticky="w", padx=(0, 10))

        customtkinter.CTkLabel(
            title_row,
            text="status of each plugin on this device",
            text_color=text_secondary,
            font=customtkinter.CTkFont(size=11),
        ).grid(row=0, column=1, sticky="w")

        legend = customtkinter.CTkFrame(header, fg_color="transparent")
        legend.grid(row=0, column=1, sticky="e")
        for i, key in enumerate(_LEGEND_KEYS):
            color = self._segment_color(key)
            customtkinter.CTkLabel(
                legend,
                text=f"●  {key.capitalize()}",
                text_color=color,
                font=customtkinter.CTkFont(size=11, weight="bold"),
            ).grid(row=0, column=i, sticky="w", padx=(0, 10))

    # ----- section 3 (b): module card grid -----------------------------------

    def _build_module_grid(self, parent, row):
        wrapper = customtkinter.CTkFrame(parent, fg_color="transparent")
        wrapper.grid(row=row, column=0, sticky="nsew")
        wrapper.grid_columnconfigure(0, weight=1)
        wrapper.grid_rowconfigure(0, weight=1)
        self._module_wrapper = wrapper

        self._populate_module_grid()
        self._bind_module_resize()

    def _compute_max_cols(self):
        try:
            window_width = self.app.winfo_width()
        except Exception:
            window_width = 0
        if window_width <= 1:
            try:
                window_width = int(self.app.winfo_screenwidth() * 0.7)
            except Exception:
                window_width = 1024
        content_width = max(1, window_width - 250 - self._padding_offset)
        if content_width < 480:
            return 1
        if content_width < 720:
            return 2
        return 3

    def _module_cards(self):
        """Compute module-card data from the live /api/v1/me/* responses.

        Cards backed by an endpoint cycle through four states: loading (slot's
        Event not yet set), loaded (data arrived), error (slot's Event set but
        client returned an error), and — for hotfixes — a "not applicable"
        variant when the platform legitimately has no data. Cards with no
        endpoint backing (Security Alerts, File Integrity, Rootcheck) render
        a permanent "Data unavailable" pending future API support."""
        cards = []

        cards.append(_unavailable_card(
            "Security Alerts",
            "Threats and security incidents detected",
            target_tab="Events",
        ))

        cards.append(self._vuln_card())
        cards.append(self._sca_card())

        cards.append(_unavailable_card(
            "File Integrity",
            "Created · added/modified · deleted",
        ))
        cards.append(_unavailable_card(
            "Rootcheck",
            "Recent rootkit / process detection",
        ))

        cards.append(self._hotfix_card())
        cards.append(self._inventory_card())
        cards.append(self._agent_health_card())
        cards.append(self._manager_card())

        return cards

    def _vuln_card(self):
        title = "Vulnerabilities"
        desc = "CVEs across installed packages"
        target = "Vulnerabilities"
        if not _remote_vulns_ready.is_set():
            return _loading_card(title, desc, target_tab=target)
        if _REMOTE_VULNS_ERROR:
            return _error_card(title, desc, target_tab=target)
        counts = _bucket_by_severity(_REMOTE_VULNS)
        total = sum(counts.values())
        if total == 0:
            return {
                "title": title,
                "status": "OK",
                "description": desc,
                "stats": (("No vulnerabilities", "ok"),),
                "target_tab": target,
            }
        highest = next(
            (s for s in _SEVERITY_LEVELS if counts.get(s, 0) > 0),
            "low",
        )
        stats = _severity_stats(counts)
        return {
            "title": title,
            "status": _SEV_TO_STATUS[highest],
            "description": desc,
            "stats": stats,
            "target_tab": target,
        }

    def _sca_card(self):
        title = "Compliance · SCA"
        if not _remote_sca_ready.is_set():
            return _loading_card(title, "OS signature checks and benchmarks")
        if _REMOTE_SCA_ERROR:
            return _error_card(title, "OS signature checks and benchmarks")
        if not _REMOTE_SCA:
            return {
                "title": title,
                "status": "INFO",
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
            (f"{score}% score", score_color),
            ("  ·  ", "muted"),
            (f"{passed} pass", "ok"),
            ("  ·  ", "muted"),
            (f"{failed} fail", "error"),
        ]
        if invalid:
            stats.extend([("  ·  ", "muted"), (f"{invalid} invalid", "muted")])
        return {
            "title": title,
            "status": sca_status,
            "description": desc,
            "stats": tuple(stats),
        }

    def _hotfix_card(self):
        title = "Hotfixes"
        desc = "Windows KB updates applied"
        if not _remote_hotfixes_ready.is_set():
            return _loading_card(title, desc)
        if _REMOTE_HOTFIXES_ERROR:
            return _error_card(title, desc)
        if not _REMOTE_HOTFIXES:
            # Empty list is a successful response. Distinguish "non-Windows
            # OS — N/A" from "Windows but nothing reported" via the agent's
            # OS info; fall back to the local platform if the agent endpoint
            # is still pending or errored.
            if _is_windows_agent():
                return {
                    "title": title,
                    "status": "INFO",
                    "description": desc,
                    "stats": (("No hotfixes reported", "muted"),),
                }
            return {
                "title": title,
                "status": "INFO",
                "description": desc,
                "stats": (("Not applicable on this OS", "muted"),),
            }
        n = len(_REMOTE_HOTFIXES)
        noun = "hotfix" if n == 1 else "hotfixes"
        return {
            "title": title,
            "status": "OK",
            "description": desc,
            "stats": ((f"{n} {noun} installed", "ok"),),
        }

    def _inventory_card(self):
        title = "Inventory"
        desc = "Devices linked to your account"
        target = "Inventory"
        if not _remote_inventory_ready.is_set():
            return _loading_card(title, desc, target_tab=target)
        if _REMOTE_INVENTORY_ERROR:
            return _error_card(title, desc, target_tab=target)
        total = int(_REMOTE_INVENTORY.get("total") or 0)
        if total == 0:
            return {
                "title": title,
                "status": "INFO",
                "description": desc,
                "stats": (("No devices", "muted"),),
                "target_tab": target,
            }
        noun = "device" if total == 1 else "devices"
        return {
            "title": title,
            "status": "OK",
            "description": desc,
            "stats": ((f"{total} {noun}", "muted"),),
            "target_tab": target,
        }

    def _agent_health_card(self):
        title = "Agent Health"
        desc = "Connectivity & configuration"
        if not _remote_agent_ready.is_set():
            return _loading_card(title, desc)
        if _REMOTE_AGENT_ERROR or not _REMOTE_AGENT:
            return _error_card(title, desc)
        bi = _REMOTE_AGENT
        is_connected = (bi.get("status") or "").lower() in ("active", "connected")
        if is_connected:
            return {
                "title": title,
                "status": "OK",
                "description": desc,
                "stats": (
                    (f"Connected · keep-alive {_format_relative(bi.get('lastKeepAlive'))}", "ok"),
                ),
            }
        return {
            "title": title,
            "status": "ERROR",
            "description": desc,
            "stats": (
                (f"Disconnected · {_format_relative(bi.get('disconnection_time'))}", "error"),
            ),
        }

    def _manager_card(self):
        title = "Manager"
        desc = "Wazuh cluster reachable by node"
        if not _remote_agent_ready.is_set():
            return _loading_card(title, desc)
        if _REMOTE_AGENT_ERROR or not _REMOTE_AGENT:
            return _error_card(title, desc)
        bi = _REMOTE_AGENT
        manager = bi.get("manager") or ""
        node = bi.get("node_name") or ""
        # group_config_status isn't part of the /me/agent contract; render
        # the "synced" pill only when the field shows up in the response.
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
        return {
            "title": title,
            "status": "OK" if config_synced else "INFO",
            "description": desc,
            "stats": tuple(segments),
        }

    def _populate_module_grid(self):
        if not self._module_wrapper or not self._module_wrapper.winfo_exists():
            return

        if self._module_grid_frame:
            try:
                self._module_grid_frame.destroy()
            except Exception:
                pass

        cards_data = self._module_cards()
        max_cols = self._compute_max_cols()
        n = len(cards_data)
        cols = min(n, max_cols)
        rows = (n + cols - 1) // cols if cols > 0 else 1
        self._module_current_cols = cols

        grid = customtkinter.CTkFrame(self._module_wrapper, fg_color="transparent")
        grid.grid(row=0, column=0, sticky="nsew")
        for c in range(cols):
            grid.grid_columnconfigure(c, weight=1, uniform="module")
        for r in range(rows):
            grid.grid_rowconfigure(r, weight=0)
        self._module_grid_frame = grid

        for index, card_data in enumerate(cards_data):
            r = index // cols
            c = index % cols
            self._make_module_card(grid, r, c, card_data)

        # Match the dashboard's square card proportions: drive row minsize off
        # the per-column width so cards scale with window size. Without this the
        # rows would collapse to the natural content height (~100px) and the
        # cards would read as small compared to the dashboard's plugin cards.
        self._bind_module_aspect_ratio(grid, cols, rows)

    def _bind_module_aspect_ratio(self, grid, cols, rows):
        last_w = [-1]
        job = [None]

        def apply(force_width=None):
            job[0] = None
            try:
                if not grid.winfo_exists():
                    return
                total = force_width if force_width else grid.winfo_width()
                if total <= 1:
                    return
                if last_w[0] != -1 and abs(total - last_w[0]) < 4:
                    return
                last_w[0] = total
                col_w = total / cols if cols else total
                card_w = max(1, col_w - 16)  # 8px padx per side
                # Same clamp + formula as create_grid(aspect_ratio=1.0):
                # square-ish, with a 160px floor and 300px ceiling.
                target_h = max(160, min(300, int(card_w) + 20))
                for r in range(rows):
                    grid.grid_rowconfigure(r, minsize=target_h)
            except (tk.TclError, AttributeError, RuntimeError):
                pass

        def on_configure(_e=None):
            if job[0] is not None:
                try:
                    grid.after_cancel(job[0])
                except Exception:
                    pass
            # 200ms debounce matches create_grid so both fire in the same pass.
            job[0] = grid.after(200, apply)

        grid.bind("<Configure>", on_configure)
        # Synchronous first pass using the wrapper's actual width if known, so
        # the initial paint already has the correct row heights instead of
        # flashing the small natural height.
        try:
            hint = self._module_wrapper.winfo_width()
        except Exception:
            hint = 0
        if hint > 1:
            apply(force_width=hint)
        else:
            grid.after(10, apply)

    def _make_module_card(self, parent, row, column, card_data):
        text_secondary = self._theme("text_secondary", default=["#6B7280", "#9CA3AF"])
        target_tab = card_data.get("target_tab")

        card = customtkinter.CTkFrame(parent, corner_radius=12, border_width=1)
        card.grid(row=row, column=column, sticky="nsew", padx=8, pady=8)
        card.grid_columnconfigure(0, weight=1)
        card.grid_columnconfigure(1, weight=0)
        card.grid_rowconfigure(2, weight=1)

        title = customtkinter.CTkLabel(
            card,
            text=card_data["title"],
            font=customtkinter.CTkFont(family="Inter", size=16, weight="bold"),
            anchor="w",
        )
        title.grid(row=0, column=0, sticky="w", padx=16, pady=(16, 0))

        bg, fg = self._badge_colors(card_data["status"])
        badge = customtkinter.CTkLabel(
            card,
            text=f"  ●  {card_data['status']}  ",
            fg_color=bg,
            text_color=fg,
            corner_radius=6,
            height=22,
            font=customtkinter.CTkFont(size=11, weight="bold"),
        )
        badge.grid(row=0, column=1, sticky="ne", padx=(0, 16), pady=(16, 0))

        desc = customtkinter.CTkLabel(
            card,
            text=card_data["description"],
            text_color=text_secondary,
            font=customtkinter.CTkFont(size=12),
            anchor="w",
        )
        desc.grid(row=1, column=0, columnspan=2, sticky="w", padx=16, pady=(4, 8))

        stats = customtkinter.CTkFrame(card, fg_color="transparent")
        stats.grid(row=2, column=0, sticky="sw", padx=16, pady=(0, 16))
        stat_labels = []
        for i, (text, color_key) in enumerate(card_data["stats"]):
            color = self._segment_color(color_key)
            weight = "bold" if color_key not in ("muted",) else "normal"
            lbl = customtkinter.CTkLabel(
                stats,
                text=text,
                text_color=color,
                font=customtkinter.CTkFont(size=13, weight=weight),
            )
            lbl.grid(row=0, column=i, sticky="w")
            stat_labels.append(lbl)

        arrow = customtkinter.CTkLabel(
            card,
            text="›",
            text_color=text_secondary,
            font=customtkinter.CTkFont(size=20),
        )
        arrow.grid(row=2, column=1, sticky="se", padx=(0, 16), pady=(0, 16))

        # Make clickable cards navigate to a sibling tab on the same plugin.
        if target_tab and target_tab in _TAB_NAMES:
            def on_click(_e=None, t=target_tab):
                self._switch_tab(t)

            for w in (card, title, desc, stats, arrow, *stat_labels):
                w.bind("<Button-1>", on_click)
                try:
                    w.configure(cursor="hand2")
                except Exception:
                    pass

    def _bind_module_resize(self):
        last_size = [0, 0]

        def on_resize_settled():
            self._module_resize_after_id = None
            if not self._module_wrapper or not self._module_wrapper.winfo_exists():
                return
            try:
                if not self._module_wrapper.winfo_ismapped():
                    return
            except Exception:
                return
            target_cols = min(len(self._module_cards()), self._compute_max_cols())
            if self._module_current_cols == target_cols:
                return
            self._populate_module_grid()

        def debounced(event=None):
            if event is not None:
                if event.width == last_size[0] and event.height == last_size[1]:
                    return
                last_size[0] = event.width
                last_size[1] = event.height
            if self._module_resize_after_id:
                try:
                    self.app.after_cancel(self._module_resize_after_id)
                except Exception:
                    pass
            self._module_resize_after_id = self.app.after(250, on_resize_settled)

        if self._module_resize_handler_id:
            try:
                self.app.unbind("<Configure>", self._module_resize_handler_id)
            except Exception:
                pass
        self._module_resize_handler_id = self.app.bind(
            "<Configure>", debounced, add="+"
        )

    # ----- cleanup -----------------------------------------------------------

    # ----- Events pane -------------------------------------------------------

    def _build_events_pane(self, parent):
        # Clear any prior contents (loading placeholder or earlier render) so
        # this method is safe to call again once background data arrives.
        for w in parent.winfo_children():
            try:
                w.destroy()
            except Exception:
                pass

        if not _events_ready.is_set():
            self._render_events_loading(parent)
            self._schedule_events_ready_check(parent)
            return

        parent.grid_columnconfigure(0, weight=1)
        parent.grid_rowconfigure(0, weight=0)  # severity pills
        parent.grid_rowconfigure(1, weight=0)  # bar chart
        parent.grid_rowconfigure(2, weight=0)  # EVENT STREAM header
        parent.grid_rowconfigure(3, weight=1)  # list + detail split

        self._build_severity_pills(parent, row=0)
        self._build_event_chart(parent, row=1)
        self._build_event_stream_header(parent, row=2)
        self._build_event_stream(parent, row=3)

        # Default selection: most recent event (already sorted newest-first)
        if _EVENTS:
            self._select_event(_EVENTS[0]["id"])

    def _render_events_loading(self, parent):
        parent.grid_columnconfigure(0, weight=1)
        parent.grid_rowconfigure(0, weight=1)
        text_secondary = self._theme(
            "text_secondary", default=["#6B7280", "#9CA3AF"]
        )
        customtkinter.CTkLabel(
            parent,
            text="Loading events…",
            text_color=text_secondary,
            font=customtkinter.CTkFont(size=14),
        ).grid(row=0, column=0, sticky="nsew", padx=20, pady=40)

    def _schedule_events_ready_check(self, parent):
        # 20 ms ≈ one frame at 50 Hz. Tight enough that the placeholder→content
        # handoff feels instant once the background loader finishes; loose
        # enough that pre-ready polls are negligible.
        poll_ms = 20

        def check():
            self._events_ready_after_id = None
            if not parent.winfo_exists():
                return
            if _events_ready.is_set():
                self._build_events_pane(parent)
            else:
                self._events_ready_after_id = self.app.after(poll_ms, check)

        self._events_ready_after_id = self.app.after(poll_ms, check)

    def _severity_palette(self, level):
        """Return (bg, text) tuple for a severity level, theme-resolved."""
        key = _SEVERITY_THEME_KEY.get(level, "info")
        bg = self._theme("status_badge_bg", key, default=["#F3F4F6", "#1F2937"])
        fg = self._theme("status_badge_text", key, default=["#6B7280", "#9CA3AF"])
        return bg, fg

    def _severity_counts(self):
        events_id = id(_EVENTS)
        cache = self._severity_counts_cache
        if cache is not None and cache[0] == events_id:
            return cache[1]
        counts = {lvl: 0 for lvl in _SEVERITY_LEVELS}
        for ev in _EVENTS:
            sev = (ev.get("severity") or "").lower()
            if sev in counts:
                counts[sev] += 1
        self._severity_counts_cache = (events_id, counts)
        return counts

    def _build_severity_pills(self, parent, row):
        counts = self._severity_counts()

        bar = customtkinter.CTkFrame(parent, fg_color="transparent")
        bar.grid(row=row, column=0, sticky="ew", pady=(0, 12))
        for c in range(len(_SEVERITY_LEVELS)):
            bar.grid_columnconfigure(c, weight=1, uniform="sev")

        for col, level in enumerate(_SEVERITY_LEVELS):
            bg, fg = self._severity_palette(level)
            pill = customtkinter.CTkFrame(bar, fg_color=bg, corner_radius=10)
            pill.grid(row=0, column=col, sticky="ew", padx=4, pady=2)
            pill.grid_columnconfigure(0, weight=0)
            pill.grid_columnconfigure(1, weight=1)
            pill.grid_columnconfigure(2, weight=0)

            customtkinter.CTkLabel(
                pill,
                text="●",
                text_color=fg,
                font=customtkinter.CTkFont(size=14),
            ).grid(row=0, column=0, sticky="w", padx=(14, 6), pady=10)

            customtkinter.CTkLabel(
                pill,
                text=level.upper(),
                text_color=fg,
                font=customtkinter.CTkFont(size=11, weight="bold"),
            ).grid(row=0, column=1, sticky="w", pady=10)

            customtkinter.CTkLabel(
                pill,
                text=str(counts[level]),
                text_color=fg,
                font=customtkinter.CTkFont(family="Inter", size=20, weight="bold"),
            ).grid(row=0, column=2, sticky="e", padx=(0, 14), pady=10)

    # ----- 30-min stacked bar chart -----

    def _bucket_events_30min(self):
        """Group events into 30-minute bucket dicts keyed by datetime."""
        events_id = id(_EVENTS)
        cache = self._bucket_events_cache
        if cache is not None and cache[0] == events_id:
            return cache[1]
        if not _EVENTS:
            self._bucket_events_cache = (events_id, ([], {}))
            return [], {}

        timestamps = []
        per_event = []
        for ev in _EVENTS:
            try:
                dt = datetime.fromisoformat(ev["timestamp"].replace("Z", "+00:00"))
            except (KeyError, ValueError):
                continue
            sev = (ev.get("severity") or "").lower()
            if sev not in _SEVERITY_LEVELS:
                continue
            # Floor to nearest :00 / :30
            floored = dt.replace(
                minute=0 if dt.minute < 30 else 30, second=0, microsecond=0
            )
            timestamps.append(floored)
            per_event.append((floored, sev))

        if not timestamps:
            self._bucket_events_cache = (events_id, ([], {}))
            return [], {}

        start = min(timestamps)
        end = max(timestamps)
        buckets = []
        cursor = start
        while cursor <= end:
            buckets.append(cursor)
            cursor += timedelta(minutes=30)

        counts = {b: {lvl: 0 for lvl in _SEVERITY_LEVELS} for b in buckets}
        for floored, sev in per_event:
            counts[floored][sev] += 1
        self._bucket_events_cache = (events_id, (buckets, counts))
        return buckets, counts

    def _chart_theme(self):
        is_dark = customtkinter.get_appearance_mode() == "Dark"
        # Match the page background ["gray92","gray14"] so the chart blends in.
        return {
            "bg": "#242424" if is_dark else "#EBEBEB",
            "text": "#E5E7EB" if is_dark else "#1F2937",
            "grid": "#3A3A3A" if is_dark else "#D1D5DB",
            "is_dark": is_dark,
        }

    def _card_bg(self, card):
        """Resolve a CTkFrame's current fg_color to a #RRGGBB hex string."""
        is_dark = customtkinter.get_appearance_mode() == "Dark"
        fg = card.cget("fg_color")
        if isinstance(fg, (tuple, list)):
            color = fg[1] if is_dark else fg[0]
        else:
            color = fg
        if isinstance(color, str) and color.startswith("#"):
            return color
        rgb = card.winfo_rgb(color)
        return "#{:02X}{:02X}{:02X}".format(
            rgb[0] // 256, rgb[1] // 256, rgb[2] // 256
        )

    def _resolve_severity_color(self, level, is_dark):
        # Pull text color (more saturated than the badge bg) for the bar fill.
        key = _SEVERITY_THEME_KEY.get(level, "info")
        pair = self._theme("status_badge_text", key, default=["#6B7280", "#9CA3AF"])
        return pair[1] if is_dark else pair[0]

    def _build_event_chart(self, parent, row):
        Figure, FigureCanvasTkAgg = _ensure_matplotlib()
        chart_theme = self._chart_theme()

        wrapper = customtkinter.CTkFrame(
            parent, fg_color=chart_theme["bg"], corner_radius=12, border_width=1
        )
        wrapper.grid(row=row, column=0, sticky="ew", pady=(0, 12))
        wrapper.grid_columnconfigure(0, weight=1)
        wrapper.grid_rowconfigure(0, weight=1)

        # Compute the bucket data once per page render. Click-to-filter mutates
        # self._selected_bucket and triggers _render_event_chart for repaint.
        self._chart_buckets, self._chart_counts = self._bucket_events_30min()

        fig = Figure(figsize=(8, 1.7), dpi=100, facecolor=chart_theme["bg"])
        ax = fig.add_subplot(111)
        self._chart_ax = ax
        self._event_chart_figure = fig

        canvas = FigureCanvasTkAgg(fig, master=wrapper)
        canvas_widget = canvas.get_tk_widget()
        canvas_widget.configure(highlightthickness=0, bd=0, bg=chart_theme["bg"])
        canvas_widget.grid(row=0, column=0, sticky="ew", padx=8, pady=8)
        self._event_chart_canvas = canvas

        canvas.mpl_connect("button_press_event", self._on_chart_click)

        self._render_event_chart()

    def _render_event_chart(self):
        ax = self._chart_ax
        canvas = self._event_chart_canvas
        if ax is None or canvas is None:
            return

        chart_theme = self._chart_theme()
        ax.clear()
        ax.set_facecolor(chart_theme["bg"])

        buckets = self._chart_buckets
        counts = self._chart_counts
        sel = self._selected_bucket

        if buckets:
            import matplotlib.colors as mcolors
            x = list(range(len(buckets)))
            bottoms = [0] * len(buckets)
            for level in _SEVERITY_LEVELS:
                heights = [counts[b][level] for b in buckets]
                base = self._resolve_severity_color(level, chart_theme["is_dark"])
                rgb = mcolors.to_rgb(base)
                # Per-bar alpha: full when no filter, full for the selected
                # bucket, dim for the rest while a filter is active.
                colors = [
                    (rgb[0], rgb[1], rgb[2], 1.0 if (sel is None or b == sel) else 0.25)
                    for b in buckets
                ]
                ax.bar(
                    x,
                    heights,
                    bottom=bottoms,
                    width=0.85,
                    color=colors,
                    edgecolor="none",
                    label=level.capitalize(),
                )
                bottoms = [a + b for a, b in zip(bottoms, heights)]

            tick_step = max(1, len(buckets) // 6)
            tick_positions = list(range(0, len(buckets), tick_step))
            tick_labels = [buckets[i].strftime("%H:%M") for i in tick_positions]
            ax.set_xticks(tick_positions)
            ax.set_xticklabels(tick_labels, fontsize=8, color=chart_theme["text"])

            max_h = max(bottoms) if bottoms else 1
            ax.set_ylim(0, max_h + 1)
            ax.set_yticks(range(0, max_h + 2, max(1, (max_h + 1) // 4)))
        else:
            ax.text(
                0.5, 0.5, "No events",
                transform=ax.transAxes,
                ha="center", va="center",
                color=chart_theme["text"],
                fontsize=11,
            )
            ax.set_xticks([])
            ax.set_yticks([])

        ax.tick_params(colors=chart_theme["text"], labelsize=8)
        ax.spines["top"].set_visible(False)
        ax.spines["right"].set_visible(False)
        ax.spines["left"].set_color(chart_theme["text"])
        ax.spines["bottom"].set_color(chart_theme["text"])
        ax.yaxis.grid(True, color=chart_theme["grid"], linewidth=0.4, alpha=0.5)
        ax.set_axisbelow(True)
        self._event_chart_figure.tight_layout()
        canvas.draw_idle()

    def _on_chart_click(self, event):
        # Resolve the click into a bucket index, or clear selection if the
        # click misses an event-bearing bucket.
        prev = self._selected_bucket
        new_selection = None

        if (
            event.inaxes is self._chart_ax
            and event.xdata is not None
            and self._chart_buckets
        ):
            idx = int(round(event.xdata))
            if 0 <= idx < len(self._chart_buckets):
                bucket = self._chart_buckets[idx]
                bucket_total = sum(self._chart_counts.get(bucket, {}).values())
                if bucket_total > 0:
                    # Toggle: same bucket clears, different bucket sets.
                    new_selection = None if bucket == prev else bucket

        if new_selection == prev:
            return  # nothing changed
        self._selected_bucket = new_selection
        self._render_event_chart()
        query = self._event_search_var.get() if self._event_search_var else ""
        self._render_event_list(query)

    # ----- EVENT STREAM header -----

    def _build_event_stream_header(self, parent, row):
        text_secondary = self._theme("text_secondary", default=["#6B7280", "#9CA3AF"])

        header = customtkinter.CTkFrame(parent, fg_color="transparent")
        header.grid(row=row, column=0, sticky="ew", pady=(0, 8))
        header.grid_columnconfigure(0, weight=0)
        header.grid_columnconfigure(1, weight=1)
        header.grid_columnconfigure(2, weight=0)

        customtkinter.CTkLabel(
            header,
            text="EVENT SEARCH",
            font=customtkinter.CTkFont(size=11, weight="bold"),
        ).grid(row=0, column=0, sticky="w", padx=(0, 16))

        self._event_search_var = tk.StringVar()
        self._event_search_var.trace_add("write", lambda *a: self._render_event_list(
            self._event_search_var.get()
        ))
        customtkinter.CTkEntry(
            header,
            placeholder_text="Search rule, IP, description…",
            textvariable=self._event_search_var,
            height=30,
            corner_radius=8,
        ).grid(row=0, column=1, sticky="ew", padx=8)

        self._event_count_label = customtkinter.CTkLabel(
            header,
            text=f"{len(_EVENTS)} events",
            text_color=text_secondary,
            font=customtkinter.CTkFont(size=11),
        )
        self._event_count_label.grid(row=0, column=2, sticky="e", padx=(8, 0))

    # ----- Event list + detail split -----

    def _build_event_stream(self, parent, row):
        split = customtkinter.CTkFrame(parent, fg_color="transparent")
        split.grid(row=row, column=0, sticky="nsew")
        split.grid_columnconfigure(0, weight=3, uniform="stream")
        split.grid_columnconfigure(1, weight=2, uniform="stream")
        split.grid_rowconfigure(0, weight=1)

        # Left: scrollable list
        list_wrapper = customtkinter.CTkFrame(
            split, corner_radius=12, border_width=1
        )
        list_wrapper.grid(row=0, column=0, sticky="nsew", padx=(0, 6))
        list_wrapper.grid_columnconfigure(0, weight=1)
        list_wrapper.grid_rowconfigure(1, weight=1)

        self._build_event_list_header(list_wrapper, row=0)

        self._event_list_frame = customtkinter.CTkScrollableFrame(
            list_wrapper, fg_color="transparent"
        )
        self._event_list_frame.grid(row=1, column=0, sticky="nsew", padx=4, pady=(0, 4))
        self._event_list_frame.grid_columnconfigure(0, weight=1)

        # Right: detail panel
        self._event_detail_frame = customtkinter.CTkFrame(
            split, corner_radius=12, border_width=1
        )
        self._event_detail_frame.grid(row=0, column=1, sticky="nsew", padx=(6, 0))
        self._event_detail_frame.grid_columnconfigure(0, weight=1)

        self._render_event_list("")

    def _build_event_list_header(self, parent, row):
        text_secondary = self._theme("text_secondary", default=["#6B7280", "#9CA3AF"])

        head = customtkinter.CTkFrame(parent, fg_color="transparent")
        head.grid(row=row, column=0, sticky="ew", padx=10, pady=(10, 4))
        head.grid_columnconfigure(0, weight=0)  # severity dot
        head.grid_columnconfigure(1, weight=0)  # rule
        head.grid_columnconfigure(2, weight=1)  # description
        head.grid_columnconfigure(3, weight=0)  # metric
        head.grid_columnconfigure(4, weight=0)  # when

        small_bold = customtkinter.CTkFont(size=10, weight="bold")
        for col, label in enumerate(("", "RULE", "DESCRIPTION", "METRIC", "WHEN")):
            customtkinter.CTkLabel(
                head, text=label, text_color=text_secondary, font=small_bold
            ).grid(row=0, column=col, sticky="w", padx=(0, 12) if col < 4 else (0, 0))

    def _filter_events(self, query):
        sel = self._selected_bucket
        q = (query or "").lower().strip()
        out = []
        for ev in _EVENTS:
            # Bucket filter (from clicking a bar in the chart)
            if sel is not None:
                ts = ev.get("timestamp")
                if not ts:
                    continue
                try:
                    dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
                except ValueError:
                    continue
                floored = dt.replace(
                    minute=0 if dt.minute < 30 else 30,
                    second=0,
                    microsecond=0,
                )
                if floored != sel:
                    continue
            # Search-text filter
            if q:
                haystack = " ".join((
                    str(ev.get("rule_id", "")),
                    ev.get("description", ""),
                    ev.get("ip", ""),
                    (ev.get("severity") or ""),
                    " ".join(ev.get("mitre", []) or []),
                )).lower()
                if q not in haystack:
                    continue
            out.append(ev)
        return out

    def _render_event_list(self, query=""):
        if not self._event_list_frame or not self._event_list_frame.winfo_exists():
            return

        # Tear down existing rows
        for w in self._event_list_frame.winfo_children():
            try:
                w.destroy()
            except Exception:
                pass
        self._event_row_frames.clear()

        events = self._filter_events(query)
        if self._event_count_label:
            total = len(_EVENTS)
            shown = len(events)
            text = f"{shown} events" if shown == total else f"{shown}/{total} events"
            sel = self._selected_bucket
            if sel is not None:
                end = sel + timedelta(minutes=30)
                text += f" · {sel.strftime('%H:%M')}–{end.strftime('%H:%M')}"
            self._event_count_label.configure(text=text)

        # Ensure selection still exists in filtered list; otherwise pick first.
        selected_ids = {ev["id"] for ev in events}
        if events and self._selected_event_id not in selected_ids:
            self._selected_event_id = events[0]["id"]

        for r, ev in enumerate(events):
            self._event_row(self._event_list_frame, ev, r)

        # Repaint detail in case selection changed
        if events:
            ev = next((e for e in events if e["id"] == self._selected_event_id), events[0])
            self._render_event_detail(ev)
        else:
            self._render_event_detail(None)

    def _event_row(self, parent, ev, row):
        fonts = self._ensure_fonts()
        text_secondary = self._theme("text_secondary", default=["#6B7280", "#9CA3AF"])
        active_bg = self._theme(
            "sidebar_active_bg", default=["#EBF0FF", "#1A2744"]
        )
        hover_bg = self._theme(
            "sidebar_hover_bg", default=["#F0F0F5", "#1F1F22"]
        )
        is_selected = ev["id"] == self._selected_event_id
        sev = (ev.get("severity") or "").lower()
        _, dot_color = self._severity_palette(sev)

        row_frame = customtkinter.CTkFrame(
            parent,
            fg_color=active_bg if is_selected else "transparent",
            corner_radius=8,
        )
        row_frame.grid(row=row, column=0, sticky="ew", padx=2, pady=1)
        row_frame.grid_columnconfigure(0, weight=0)
        row_frame.grid_columnconfigure(1, weight=0)
        row_frame.grid_columnconfigure(2, weight=1)
        row_frame.grid_columnconfigure(3, weight=0)
        row_frame.grid_columnconfigure(4, weight=0)

        def on_click(_e=None, eid=ev["id"]):
            self._select_event(eid)

        # Make the entire row clickable: bind on the frame and every child label.
        row_frame.bind("<Button-1>", on_click)

        def labeled(col, text, **opts):
            lbl = customtkinter.CTkLabel(row_frame, text=text, **opts)
            lbl.grid(row=0, column=col, sticky="w", padx=(0, 12) if col < 4 else (0, 0), pady=8)
            lbl.bind("<Button-1>", on_click)
            return lbl

        labeled(
            0, "●", text_color=dot_color,
            font=fonts["dot_14"],
        )
        labeled(
            1, str(ev.get("rule_id", "—")),
            font=fonts["inter_bold_12"],
        )
        labeled(
            2, ev.get("description", "—"),
            font=fonts["size_12"],
            anchor="w",
        )
        metric = (ev.get("mitre") or [None])[0] or ev.get("ip") or "—"
        labeled(
            3, metric,
            text_color=text_secondary,
            font=fonts["size_11"],
        )
        labeled(
            4, _format_timestamp(ev.get("timestamp")),
            text_color=text_secondary,
            font=fonts["size_11"],
        )

        # Hover effect for non-selected rows
        if not is_selected:
            def on_enter(_e=None, rf=row_frame):
                try:
                    rf.configure(fg_color=hover_bg)
                except Exception:
                    pass

            def on_leave(_e=None, rf=row_frame):
                try:
                    rf.configure(fg_color="transparent")
                except Exception:
                    pass

            for w in (row_frame, *row_frame.winfo_children()):
                w.bind("<Enter>", on_enter)
                w.bind("<Leave>", on_leave)

        self._event_row_frames[ev["id"]] = row_frame

    def _select_event(self, event_id):
        if event_id == self._selected_event_id:
            return
        self._selected_event_id = event_id

        active_bg = self._theme(
            "sidebar_active_bg", default=["#EBF0FF", "#1A2744"]
        )
        # Restyle previously-rendered rows
        for eid, rf in list(self._event_row_frames.items()):
            try:
                if not rf.winfo_exists():
                    continue
                rf.configure(
                    fg_color=active_bg if eid == event_id else "transparent"
                )
            except Exception:
                pass

        ev = next((e for e in _EVENTS if e["id"] == event_id), None)
        self._render_event_detail(ev)

    def _render_event_detail(self, ev):
        if not self._event_detail_frame or not self._event_detail_frame.winfo_exists():
            return

        for w in self._event_detail_frame.winfo_children():
            try:
                w.destroy()
            except Exception:
                pass

        text_secondary = self._theme(
            "text_secondary", default=["#6B7280", "#9CA3AF"]
        )
        divider_color = self._theme(
            "divider_color", default=["#E5E7EB", "#2A2A2A"]
        )

        if ev is None:
            customtkinter.CTkLabel(
                self._event_detail_frame,
                text="Select an event to see details",
                text_color=text_secondary,
            ).grid(row=0, column=0, sticky="nsew", padx=20, pady=40)
            return

        sev = (ev.get("severity") or "").lower()
        bg, fg = self._severity_palette(sev)

        # Header row: severity badge, rule, relative time
        header = customtkinter.CTkFrame(self._event_detail_frame, fg_color="transparent")
        header.grid(row=0, column=0, sticky="ew", padx=20, pady=(16, 8))
        header.grid_columnconfigure(2, weight=1)

        customtkinter.CTkLabel(
            header,
            text=f"  ●  {sev.upper()}  ",
            fg_color=bg,
            text_color=fg,
            corner_radius=6,
            font=customtkinter.CTkFont(size=10, weight="bold"),
        ).grid(row=0, column=0, sticky="w")

        customtkinter.CTkLabel(
            header,
            text=f"rule {ev.get('rule_id', '—')}",
            text_color=text_secondary,
            font=customtkinter.CTkFont(size=11, weight="bold"),
        ).grid(row=0, column=1, sticky="w", padx=(10, 0))

        customtkinter.CTkLabel(
            header,
            text=_format_relative(ev.get("timestamp")),
            text_color=text_secondary,
            font=customtkinter.CTkFont(size=11),
        ).grid(row=0, column=2, sticky="e")

        # Title
        customtkinter.CTkLabel(
            self._event_detail_frame,
            text=ev.get("description", "—"),
            font=customtkinter.CTkFont(family="Inter", size=18, weight="bold"),
            anchor="w",
            justify="left",
            wraplength=380,
        ).grid(row=1, column=0, sticky="w", padx=20, pady=(0, 10))

        # Metadata table
        meta = customtkinter.CTkFrame(self._event_detail_frame, fg_color="transparent")
        meta.grid(row=2, column=0, sticky="ew", padx=20, pady=(0, 10))
        meta.grid_columnconfigure(0, weight=0)
        meta.grid_columnconfigure(1, weight=1)

        rows = [
            ("AGENT", ev.get("agent", "—")),
            ("HOST", ev.get("host", "—")),
            ("IP", ev.get("ip", "—")),
            ("MITRE TECHNIQUES", ", ".join(ev.get("mitre", []) or []) or "—"),
            ("HASH", ev.get("hash", "—")),
        ]
        for r, (label, value) in enumerate(rows):
            customtkinter.CTkLabel(
                meta, text=label,
                text_color=text_secondary,
                font=customtkinter.CTkFont(size=10, weight="bold"),
            ).grid(row=r, column=0, sticky="w", padx=(0, 12), pady=2)
            customtkinter.CTkLabel(
                meta, text=value,
                font=customtkinter.CTkFont(family="Inter", size=12),
                anchor="w", justify="left",
                wraplength=260,
            ).grid(row=r, column=1, sticky="w", pady=2)

        customtkinter.CTkFrame(
            self._event_detail_frame, height=1, fg_color=divider_color, corner_radius=0
        ).grid(row=3, column=0, sticky="ew", padx=20, pady=(8, 8))

        customtkinter.CTkLabel(
            self._event_detail_frame,
            text="RAW LOG",
            text_color=text_secondary,
            font=customtkinter.CTkFont(size=10, weight="bold"),
        ).grid(row=4, column=0, sticky="w", padx=20, pady=(0, 4))

        raw_box = customtkinter.CTkTextbox(
            self._event_detail_frame,
            height=90,
            font=customtkinter.CTkFont(family="Courier", size=11),
            wrap="word",
        )
        raw_box.grid(row=5, column=0, sticky="ew", padx=20, pady=(0, 12))
        raw_box.insert("0.0", ev.get("raw_log", ""))
        raw_box.configure(state="disabled")

        # Footer buttons
        footer = customtkinter.CTkFrame(self._event_detail_frame, fg_color="transparent")
        footer.grid(row=6, column=0, sticky="ew", padx=20, pady=(0, 16))
        footer.grid_columnconfigure(0, weight=1)
        footer.grid_columnconfigure(1, weight=0)
        footer.grid_columnconfigure(2, weight=0)

        customtkinter.CTkButton(
            footer,
            text="Acknowledge",
            height=30,
            corner_radius=8,
            font=customtkinter.CTkFont(size=12, weight="bold"),
            command=lambda eid=ev["id"]: self._on_acknowledge(eid),
        ).grid(row=0, column=1, padx=(0, 8))

        customtkinter.CTkButton(
            footer,
            text="View in manager",
            height=30,
            corner_radius=8,
            fg_color="transparent",
            border_width=1,
            text_color=text_secondary,
            border_color=divider_color,
            hover_color=self._hover_bg,
            font=customtkinter.CTkFont(size=12),
            command=lambda eid=ev["id"]: self._on_view_in_manager(eid),
        ).grid(row=0, column=2)

    def _on_acknowledge(self, event_id):
        logger.info(f"Endpoint 2: Acknowledge clicked for {event_id} (placeholder)")

    def _on_view_in_manager(self, event_id):
        logger.info(f"Endpoint 2: View in manager clicked for {event_id} (placeholder)")

    # ----- Vulnerabilities pane ---------------------------------------------

    # Sentinel for the device-picker dropdown's "show every device" choice.
    # Mirrors _GROUP_ALL on the Inventory tab.
    _VULN_DEVICE_ALL = "All devices"

    def _build_vulnerabilities_pane(self, parent):
        # Close any matplotlib figures from a prior render so successive
        # rebuilds (e.g., device dropdown changes) don't leak Figure objects.
        # destroy()'s teardown handles the full plugin exit; this covers the
        # mid-session rebuild path.
        for attr in ("_vuln_donut_figure", "_vuln_cvss_figure"):
            fig = getattr(self, attr, None)
            if fig is not None:
                try:
                    # fig.clear() drops the Figure's Axes/Artist references
                    # immediately. We deliberately avoid pyplot.close() — see
                    # _ensure_matplotlib() for why.
                    fig.clear()
                except Exception:
                    pass
                setattr(self, attr, None)

        # Clear any prior children (loading placeholder, error pane, or an
        # earlier render) so this method is safe to call after the readiness
        # poll fires. Mirrors _build_inventory_pane's teardown.
        for w in parent.winfo_children():
            try:
                w.destroy()
            except Exception:
                pass

        # The previous widget tree was just destroyed, so any cached row /
        # detail widget references are dead. Reset selection so the first
        # row of the new render auto-selects via _render_vuln_list.
        self._selected_vuln_key = None
        self._vuln_row_frames = {}
        self._vuln_detail_frame = None
        # Severity filter is scoped to the current device + dataset, so the
        # full-pane rebuild (device switch, initial data arrival) drops it.
        self._vuln_severity_filter = None
        self._vuln_donut_wedges = []

        self._vuln_pane_parent = parent
        # Idempotent: repeated kicks short-circuit on the locked guard, so
        # opening the Vulnerabilities tab directly (without visiting Overview
        # first) still triggers the /me/* fetch.
        _kick_overview_api_loader()

        if not _remote_vulns_ready.is_set():
            self._render_vuln_loading(parent)
            self._schedule_vuln_ready_check(parent)
            return

        if _REMOTE_VULNS_ERROR:
            self._render_vuln_error(parent, _REMOTE_VULNS_ERROR)
            return

        # Lazily resolve the default device selection now that _REMOTE_VULNS
        # and _REMOTE_AGENT have both landed. Re-resolve if a prior value is
        # no longer present in the current device list (e.g., the chosen
        # device dropped out across refreshes).
        if self._vuln_device is None or self._vuln_device not in self._vuln_device_values():
            self._vuln_device = self._default_vuln_device()

        parent.grid_columnconfigure(0, weight=1)
        parent.grid_rowconfigure(0, weight=0)  # charts row
        parent.grid_rowconfigure(1, weight=0)  # table header
        parent.grid_rowconfigure(2, weight=1)  # table list

        self._build_vuln_charts_row(parent, row=0)
        self._build_vuln_table_header(parent, row=1)
        self._build_vuln_table(parent, row=2)

    def _render_vuln_loading(self, parent):
        parent.grid_columnconfigure(0, weight=1)
        parent.grid_rowconfigure(0, weight=1)
        text_secondary = self._theme("text_secondary", default=["#6B7280", "#9CA3AF"])
        customtkinter.CTkLabel(
            parent,
            text="Loading vulnerabilities…",
            text_color=text_secondary,
            font=customtkinter.CTkFont(size=14),
        ).grid(row=0, column=0, sticky="nsew", padx=20, pady=40)

    def _render_vuln_error(self, parent, err):
        parent.grid_columnconfigure(0, weight=1)
        parent.grid_rowconfigure(0, weight=1)
        text_secondary = self._theme("text_secondary", default=["#6B7280", "#9CA3AF"])
        container = customtkinter.CTkFrame(parent, fg_color="transparent")
        container.grid(row=0, column=0, sticky="nsew", padx=20, pady=40)
        container.grid_columnconfigure(0, weight=1)
        customtkinter.CTkLabel(
            container,
            text="Couldn't load vulnerabilities",
            font=customtkinter.CTkFont(size=14, weight="bold"),
        ).grid(row=0, column=0, sticky="n")
        customtkinter.CTkLabel(
            container,
            text=str(err),
            text_color=text_secondary,
            font=customtkinter.CTkFont(size=12),
        ).grid(row=1, column=0, sticky="n", pady=(6, 0))

    def _schedule_vuln_ready_check(self, parent):
        # 20 ms matches the inventory + events poll cadence — tight enough to
        # feel instant when the loader thread finishes.
        poll_ms = 20

        def check():
            self._vuln_after_id = None
            if not parent.winfo_exists():
                return
            if _remote_vulns_ready.is_set():
                self._build_vulnerabilities_pane(parent)
            else:
                self._vuln_after_id = self.app.after(poll_ms, check)

        self._vuln_after_id = self.app.after(poll_ms, check)

    def _vuln_device_values(self):
        """Distinct device names that actually contributed at least one CVE in
        _REMOTE_VULNS, sorted, with _VULN_DEVICE_ALL prepended. A fully-patched
        device therefore doesn't appear as a filter option."""
        seen = set()
        for v in _REMOTE_VULNS:
            name = v.get("agent_name")
            if name:
                seen.add(name)
        return [self._VULN_DEVICE_ALL] + sorted(seen)

    def _default_vuln_device(self):
        """Default dropdown selection: the local device's name (from
        _REMOTE_AGENT) when it actually contributed CVEs. Falls back to
        _VULN_DEVICE_ALL when the agent fetch failed or the local machine
        had no CVEs."""
        values = self._vuln_device_values()
        if isinstance(_REMOTE_AGENT, dict):
            local_name = _REMOTE_AGENT.get("name")
            if local_name and local_name in values:
                return local_name
        return self._VULN_DEVICE_ALL

    def _vuln_total_for_device(self):
        """Count of CVEs available within the current device scope (before any
        search-box filtering). Drives the table header's 'X vulnerabilities'
        / 'shown/total' labels so the totals are coherent with the dropdown."""
        device = self._vuln_device
        if not device or device == self._VULN_DEVICE_ALL:
            return len(_REMOTE_VULNS)
        return sum(1 for v in _REMOTE_VULNS if v.get("agent_name") == device)

    def _on_vuln_device_change(self, device_name):
        if device_name == self._vuln_device:
            return
        self._vuln_device = device_name
        # Rebuild the whole pane so the donut, severity legend, CVSS chart,
        # table header count, and table rows all re-render against the new
        # device scope. The CTkOptionMenu's `command` fires after the user's
        # selection commits, so the menu has already closed — destroying and
        # recreating it here doesn't disrupt interaction.
        parent = self._vuln_pane_parent
        if parent is not None and parent.winfo_exists():
            self._build_vulnerabilities_pane(parent)

    def _vuln_severity_counts(self):
        vulns = _REMOTE_VULNS
        device = self._vuln_device
        # Cache keyed on (vulns identity, device filter) so a dropdown change
        # invalidates without re-counting on every render of the same view.
        cache_key = (id(vulns), device)
        cache = self._vuln_severity_cache
        if cache is not None and cache[0] == cache_key:
            return cache[1]
        counts = {lvl: 0 for lvl in _SEVERITY_LEVELS}
        for v in vulns:
            if device and device != self._VULN_DEVICE_ALL and v.get("agent_name") != device:
                continue
            sev = (v.get("severity") or "").lower()
            if sev in counts:
                counts[sev] += 1
        self._vuln_severity_cache = (cache_key, counts)
        return counts

    # ----- top-row cards -----

    def _build_vuln_charts_row(self, parent, row):
        wrapper = customtkinter.CTkFrame(parent, fg_color="transparent")
        wrapper.grid(row=row, column=0, sticky="ew", pady=(0, 12))
        wrapper.grid_columnconfigure(0, weight=1, uniform="vc")
        wrapper.grid_columnconfigure(1, weight=1, uniform="vc")
        wrapper.grid_rowconfigure(0, weight=1)

        donut = customtkinter.CTkFrame(wrapper, corner_radius=12, border_width=1)
        donut.grid(row=0, column=0, sticky="nsew", padx=(0, 6))
        self._build_vuln_donut_card(donut)

        cvss = customtkinter.CTkFrame(wrapper, corner_radius=12, border_width=1)
        cvss.grid(row=0, column=1, sticky="nsew", padx=(6, 0))
        self._build_vuln_cvss_card(cvss)

    def _build_vuln_donut_card(self, card):
        text_secondary = self._theme(
            "text_secondary", default=["#6B7280", "#9CA3AF"]
        )
        chart_theme = self._chart_theme()
        card_bg = self._card_bg(card)

        card.grid_columnconfigure(0, weight=1)
        card.grid_columnconfigure(1, weight=1)
        card.grid_rowconfigure(1, weight=1)

        customtkinter.CTkLabel(
            card,
            text="SEVERITY BREAKDOWN",
            text_color=text_secondary,
            font=customtkinter.CTkFont(size=11, weight="bold"),
        ).grid(row=0, column=0, columnspan=2, sticky="w", padx=14, pady=(12, 6))

        counts = self._vuln_severity_counts()
        total = sum(counts.values())

        if total > 0:
            self._draw_vuln_donut_chart(
                card, card_bg, chart_theme, text_secondary, counts, total
            )
        else:
            # Zero-data state: draw a flat ring on a plain tkinter canvas. The
            # matplotlib data path can't render a meaningful donut from all-zero
            # sizes, so reuse a hand-drawn placeholder that reads as intentional
            # rather than a degenerate chart. No figure is created here.
            self._vuln_donut_figure = None
            self._vuln_donut_canvas = None
            self._draw_empty_vuln_donut(card, card_bg, chart_theme)

        # Legend on the right — spacer rows top/bottom vertically center the items.
        legend = customtkinter.CTkFrame(card, fg_color="transparent")
        legend.grid(row=1, column=1, sticky="nsew", padx=(4, 12), pady=(0, 10))
        legend.grid_columnconfigure(0, weight=1)
        legend.grid_rowconfigure(0, weight=1)
        legend.grid_rowconfigure(len(_SEVERITY_LEVELS) + 1, weight=1)
        for i, lvl in enumerate(_SEVERITY_LEVELS):
            row_idx = i + 1
            legend.grid_rowconfigure(row_idx, weight=0)
            row_f = customtkinter.CTkFrame(legend, fg_color="transparent")
            row_f.grid(row=row_idx, column=0, sticky="ew", pady=2)
            row_f.grid_columnconfigure(0, weight=0)
            row_f.grid_columnconfigure(1, weight=1)
            row_f.grid_columnconfigure(2, weight=0)

            _, dot_color = self._severity_palette(lvl)
            customtkinter.CTkLabel(
                row_f,
                text="●",
                text_color=dot_color,
                font=customtkinter.CTkFont(size=14),
            ).grid(row=0, column=0, sticky="w", padx=(0, 6))
            customtkinter.CTkLabel(
                row_f,
                text=lvl.capitalize(),
                font=customtkinter.CTkFont(size=12),
                anchor="w",
            ).grid(row=0, column=1, sticky="w")
            customtkinter.CTkLabel(
                row_f,
                text=str(counts[lvl]),
                text_color=dot_color,
                font=customtkinter.CTkFont(family="Inter", size=14, weight="bold"),
            ).grid(row=0, column=2, sticky="e")

    def _draw_vuln_donut_chart(self, card, card_bg, chart_theme, text_secondary, counts, total):
        """Data-state donut: a matplotlib pie with a hollow center showing the
        total CVE count. Only built when total > 0 (see _draw_empty_vuln_donut
        for the zero-data placeholder).

        Each wedge is interactive: clicking it sets the severity filter on the
        table below; clicking the active wedge again clears it. Non-selected
        wedges dim to alpha 0.25 while a filter is active so the live severity
        reads visually."""
        import matplotlib.colors as mcolors

        Figure, FigureCanvasTkAgg = _ensure_matplotlib()
        fig = Figure(figsize=(2.6, 2.2), dpi=100, facecolor=card_bg)
        self._vuln_donut_figure = fig
        ax = fig.add_subplot(111)
        ax.set_facecolor(card_bg)

        sizes = [counts[lvl] for lvl in _SEVERITY_LEVELS]
        sel = self._vuln_severity_filter
        rgba_colors = []
        for lvl in _SEVERITY_LEVELS:
            base = self._resolve_severity_color(lvl, chart_theme["is_dark"])
            rgb = mcolors.to_rgb(base)
            alpha = 1.0 if (sel is None or lvl == sel) else 0.25
            rgba_colors.append((rgb[0], rgb[1], rgb[2], alpha))
        wedges, _texts = ax.pie(
            sizes,
            colors=rgba_colors,
            startangle=90,
            counterclock=False,
            wedgeprops={"width": 0.32, "edgecolor": card_bg},
        )
        # Pair wedges with their severity level so the click handler can map
        # a hit back to a filter value without recomputing angles.
        self._vuln_donut_wedges = list(zip(wedges, _SEVERITY_LEVELS))
        ax.text(
            0,
            0.08,
            str(total),
            ha="center",
            va="center",
            color=chart_theme["text"],
            fontsize=20,
            fontweight="bold",
        )
        ax.text(
            0,
            -0.22,
            "CVEs",
            ha="center",
            va="center",
            color=text_secondary[1] if chart_theme["is_dark"] else text_secondary[0],
            fontsize=9,
        )
        ax.set_aspect("equal")

        canvas = FigureCanvasTkAgg(fig, master=card)
        widget = canvas.get_tk_widget()
        widget.configure(highlightthickness=0, bd=0, bg=card_bg)
        widget.grid(row=1, column=0, sticky="nsew", padx=(8, 4), pady=(0, 10))
        self._vuln_donut_canvas = canvas
        canvas.mpl_connect("button_press_event", self._on_vuln_donut_click)
        canvas.draw_idle()

    def _draw_empty_vuln_donut(self, card, card_bg, chart_theme):
        """Zero-data donut placeholder: a flat ring drawn on a tkinter canvas
        with 'No CVEs' centered. The ring geometry mirrors the matplotlib
        donut (stroke ≈ 0.16 of diameter, matching wedge width 0.32 of radius)
        so the empty and populated states read as the same widget. Redraws on
        <Configure> so the ring stays centered as the card resizes."""
        ring_color = chart_theme["grid"]
        text_color = chart_theme["text"]
        canvas = tk.Canvas(card, bg=card_bg, highlightthickness=0, bd=0)
        canvas.grid(row=1, column=0, sticky="nsew", padx=(8, 4), pady=(0, 10))

        def redraw(_e=None):
            canvas.delete("all")
            w = canvas.winfo_width()
            h = canvas.winfo_height()
            if w <= 1 or h <= 1:
                return
            cx, cy = w / 2, h / 2
            diameter = min(w, h) * 0.7
            thickness = max(6.0, diameter * 0.16)
            # tkinter strokes the oval centered on its path, so inset the radius
            # by half the stroke width to keep the outer edge inside the canvas.
            rr = diameter / 2 - thickness / 2
            canvas.create_oval(
                cx - rr, cy - rr, cx + rr, cy + rr,
                outline=ring_color,
                width=thickness,
            )
            canvas.create_text(
                cx, cy, text="No CVEs", fill=text_color, font=("Inter", 11)
            )

        canvas.bind("<Configure>", redraw)

    def _on_vuln_donut_click(self, event):
        """Resolve a matplotlib click to a donut wedge and toggle the
        severity filter for that slice. Clicks outside any wedge are a no-op
        (the user is reaching for the legend or just missed)."""
        if event.inaxes is None or not self._vuln_donut_wedges:
            return
        for wedge, level in self._vuln_donut_wedges:
            # Zero-count severities have a degenerate (zero-angle) wedge —
            # contains() returns False on them naturally, but the explicit
            # guard skips wedge.contains' Path traversal when it can't match.
            if wedge.theta1 == wedge.theta2:
                continue
            contains, _ = wedge.contains(event)
            if contains:
                self._toggle_vuln_severity_filter(level)
                return

    def _toggle_vuln_severity_filter(self, level):
        """Switch the severity filter to `level`, or clear it if `level` is
        already active. Refresh the donut's per-wedge dimming in place and
        re-render the table rows so the change is visible immediately, no
        full pane rebuild needed."""
        if self._vuln_severity_filter == level:
            self._vuln_severity_filter = None
        else:
            self._vuln_severity_filter = level
        self._refresh_vuln_donut_alpha()
        # Invalidate the severity-count cache — the donut center figure and
        # the legend counts read from it on the next render. Today's
        # _vuln_severity_counts cache key only tracks (vulns_id, device); the
        # severity filter doesn't shrink the counts, so no invalidation is
        # needed here. Left as a note for the future.
        query = self._vuln_search_var.get() if self._vuln_search_var else ""
        self._render_vuln_list(query)

    def _refresh_vuln_donut_alpha(self):
        """Re-skin each wedge's alpha against the current severity filter,
        without rebuilding the figure. Cheaper than a full re-render and
        avoids the flash of a destroy-then-recreate."""
        sel = self._vuln_severity_filter
        for wedge, level in self._vuln_donut_wedges:
            try:
                wedge.set_alpha(1.0 if (sel is None or level == sel) else 0.25)
            except Exception:
                pass
        if self._vuln_donut_canvas is not None:
            try:
                self._vuln_donut_canvas.draw_idle()
            except Exception:
                pass

    def _bucket_vulns_daily(self):
        """Group CVEs into 30 daily buckets ending today (UTC) by detection_date."""
        today = datetime.now(timezone.utc).date()
        vulns = _REMOTE_VULNS
        device = self._vuln_device
        # Cache keyed on (vulns identity, today, device filter) so that
        # crossing a day boundary OR switching the device dropdown both
        # naturally invalidate the buckets.
        cache_key = (id(vulns), today, device)
        cache = self._bucket_vulns_cache
        if cache is not None and cache[0] == cache_key:
            return cache[1]
        buckets = [today - timedelta(days=29 - i) for i in range(30)]
        counts = {b: {lvl: 0 for lvl in _SEVERITY_LEVELS} for b in buckets}
        for v in vulns:
            if device and device != self._VULN_DEVICE_ALL and v.get("agent_name") != device:
                continue
            ts = v.get("detection_date") or ""
            sev = (v.get("severity") or "").lower()
            if sev not in _SEVERITY_LEVELS or not ts:
                continue
            try:
                d = datetime.fromisoformat(ts.replace("Z", "+00:00")).date()
            except ValueError:
                continue
            if d in counts:
                counts[d][sev] += 1
        self._bucket_vulns_cache = (cache_key, (buckets, counts))
        return buckets, counts

    def _build_vuln_cvss_card(self, card):
        Figure, FigureCanvasTkAgg = _ensure_matplotlib()
        text_secondary = self._theme(
            "text_secondary", default=["#6B7280", "#9CA3AF"]
        )
        chart_theme = self._chart_theme()
        card_bg = self._card_bg(card)

        card.grid_columnconfigure(0, weight=1)
        card.grid_rowconfigure(1, weight=1)

        customtkinter.CTkLabel(
            card,
            text="CVSS DISTRIBUTION — LAST 30 DAYS",
            text_color=text_secondary,
            font=customtkinter.CTkFont(size=11, weight="bold"),
        ).grid(row=0, column=0, sticky="w", padx=14, pady=(12, 6))

        fig = Figure(figsize=(5.5, 2.2), dpi=100, facecolor=card_bg)
        self._vuln_cvss_figure = fig
        ax = fig.add_subplot(111)
        ax.set_facecolor(card_bg)

        buckets, counts = self._bucket_vulns_daily()
        x = list(range(len(buckets)))
        bottoms = [0] * len(buckets)
        has_data = any(
            sum(counts[b].values()) for b in buckets
        )
        if has_data:
            for level in _SEVERITY_LEVELS:
                heights = [counts[b][level] for b in buckets]
                color = self._resolve_severity_color(level, chart_theme["is_dark"])
                ax.bar(
                    x,
                    heights,
                    bottom=bottoms,
                    width=0.85,
                    color=color,
                    edgecolor="none",
                )
                bottoms = [a + b for a, b in zip(bottoms, heights)]

            tick_step = max(1, len(buckets) // 6)
            tick_positions = list(range(0, len(buckets), tick_step))
            tick_labels = [buckets[i].strftime("%b %d") for i in tick_positions]
            ax.set_xticks(tick_positions)
            ax.set_xticklabels(tick_labels, fontsize=8, color=chart_theme["text"])
            max_h = max(bottoms) if bottoms else 1
            ax.set_ylim(0, max_h + 1)
            ax.set_yticks(range(0, max_h + 2, max(1, (max_h + 1) // 4)))
        else:
            ax.text(
                0.5,
                0.5,
                "No detections in the last 30 days",
                transform=ax.transAxes,
                ha="center",
                va="center",
                color=chart_theme["text"],
                fontsize=11,
            )
            ax.set_xticks([])
            ax.set_yticks([])

        ax.tick_params(colors=chart_theme["text"], labelsize=8)
        ax.spines["top"].set_visible(False)
        ax.spines["right"].set_visible(False)
        ax.spines["left"].set_color(chart_theme["text"])
        ax.spines["bottom"].set_color(chart_theme["text"])
        ax.yaxis.grid(True, color=chart_theme["grid"], linewidth=0.4, alpha=0.5)
        ax.set_axisbelow(True)
        fig.tight_layout()

        canvas = FigureCanvasTkAgg(fig, master=card)
        widget = canvas.get_tk_widget()
        widget.configure(highlightthickness=0, bd=0, bg=card_bg)
        widget.grid(row=1, column=0, sticky="nsew", padx=8, pady=(0, 10))
        self._vuln_cvss_canvas = canvas
        canvas.draw_idle()

    # ----- table header -----

    def _build_vuln_table_header(self, parent, row):
        text_secondary = self._theme(
            "text_secondary", default=["#6B7280", "#9CA3AF"]
        )

        header = customtkinter.CTkFrame(parent, fg_color="transparent")
        header.grid(row=row, column=0, sticky="ew", pady=(0, 8))
        header.grid_columnconfigure(0, weight=0)
        header.grid_columnconfigure(1, weight=1)
        header.grid_columnconfigure(2, weight=0)

        customtkinter.CTkLabel(
            header,
            text="AFFECTED PACKAGES & CVES",
            font=customtkinter.CTkFont(size=11, weight="bold"),
        ).grid(row=0, column=0, sticky="w", padx=(0, 16))

        self._vuln_search_var = tk.StringVar()
        self._vuln_search_var.trace_add(
            "write",
            lambda *a: self._render_vuln_list(self._vuln_search_var.get()),
        )
        customtkinter.CTkEntry(
            header,
            placeholder_text="Search CVE, package, severity…",
            textvariable=self._vuln_search_var,
            height=30,
            corner_radius=8,
        ).grid(row=0, column=1, sticky="ew", padx=8)

        self._vuln_count_label = customtkinter.CTkLabel(
            header,
            text=f"{self._vuln_total_for_device()} vulnerabilities",
            text_color=text_secondary,
            font=customtkinter.CTkFont(size=11),
        )
        self._vuln_count_label.grid(row=0, column=2, sticky="e", padx=(8, 0))

        # Device-picker dropdown: a new row anchored directly under the
        # "AFFECTED PACKAGES & CVES" title. Defaults to the local device
        # (see _default_vuln_device). Hidden when fewer than 2 devices
        # actually contributed CVEs — mirrors the Inventory tab's "show only
        # when there's a real choice" guard.
        device_values = self._vuln_device_values()
        if len(device_values) >= 3:
            if self._vuln_device not in device_values:
                self._vuln_device = self._default_vuln_device()
            device_dropdown = customtkinter.CTkOptionMenu(
                header,
                values=device_values,
                command=self._on_vuln_device_change,
                height=30,
                corner_radius=8,
            )
            device_dropdown.set(self._vuln_device)
            device_dropdown.grid(row=1, column=0, sticky="w", pady=(6, 0))
        else:
            # No real choice — pin to the sentinel so the filter is a no-op.
            self._vuln_device = self._VULN_DEVICE_ALL

    # ----- table -----

    def _build_vuln_table(self, parent, row):
        # 3:2 split — bordered list card on the left, bordered detail card on
        # the right. Mirrors _build_event_stream so both panes feel uniform.
        split = customtkinter.CTkFrame(parent, fg_color="transparent")
        split.grid(row=row, column=0, sticky="nsew")
        split.grid_columnconfigure(0, weight=3, uniform="vstream")
        split.grid_columnconfigure(1, weight=2, uniform="vstream")
        split.grid_rowconfigure(0, weight=1)

        wrapper = customtkinter.CTkFrame(split, corner_radius=12, border_width=1)
        wrapper.grid(row=0, column=0, sticky="nsew", padx=(0, 6))
        wrapper.grid_columnconfigure(0, weight=1)
        wrapper.grid_rowconfigure(1, weight=1)

        self._build_vuln_table_columns(wrapper, row=0)

        self._vuln_list_frame = customtkinter.CTkScrollableFrame(
            wrapper, fg_color="transparent"
        )
        self._vuln_list_frame.grid(row=1, column=0, sticky="nsew", padx=4, pady=(0, 4))
        self._vuln_list_frame.grid_columnconfigure(0, weight=1)

        self._vuln_detail_frame = customtkinter.CTkFrame(
            split, corner_radius=12, border_width=1
        )
        self._vuln_detail_frame.grid(row=0, column=1, sticky="nsew", padx=(6, 0))
        self._vuln_detail_frame.grid_columnconfigure(0, weight=1)

        self._render_vuln_list("")

    def _build_vuln_table_columns(self, parent, row):
        text_secondary = self._theme(
            "text_secondary", default=["#6B7280", "#9CA3AF"]
        )
        head = customtkinter.CTkFrame(parent, fg_color="transparent")
        # Match the horizontal extent of the scrollable rows: rows sit at
        # wrapper-padx(4) + row-padx(2) = 6 from the left, and the scrollable
        # reserves ~16px on the right for the scrollbar + row-padx(2) + wrapper-padx(4).
        head.grid(row=row, column=0, sticky="ew", padx=(6, 22), pady=(10, 4))
        self._configure_vuln_row_grid(head)

        small_bold = customtkinter.CTkFont(size=10, weight="bold")
        labels = ("SEV", "CVE", "AFFECTED PACKAGE")
        last_col = len(labels) - 1
        for col, label in enumerate(labels):
            # SEV column rows render a badge with "  HIGH  " interior padding,
            # so nudge the SEV header right to land on the badge's visible text.
            left_pad = 8 if col == 0 else 0
            right_pad = 12 if col < last_col else 0
            customtkinter.CTkLabel(
                head, text=label, text_color=text_secondary, font=small_bold
            ).grid(row=0, column=col, sticky="w", padx=(left_pad, right_pad))

    @staticmethod
    def _configure_vuln_row_grid(frame):
        frame.grid_columnconfigure(0, weight=0, minsize=70)   # severity badge
        frame.grid_columnconfigure(1, weight=0, minsize=180)  # CVE id + modified
        frame.grid_columnconfigure(2, weight=1, minsize=240)  # package (last column)

    def _filter_vulns(self, query):
        q = (query or "").lower().strip()
        device_filter = self._vuln_device
        sev_filter = self._vuln_severity_filter
        out = []
        for v in _REMOTE_VULNS:
            if device_filter and device_filter != self._VULN_DEVICE_ALL \
                    and v.get("agent_name") != device_filter:
                continue
            if sev_filter and (v.get("severity") or "").lower() != sev_filter:
                continue
            if q:
                haystack = " ".join((
                    str(v.get("id", "")),
                    str(v.get("package_name", "")),
                    str(v.get("package_version", "")),
                    str(v.get("severity", "")),
                    str(v.get("status", "")),
                    str(v.get("description", "")),
                    str(v.get("agent_name", "")),
                )).lower()
                if q not in haystack:
                    continue
            out.append(v)
        # Sort by CVSS desc so the worst CVEs surface first.
        out.sort(key=lambda x: float(x.get("cvss_score") or 0.0), reverse=True)
        return out

    def _render_vuln_list(self, query=""):
        if not self._vuln_list_frame or not self._vuln_list_frame.winfo_exists():
            return

        for w in self._vuln_list_frame.winfo_children():
            try:
                w.destroy()
            except Exception:
                pass
        self._vuln_row_frames.clear()

        vulns = self._filter_vulns(query)
        if self._vuln_count_label:
            total = self._vuln_total_for_device()
            shown = len(vulns)
            text = (
                f"{shown} vulnerabilities"
                if shown == total
                else f"{shown}/{total} vulnerabilities"
            )
            self._vuln_count_label.configure(text=text)

        # Drop the selection if the previously selected vuln has filtered out
        # so the row builder below doesn't try to highlight a row that won't
        # render. We re-anchor to the top of the visible list afterwards.
        visible_keys = {self._vuln_key(v) for v in vulns}
        if self._selected_vuln_key not in visible_keys:
            self._selected_vuln_key = None

        for r, v in enumerate(vulns):
            self._vuln_row(self._vuln_list_frame, v, r)

        if not vulns:
            self._render_vuln_detail(None)
        elif self._selected_vuln_key is None:
            self._select_vuln(self._vuln_key(vulns[0]))

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

    @staticmethod
    def _vuln_key(vuln):
        """Composite selection key — agent id paired with CVE id so the same
        CVE on two devices doesn't collide in the All-devices view."""
        return f"{vuln.get('agent_id') or ''}::{vuln.get('id') or ''}"

    def _vuln_row(self, parent, vuln, row):
        fonts = self._ensure_fonts()
        text_secondary = self._theme(
            "text_secondary", default=["#6B7280", "#9CA3AF"]
        )
        hover_bg = self._theme(
            "sidebar_hover_bg", default=["#F0F0F5", "#1F1F22"]
        )
        active_bg = self._theme(
            "sidebar_active_bg", default=["#EBF0FF", "#1A2744"]
        )

        sev = (vuln.get("severity") or "").lower()
        sev_bg, sev_fg = self._severity_palette(sev)
        sev_label = _SEVERITY_SHORT.get(sev, sev.upper() or "—")

        key = self._vuln_key(vuln)
        is_selected = key == self._selected_vuln_key

        row_frame = customtkinter.CTkFrame(
            parent,
            fg_color=active_bg if is_selected else "transparent",
            corner_radius=8,
        )
        row_frame.grid(row=row, column=0, sticky="ew", padx=2, pady=1)
        self._configure_vuln_row_grid(row_frame)

        def on_click(_e=None, k=key):
            self._select_vuln(k)

        row_frame.bind("<Button-1>", on_click)

        # SEV badge
        sev_lbl = customtkinter.CTkLabel(
            row_frame,
            text=f"  {sev_label}  ",
            fg_color=sev_bg,
            text_color=sev_fg,
            corner_radius=6,
            font=fonts["bold_10"],
        )
        sev_lbl.grid(row=0, column=0, sticky="w", padx=(0, 12), pady=8)
        sev_lbl.bind("<Button-1>", on_click)

        # CVE id + modified date
        cve_cell = customtkinter.CTkFrame(row_frame, fg_color="transparent")
        cve_cell.grid(row=0, column=1, sticky="w", padx=(0, 12), pady=4)
        cve_cell.grid_columnconfigure(0, weight=1)
        cve_id_lbl = customtkinter.CTkLabel(
            cve_cell,
            text=vuln.get("id", "—"),
            font=fonts["inter_bold_12"],
            anchor="w",
        )
        cve_id_lbl.grid(row=0, column=0, sticky="w")
        modified = _format_relative(vuln.get("modified_date"))
        cve_mod_lbl = customtkinter.CTkLabel(
            cve_cell,
            text=f"modified {modified}",
            text_color=text_secondary,
            font=fonts["size_10"],
            anchor="w",
        )
        cve_mod_lbl.grid(row=1, column=0, sticky="w")
        cve_cell.bind("<Button-1>", on_click)
        cve_id_lbl.bind("<Button-1>", on_click)
        cve_mod_lbl.bind("<Button-1>", on_click)

        # Affected package + version
        pkg_cell = customtkinter.CTkFrame(row_frame, fg_color="transparent")
        pkg_cell.grid(row=0, column=2, sticky="w", padx=(0, 12), pady=4)
        pkg_cell.grid_columnconfigure(0, weight=1)
        pkg_name_lbl = customtkinter.CTkLabel(
            pkg_cell,
            text=vuln.get("package_name", "—"),
            font=fonts["inter_bold_12"],
            anchor="w",
        )
        pkg_name_lbl.grid(row=0, column=0, sticky="w")
        pkg_ver_lbl = customtkinter.CTkLabel(
            pkg_cell,
            text=str(vuln.get("package_version", "")),
            text_color=text_secondary,
            font=fonts["size_10"],
            anchor="w",
        )
        pkg_ver_lbl.grid(row=1, column=0, sticky="w")
        pkg_cell.bind("<Button-1>", on_click)
        pkg_name_lbl.bind("<Button-1>", on_click)
        pkg_ver_lbl.bind("<Button-1>", on_click)

        self._vuln_row_frames[key] = row_frame

        # Hover effect for non-selected rows only — mirrors _event_row so the
        # active row's highlight isn't blown away by a Leave event.
        if not is_selected:
            def on_enter(_e=None, rf=row_frame):
                try:
                    rf.configure(fg_color=hover_bg)
                except Exception:
                    pass

            def on_leave(_e=None, rf=row_frame):
                try:
                    rf.configure(fg_color="transparent")
                except Exception:
                    pass

            for w in (row_frame, *row_frame.winfo_children()):
                w.bind("<Enter>", on_enter)
                w.bind("<Leave>", on_leave)

    def _find_vuln_by_key(self, key):
        for v in _REMOTE_VULNS:
            if self._vuln_key(v) == key:
                return v
        return None

    def _select_vuln(self, key):
        if key == self._selected_vuln_key:
            return
        self._selected_vuln_key = key

        active_bg = self._theme(
            "sidebar_active_bg", default=["#EBF0FF", "#1A2744"]
        )
        for k, rf in list(self._vuln_row_frames.items()):
            try:
                if not rf.winfo_exists():
                    continue
                rf.configure(fg_color=active_bg if k == key else "transparent")
            except Exception:
                pass

        self._render_vuln_detail(self._find_vuln_by_key(key))

    def _render_vuln_detail(self, vuln):
        if not self._vuln_detail_frame or not self._vuln_detail_frame.winfo_exists():
            return

        for w in self._vuln_detail_frame.winfo_children():
            try:
                w.destroy()
            except Exception:
                pass

        text_secondary = self._theme(
            "text_secondary", default=["#6B7280", "#9CA3AF"]
        )
        divider_color = self._theme(
            "divider_color", default=["#E5E7EB", "#2A2A2A"]
        )

        if vuln is None:
            customtkinter.CTkLabel(
                self._vuln_detail_frame,
                text="Select a vulnerability to see details",
                text_color=text_secondary,
            ).grid(row=0, column=0, sticky="nsew", padx=20, pady=40)
            return

        sev = (vuln.get("severity") or "").lower()
        sev_bg, sev_fg = self._severity_palette(sev)
        sev_label = _SEVERITY_SHORT.get(sev, sev.upper() or "—")

        header = customtkinter.CTkFrame(self._vuln_detail_frame, fg_color="transparent")
        header.grid(row=0, column=0, sticky="ew", padx=20, pady=(16, 8))
        header.grid_columnconfigure(2, weight=1)

        customtkinter.CTkLabel(
            header,
            text=f"  {sev_label}  ",
            fg_color=sev_bg,
            text_color=sev_fg,
            corner_radius=6,
            font=customtkinter.CTkFont(size=10, weight="bold"),
        ).grid(row=0, column=0, sticky="w")

        customtkinter.CTkLabel(
            header,
            text=vuln.get("id", "—"),
            text_color=text_secondary,
            font=customtkinter.CTkFont(size=11, weight="bold"),
        ).grid(row=0, column=1, sticky="w", padx=(10, 0))

        customtkinter.CTkLabel(
            header,
            text=_format_relative(vuln.get("modified_date")),
            text_color=text_secondary,
            font=customtkinter.CTkFont(size=11),
        ).grid(row=0, column=2, sticky="e")

        pkg_name = vuln.get("package_name") or ""
        pkg_ver = vuln.get("package_version") or ""
        title_text = f"{pkg_name} {pkg_ver}".strip() or vuln.get("id") or "—"
        customtkinter.CTkLabel(
            self._vuln_detail_frame,
            text=title_text,
            font=customtkinter.CTkFont(family="Inter", size=18, weight="bold"),
            anchor="w",
            justify="left",
            wraplength=380,
        ).grid(row=1, column=0, sticky="w", padx=20, pady=(0, 10))

        meta = customtkinter.CTkFrame(self._vuln_detail_frame, fg_color="transparent")
        meta.grid(row=2, column=0, sticky="ew", padx=20, pady=(0, 10))
        meta.grid_columnconfigure(0, weight=0)
        meta.grid_columnconfigure(1, weight=1)

        rows = []
        try:
            cvss_text = f"{float(vuln.get('cvss_score') or 0.0):.1f}"
            rows.append(("CVSS", cvss_text, sev_fg))
        except (TypeError, ValueError):
            pass

        epss = vuln.get("epss")
        try:
            epss_text = f"{float(epss) * 100:.0f}%"
            epss_key = self._epss_color_key(epss)
            if epss_key == "muted":
                epss_color = None
            else:
                _, epss_color = self._severity_palette(
                    "high" if epss_key == "high" else "medium"
                )
            rows.append(("EPSS", epss_text, epss_color))
        except (TypeError, ValueError):
            pass

        status = (vuln.get("status") or "").strip()
        if status:
            rows.append(("STATUS", status.capitalize(), None))

        device = vuln.get("agent_name")
        if device:
            rows.append(("DEVICE", device, None))

        for label, key in (
            ("DETECTED", "detection_date"),
            ("PUBLISHED", "published_date"),
            ("LAST MODIFIED", "modified_date"),
        ):
            ts = vuln.get(key)
            if ts:
                rows.append((label, _format_timestamp(ts), None))

        for r, (label, value, value_color) in enumerate(rows):
            customtkinter.CTkLabel(
                meta, text=label,
                text_color=text_secondary,
                font=customtkinter.CTkFont(size=10, weight="bold"),
            ).grid(row=r, column=0, sticky="w", padx=(0, 12), pady=2)
            value_kwargs = dict(
                text=value,
                font=customtkinter.CTkFont(family="Inter", size=12),
                anchor="w", justify="left",
                wraplength=260,
            )
            if value_color is not None:
                value_kwargs["text_color"] = value_color
            customtkinter.CTkLabel(meta, **value_kwargs).grid(
                row=r, column=1, sticky="w", pady=2
            )

        customtkinter.CTkFrame(
            self._vuln_detail_frame, height=1, fg_color=divider_color, corner_radius=0
        ).grid(row=3, column=0, sticky="ew", padx=20, pady=(8, 8))

        customtkinter.CTkLabel(
            self._vuln_detail_frame,
            text="DESCRIPTION",
            text_color=text_secondary,
            font=customtkinter.CTkFont(size=10, weight="bold"),
        ).grid(row=4, column=0, sticky="w", padx=20, pady=(0, 4))

        description = vuln.get("description") or ""
        if description:
            desc_box = customtkinter.CTkTextbox(
                self._vuln_detail_frame,
                height=140,
                font=customtkinter.CTkFont(family="Courier", size=11),
                wrap="word",
            )
            desc_box.grid(row=5, column=0, sticky="ew", padx=20, pady=(0, 16))
            desc_box.insert("0.0", description)
            desc_box.configure(state="disabled")
        else:
            customtkinter.CTkLabel(
                self._vuln_detail_frame,
                text="No description available.",
                text_color=text_secondary,
                font=customtkinter.CTkFont(size=12),
            ).grid(row=5, column=0, sticky="w", padx=20, pady=(0, 16))

    # ----- Inventory pane ----------------------------------------------------

    def _build_inventory_pane(self, parent):
        # Clear any previous contents (loading placeholder or earlier render)
        # so this method is safe to call after the agents loader fires.
        for w in parent.winfo_children():
            try:
                w.destroy()
            except Exception:
                pass

        self._inventory_pane_parent = parent
        _kick_agents_loader()

        if not _agents_ready.is_set():
            self._render_inventory_loading(parent)
            self._schedule_inventory_ready_check(parent)
            return

        self._render_inventory_list(parent)

    def _render_inventory_loading(self, parent):
        parent.grid_columnconfigure(0, weight=1)
        parent.grid_rowconfigure(0, weight=1)
        text_secondary = self._theme("text_secondary", default=["#6B7280", "#9CA3AF"])
        customtkinter.CTkLabel(
            parent,
            text="Loading devices…",
            text_color=text_secondary,
            font=customtkinter.CTkFont(size=14),
        ).grid(row=0, column=0, sticky="nsew", padx=20, pady=40)

    def _schedule_inventory_ready_check(self, parent):
        # 20 ms matches the events-pane poll cadence — tight enough to feel
        # instant when the loader thread finishes.
        poll_ms = 20

        def check():
            self._inventory_after_id = None
            if not parent.winfo_exists():
                return
            if _agents_ready.is_set():
                self._build_inventory_pane(parent)
            else:
                self._inventory_after_id = self.app.after(poll_ms, check)

        self._inventory_after_id = self.app.after(poll_ms, check)

    def _events_threat_by_agent(self):
        """Map agent name → highest event severity present for that agent.
        Only includes agents with at least one event."""
        out = {}
        for ev in _EVENTS:
            name = (ev.get("agent") or "").strip()
            sev = (ev.get("severity") or "").lower()
            if not name or sev not in _THREAT_RANK:
                continue
            prev = out.get(name)
            if prev is None or _THREAT_RANK[sev] > _THREAT_RANK[prev]:
                out[name] = sev
        return out

    def _vulns_threat_for_name(self, target_name):
        """Highest vuln severity for the device whose basic_info.name matches
        the loaded single-agent sample (vulnerabilities.json has no agent_id
        field, so vulns are scoped implicitly to this one device). Returns
        None if no match or no vulns."""
        ref = (_get_agent_data().get("basic_info", {}) or {}).get("name")
        if not ref or ref != target_name:
            return None
        best = None
        for v in _get_vulns():
            sev = (v.get("severity") or "").lower()
            if sev not in _THREAT_RANK:
                continue
            if best is None or _THREAT_RANK[sev] > _THREAT_RANK[best]:
                best = sev
        return best

    def _device_threat_level(self, agent_name, events_by_agent):
        """Composite threat for one device: max(events, vulns). Returns one of
        critical|high|medium|low|ok."""
        ev_sev = events_by_agent.get(agent_name)
        vuln_sev = self._vulns_threat_for_name(agent_name)
        best_rank = 0
        for sev in (ev_sev, vuln_sev):
            if sev and _THREAT_RANK.get(sev, 0) > best_rank:
                best_rank = _THREAT_RANK[sev]
        if best_rank == 0:
            return "ok"
        for sev, rank in _THREAT_RANK.items():
            if rank == best_rank:
                return sev
        return "ok"

    def _inventory_rows(self):
        """Build sorted device row data. Returns list of dicts."""
        events_by_agent = self._events_threat_by_agent()
        rows = []
        for agent in _AGENTS:
            bi = agent.get("basic_info") or {}
            name = bi.get("name") or "(unknown)"
            threat = self._device_threat_level(name, events_by_agent)
            rows.append({
                "name": name,
                # status drives the row's "Active now" label vs. a relative
                # last-seen time (see _inventory_row).
                "status": (bi.get("status") or "").lower(),
                "last_keep": bi.get("lastKeepAlive"),
                "agent_id": bi.get("id") or "—",
                "ip": bi.get("ip") or "—",
                "threat": threat,
                # groups feeds the group-filter dropdown; the Overview
                # Inventory card ignores this field.
                "groups": self._agent_groups(bi),
            })
        # threat desc, then name asc — stable
        rows.sort(key=lambda r: (-_THREAT_RANK.get(r["threat"], 0), r["name"].lower()))
        return rows

    def _inventory_counts_rows(self, field_path):
        """Per-device row data for the count-based views (Processes/Ports/
        Network). `field_path` is a tuple of keys into each agent dict
        leading to a syscollector object that has `affected_items`. Sort:
        count desc, name asc. Devices with no syscollector data show 0."""
        rows = []
        for agent in _AGENTS:
            bi = agent.get("basic_info") or {}
            name = bi.get("name") or "(unknown)"
            node = agent
            for key in field_path:
                if not isinstance(node, dict):
                    node = None
                    break
                node = node.get(key)
            items = (node or {}).get("affected_items") if isinstance(node, dict) else None
            count = len(items) if isinstance(items, list) else 0
            rows.append({
                "name": name,
                "status": (bi.get("status") or "").lower(),
                "last_keep": bi.get("lastKeepAlive"),
                "agent_id": bi.get("id") or "—",
                "ip": bi.get("ip") or "—",
                "count": count,
                "groups": self._agent_groups(bi),
            })
        rows.sort(key=lambda r: (-r["count"], r["name"].lower()))
        return rows

    # Maps the dropdown's view name → the syscollector path used to count
    # affected_items for that view. None for "Devices" (no count column —
    # the lead is the threat badge instead).
    _INVENTORY_COUNT_FIELDS = {
        "Devices": None,
        "Processes": ("syscollector", "processes"),
        "Ports": ("syscollector", "network", "ports"),
        "Network": ("syscollector", "network", "interfaces"),
    }
    # Lead-column header text per view (col 1 of the row layout).
    _INVENTORY_LEAD_HEADER = {
        "Devices": "THREAT",
        "Processes": "PROCESSES",
        "Ports": "OPEN PORTS",
        "Network": "INTERFACES",
    }

    # Sentinels for the group dropdown. "All groups" is the unfiltered
    # default; "(no group)" buckets agents whose basic_info.group is
    # missing/empty (one such agent exists in the bundled sample).
    _GROUP_ALL = "All groups"
    _GROUP_NONE = "(no group)"

    # Inventory list pagination. 20 rows/page so the list fits comfortably
    # in a single viewport without scrolling; the pager shows just three
    # adjacent page numbers (prev, current, next) per the design.
    _INVENTORY_PAGE_SIZE = 20

    def _inventory_group_values(self):
        """Distinct group names present in _AGENTS, with "All groups" pinned
        first and "(no group)" appended only if any agent actually lacks a
        group. Result is the dropdown's `values` list."""
        seen = set()
        has_empty = False
        for agent in _AGENTS:
            bi = agent.get("basic_info") or {}
            raw = bi.get("group")
            if isinstance(raw, list):
                groups = [g for g in raw if g]
            elif raw:
                groups = [raw]
            else:
                groups = []
            if not groups:
                has_empty = True
            else:
                seen.update(groups)
        out = [self._GROUP_ALL] + sorted(seen)
        if has_empty:
            out.append(self._GROUP_NONE)
        return out

    def _agent_groups(self, bi):
        """Normalize basic_info.group into a list. Empty list means
        the agent has no group assignment."""
        raw = bi.get("group")
        if isinstance(raw, list):
            return [g for g in raw if g]
        if raw:
            return [raw]
        return []

    def _row_in_group(self, row, group_filter):
        """Filter predicate: does this row's agent belong to the selected
        group? Row dicts carry their group list under "groups"."""
        if group_filter == self._GROUP_ALL:
            return True
        groups = row.get("groups") or []
        if group_filter == self._GROUP_NONE:
            return not groups
        return group_filter in groups

    def _render_inventory_list(self, parent):
        divider_color = self._theme("divider_color", default=["#E5E7EB", "#2A2A2A"])

        parent.grid_columnconfigure(0, weight=1)
        parent.grid_rowconfigure(0, weight=1)

        # The whole inventory is a single bordered card so it reads as its own
        # widget against the page background (matches the Events stream's
        # bordered list_wrapper at line ~1841).
        wrapper = customtkinter.CTkFrame(parent, corner_radius=12, border_width=1)
        wrapper.grid(row=0, column=0, sticky="nsew")
        wrapper.grid_columnconfigure(0, weight=1)
        wrapper.grid_rowconfigure(0, weight=0)  # title bar (dropdown + count)
        wrapper.grid_rowconfigure(1, weight=0)  # divider
        wrapper.grid_rowconfigure(2, weight=0)  # column header
        wrapper.grid_rowconfigure(3, weight=1)  # scrollable list
        self._inventory_wrapper = wrapper

        # ----- title bar: two dropdowns on row 0, count label on row 1 -----
        title_bar = customtkinter.CTkFrame(wrapper, fg_color="transparent")
        title_bar.grid(row=0, column=0, sticky="ew", padx=16, pady=(14, 10))
        title_bar.grid_columnconfigure(0, weight=0)  # category dropdown
        title_bar.grid_columnconfigure(1, weight=0)  # group dropdown
        title_bar.grid_columnconfigure(2, weight=1)  # absorbs trailing space

        category_dropdown = customtkinter.CTkOptionMenu(
            title_bar,
            values=list(self._INVENTORY_COUNT_FIELDS.keys()),
            command=self._on_inventory_view_change,
            height=30,
            corner_radius=8,
        )
        category_dropdown.set(self._inventory_view)
        category_dropdown.grid(row=0, column=0, sticky="w", padx=(0, 8))

        # Group filter — values list reflects the actual groups present in
        # the loaded agents. The list always leads with "All groups", so it
        # only offers a real choice when there are ≥2 group partitions (i.e.
        # ≥3 entries). With a single group the filter is a no-op, so hide the
        # dropdown entirely and pin the view to "All groups".
        group_values = self._inventory_group_values()
        if len(group_values) >= 3:
            if self._inventory_group not in group_values:
                self._inventory_group = self._GROUP_ALL
            group_dropdown = customtkinter.CTkOptionMenu(
                title_bar,
                values=group_values,
                command=self._on_inventory_group_change,
                height=30,
                corner_radius=8,
            )
            group_dropdown.set(self._inventory_group)
            group_dropdown.grid(row=0, column=1, sticky="w")
        else:
            self._inventory_group = self._GROUP_ALL

        # Pagination frame — right-aligned in col 2, which absorbs the
        # trailing space. _render_inventory_body destroys + rebuilds the
        # children of this frame on every render so page numbers and
        # arrow-button enabled states reflect the current page + total.
        self._inventory_pagination_frame = customtkinter.CTkFrame(
            title_bar, fg_color="transparent"
        )
        self._inventory_pagination_frame.grid(row=0, column=2, sticky="e")

        text_secondary = self._theme("text_secondary", default=["#6B7280", "#9CA3AF"])
        self._inventory_count_label = customtkinter.CTkLabel(
            title_bar,
            text="",  # filled by _render_inventory_body
            text_color=text_secondary,
            font=customtkinter.CTkFont(size=11),
            anchor="w",
        )
        self._inventory_count_label.grid(row=1, column=0, columnspan=3, sticky="w", pady=(6, 0))

        # ----- divider -----
        customtkinter.CTkFrame(
            wrapper, height=1, fg_color=divider_color, corner_radius=0
        ).grid(row=1, column=0, sticky="ew")

        # ----- body (column header + list) — separate method so the dropdown
        # callback can re-render it in place without disturbing the title bar.
        self._render_inventory_body()

    def _render_inventory_body(self):
        wrapper = self._inventory_wrapper
        if wrapper is None or not wrapper.winfo_exists():
            return

        text_secondary = self._theme("text_secondary", default=["#6B7280", "#9CA3AF"])
        divider_color = self._theme("divider_color", default=["#E5E7EB", "#2A2A2A"])
        fonts = self._ensure_fonts()

        # Tear down any previously rendered body widgets (rows 2 and 3 of the
        # wrapper grid). Mirrors the teardown idiom in _render_event_list:
        # walk children, destroy each, exception-safe.
        for child in wrapper.winfo_children():
            try:
                info = child.grid_info()
            except Exception:
                continue
            if info.get("row") in (2, 3):
                try:
                    child.destroy()
                except Exception:
                    pass

        view = self._inventory_view
        is_devices = view == "Devices"
        field_path = self._INVENTORY_COUNT_FIELDS.get(view)
        group_filter = self._inventory_group

        if is_devices:
            rows = self._inventory_rows()
            rows = [r for r in rows if self._row_in_group(r, group_filter)]
            count_text = f"{len(rows)} linked · sorted by threat level"
        else:
            rows = self._inventory_counts_rows(field_path)
            rows = [r for r in rows if self._row_in_group(r, group_filter)]
            total = sum(r["count"] for r in rows)
            n_with_data = sum(1 for r in rows if r["count"] > 0)
            label_word = view.lower()
            if view == "Network":
                label_word = "interfaces"
            count_text = f"{n_with_data} devices · {total} {label_word} total"

        if self._inventory_count_label is not None and self._inventory_count_label.winfo_exists():
            self._inventory_count_label.configure(text=count_text)

        # Pagination: derive total pages from the *filtered* row set, clamp
        # the current page in case a stale value (e.g., page 5 before a
        # filter dropped us to 3 pages) is now out of range, then slice.
        page_size = self._INVENTORY_PAGE_SIZE
        total_pages = max(1, (len(rows) + page_size - 1) // page_size)
        current_page = max(1, min(self._inventory_page, total_pages))
        self._inventory_page = current_page
        start = (current_page - 1) * page_size
        page_rows = rows[start : start + page_size]
        self._render_inventory_pagination(total_pages)

        # ----- column header -----
        col_header = customtkinter.CTkFrame(wrapper, fg_color="transparent")
        col_header.grid(row=2, column=0, sticky="ew", padx=16, pady=(10, 6))
        self._configure_inventory_columns(col_header)
        small_bold = customtkinter.CTkFont(size=10, weight="bold")
        lead_header = self._INVENTORY_LEAD_HEADER.get(view, "THREAT")
        for c, label in enumerate((lead_header, "DEVICE", "LAST SEEN", "AGENT ID", "IP")):
            customtkinter.CTkLabel(
                col_header,
                text=label,
                text_color=text_secondary,
                font=small_bold,
                anchor="w",
            ).grid(row=0, column=c, sticky="w", padx=(0, 12) if c < 4 else 0)

        # ----- scrollable list -----
        # corner_radius=0 is intentional: CTkScrollableFrame's source computes
        # an internal `border_spacing = corner_radius + border_width` and adds
        # that as padx on its inner canvas (see customtkinter's
        # ctk_scrollable_frame.py line 81). With the theme default of
        # corner_radius=12, every row would be offset 12 px further right than
        # the column header. Zeroing the radius eliminates that pad. The
        # scrollable's fg_color is transparent so the corner shape is never
        # visible.
        list_frame = customtkinter.CTkScrollableFrame(
            wrapper, fg_color="transparent", corner_radius=0
        )
        list_frame.grid(row=3, column=0, sticky="nsew", padx=16, pady=(0, 8))
        list_frame.grid_columnconfigure(0, weight=1)

        if is_devices:
            for i, dev in enumerate(page_rows):
                self._inventory_row(list_frame, dev, i, fonts, divider_color)
        else:
            for i, dev in enumerate(page_rows):
                self._inventory_counts_row(list_frame, dev, i, fonts)

    def _on_inventory_view_change(self, view_name):
        if view_name not in self._INVENTORY_COUNT_FIELDS:
            return
        if view_name == self._inventory_view:
            return
        self._inventory_view = view_name
        # Reset to page 1 — the new view's row set may be shorter and a
        # stale page index would render an empty page.
        self._inventory_page = 1
        self._render_inventory_body()

    def _on_inventory_group_change(self, group_name):
        if group_name == self._inventory_group:
            return
        self._inventory_group = group_name
        # Same reasoning as the view-change callback.
        self._inventory_page = 1
        self._render_inventory_body()

    def _set_inventory_page(self, page):
        """Handler for the pager's arrow + page-number buttons. The actual
        clamp against total_pages happens in _render_inventory_body, so
        passing a value beyond the last page just snaps to the last page."""
        page = max(1, int(page))
        if page == self._inventory_page:
            return
        self._inventory_page = page
        self._render_inventory_body()

    def _render_inventory_pagination(self, total_pages):
        """Build the right-aligned page navigator. Format per design:
        [◀] [prev?] [current] [next?] [▶]  — prev shown only when current ≥ 2,
        next shown only when current < total_pages, arrows disabled at the
        boundary pages. When everything fits on a single page the navigator is
        hidden entirely (no buttons)."""
        frame = self._inventory_pagination_frame
        if frame is None or not frame.winfo_exists():
            return
        for child in frame.winfo_children():
            try:
                child.destroy()
            except Exception:
                pass

        # Single page → no navigator at all. grid_remove (not just emptying the
        # frame) so it stops reserving space — an empty CTkFrame keeps its
        # default 200px height and would inflate the title row otherwise.
        if total_pages <= 1:
            frame.grid_remove()
            return

        # Restore the frame in case a previous render removed it.
        frame.grid()

        current = self._inventory_page
        text_secondary = self._theme("text_secondary", default=["#6B7280", "#9CA3AF"])
        # sidebar_active_bg is the soft accent the Events pane uses for the
        # selected event row — same idiom carries over to "selected page".
        active_bg = self._theme("sidebar_active_bg", default=["#EBF0FF", "#1A2744"])
        hover_bg = self._hover_bg

        page_font = customtkinter.CTkFont(size=12)
        page_font_bold = customtkinter.CTkFont(size=12, weight="bold")

        def page_btn(text, command, is_current=False, disabled=False):
            kwargs = dict(
                master=frame,
                text=text,
                width=30,
                height=28,
                corner_radius=6,
                command=command,
            )
            if is_current:
                kwargs.update(
                    fg_color=active_bg,
                    text_color=self._accent_color,
                    hover_color=active_bg,
                    font=page_font_bold,
                )
            else:
                kwargs.update(
                    fg_color="transparent",
                    text_color=text_secondary,
                    hover_color=hover_bg,
                    font=page_font,
                )
            btn = customtkinter.CTkButton(**kwargs)
            if disabled:
                btn.configure(state="disabled")
            return btn

        col = 0
        left = page_btn(
            "◀",
            command=lambda: self._set_inventory_page(current - 1),
            disabled=(current <= 1),
        )
        left.grid(row=0, column=col, padx=(0, 4))
        col += 1

        if current >= 2:
            prev_page = current - 1
            page_btn(
                str(prev_page),
                command=lambda p=prev_page: self._set_inventory_page(p),
            ).grid(row=0, column=col, padx=2)
            col += 1

        page_btn(
            str(current),
            command=lambda: None,
            is_current=True,
        ).grid(row=0, column=col, padx=2)
        col += 1

        if current < total_pages:
            next_page = current + 1
            page_btn(
                str(next_page),
                command=lambda p=next_page: self._set_inventory_page(p),
            ).grid(row=0, column=col, padx=2)
            col += 1

        right = page_btn(
            "▶",
            command=lambda: self._set_inventory_page(current + 1),
            disabled=(current >= total_pages),
        )
        right.grid(row=0, column=col, padx=(4, 0))

    def _configure_inventory_columns(self, frame):
        # Use explicit minsize on the fixed-width columns and weight=1 only on
        # the device-name column. Both the column-header frame and every row
        # frame call this helper, which guarantees column alignment across
        # parents — unlike `uniform=…`, minsize/weight are intrinsic to each
        # frame's own grid and don't need to share a uniform-group scope.
        frame.grid_columnconfigure(0, weight=0, minsize=110)  # threat badge
        frame.grid_columnconfigure(1, weight=1)               # device name (stretches)
        frame.grid_columnconfigure(2, weight=0, minsize=140)  # last seen
        frame.grid_columnconfigure(3, weight=0, minsize=80)   # agent id
        frame.grid_columnconfigure(4, weight=0, minsize=140)  # ip

    def _inventory_row(self, parent, dev, row, fonts, divider_color):
        hover_bg = self._hover_bg
        text_secondary = self._theme("text_secondary", default=["#6B7280", "#9CA3AF"])

        row_frame = customtkinter.CTkFrame(parent, fg_color="transparent", corner_radius=6)
        # No padx — the parent list_frame already sits 16 px in from the
        # wrapper edge (matching the column header). Adding padx here would
        # re-introduce the misalignment we just fixed.
        row_frame.grid(row=row, column=0, sticky="ew", pady=1)
        self._configure_inventory_columns(row_frame)

        # Threat badge — col 0
        threat = dev["threat"]
        status_label = _SEV_TO_STATUS.get(threat, "OK")
        t_bg, t_fg = self._badge_colors(status_label)
        customtkinter.CTkLabel(
            row_frame,
            text=f"  ●  {status_label}  ",
            fg_color=t_bg,
            text_color=t_fg,
            corner_radius=6,
            height=22,
            font=customtkinter.CTkFont(size=11, weight="bold"),
        ).grid(row=0, column=0, sticky="w", padx=(0, 12), pady=8)

        # Device name — col 1 (stretches)
        customtkinter.CTkLabel(
            row_frame,
            text=dev["name"],
            font=fonts["inter_bold_13"],
            anchor="w",
        ).grid(row=0, column=1, sticky="w", padx=(0, 12), pady=8)

        # Last seen — col 2. The /me/inventory status field is authoritative
        # for connectivity: an "active" agent is connected right now, so show
        # "Active now". Otherwise show the relative last-scan time.
        is_connected = dev["status"] in ("active", "connected")
        if is_connected:
            last_seen_text = "Active now"
        else:
            last_seen_text = _format_relative(dev["last_keep"])
        customtkinter.CTkLabel(
            row_frame,
            text=last_seen_text,
            text_color=text_secondary,
            font=fonts["size_12"],
            anchor="w",
        ).grid(row=0, column=2, sticky="w", padx=(0, 12), pady=8)

        # Agent ID — col 3
        customtkinter.CTkLabel(
            row_frame,
            text=str(dev["agent_id"]),
            text_color=text_secondary,
            font=fonts["size_12"],
            anchor="w",
        ).grid(row=0, column=3, sticky="w", padx=(0, 12), pady=8)

        # IP — col 4
        customtkinter.CTkLabel(
            row_frame,
            text=dev["ip"],
            text_color=text_secondary,
            font=fonts["size_12"],
            anchor="w",
        ).grid(row=0, column=4, sticky="w", pady=8)

        def on_enter(_e=None, rf=row_frame):
            try:
                rf.configure(fg_color=hover_bg)
            except Exception:
                pass

        def on_leave(_e=None, rf=row_frame):
            try:
                rf.configure(fg_color="transparent")
            except Exception:
                pass

        for w in (row_frame, *row_frame.winfo_children()):
            w.bind("<Enter>", on_enter)
            w.bind("<Leave>", on_leave)

    def _inventory_counts_row(self, parent, dev, row, fonts):
        """Row renderer for Processes/Ports/Network views. Same DEVICE /
        LAST SEEN / IP columns as _inventory_row, but the lead column is
        a bold count instead of a severity badge."""
        hover_bg = self._hover_bg
        text_secondary = self._theme("text_secondary", default=["#6B7280", "#9CA3AF"])

        row_frame = customtkinter.CTkFrame(parent, fg_color="transparent", corner_radius=6)
        row_frame.grid(row=row, column=0, sticky="ew", pady=1)
        self._configure_inventory_columns(row_frame)

        # Count — col 0. Muted if zero so devices missing syscollector data
        # don't visually compete with devices that have real counts.
        count = dev["count"]
        count_color = text_secondary if count == 0 else None
        customtkinter.CTkLabel(
            row_frame,
            text=str(count),
            text_color=count_color,
            font=fonts["inter_bold_13"],
            anchor="w",
        ).grid(row=0, column=0, sticky="w", padx=(0, 12), pady=8)

        # Device name — col 1 (stretches)
        customtkinter.CTkLabel(
            row_frame,
            text=dev["name"],
            font=fonts["inter_bold_13"],
            anchor="w",
        ).grid(row=0, column=1, sticky="w", padx=(0, 12), pady=8)

        # Last seen — col 2 (same status-driven handling as Devices)
        is_connected = dev["status"] in ("active", "connected")
        if is_connected:
            last_seen_text = "Active now"
        else:
            last_seen_text = _format_relative(dev["last_keep"])
        customtkinter.CTkLabel(
            row_frame,
            text=last_seen_text,
            text_color=text_secondary,
            font=fonts["size_12"],
            anchor="w",
        ).grid(row=0, column=2, sticky="w", padx=(0, 12), pady=8)

        # Agent ID — col 3
        customtkinter.CTkLabel(
            row_frame,
            text=str(dev["agent_id"]),
            text_color=text_secondary,
            font=fonts["size_12"],
            anchor="w",
        ).grid(row=0, column=3, sticky="w", padx=(0, 12), pady=8)

        # IP — col 4
        customtkinter.CTkLabel(
            row_frame,
            text=dev["ip"],
            text_color=text_secondary,
            font=fonts["size_12"],
            anchor="w",
        ).grid(row=0, column=4, sticky="w", pady=8)

        def on_enter(_e=None, rf=row_frame):
            try:
                rf.configure(fg_color=hover_bg)
            except Exception:
                pass

        def on_leave(_e=None, rf=row_frame):
            try:
                rf.configure(fg_color="transparent")
            except Exception:
                pass

        for w in (row_frame, *row_frame.winfo_children()):
            w.bind("<Enter>", on_enter)
            w.bind("<Leave>", on_leave)

    # ----- cleanup -----------------------------------------------------------

    def destroy(self):
        if self._events_ready_after_id:
            try:
                self.app.after_cancel(self._events_ready_after_id)
            except Exception:
                pass
            self._events_ready_after_id = None
        if self._overview_events_after_id:
            try:
                self.app.after_cancel(self._overview_events_after_id)
            except Exception:
                pass
            self._overview_events_after_id = None
        if self._inventory_after_id:
            try:
                self.app.after_cancel(self._inventory_after_id)
            except Exception:
                pass
            self._inventory_after_id = None
        if self._vuln_after_id:
            try:
                self.app.after_cancel(self._vuln_after_id)
            except Exception:
                pass
            self._vuln_after_id = None
        if self._module_resize_after_id:
            try:
                self.app.after_cancel(self._module_resize_after_id)
            except Exception:
                pass
            self._module_resize_after_id = None
        if self._module_resize_handler_id:
            try:
                self.app.unbind("<Configure>", self._module_resize_handler_id)
            except Exception:
                pass
            self._module_resize_handler_id = None
        if self._event_chart_figure is not None:
            try:
                # See _ensure_matplotlib() — pyplot is never imported here.
                self._event_chart_figure.clear()
            except Exception:
                pass
            self._event_chart_figure = None
            self._event_chart_canvas = None
        for attr in ("_vuln_donut_figure", "_vuln_cvss_figure"):
            fig = getattr(self, attr, None)
            if fig is not None:
                try:
                    # See _ensure_matplotlib() — pyplot is never imported here.
                    fig.clear()
                except Exception:
                    pass
                setattr(self, attr, None)
        self._vuln_donut_canvas = None
        self._vuln_cvss_canvas = None
        super().destroy()
