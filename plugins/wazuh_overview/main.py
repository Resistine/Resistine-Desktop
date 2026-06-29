"""
Wazuh Overview Plugin
A sidebar entry that renders agent, vulnerability, SCA, hotfix, inventory,
and detection-event data from the IP-identified /api/v1/me/* endpoints (see
plugins/wazuh_overview/api_client.py). Eager preload populates the always-
visible Overview cards; the Vulnerabilities and Events tabs lazy-load their
heavier per-device fan-outs on first open. Sections without backing data
render as "No data available" rather than fabricating numbers.
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
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta, timezone

import customtkinter
from customtkinter import ThemeManager

from plugins.base_plugin import BasePlugin
from plugins.wazuh_overview import api_client
from plugins.wazuh_overview.config import MAX_PARALLEL_FETCHES
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

# TEMPORARY: dev-only refresh button visibility. Hardcoded True while debug
# mode (`python main.py -d`) is broken; flip to False (or replace the
# Plugin._build_modules_header gate with `hasattr(self.app, "inspector")`)
# before shipping to production.
_SHOW_DEV_REFRESH_BUTTON = True

class _SimpleResizeEvent:
    """Minimal stand-in for a Tk <Configure> event. matplotlib's
    FigureCanvasTkAgg.resize() reads only .width/.height, so this lets us drive
    a full canvas resize (figure size + backing PhotoImage) from our debounced
    handler without a real event. See Plugin._bind_figure_autoresize."""

    __slots__ = ("width", "height")

    def __init__(self, width, height):
        self.width = int(width)
        self.height = int(height)


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
# Reverse map (rank → severity name) so _device_threat_level can index instead
# of linear-scanning _THREAT_RANK per device.
_RANK_TO_SEV = {v: k for k, v in _THREAT_RANK.items()}

# Responsive layout constants (shared so a breakpoint change is one edit).
# _content_width = window width − sidebar − platform padding; the column ladder
# steps 1/2/3/4 at the _COL_BREAKPOINTS, and the chart rows / list-detail splits
# collapse to a single stacked column below _STACK_BREAKPOINT.
_SIDEBAR_WIDTH = 250
_COL_BREAKPOINTS = (480, 680, 1000)
_STACK_BREAKPOINT = 680
# Card aspect-ratio row-height clamp (matches create_grid's 160..300).
_CARD_MIN_H = 160
_CARD_MAX_H = 300

# Default theme color pairs [light, dark] used as _theme(...) fallbacks. Pulled
# out so the same literal pair isn't retyped at every call site.
_DEFAULT_TEXT_SECONDARY = ["#6B7280", "#9CA3AF"]
_DEFAULT_ACTIVE_BG = ["#EBF0FF", "#1A2744"]
_DEFAULT_HOVER_BG = ["#F0F0F5", "#1F1F22"]
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
    """Flatten a Wazuh alert hit into the dict shape the events UI expects.

    Tolerates three shapes:
      - OpenSearch-shaped hits with `_source` envelope and nested
        rule.{id,level,description} / agent.{name,ip} objects.
      - Pre-flattened payloads with the same nested objects but no envelope.
      - The live /me/vulnerabilities/{id}/events shape, which is flat AND
        renames fields: top-level `cve` / `severity` (string, capitalized)
        / `rule_id` / `rule_level` / `title` / `package` / `version`, with
        no nested `rule` or `agent` objects.

    Live-shape fields are tried first per slot, then the legacy nested
    accessors as fallbacks, so a future shape change can't blank the UI."""
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
            # Live API events carry flat package/version/title fields instead
            # of data/full_log. Synthesize a minimal raw_log so the detail
            # pane still shows package context for the affected CVE.
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


def _load_all_agents(devices=None):
    """Fetch the device list from /api/v1/me/inventory and per-device detail
    from /api/v1/me/inventory/{id} IN PARALLEL, returning agent dicts in the
    legacy shape the Inventory tab consumes.

    Pass `devices` to skip the internal `fetch_inventory_full()` call when the
    caller already has the device list cached (the preloader caches it via
    `_REMOTE_INVENTORY`). When omitted, the device list is fetched here for
    self-contained use (Inventory tab opened before the preloader finished).

    Per-device fan-out runs through a ThreadPoolExecutor capped at
    `MAX_PARALLEL_FETCHES`. Wall-clock collapses from `sum(per-device)` to
    `max(per-device)` — significant for groups with a slow outlier device."""
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
        # If the preloader has already cached the device list under
        # _REMOTE_INVENTORY, hand it in so _load_all_agents skips the
        # /me/inventory call entirely and goes straight to the parallel
        # per-device fan-out. If the preloader hasn't completed yet (rare —
        # Inventory tab opened mid-preload), pass None so _load_all_agents
        # fetches the list itself.
        cached = None
        if _remote_inventory_ready.is_set() and isinstance(_REMOTE_INVENTORY, dict):
            items = _REMOTE_INVENTORY.get("items")
            if isinstance(items, list) and items:
                cached = items
        _AGENTS = _load_all_agents(devices=cached)
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

# Group-level vulnerability summary (by_severity counts + per-device totals).
# Lands ~370 ms after preloader start vs ~1.5 s for the full per-device fan-out,
# so the Overview Vulnerabilities card paints from this rather than waiting on
# the heavier _REMOTE_VULNS. Full row data still comes from _REMOTE_VULNS — the
# summary is capped at 50 CVEs per device and lacks first_detected_at.
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

# Vulnerability detection events from /me/vulnerabilities/{agent_id}/events.
# Two-phase load: _remote_vuln_events_ready fires once the LOCAL device's
# events finish (Events tab can render immediately at that point);
# _remote_vuln_events_complete fires once every device in the group has been
# fetched (the Events pane's poll uses it to know when to stop rebuilding).
# Identity of _REMOTE_VULN_EVENTS changes on each merge — the Events pane's
# id(...)-keyed caches treat that as cache invalidation automatically.
_REMOTE_VULN_EVENTS = []
_remote_vuln_events_ready = threading.Event()
_remote_vuln_events_complete = threading.Event()

# Overview preloader. Fires from the Dashboard's first-build completion hook
# (see plugins/dashboard/main.py:_kick_overview_early_endpoints) to pre-warm
# every /me/* endpoint the Wazuh tab depends on, so subsequent tab opens have
# data already in hand. Idempotent via the locked started-flag, so the Wazuh
# tab's _kick_overview_api_loader call on tab entry is safe — it's a no-op
# whenever Dashboard already kicked things off.
_overview_early_loader_started = False
_overview_early_loader_lock = threading.Lock()

# Phase 2 of the Events tab loader (per-device fan-out across the group) is
# the heaviest call sequence in the plugin and is consumed only by the Events
# pane. We kick it lazily on the first Events-tab open instead of eagerly at
# plugin load, so users who never visit Events don't pay the cost. Same
# one-shot lock pattern as the overview preloader.
_vuln_events_phase2_started = False
_vuln_events_phase2_lock = threading.Lock()

# Per-device vulnerability fan-out is consumed only by the Vulnerabilities
# tab. Overview's vuln card paints from _REMOTE_VULNS_SUMMARY (the cheap
# ~370ms group aggregation), so paying for N per-device CVE fetches at
# preload is pure waste for users who never open Vulnerabilities. Same
# one-shot lock pattern as Events Phase 2 — fires from
# _build_vulnerabilities_pane the first time the tab is opened (or from
# the pre-build chain if the user lingers on Overview).
_vulns_loader_started = False
_vulns_loader_lock = threading.Lock()


def _wait_for_vpn(poll_interval=2.0, timeout=60.0):
    """Wait (up to `timeout` seconds) for the VPN tunnel to report connected.
    The /api/v1/me/* host is only reachable through the tunnel, so the preloader
    waits — otherwise every GET errors out and the Overview cards land in their
    "Couldn't load" state until something refreshes them.

    Bounded by `timeout` so the gate fails SAFE, not HUNG: if VPN state can't be
    confirmed (e.g. running from source where the status helper is unavailable
    and is_vpn_connected() never flips True), the preloader proceeds anyway and
    lets the actual GETs decide. A real disconnect then surfaces as "Couldn't
    load" instead of leaving 4 of the 5 overview endpoints permanently unfetched.

    Lazy-imports `is_vpn_connected` so this module stays usable in stripped
    builds where the VPN plugin isn't shipped (the gate degrades to a no-op).
    plugins.vpn.main exposes no event/observer for state changes, so polling
    is the only option available today."""
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

    Strategy:
      1. Park until the VPN tunnel is up — every endpoint is behind it.
      2. Fetch /me/inventory once and cache the device list. The summary card
         is derived from the cached list (no separate /me/inventory?limit=1
         call). The cached list is also fed into fetch_all_vulnerabilities so
         it doesn't repeat the /me/inventory call internally. Three list calls
         become one.
      3. Fan out the remaining four endpoints (agent, sca, hotfixes,
         vulnerabilities) on a ThreadPoolExecutor. Each thread owns its own
         module global, so no locking is needed (single-statement assignment
         + GIL = safe). Each sets its readiness event the moment it completes
         so the Overview cards paint in completion order.

    Net effect: total preloader wall-clock drops from ~sum(all endpoints) to
    ~max(inventory + slowest-of-four-parallel-fetches)."""
    _wait_for_vpn()

    # Step 1: inventory list, fetched once. Both the inventory summary card
    # and fetch_all_vulnerabilities consume this.
    devices, devices_err = api_client.fetch_inventory_full()

    global _REMOTE_INVENTORY, _REMOTE_INVENTORY_ERROR
    if devices is None:
        _REMOTE_INVENTORY_ERROR = devices_err
    else:
        _REMOTE_INVENTORY = {"total": len(devices), "items": list(devices)}
    _remote_inventory_ready.set()

    # Step 2: fan out the four endpoints that don't share state.
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
        # Fast group-level aggregation (~370 ms). Drives the Overview vuln
        # card so it paints without waiting on the slower per-device fan-out.
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
            # Surface unexpected exceptions to the log; the per-fetch error
            # path already populates _REMOTE_*_ERROR for expected failures.
            try:
                f.result()
            except Exception as e:
                logger.error(f"[WAZUH-OVERVIEW] preloader thread crashed: {e}")


def _load_vuln_events_phase1_async():
    """Eager Phase 1 loader for the Events tab.

    Waits for the agent fetch, then pulls every vulnerability detection event
    for the LOCAL device in a single pagination stream (see
    api_client.fetch_device_vulnerability_events). As soon as that finishes,
    sets _remote_vuln_events_ready so the Events tab can render the moment
    the user opens it.

    Does NOT set _remote_vuln_events_complete — group-device events are now
    fetched lazily by _load_vuln_events_phase2_async, which fires only when
    the user actually opens the Events tab. The early-exit branch sets both
    events because there's no Phase 2 work to wait for in that case."""
    global _REMOTE_VULN_EVENTS, _vuln_events_phase2_started

    _remote_agent_ready.wait()
    local_id = (_REMOTE_AGENT or {}).get("id") if isinstance(_REMOTE_AGENT, dict) else None
    if not local_id:
        _remote_vuln_events_ready.set()
        _remote_vuln_events_complete.set()
        # No Phase 2 will ever run; suppress the lazy kicker so the Events
        # tab open doesn't try to spin up a fan-out we can't complete.
        with _vuln_events_phase2_lock:
            _vuln_events_phase2_started = True
        return

    local_events, err = api_client.fetch_device_vulnerability_events(local_id)
    if not err:
        normalized = [_normalize_wazuh_hit(h) for h in (local_events or [])]
        normalized.sort(key=lambda e: e.get("timestamp") or "", reverse=True)
        _REMOTE_VULN_EVENTS = normalized
    _remote_vuln_events_ready.set()


def _load_vuln_events_phase2_async():
    """Lazy Phase 2 loader for the Events tab.

    Waits for inventory, then fans out to the rest of the group's devices via
    a ThreadPoolExecutor. Each device's result is merged into
    _REMOTE_VULN_EVENTS by ATOMIC REBIND of the global — no lock needed
    because all rebinds happen on this single coordinator thread. The Events
    pane's id(_REMOTE_VULN_EVENTS)-keyed caches naturally invalidate on each
    rebind, and the pane's poll callback (_schedule_events_ready_check)
    rebuilds the list whenever the identity changes.

    Kicked by _kick_vuln_events_phase2_loader from _build_events_pane the
    first time the user opens the Events tab — so users who never visit
    Events don't pay the per-device fan-out cost on plugin load."""
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
            ex.submit(api_client.fetch_device_vulnerability_events, aid): aid
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
    threading.Thread(
        target=_load_vuln_events_phase1_async,
        name="endpoint2-vuln-events-phase1",
        daemon=True,
    ).start()


def _kick_vuln_events_phase2_loader():
    """Idempotent: spawn the Events-tab Phase 2 fan-out at most once per
    process. Called from _build_events_pane on first tab open, so the
    per-device events fan-out (the heaviest sequence in the plugin) only
    runs when the user actually wants to see Events."""
    global _vuln_events_phase2_started
    with _vuln_events_phase2_lock:
        if _vuln_events_phase2_started:
            return
        _vuln_events_phase2_started = True
    threading.Thread(
        target=_load_vuln_events_phase2_async,
        name="endpoint2-vuln-events-phase2",
        daemon=True,
    ).start()


def _load_vulns_async():
    """Lazy loader for the Vulnerabilities tab's per-device CVE fan-out.

    Waits for inventory (the device list seeds the fan-out) and runs
    fetch_all_vulnerabilities with that cached list so the client doesn't
    re-fetch /me/inventory. Result lands in _REMOTE_VULNS and arrival is
    signalled via _remote_vulns_ready — the Vulnerabilities pane's existing
    poll (_schedule_vuln_ready_check) swaps from the loading placeholder
    to the populated table as soon as this fires.

    Overview's vuln card is driven by _REMOTE_VULNS_SUMMARY (cheap group
    aggregation, still eager), so this lazy path doesn't affect the
    always-visible Overview paint."""
    global _REMOTE_VULNS, _REMOTE_VULNS_ERROR

    _remote_inventory_ready.wait()
    items = _REMOTE_INVENTORY.get("items") if isinstance(_REMOTE_INVENTORY, dict) else []
    data, err = api_client.fetch_all_vulnerabilities(devices=items)
    if data is not None:
        _REMOTE_VULNS = data
    _REMOTE_VULNS_ERROR = err
    _remote_vulns_ready.set()


def _kick_vulns_loader():
    """Idempotent: spawn the Vulnerabilities-tab CVE fan-out at most once
    per process. Called from _build_vulnerabilities_pane on first tab open
    (which the pre-build chain may also trigger if the user lingers on
    Overview), so the N per-device /me/vulnerabilities/{id} calls only fire
    when the user actually wants to see the Vulnerabilities table."""
    global _vulns_loader_started
    with _vulns_loader_lock:
        if _vulns_loader_started:
            return
        _vulns_loader_started = True
    threading.Thread(
        target=_load_vulns_async,
        name="endpoint2-vulns-loader",
        daemon=True,
    ).start()


def _kick_overview_api_loader():
    """Back-compat alias for the Wazuh Overview + Vulnerabilities panes' tab-
    entry kicks. Delegates to the preloader's idempotent kick — a no-op when
    the Dashboard's end-of-build hook already started the fetch."""
    _kick_overview_early_loader()


def refresh_all_remote_data():
    """Trigger a full re-fetch of every cached /me/* endpoint.

    Resets the four one-shot loader guards (overview-early, vulns,
    vuln-events-phase2, agents) and re-kicks them. The kickers spawn fresh
    daemon threads which rebind their respective globals atomically when
    new data lands; readiness events stay SET and module globals stay
    populated throughout, so the UI keeps showing stale values until each
    rebind — no "Loading…" flash.

    Decoupled from any UI surface: safe to call from a button handler, an
    auto-refresh timer, a settings toggle, a hotkey, or the debug
    inspector. For UI repaint after the rebinds land, see
    Plugin.request_refresh.

    Caveat: lazy loaders that haven't been kicked yet in this process
    (e.g. the user never opened the Vulnerabilities or Events tab) WILL
    be kicked by this call. That's "refresh + warm" rather than strict
    "refresh only what's already loaded." Acceptable for a dev gesture;
    a stricter variant would snapshot the four flags first and only
    re-kick the ones that were True."""
    global _overview_early_loader_started, _vulns_loader_started
    global _vuln_events_phase2_started, _agents_loader_started

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
    """Bitmask of which remote slots have completed (any state: data or error).
    Used by the refresh poll to detect transitions without re-rendering on
    every 100 ms tick.

    Bit 2 tracks the vulns SUMMARY (not the full per-device data) because
    the Overview vuln card reads from the summary — that's the slot whose
    arrival should trigger a card repaint. _remote_vulns_ready is consumed
    directly by the Vulnerabilities tab, which has its own readiness poll."""
    return (
        (1 if _remote_agent_ready.is_set() else 0)
        | (2 if _remote_vulns_summary_ready.is_set() else 0)
        | (4 if _remote_sca_ready.is_set() else 0)
        | (8 if _remote_inventory_ready.is_set() else 0)
        | (16 if _remote_hotfixes_ready.is_set() else 0)
    )


_READY_ALL = 31  # all 5 slots set


def _overview_has_errors():
    """True if any of the five Overview /me/* slots completed with an error.

    Used to auto-recover when a prior (typically startup) preload cached a
    transient failure: the one-shot loader won't retry on its own, and the
    readiness poll only repaints on a bitmask CHANGE (already maxed once every
    slot has completed), so without an explicit re-fetch the cards stay stranded
    on empty/zero until the user manually hits Refresh."""
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


def _status_card(title, description, stat_text, target_tab=None):
    """Shared module-card stub: an INFO card whose single muted stat line is
    `stat_text`. The three named variants below differ only in that text."""
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
    """Card stub for modules that have no /me/* endpoint yet."""
    return _status_card(title, description, "Data unavailable", target_tab)


def _loading_card(title, description, target_tab=None):
    return _status_card(title, description, "Loading…", target_tab)


def _error_card(title, description, target_tab=None):
    return _status_card(title, description, "Couldn't load", target_tab)


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
        self._severity_counts_cache = None  # (id(_REMOTE_VULN_EVENTS), result) or None
        self._bucket_events_cache = None    # (id(_REMOTE_VULN_EVENTS), result) or None
        self._vuln_severity_cache = None    # (id(vulns), result) or None
        self._bucket_vulns_cache = None     # (id(vulns), result) or None
        # (key, sorted-filtered list) — key = (id(vulns), device, sev, query)
        self._filter_vulns_cache = None
        self._chart_theme_cache = None      # (is_dark, theme dict) or None
        # Inventory row caches — the threat path scans _REMOTE_VULNS per device,
        # so paging/group changes shouldn't re-derive it. Keyed on data identity.
        self._inventory_rows_cache = None   # (key, rows) or None
        self._inventory_counts_cache = None  # (key, rows) or None
        # Events pane state
        self._selected_event_id = None
        self._event_list_frame = None
        self._event_detail_frame = None
        self._event_row_frames = {}
        self._event_search_var = None
        self._event_search_after_id = None  # debounce handle for the search box
        self._event_count_label = None
        # Events list/detail split — collapses 2-up -> stacked below 680px.
        self._events_pane_parent = None
        self._events_split = None
        self._events_split_row = 0
        self._events_split_stacked = False
        self._events_resize_after_id = None
        self._events_resize_handler_id = None
        # Events list pagination (1-based page + its pager frame).
        self._event_page = 1
        self._event_pagination_frame = None
        # Severity pill count labels, keyed by level. Stashed by
        # _build_severity_pills so _update_severity_pills can rewrite the
        # numbers in place during Phase 2 rebinds without tearing down the
        # pill row (which would otherwise force a full pane rebuild — see
        # _refresh_events_content for the rebind path).
        self._severity_count_labels = {}
        self._event_chart_canvas = None
        self._event_chart_figure = None
        self._chart_ax = None
        self._chart_buckets = []
        self._chart_counts = {}
        self._selected_bucket = None  # datetime of the active 1-hour bucket filter, or None
        self._events_ready_after_id = None  # poll handle for the background events loader
        self._events_last_seen_id = None    # id(_REMOTE_VULN_EVENTS) at last rebuild; used to detect incremental merges
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
        self._vuln_search_after_id = None  # debounce handle for the search box
        self._vuln_count_label = None
        self._vuln_list_frame = None
        self._vuln_donut_figure = None
        self._vuln_donut_canvas = None
        self._vuln_cvss_figure = None
        self._vuln_cvss_canvas = None
        self._vuln_after_id = None  # poll handle for the Vulnerabilities readiness check
        self._vuln_pane_parent = None  # reference for swapping loading -> table
        # Charts-row responsive state. The row collapses from 2-up to stacked
        # below 680px content width; the resize handler rebuilds only that row.
        self._vuln_charts_wrapper = None
        self._vuln_charts_row = 0
        self._vuln_charts_stacked = False
        self._vuln_resize_after_id = None
        self._vuln_resize_handler_id = None
        # Table list/detail split — collapses 2-up -> stacked at the same 680px
        # breakpoint; the same vuln resize handler rebuilds it.
        self._vuln_table_split = None
        self._vuln_table_row = 0
        self._vuln_table_stacked = False
        # Vuln list pagination (1-based page + its pager frame).
        self._vuln_page = 1
        self._vuln_pagination_frame = None
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
        # Refresh button reference. Stashed by _build_modules_header so
        # request_refresh can disable it for the duration of the redraw
        # window. None until the Overview pane builds.
        self._refresh_button = None
        # Refresh repaint bookkeeping: pending tick after-ids (for cancel),
        # the button-restore after-id, and the per-pane content fingerprints
        # so a tick that finds nothing changed is a no-op.
        self._refresh_repaint_after_ids = []
        self._refresh_button_after_id = None
        self._refresh_seen_ids = {}

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
            if _remote_vuln_events_ready.is_set():
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
            # Module-card fonts (hoisted out of _make_module_card so they're not
            # rebuilt per card on every grid populate).
            "inter_bold_16": customtkinter.CTkFont(family="Inter", size=16, weight="bold"),
            "bold_11": customtkinter.CTkFont(size=11, weight="bold"),
            "size_20": customtkinter.CTkFont(size=20),
            "size_13": customtkinter.CTkFont(size=13),
            "bold_13": customtkinter.CTkFont(size=13, weight="bold"),
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
        if _ready_mask() == _READY_ALL and _overview_has_errors():
            # A prior preload (typically at startup, before the VPN tunnel and
            # gateway token had settled) cached an error for at least one
            # endpoint. The one-shot loader won't retry, and the readiness poll
            # only repaints on a bitmask CHANGE — which is already maxed — so the
            # cards would stay stranded on empty/zero until a manual Refresh.
            # Auto-recover by re-fetching and scheduling best-effort repaints,
            # exactly as the Refresh button does.
            logger.info(
                "[WAZUH-OVERVIEW] Cached preload had errors — auto-refreshing on tab open"
            )
            refresh_all_remote_data()
            self._schedule_refresh_repaints()
        elif _ready_mask() != _READY_ALL:
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

    def request_refresh(self):
        """Fire a data refresh and schedule best-effort UI repaints.

        The data half (refresh_all_remote_data) is decoupled — anything
        that wants to re-fetch without touching the UI can call that
        module-level function directly. This wrapper exists for the dev
        refresh button (and any future UI surface) so the panes pick up
        the rebinds without waiting for a tab switch."""
        refresh_all_remote_data()
        # Disable the refresh button for the duration of the redraw window
        # — visual feedback that the refresh is running, plus debounce so
        # rapid clicks don't queue overlapping repaint cycles.
        if self._refresh_button is not None:
            try:
                if self._refresh_button.winfo_exists():
                    self._refresh_button.configure(state="disabled")
            except Exception:
                pass
        self._schedule_refresh_repaints()
        # Re-enable the button once the redraw window closes. Tracked so
        # destroy() can cancel it if the user navigates away mid-window.
        self._refresh_button_after_id = self.app.after(
            6000, self._restore_refresh_button)

    def _schedule_refresh_repaints(self):
        """Schedule best-effort repaint ticks across the window in which eager +
        lazy fetches land. The eager preload's fast endpoints arrive within
        ~500ms; lazy fan-outs (CVEs, Phase 2 events, per-device inventory) finish
        by ~2-4s. A handful of ticks across that window pick up rebinds without
        polling forever — each tick is cheap when nothing changed, since the
        renderers just re-read the globals and reapply text/data.

        Shared by request_refresh (the dev Refresh button) and the auto-recover
        path in _build_overview_pane, so both repaint identically. Each tick is a
        no-op when nothing changed (the content-identity guard in
        _refresh_visible_panes). Three ticks cover the eager (~500ms) and lazy
        (~2-4s) landing windows; the after-ids are tracked for destroy() cleanup."""
        # Cancel any ticks still pending from a previous refresh press.
        for aid in self._refresh_repaint_after_ids:
            try:
                self.app.after_cancel(aid)
            except Exception:
                pass
        self._refresh_repaint_after_ids = [
            self.app.after(delay_ms, self._refresh_visible_panes)
            for delay_ms in (500, 2000, 6000)
        ]

    def _restore_refresh_button(self):
        """Re-enable the refresh button at the end of the redraw window.
        Tolerates the button having been destroyed (e.g. modules header
        was rebuilt mid-refresh) — the new button created by the next
        _build_modules_header call is already in its normal state."""
        if self._refresh_button is None:
            return
        try:
            if self._refresh_button.winfo_exists():
                self._refresh_button.configure(state="normal")
        except Exception:
            pass

    def _overview_data_fingerprint(self):
        """Identity of the data the module-grid cards render: the readiness
        bitmask plus the id() of each source global. A refresh rebinds those
        globals (new ids) even when readiness stays set, so both parts are
        needed to detect 'something actually changed since the last tick'."""
        return (
            _ready_mask(),
            id(_REMOTE_AGENT), id(_REMOTE_VULNS_SUMMARY), id(_REMOTE_SCA),
            id(_REMOTE_INVENTORY), id(_REMOTE_HOTFIXES),
        )

    def _refresh_visible_panes(self):
        """Best-effort repaint of every pane that's currently alive. Routes
        through the narrow refresh paths so static widgets don't flicker. Each
        pane is guarded by a content-identity check (_refresh_seen_ids) so a
        repaint tick that finds nothing changed since the last one is a no-op —
        the data globals are rebound (new id) only when fresh data lands."""
        seen = self._refresh_seen_ids
        # Overview module-grid cards.
        if self._module_wrapper is not None and self._module_wrapper.winfo_exists():
            fp = self._overview_data_fingerprint()
            if seen.get("overview") != fp:
                seen["overview"] = fp
                self._refresh_overview_data_only()
        # Events pane (in-place: chart Figure preserved; rows + detail re-render).
        if self._event_list_frame is not None and self._event_list_frame.winfo_exists():
            eid = id(_REMOTE_VULN_EVENTS)
            if seen.get("events") != eid:
                seen["events"] = eid
                self._refresh_events_content()
        # Vulnerabilities pane (in-place: donut + CVSS Figures preserved). Also
        # run when the table isn't built yet so the error->table recovery path
        # gets a chance to rebuild once good data lands.
        if (
            self._vuln_pane_parent is not None
            and self._vuln_pane_parent.winfo_exists()
        ):
            vid = id(_REMOTE_VULNS)
            table_built = (
                self._vuln_list_frame is not None
                and self._vuln_list_frame.winfo_exists()
            )
            if seen.get("vulns") != vid or not table_built:
                seen["vulns"] = vid
                self._refresh_vulns_content()

    def _refresh_overview_data_only(self):
        """Refresh just the module-grid cards. Skips the top device widget
        and alert bar — their data is effectively static for the local
        device and rebuilding them on every refresh tick causes visible
        flicker without changing anything the user sees. The initial-load
        polling loop still uses _refresh_overview_section, which DOES
        rebuild those widgets, to swap their loading placeholders for
        populated content as each endpoint lands."""
        if self._module_wrapper is None or not self._module_wrapper.winfo_exists():
            return
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
        header.grid_columnconfigure(2, weight=0)

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

        # Dev-only refresh button. TEMPORARY gate: hardcoded True until
        # debug mode is fixed and we can switch back to
        # `hasattr(self.app, "inspector")`. Flip _SHOW_DEV_REFRESH_BUTTON
        # to False (or restore the inspector check) when shipping. The
        # button does nothing but call request_refresh — the refresh
        # logic itself lives in the decoupled refresh_all_remote_data()
        # module function.
        #
        # Styled with a solid accent fill so it's easy to spot while it's
        # a temporary dev gesture. Drop back to a subtle transparent style
        # when this gets promoted to a normal user-facing feature.
        if _SHOW_DEV_REFRESH_BUTTON:
            self._refresh_button = customtkinter.CTkButton(
                header,
                text="↻ Refresh data",
                fg_color=["#2563EB", "#3B82F6"],
                hover_color=["#1D4ED8", "#2563EB"],
                text_color=["#FFFFFF", "#FFFFFF"],
                corner_radius=8,
                width=120,
                height=30,
                font=customtkinter.CTkFont(size=12, weight="bold"),
                command=self.request_refresh,
            )
            self._refresh_button.grid(row=0, column=2, sticky="e", padx=(16, 0))

    # ----- section 3 (b): module card grid -----------------------------------

    def _build_module_grid(self, parent, row):
        wrapper = customtkinter.CTkFrame(parent, fg_color="transparent")
        wrapper.grid(row=row, column=0, sticky="nsew")
        wrapper.grid_columnconfigure(0, weight=1)
        wrapper.grid_rowconfigure(0, weight=1)
        self._module_wrapper = wrapper

        self._populate_module_grid()
        self._bind_module_resize()

    def _content_width(self):
        """Usable content width = window width minus the sidebar + padding.

        Matches the Dashboard's formula (winfo_width - 250 sidebar - platform
        padding) so width-driven breakpoints agree across plugins. Falls back to
        ~70% of the screen width before the window has been realized."""
        try:
            window_width = self.app.winfo_width()
        except Exception:
            window_width = 0
        if window_width <= 1:
            try:
                window_width = int(self.app.winfo_screenwidth() * 0.7)
            except Exception:
                window_width = 1024
        return max(1, window_width - _SIDEBAR_WIDTH - self._padding_offset)

    def _debounce(self, after_attr, delay_ms, fn):
        """Coalesce rapid callbacks (e.g. per-keystroke search) into one call
        after `delay_ms` of quiet. `after_attr` is the instance-attribute name
        holding this debounce's pending `after` id so it can be cancelled here
        and in destroy(). The trailing call sees the latest state."""
        pending = getattr(self, after_attr, None)
        if pending:
            try:
                self.app.after_cancel(pending)
            except Exception:
                pass
        setattr(self, after_attr, self.app.after(delay_ms, fn))

    @staticmethod
    def _bind_row_hover(row_frame, hover_bg, idle="transparent"):
        """Highlight a list row (and all its children) on hover, reverting to
        `idle` on leave. Shared by the event / vuln / inventory row builders —
        callers gate the call on `not is_selected` where a selected row keeps a
        persistent highlight."""
        def on_enter(_e=None):
            try:
                row_frame.configure(fg_color=hover_bg)
            except Exception:
                pass

        def on_leave(_e=None):
            try:
                row_frame.configure(fg_color=idle)
            except Exception:
                pass

        for w in (row_frame, *row_frame.winfo_children()):
            w.bind("<Enter>", on_enter)
            w.bind("<Leave>", on_leave)

    @staticmethod
    def _matches_query(q, fields):
        """True if `q` (already lowercased + stripped) is a substring of the
        space-joined, lowercased `fields`. Empty `q` always matches and skips
        building the haystack."""
        if not q:
            return True
        return q in " ".join(str(f) for f in fields).lower()

    def _compute_max_cols(self):
        content_width = self._content_width()
        # Width-driven column ladder. The Dashboard's sqrt-then-cap math pins a
        # 9-card grid at 3 columns for any width >=680, so the count rarely
        # changed as the window resized. Stepping 1/2/3/4 directly by width
        # makes the layout visibly adapt across the usable range (and reach a
        # fuller 4-wide arrangement on large monitors).
        c1, c2, c3 = _COL_BREAKPOINTS
        if content_width < c1:
            return 1
        if content_width < c2:
            return 2
        if content_width < c3:
            return 3
        return 4

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
        # Counts come from /me/vulnerabilities (group-level summary) which
        # lands ~4x faster than the per-device fan-out. The full per-device
        # CVE list (_REMOTE_VULNS) is only needed by the Vulnerabilities
        # tab's table + timeline chart.
        if not _remote_vulns_summary_ready.is_set():
            return _loading_card(title, desc, target_tab=target)
        if _REMOTE_VULNS_SUMMARY_ERROR or not isinstance(_REMOTE_VULNS_SUMMARY, dict):
            return _error_card(title, desc, target_tab=target)

        by_sev = _REMOTE_VULNS_SUMMARY.get("by_severity") or {}
        # The server's by_severity keys are capitalized ("Critical", "High"...);
        # our level constants are lowercase. Normalize both sides.
        counts = {
            lvl: int(by_sev.get(lvl.capitalize(), by_sev.get(lvl, 0)) or 0)
            for lvl in _SEVERITY_LEVELS
        }
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
        n = len(cards_data)
        # Width-driven column count: the breakpoint value IS the column count
        # (capped only by the card count). Unlike sqrt-then-cap this actually
        # reaches the wide-window column counts instead of being silently
        # re-capped, so the grid visibly steps 1->2->3->4 with the window.
        cols = max(1, min(self._compute_max_cols(), n))
        rows = (n + cols - 1) // cols
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
                target_h = max(_CARD_MIN_H, min(_CARD_MAX_H, int(card_w) + 20))
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

    def _bind_figure_autoresize(self, canvas, fig, use_tight_layout=False, settle_ms=150):
        """Make a matplotlib FigureCanvasTkAgg track its widget size on resize,
        cheaply and smoothly — the "freeze-and-scale" technique.

        Re-rastering matplotlib on every <Configure> is expensive (jank); only
        re-rendering after the drag stops leaves the chart frozen mid-drag. So we
        REPLACE matplotlib's native <Configure>->resize with a handler that, during
        the drag, just stretches the LAST crisp render (a cached PIL snapshot) to
        the live widget size — near-zero cost, so the chart visibly tracks the
        window — and does the single real re-render once the drag settles
        (`settle_ms` debounce).

        The crisp render goes through canvas.resize() (reads only event.width/
        height; stable across mpl versions), which also grows the backing Tk
        PhotoImage and recreates the canvas image item — automatically replacing
        our scaled bitmap with the sharp render.

        Degrades gracefully: if PIL or the mpl canvas internals are unavailable,
        the scale path is skipped and it behaves as a plain debounced crisp resize.

        Bound on the canvas's own tk widget; the widget is recreated on every pane
        rebuild, so the binding dies with it (no manual unbind)."""
        widget = canvas.get_tk_widget()
        job = [None]
        snap = [None]        # cached PIL snapshot of the last crisp render
        photo_ref = [None]   # keep the ImageTk ref alive (Tk holds only a weak one)
        dragging = [False]

        try:
            from PIL import Image, ImageTk
        except Exception:
            Image = ImageTk = None

        def _capture_snapshot():
            # Grab the current crisp raster from the Agg buffer as a PIL image.
            if Image is None:
                return
            try:
                w0, h0 = canvas.get_width_height()
                snap[0] = Image.frombuffer(
                    "RGBA", (w0, h0), canvas.buffer_rgba(), "raw", "RGBA", 0, 1
                ).copy()
            except Exception:
                snap[0] = None

        def _show_scaled(w, h):
            # Stretch the cached snapshot onto the canvas image item for cheap
            # live feedback during the drag. Read the item id fresh — canvas
            # .resize() recreates it after every crisp render.
            if snap[0] is None or Image is None:
                return
            try:
                tkc = getattr(canvas, "_tkcanvas", None)
                item = getattr(canvas, "_tkcanvas_image_region", None)
                if tkc is None or item is None:
                    return
                scaled = snap[0].resize((max(1, w), max(1, h)), Image.BILINEAR)
                photo_ref[0] = ImageTk.PhotoImage(scaled, master=widget)
                tkc.itemconfigure(item, image=photo_ref[0])
                tkc.coords(item, w // 2, h // 2)
            except Exception:
                pass

        def apply():
            job[0] = None
            dragging[0] = False
            try:
                if not widget.winfo_exists():
                    return
                w, h = widget.winfo_width(), widget.winfo_height()
                if w <= 1 or h <= 1:
                    return
                # tight_layout recomputes axis/label margins for the new size so
                # bar labels don't crowd. Size must be current first; skip it for
                # the donut (it fights set_aspect("equal") and warps the pie).
                if use_tight_layout:
                    fig.set_size_inches(w / fig.dpi, h / fig.dpi, forward=False)
                    fig.tight_layout()
                # Crisp render incl. the Tk PhotoImage; recreates the image item,
                # replacing any scaled bitmap shown during the drag.
                canvas.resize(_SimpleResizeEvent(w, h))
            except (tk.TclError, AttributeError, RuntimeError, ValueError):
                pass

        def on_configure(_e=None):
            try:
                w, h = widget.winfo_width(), widget.winfo_height()
            except Exception:
                return
            # First event of a drag: snapshot the current crisp render, then
            # scale it for the rest of the drag.
            if not dragging[0]:
                dragging[0] = True
                _capture_snapshot()
            if w > 1 and h > 1:
                _show_scaled(w, h)
            # Debounce the crisp re-render to the end of the drag.
            if job[0] is not None:
                try:
                    widget.after_cancel(job[0])
                except Exception:
                    pass
            job[0] = widget.after(settle_ms, apply)

        widget.bind("<Configure>", on_configure)

    def _make_module_card(self, parent, row, column, card_data):
        text_secondary = self._theme("text_secondary", default=_DEFAULT_TEXT_SECONDARY)
        fonts = self._ensure_fonts()
        target_tab = card_data.get("target_tab")

        card = customtkinter.CTkFrame(parent, corner_radius=12, border_width=1)
        card.grid(row=row, column=column, sticky="nsew", padx=8, pady=8)
        card.grid_columnconfigure(0, weight=1)
        card.grid_columnconfigure(1, weight=0)
        card.grid_rowconfigure(2, weight=1)

        title = customtkinter.CTkLabel(
            card,
            text=card_data["title"],
            font=fonts["inter_bold_16"],
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
            font=fonts["bold_11"],
        )
        badge.grid(row=0, column=1, sticky="ne", padx=(0, 16), pady=(16, 0))

        desc = customtkinter.CTkLabel(
            card,
            text=card_data["description"],
            text_color=text_secondary,
            font=fonts["size_12"],
            anchor="w",
        )
        desc.grid(row=1, column=0, columnspan=2, sticky="w", padx=16, pady=(4, 8))

        stats = customtkinter.CTkFrame(card, fg_color="transparent")
        stats.grid(row=2, column=0, sticky="sw", padx=16, pady=(0, 16))
        stat_labels = []
        for i, (text, color_key) in enumerate(card_data["stats"]):
            color = self._segment_color(color_key)
            font = fonts["size_13"] if color_key == "muted" else fonts["bold_13"]
            lbl = customtkinter.CTkLabel(
                stats,
                text=text,
                text_color=color,
                font=font,
            )
            lbl.grid(row=0, column=i, sticky="w")
            stat_labels.append(lbl)

        arrow = customtkinter.CTkLabel(
            card,
            text="›",
            text_color=text_secondary,
            font=fonts["size_20"],
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
            # Mirror _populate_module_grid's width-driven column math so the
            # guard and the rebuild agree (no missed or redundant rebuilds).
            target_cols = max(1, min(
                self._compute_max_cols(), len(self._module_cards())))
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

    def _bind_breakpoint_rebuild(self, after_attr, handler_attr, on_settled):
        """Shared responsive-rebuild plumbing for panes whose layout flips at a
        width breakpoint (the chart row + the list/detail splits). Binds the app
        window's <Configure> with a 250ms debounce (never mid-drag — matches the
        Dashboard), filters position-only events, and unbinds any handler left
        from a previous build (leak prevention). `on_settled()` runs once the
        drag pauses; it owns its own change-detection and does the rebuild.

        `after_attr`/`handler_attr` are the instance-attribute NAMES holding this
        binding's pending-after id and bound-handler id, so each pane gets an
        independent, separately-cancellable binding."""
        last_size = [0, 0]

        def settled():
            setattr(self, after_attr, None)
            try:
                on_settled()
            except (tk.TclError, AttributeError, RuntimeError):
                pass

        def debounced(event=None):
            if event is not None:
                if event.width == last_size[0] and event.height == last_size[1]:
                    return
                last_size[0] = event.width
                last_size[1] = event.height
            pending = getattr(self, after_attr, None)
            if pending:
                try:
                    self.app.after_cancel(pending)
                except Exception:
                    pass
            setattr(self, after_attr, self.app.after(250, settled))

        prior = getattr(self, handler_attr, None)
        if prior:
            try:
                self.app.unbind("<Configure>", prior)
            except Exception:
                pass
        setattr(self, handler_attr,
                self.app.bind("<Configure>", debounced, add="+"))

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

        # First open of the Events tab kicks the per-device group fan-out.
        # Idempotent — subsequent rebuilds (polling, manual rebind) short-
        # circuit on the started flag.
        _kick_vuln_events_phase2_loader()

        if not _remote_vuln_events_ready.is_set():
            self._render_events_loading(parent)
            self._schedule_events_ready_check(parent)
            return

        self._events_pane_parent = parent
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
        if _REMOTE_VULN_EVENTS:
            self._select_event(_REMOTE_VULN_EVENTS[0]["id"])

        # Re-binds after unbinding any prior handler, so re-renders don't stack
        # duplicate <Configure> listeners.
        self._bind_events_resize()

    def _render_centered_message(self, parent, text, detail=None):
        """Center a single message in `parent` (used for the per-tab loading
        placeholders and the vulnerabilities error pane). When `detail` is given
        the primary line is bold and the detail renders muted beneath it."""
        parent.grid_columnconfigure(0, weight=1)
        parent.grid_rowconfigure(0, weight=1)
        text_secondary = self._theme("text_secondary", default=_DEFAULT_TEXT_SECONDARY)
        if detail is None:
            customtkinter.CTkLabel(
                parent,
                text=text,
                text_color=text_secondary,
                font=customtkinter.CTkFont(size=14),
            ).grid(row=0, column=0, sticky="nsew", padx=20, pady=40)
            return
        container = customtkinter.CTkFrame(parent, fg_color="transparent")
        container.grid(row=0, column=0, sticky="nsew", padx=20, pady=40)
        container.grid_columnconfigure(0, weight=1)
        customtkinter.CTkLabel(
            container, text=text,
            font=customtkinter.CTkFont(size=14, weight="bold"),
        ).grid(row=0, column=0, sticky="n")
        customtkinter.CTkLabel(
            container, text=str(detail), text_color=text_secondary,
            font=customtkinter.CTkFont(size=12),
        ).grid(row=1, column=0, sticky="n", pady=(6, 0))

    def _render_events_loading(self, parent):
        self._render_centered_message(parent, "Loading events…")

    def _refresh_events_content(self):
        """Update Events pane content in place after a Phase 2 rebind.

        The pane skeleton (pills row, matplotlib Figure + canvas, scrollable
        list wrapper, detail frame) was built once by _build_events_pane and
        is reused here. Allocating a new Figure every 250ms during Phase 2
        merging was the dominant cost of the old polling path, which called
        _build_events_pane on each rebind — full teardown + matplotlib
        Figure realloc + selection/scroll wipe. This path leaves widgets in
        place and only rewrites text/data:

          - severity pills: in-place .configure(text=...) on cached labels
          - bar chart: ax.clear() + redraw bars on the existing Figure
          - row list: tear down children of _event_list_frame only (the
            ScrollableFrame keeps its scroll position) and rebuild rows

        _render_event_list (the existing helper) already preserves the
        selection across refreshes by checking if _selected_event_id still
        exists in the filtered list, so the user's click survives the
        merge."""
        self._update_severity_pills()
        # Rebucket and repaint the chart. _bucket_events_24h_hourly is keyed on
        # (id(_REMOTE_VULN_EVENTS), right_edge) so the walk is skipped when
        # neither the event list nor the wall-clock hour changed.
        self._chart_buckets, self._chart_counts = self._bucket_events_24h_hourly()
        self._render_event_chart()
        query = self._event_search_var.get() if self._event_search_var else ""
        self._render_event_list(query)

    def _schedule_events_ready_check(self, parent):
        # Tight pre-ready cadence so the placeholder→content handoff feels
        # instant the moment the local-device fetch completes. Once we've
        # rendered, fall back to a slower poll: the loader keeps appending
        # group-device events behind the scenes, and the pane has to update
        # whenever the global is rebound (id(_REMOTE_VULN_EVENTS) changes).
        # Stop polling entirely once _remote_vuln_events_complete fires.
        # 120ms still feels instant on the handoff but wakes the Tk main thread
        # ~6x less often than the old 20ms spin while the loader is network-bound.
        pre_ready_poll_ms = 120
        post_ready_poll_ms = 250

        def check():
            self._events_ready_after_id = None
            if not parent.winfo_exists():
                return
            if not _remote_vuln_events_ready.is_set():
                self._events_ready_after_id = self.app.after(pre_ready_poll_ms, check)
                return
            current_id = id(_REMOTE_VULN_EVENTS)
            if self._events_last_seen_id != current_id:
                self._events_last_seen_id = current_id
                # Refresh-in-place when the skeleton is alive; full rebuild
                # only if the user tabbed away and the list frame was torn
                # down. The fast path skips the matplotlib Figure realloc
                # that used to fire on every Phase 2 device merge.
                if self._event_list_frame and self._event_list_frame.winfo_exists():
                    self._refresh_events_content()
                else:
                    self._build_events_pane(parent)
            if _remote_vuln_events_complete.is_set():
                return
            self._events_ready_after_id = self.app.after(post_ready_poll_ms, check)

        self._events_ready_after_id = self.app.after(pre_ready_poll_ms, check)

    def _severity_palette(self, level):
        """Return (bg, text) tuple for a severity level, theme-resolved."""
        key = _SEVERITY_THEME_KEY.get(level, "info")
        bg = self._theme("status_badge_bg", key, default=["#F3F4F6", "#1F2937"])
        fg = self._theme("status_badge_text", key, default=_DEFAULT_TEXT_SECONDARY)
        return bg, fg

    def _severity_counts(self):
        events_id = id(_REMOTE_VULN_EVENTS)
        cache = self._severity_counts_cache
        if cache is not None and cache[0] == events_id:
            return cache[1]
        counts = _bucket_by_severity(_REMOTE_VULN_EVENTS)
        self._severity_counts_cache = (events_id, counts)
        return counts

    def _build_severity_pills(self, parent, row):
        counts = self._severity_counts()
        # Fresh build: prior count labels (if any) belonged to a destroyed
        # parent. Reset the cache so _update_severity_pills doesn't try to
        # .configure() into freed widgets after a tab tear-down/rebuild.
        self._severity_count_labels = {}

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

            count_label = customtkinter.CTkLabel(
                pill,
                text=str(counts[level]),
                text_color=fg,
                font=customtkinter.CTkFont(family="Inter", size=20, weight="bold"),
            )
            count_label.grid(row=0, column=2, sticky="e", padx=(0, 14), pady=10)
            self._severity_count_labels[level] = count_label

    def _update_severity_pills(self):
        """Rewrite pill count text without rebuilding the pill row.

        Called from _refresh_events_content on every Phase 2 rebind so the
        numbers reflect the merged group totals. No-op when the pills haven't
        been built yet (e.g. the Events tab was never opened in this session)
        or after a tear-down — in either case the next _build_severity_pills
        call will repopulate the cache."""
        counts = self._severity_counts()
        for level, label in self._severity_count_labels.items():
            try:
                if label.winfo_exists():
                    label.configure(text=str(counts[level]))
            except Exception:
                pass

    # ----- 24h hourly stacked bar chart -----

    def _bucket_events_24h_hourly(self):
        """Group events into a fixed 24-slot hourly window ending at the next
        upcoming hour boundary.

        Window is anchored to wall clock: right edge = next hour mark above
        `now` (UTC), left edge = right edge − 24h. Each bucket's key is the
        LOWER bound of its hour slot; bucket i covers [key, key+1h). Events
        outside the window are silently dropped — the chart is a rolling
        24-hour view by design.

        Cache key includes the window right-edge so we regenerate when the
        wall clock rolls past an hour boundary even if _REMOTE_VULN_EVENTS
        identity hasn't changed."""
        now = datetime.now(timezone.utc)
        right_edge = now.replace(minute=0, second=0, microsecond=0) + timedelta(hours=1)
        left_edge = right_edge - timedelta(hours=24)

        events_id = id(_REMOTE_VULN_EVENTS)
        cache_key = (events_id, right_edge)
        cache = self._bucket_events_cache
        if cache is not None and cache[0] == cache_key:
            return cache[1]

        buckets = [left_edge + timedelta(hours=i) for i in range(24)]
        counts = {b: {lvl: 0 for lvl in _SEVERITY_LEVELS} for b in buckets}

        for ev in _REMOTE_VULN_EVENTS:
            try:
                dt = datetime.fromisoformat(ev["timestamp"].replace("Z", "+00:00"))
            except (KeyError, ValueError):
                continue
            sev = (ev.get("severity") or "").lower()
            if sev not in _SEVERITY_LEVELS:
                continue
            if dt < left_edge or dt >= right_edge:
                continue
            idx = int((dt - left_edge).total_seconds() // 3600)
            counts[buckets[idx]][sev] += 1

        self._bucket_events_cache = (cache_key, (buckets, counts))
        return buckets, counts

    def _chart_theme(self):
        is_dark = customtkinter.get_appearance_mode() == "Dark"
        # Memoize per appearance mode — this is read on every chart render.
        cache = self._chart_theme_cache
        if cache is not None and cache[0] == is_dark:
            return cache[1]
        # Match the page background ["gray92","gray14"] so the chart blends in.
        theme = {
            "bg": "#242424" if is_dark else "#EBEBEB",
            "text": "#E5E7EB" if is_dark else "#1F2937",
            "grid": "#3A3A3A" if is_dark else "#D1D5DB",
            "is_dark": is_dark,
        }
        self._chart_theme_cache = (is_dark, theme)
        return theme

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
        # The bar fill is the badge TEXT color (more saturated than the bg).
        # Reuse _severity_palette so the key/default live in one place.
        _bg, fg = self._severity_palette(level)
        return fg[1] if is_dark else fg[0]

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
        self._chart_buckets, self._chart_counts = self._bucket_events_24h_hourly()

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
        self._bind_figure_autoresize(canvas, fig, use_tight_layout=True)

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

        import matplotlib.colors as mcolors
        x = list(range(24))
        bottoms = [0] * 24
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
                width=0.9,
                color=colors,
                edgecolor="none",
                label=level.capitalize(),
            )
            bottoms = [a + b for a, b in zip(bottoms, heights)]

        # Fixed 24-slot window: tick at every hour, label every 3rd so
        # labels don't overlap on a narrow chart. Hourly vertical gridlines
        # give the user a visible mark at every bar boundary.
        ax.set_xlim(-0.5, 23.5)
        ax.set_xticks(x)
        labels = [
            buckets[i].strftime("%H:%M") if i % 3 == 0 else ""
            for i in range(24)
        ]
        ax.set_xticklabels(labels, fontsize=8, color=chart_theme["text"])
        ax.xaxis.grid(True, color=chart_theme["grid"], linewidth=0.4, alpha=0.5)

        max_h = max(bottoms) if bottoms else 1
        if max_h < 1:
            max_h = 1
        ax.set_ylim(0, max_h + 1)
        ax.set_yticks(range(0, max_h + 2, max(1, (max_h + 1) // 4)))

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
        # Bucket filter changed → back to page 1 of the new result set.
        self._event_page = 1
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
        # Debounce so filtering runs once after the user pauses, not on every
        # keystroke (each render tears down + rebuilds the whole row list).
        self._event_search_var.trace_add("write", lambda *a: self._debounce(
            "_event_search_after_id", 150, self._apply_event_search))
        customtkinter.CTkEntry(
            header,
            placeholder_text="Search rule, IP, description…",
            textvariable=self._event_search_var,
            height=30,
            corner_radius=8,
        ).grid(row=0, column=1, sticky="ew", padx=8)

        self._event_count_label = customtkinter.CTkLabel(
            header,
            text=f"{len(_REMOTE_VULN_EVENTS)} events",
            text_color=text_secondary,
            font=customtkinter.CTkFont(size=11),
        )
        self._event_count_label.grid(row=0, column=2, sticky="e", padx=(8, 0))

    # ----- Event list + detail split -----

    def _build_event_stream(self, parent, row):
        split = customtkinter.CTkFrame(parent, fg_color="transparent")
        split.grid(row=row, column=0, sticky="nsew")
        self._events_split = split
        self._events_split_row = row
        # Below 680px, stack list-over-detail so neither is squeezed to a sliver.
        stacked = self._content_width() < _STACK_BREAKPOINT
        self._events_split_stacked = stacked

        # Left: scrollable list
        list_wrapper = customtkinter.CTkFrame(
            split, corner_radius=12, border_width=1
        )
        list_wrapper.grid_columnconfigure(0, weight=1)
        list_wrapper.grid_rowconfigure(1, weight=1)

        # Right: detail panel
        self._event_detail_frame = customtkinter.CTkFrame(
            split, corner_radius=12, border_width=1
        )
        self._event_detail_frame.grid_columnconfigure(0, weight=1)

        if stacked:
            split.grid_columnconfigure(0, weight=1)
            split.grid_columnconfigure(1, weight=0)
            split.grid_rowconfigure(0, weight=1)
            split.grid_rowconfigure(1, weight=1)
            list_wrapper.grid(row=0, column=0, sticky="nsew", pady=(0, 6))
            self._event_detail_frame.grid(row=1, column=0, sticky="nsew", pady=(6, 0))
        else:
            split.grid_columnconfigure(0, weight=3, uniform="stream")
            split.grid_columnconfigure(1, weight=2, uniform="stream")
            split.grid_rowconfigure(0, weight=1)
            split.grid_rowconfigure(1, weight=0)
            list_wrapper.grid(row=0, column=0, sticky="nsew", padx=(0, 6))
            self._event_detail_frame.grid(row=0, column=1, sticky="nsew", padx=(6, 0))

        self._build_event_list_header(list_wrapper, row=0)

        self._event_list_frame = customtkinter.CTkScrollableFrame(
            list_wrapper, fg_color="transparent"
        )
        self._event_list_frame.grid(row=1, column=0, sticky="nsew", padx=4, pady=(0, 4))
        self._event_list_frame.grid_columnconfigure(0, weight=1)

        # Pager (row 2) — only the current page of rows is rendered so a 250+
        # event list doesn't build hundreds of widgets at once.
        self._event_pagination_frame = customtkinter.CTkFrame(
            list_wrapper, fg_color="transparent"
        )
        self._event_pagination_frame.grid(row=2, column=0, sticky="e", padx=6, pady=(0, 6))

        self._render_event_list("")

    def _bind_events_resize(self):
        """At the 680px breakpoint, rebuild ONLY the list/detail split (flip
        2-up↔stacked) — never the whole pane, so chart selection + search and
        the running events loader are untouched."""
        def on_settled():
            parent = self._events_pane_parent
            if not parent or not parent.winfo_exists():
                return
            split = self._events_split
            try:
                if not split or not split.winfo_exists() or not split.winfo_ismapped():
                    return
            except Exception:
                return
            if (self._content_width() < _STACK_BREAKPOINT) == self._events_split_stacked:
                return
            # Preserve selection + search; only the split frame is recreated.
            prev_id = self._selected_event_id
            query = self._event_search_var.get() if self._event_search_var else ""
            try:
                split.destroy()
            except Exception:
                pass
            self._selected_event_id = prev_id
            self._build_event_stream(parent, row=self._events_split_row)
            # _render_event_list re-anchors selection if prev_id filtered out,
            # highlights the row, and repaints the (freshly rebuilt) detail.
            self._render_event_list(query)

        self._bind_breakpoint_rebuild(
            "_events_resize_after_id", "_events_resize_handler_id", on_settled)

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
        for ev in _REMOTE_VULN_EVENTS:
            # Bucket filter (from clicking a bar in the chart). Chart bars
            # are now 1-hour buckets; floor to the hour and compare against
            # the selected bucket's hour-aligned datetime.
            if sel is not None:
                ts = ev.get("timestamp")
                if not ts:
                    continue
                # Cache the hour-floored datetime on the event dict so repeated
                # renders don't re-parse the ISO string. Event dicts are rebuilt
                # (new objects) when data rebinds, so the cache can't go stale.
                # False marks an unparseable timestamp so we skip the retry.
                floored = ev.get("_ts_floored")
                if floored is None:
                    try:
                        floored = datetime.fromisoformat(
                            ts.replace("Z", "+00:00")
                        ).replace(minute=0, second=0, microsecond=0)
                    except ValueError:
                        floored = False
                    ev["_ts_floored"] = floored
                if floored is False or floored != sel:
                    continue
            # Search-text filter
            if not self._matches_query(q, (
                ev.get("rule_id", ""),
                ev.get("description", ""),
                ev.get("ip", ""),
                (ev.get("severity") or ""),
                " ".join(ev.get("mitre", []) or []),
            )):
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
            total = len(_REMOTE_VULN_EVENTS)
            shown = len(events)
            text = f"{shown} events" if shown == total else f"{shown}/{total} events"
            sel = self._selected_bucket
            if sel is not None:
                end = sel + timedelta(hours=1)
                text += f" · {sel.strftime('%H:%M')}–{end.strftime('%H:%M')}"
            self._event_count_label.configure(text=text)

        # Ensure selection still exists in filtered list; otherwise pick first.
        selected_ids = {ev["id"] for ev in events}
        if events and self._selected_event_id not in selected_ids:
            self._selected_event_id = events[0]["id"]

        # Paginate: render only the current page's rows. Selection + detail
        # still operate on the full filtered set, so the selected event's detail
        # shows even when its row is on another page.
        page_size = self._LIST_PAGE_SIZE
        total_pages = max(1, (len(events) + page_size - 1) // page_size)
        self._event_page = max(1, min(self._event_page, total_pages))
        start = (self._event_page - 1) * page_size
        for r, ev in enumerate(events[start : start + page_size]):
            self._event_row(self._event_list_frame, ev, r)
        self._render_pager(self._event_pagination_frame, self._event_page,
                           total_pages, self._set_event_page)

        # Repaint detail in case selection changed
        if events:
            ev = next((e for e in events if e["id"] == self._selected_event_id), events[0])
            self._render_event_detail(ev)
        else:
            self._render_event_detail(None)

    def _set_event_page(self, page):
        page = max(1, int(page))
        if page == self._event_page:
            return
        self._event_page = page
        self._render_event_list(
            self._event_search_var.get() if self._event_search_var else "")

    def _apply_event_search(self):
        # A new query resets to page 1 so the user sees the top matches.
        self._event_page = 1
        self._render_event_list(
            self._event_search_var.get() if self._event_search_var else "")

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
            self._bind_row_hover(row_frame, hover_bg)

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

        ev = next((e for e in _REMOTE_VULN_EVENTS if e["id"] == event_id), None)
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
        # Per-device CVE fan-out is no longer eager — it fires here so the
        # ~1.5s N-device walk only runs for users who actually open the tab.
        # Same one-shot pattern as Events Phase 2.
        _kick_vulns_loader()

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
        # Re-binds after unbinding any prior handler, so device-dropdown rebuilds
        # don't stack duplicate <Configure> listeners.
        self._bind_vuln_resize()

    def _render_vuln_loading(self, parent):
        self._render_centered_message(parent, "Loading vulnerabilities…")

    def _render_vuln_error(self, parent, err):
        self._render_centered_message(
            parent, "Couldn't load vulnerabilities", detail=err)

    def _schedule_vuln_ready_check(self, parent):
        # 120 ms still feels instant on the loader-thread handoff while waking
        # the Tk main thread far less than the old 20 ms spin.
        poll_ms = 120

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
        self._vuln_page = 1  # new device scope → back to page 1
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
        if device and device != self._VULN_DEVICE_ALL:
            filtered = [v for v in vulns if v.get("agent_name") == device]
        else:
            filtered = vulns
        counts = _bucket_by_severity(filtered)
        self._vuln_severity_cache = (cache_key, counts)
        return counts

    # ----- top-row cards -----

    def _build_vuln_charts_row(self, parent, row):
        wrapper = customtkinter.CTkFrame(parent, fg_color="transparent")
        wrapper.grid(row=row, column=0, sticky="ew", pady=(0, 12))
        self._vuln_charts_wrapper = wrapper
        self._vuln_charts_row = row

        # Below the Dashboard's single-column breakpoint, stack the two chart
        # cards vertically instead of side-by-side. At narrow widths a 2-up row
        # squeezes each chart into an unreadable, crowded sliver; one full-width
        # card each gives the bars/labels room to breathe.
        stacked = self._content_width() < _STACK_BREAKPOINT
        self._vuln_charts_stacked = stacked

        donut = customtkinter.CTkFrame(wrapper, corner_radius=12, border_width=1)
        cvss = customtkinter.CTkFrame(wrapper, corner_radius=12, border_width=1)

        if stacked:
            wrapper.grid_columnconfigure(0, weight=1)
            wrapper.grid_columnconfigure(1, weight=0)
            wrapper.grid_rowconfigure(0, weight=1)
            wrapper.grid_rowconfigure(1, weight=1)
            donut.grid(row=0, column=0, sticky="nsew", pady=(0, 6))
            cvss.grid(row=1, column=0, sticky="nsew", pady=(6, 0))
        else:
            wrapper.grid_columnconfigure(0, weight=1, uniform="vc")
            wrapper.grid_columnconfigure(1, weight=1, uniform="vc")
            wrapper.grid_rowconfigure(0, weight=1)
            wrapper.grid_rowconfigure(1, weight=0)
            donut.grid(row=0, column=0, sticky="nsew", padx=(0, 6))
            cvss.grid(row=0, column=1, sticky="nsew", padx=(6, 0))

        self._build_vuln_donut_card(donut)
        self._build_vuln_cvss_card(cvss)

    def _bind_vuln_resize(self):
        """At the 680px breakpoint, rebuild ONLY the charts row and the table
        split (both flip 2-up↔stacked) — never the whole pane, so the table
        selection + search survive. Both share the same threshold, so one
        settled handler drives both."""
        def on_settled():
            parent = self._vuln_pane_parent
            if not parent or not parent.winfo_exists():
                return
            wrapper = self._vuln_charts_wrapper
            try:
                if not wrapper or not wrapper.winfo_exists() or not wrapper.winfo_ismapped():
                    return
            except Exception:
                return
            stacked = self._content_width() < _STACK_BREAKPOINT
            if stacked != self._vuln_charts_stacked:
                self._rebuild_vuln_charts_row(parent)
            if stacked != self._vuln_table_stacked:
                self._rebuild_vuln_table_split(parent)

        self._bind_breakpoint_rebuild(
            "_vuln_resize_after_id", "_vuln_resize_handler_id", on_settled)

    def _rebuild_vuln_charts_row(self, parent):
        wrapper = self._vuln_charts_wrapper
        row = self._vuln_charts_row
        # Drop the old figures before the wrapper that holds their canvases is
        # destroyed (mirrors _build_vulnerabilities_pane's leak guard).
        for attr in ("_vuln_donut_figure", "_vuln_cvss_figure"):
            fig = getattr(self, attr, None)
            if fig is not None:
                try:
                    fig.clear()
                except Exception:
                    pass
                setattr(self, attr, None)
        try:
            if wrapper:
                wrapper.destroy()
        except Exception:
            pass
        self._vuln_donut_canvas = None
        self._vuln_cvss_canvas = None
        self._vuln_donut_wedges = []
        self._build_vuln_charts_row(parent, row=row)

    def _rebuild_vuln_table_split(self, parent):
        # Preserve the selected CVE + current search across the rebuild — only
        # the split frame is recreated, so the search entry (a sibling row) and
        # its var persist; re-applying the query repaints the filtered list.
        prev_key = self._selected_vuln_key
        query = self._vuln_search_var.get() if self._vuln_search_var else ""
        try:
            if self._vuln_table_split:
                self._vuln_table_split.destroy()
        except Exception:
            pass
        self._selected_vuln_key = prev_key
        self._build_vuln_table(parent, row=self._vuln_table_row)
        self._render_vuln_list(query)
        # _render_vuln_list highlights the preserved row but only repaints the
        # detail panel when nothing was selected; force it for the restored key
        # (the detail frame was just recreated, so it's empty otherwise).
        if self._selected_vuln_key:
            self._render_vuln_detail(
                self._find_vuln_by_key(self._selected_vuln_key))

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
        self._bind_figure_autoresize(canvas, fig)

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

        # Debounce the redraw so a window drag (a storm of <Configure> events)
        # doesn't clear+repaint the ring on every pixel — matches the debounce
        # used by the matplotlib charts and the module-grid aspect handler.
        job = [None]

        def on_configure(_e=None):
            if job[0] is not None:
                try:
                    canvas.after_cancel(job[0])
                except Exception:
                    pass
            job[0] = canvas.after(80, redraw)

        canvas.bind("<Configure>", on_configure)

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
        self._vuln_page = 1  # filter changed → back to page 1
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
        """Group CVEs into 30 daily buckets ending today (UTC) by
        first_detected_at — the immutable first-sighting date. The field is
        not currently populated by the per-device vulnerabilities endpoint
        (it moved to /me/vulnerabilities/{agent_id}/events, not yet wired
        up), so this chart will render empty until that endpoint is
        consumed. Using last-scan detection here would re-bucket every CVE
        on each scan, so the timeline would only ever show the last 30 days
        of scan activity rather than 30 days of NEW CVEs."""
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
            ts = v.get("first_detected_at") or ""
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
            text="FIRST DETECTED — LAST 30 DAYS",
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
        self._bind_figure_autoresize(canvas, fig, use_tight_layout=True)

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
        # Debounce — see _build_event_stream_header. Filter+sort over the full
        # CVE list per keystroke was a typing-lag source.
        self._vuln_search_var.trace_add(
            "write",
            lambda *a: self._debounce(
                "_vuln_search_after_id", 150, self._apply_vuln_search),
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
        # Below 680px, stack list-over-detail so neither is squeezed to a sliver.
        split = customtkinter.CTkFrame(parent, fg_color="transparent")
        split.grid(row=row, column=0, sticky="nsew")
        self._vuln_table_split = split
        self._vuln_table_row = row
        stacked = self._content_width() < _STACK_BREAKPOINT
        self._vuln_table_stacked = stacked

        wrapper = customtkinter.CTkFrame(split, corner_radius=12, border_width=1)
        wrapper.grid_columnconfigure(0, weight=1)
        wrapper.grid_rowconfigure(1, weight=1)

        self._vuln_detail_frame = customtkinter.CTkFrame(
            split, corner_radius=12, border_width=1
        )
        self._vuln_detail_frame.grid_columnconfigure(0, weight=1)

        if stacked:
            split.grid_columnconfigure(0, weight=1)
            split.grid_columnconfigure(1, weight=0)
            split.grid_rowconfigure(0, weight=1)
            split.grid_rowconfigure(1, weight=1)
            wrapper.grid(row=0, column=0, sticky="nsew", pady=(0, 6))
            self._vuln_detail_frame.grid(row=1, column=0, sticky="nsew", pady=(6, 0))
        else:
            split.grid_columnconfigure(0, weight=3, uniform="vstream")
            split.grid_columnconfigure(1, weight=2, uniform="vstream")
            split.grid_rowconfigure(0, weight=1)
            split.grid_rowconfigure(1, weight=0)
            wrapper.grid(row=0, column=0, sticky="nsew", padx=(0, 6))
            self._vuln_detail_frame.grid(row=0, column=1, sticky="nsew", padx=(6, 0))

        self._build_vuln_table_columns(wrapper, row=0)

        self._vuln_list_frame = customtkinter.CTkScrollableFrame(
            wrapper, fg_color="transparent"
        )
        self._vuln_list_frame.grid(row=1, column=0, sticky="nsew", padx=4, pady=(0, 4))
        self._vuln_list_frame.grid_columnconfigure(0, weight=1)

        # Pager (row 2) — render only the current page of CVE rows.
        self._vuln_pagination_frame = customtkinter.CTkFrame(
            wrapper, fg_color="transparent"
        )
        self._vuln_pagination_frame.grid(row=2, column=0, sticky="e", padx=6, pady=(0, 6))

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
        # Memoize the filter+sort: re-running O(n log n) over the full CVE list
        # on every keystroke / refresh tick was a typing-lag source. _REMOTE_VULNS
        # is rebound (new id) when fresh data lands, which invalidates the key.
        key = (id(_REMOTE_VULNS), device_filter, sev_filter, q)
        cache = self._filter_vulns_cache
        if cache is not None and cache[0] == key:
            return cache[1]
        out = []
        for v in _REMOTE_VULNS:
            if device_filter and device_filter != self._VULN_DEVICE_ALL \
                    and v.get("agent_name") != device_filter:
                continue
            if sev_filter and (v.get("severity") or "").lower() != sev_filter:
                continue
            if not self._matches_query(q, (
                v.get("id", ""),
                v.get("package_name", ""),
                v.get("package_version", ""),
                v.get("severity", ""),
                v.get("status", ""),
                v.get("description", ""),
                v.get("agent_name", ""),
            )):
                continue
            out.append(v)
        # Sort by CVSS desc so the worst CVEs surface first.
        out.sort(key=lambda x: float(x.get("cvss_score") or 0.0), reverse=True)
        self._filter_vulns_cache = (key, out)
        return out

    def _refresh_vulns_content(self):
        """In-place data refresh for the Vulnerabilities pane. Rebuilds the
        table rows + detail card from the current _REMOTE_VULNS via
        _render_vuln_list — children of _vuln_list_frame are torn down but
        the frame itself, the scrollable container, the search bar, the
        device dropdown, and the donut + CVSS Figures all stay alive.

        Trade-off: the donut + CVSS charts keep showing whatever severity
        breakdown they last rendered until a full pane rebuild (device
        dropdown change or tab reopen). Acceptable per the redraw-
        minimization brief — only the data-bearing rows + detail card are
        cleared and refilled. A future iteration that wants the charts to
        also reflect fresh data without a full rebuild should factor out
        render-only helpers from _build_vuln_donut_card and
        _build_vuln_cvss_card (mirroring the _render_event_chart pattern)."""
        table_built = (
            self._vuln_list_frame is not None
            and self._vuln_list_frame.winfo_exists()
        )
        if not table_built:
            # The pane is still showing the loading / error placeholder — the
            # table was never built because data wasn't ready or errored on the
            # initial open (e.g. a transient 403). The vuln readiness poll stops
            # once _remote_vulns_ready is set (even on error), so it won't
            # recover on its own. If a refresh has since landed good data, do a
            # FULL rebuild to swap the placeholder for the real table (the
            # in-place row refresh below only works once the table exists).
            if (
                self._vuln_pane_parent is not None
                and self._vuln_pane_parent.winfo_exists()
                and _remote_vulns_ready.is_set()
                and not _REMOTE_VULNS_ERROR
            ):
                self._build_vulnerabilities_pane(self._vuln_pane_parent)
            return
        query = self._vuln_search_var.get() if self._vuln_search_var else ""
        self._render_vuln_list(query)

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

        # Paginate: render only the current page's rows. Selection + detail
        # operate on the full filtered set.
        page_size = self._LIST_PAGE_SIZE
        total_pages = max(1, (len(vulns) + page_size - 1) // page_size)
        self._vuln_page = max(1, min(self._vuln_page, total_pages))
        start = (self._vuln_page - 1) * page_size
        for r, v in enumerate(vulns[start : start + page_size]):
            self._vuln_row(self._vuln_list_frame, v, r)
        self._render_pager(self._vuln_pagination_frame, self._vuln_page,
                           total_pages, self._set_vuln_page)

        if not vulns:
            self._render_vuln_detail(None)
        elif self._selected_vuln_key is None:
            self._select_vuln(self._vuln_key(vulns[0]))

    def _set_vuln_page(self, page):
        page = max(1, int(page))
        if page == self._vuln_page:
            return
        self._vuln_page = page
        self._render_vuln_list(
            self._vuln_search_var.get() if self._vuln_search_var else "")

    def _apply_vuln_search(self):
        # A new query resets to page 1 so the user sees the top matches.
        self._vuln_page = 1
        self._render_vuln_list(
            self._vuln_search_var.get() if self._vuln_search_var else "")

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
            self._bind_row_hover(row_frame, hover_bg)

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
            ("FIRST DETECTED", "first_detected_at"),
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
        self._render_centered_message(parent, "Loading devices…")

    def _schedule_inventory_ready_check(self, parent):
        # 120 ms still feels instant on the loader-thread handoff while waking
        # the Tk main thread far less than the old 20 ms spin.
        poll_ms = 120

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
        """Highest CVE severity in _REMOTE_VULNS for the device whose
        `agent_name` matches `target_name`. Returns None when the device has
        no CVEs — including the legitimate pre-fan-out state where the
        Vulnerabilities tab hasn't been opened yet and _REMOTE_VULNS is
        empty (see _kick_vulns_loader). The Inventory tab's threat indicator
        falls back to events-only severity in that case."""
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
        """Composite threat for one device: max(events, vulns). Returns one of
        critical|high|medium|low|ok."""
        ev_sev = events_by_agent.get(agent_name)
        vuln_sev = self._vulns_threat_for_name(agent_name)
        best_rank = 0
        for sev in (ev_sev, vuln_sev):
            if sev and _THREAT_RANK.get(sev, 0) > best_rank:
                best_rank = _THREAT_RANK[sev]
        return _RANK_TO_SEV.get(best_rank, "ok")

    def _base_agent_row(self, agent):
        """The fields common to every inventory row (device views and count
        views). The view-specific lead field (`threat` / `count`) is added by
        the caller. Group list feeds the group-filter dropdown."""
        bi = agent.get("basic_info") or {}
        return {
            "name": bi.get("name") or "(unknown)",
            # status drives the row's "Active now" label vs. a relative
            # last-seen time (see _inventory_row).
            "status": (bi.get("status") or "").lower(),
            "last_keep": bi.get("lastKeepAlive"),
            "agent_id": bi.get("id") or "—",
            "ip": bi.get("ip") or "—",
            "groups": self._agent_groups(bi),
        }

    def _inventory_rows(self):
        """Build sorted device row data. Returns list of dicts. Memoized: the
        threat lead scans _REMOTE_VULNS per device, so paging/group changes
        shouldn't re-derive it — keyed on the source-data identities."""
        key = (id(_AGENTS), id(_REMOTE_VULN_EVENTS), id(_REMOTE_VULNS))
        cache = self._inventory_rows_cache
        if cache is not None and cache[0] == key:
            return cache[1]
        events_by_agent = self._events_threat_by_agent()
        rows = []
        for agent in _AGENTS:
            row = self._base_agent_row(agent)
            row["threat"] = self._device_threat_level(row["name"], events_by_agent)
            rows.append(row)
        # threat desc, then name asc — stable
        rows.sort(key=lambda r: (-_THREAT_RANK.get(r["threat"], 0), r["name"].lower()))
        self._inventory_rows_cache = (key, rows)
        return rows

    def _inventory_counts_rows(self, field_path):
        """Per-device row data for the count-based views (Processes/Ports/
        Network). `field_path` is a tuple of keys into each agent dict
        leading to a syscollector object that has `affected_items`. Sort:
        count desc, name asc. Devices with no syscollector data show 0.
        Memoized on (agents identity, field_path) so paging doesn't recount."""
        key = (id(_AGENTS), field_path)
        cache = self._inventory_counts_cache
        if cache is not None and cache[0] == key:
            return cache[1]
        rows = []
        for agent in _AGENTS:
            node = agent
            for fkey in field_path:
                if not isinstance(node, dict):
                    node = None
                    break
                node = node.get(fkey)
            items = (node or {}).get("affected_items") if isinstance(node, dict) else None
            row = self._base_agent_row(agent)
            row["count"] = len(items) if isinstance(items, list) else 0
            rows.append(row)
        rows.sort(key=lambda r: (-r["count"], r["name"].lower()))
        self._inventory_counts_cache = (key, rows)
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

    # Page size for the Events + Vulnerabilities tables. Larger than Inventory's
    # since analysts scan more rows at once, but still bounds the widget count
    # so a 250+ row dataset doesn't build hundreds of CTk rows in one render.
    _LIST_PAGE_SIZE = 50

    def _inventory_group_values(self):
        """Distinct group names present in _AGENTS, with "All groups" pinned
        first and "(no group)" appended only if any agent actually lacks a
        group. Result is the dropdown's `values` list."""
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
        self._render_pager(
            self._inventory_pagination_frame, self._inventory_page,
            total_pages, self._set_inventory_page)

    def _render_pager(self, frame, current, total_pages, on_set_page):
        """Right-aligned page navigator shared by the Inventory, Events, and
        Vuln lists. Format: [◀] [prev?] [current] [next?] [▶] — prev shown only
        when current ≥ 2, next only when current < total_pages, arrows disabled
        at the boundaries. Hidden entirely (grid_remove) on a single page so an
        empty CTkFrame doesn't reserve its default height. `on_set_page(p)` is
        invoked with the target page."""
        if frame is None or not frame.winfo_exists():
            return
        for child in frame.winfo_children():
            try:
                child.destroy()
            except Exception:
                pass

        if total_pages <= 1:
            frame.grid_remove()
            return
        frame.grid()

        text_secondary = self._theme("text_secondary", default=_DEFAULT_TEXT_SECONDARY)
        active_bg = self._theme("sidebar_active_bg", default=_DEFAULT_ACTIVE_BG)
        hover_bg = self._hover_bg
        page_font = customtkinter.CTkFont(size=12)
        page_font_bold = customtkinter.CTkFont(size=12, weight="bold")

        def page_btn(text, command, is_current=False, disabled=False):
            kwargs = dict(
                master=frame, text=text, width=30, height=28,
                corner_radius=6, command=command,
            )
            if is_current:
                kwargs.update(
                    fg_color=active_bg, text_color=self._accent_color,
                    hover_color=active_bg, font=page_font_bold,
                )
            else:
                kwargs.update(
                    fg_color="transparent", text_color=text_secondary,
                    hover_color=hover_bg, font=page_font,
                )
            btn = customtkinter.CTkButton(**kwargs)
            if disabled:
                btn.configure(state="disabled")
            return btn

        col = 0
        page_btn("◀", command=lambda: on_set_page(current - 1),
                 disabled=(current <= 1)).grid(row=0, column=col, padx=(0, 4))
        col += 1
        if current >= 2:
            page_btn(str(current - 1),
                     command=lambda p=current - 1: on_set_page(p)).grid(
                row=0, column=col, padx=2)
            col += 1
        page_btn(str(current), command=lambda: None, is_current=True).grid(
            row=0, column=col, padx=2)
        col += 1
        if current < total_pages:
            page_btn(str(current + 1),
                     command=lambda p=current + 1: on_set_page(p)).grid(
                row=0, column=col, padx=2)
            col += 1
        page_btn("▶", command=lambda: on_set_page(current + 1),
                 disabled=(current >= total_pages)).grid(
            row=0, column=col, padx=(4, 0))

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

    def _inventory_common_columns(self, row_frame, dev, fonts, text_secondary):
        """Render the shared DEVICE / LAST SEEN / AGENT ID / IP columns (cols
        1-4) of an inventory row. Col 0 (threat badge or count) is rendered by
        the caller first."""
        # Device name — col 1 (stretches)
        customtkinter.CTkLabel(
            row_frame, text=dev["name"], font=fonts["inter_bold_13"], anchor="w",
        ).grid(row=0, column=1, sticky="w", padx=(0, 12), pady=8)
        # Last seen — col 2. The /me/inventory status field is authoritative for
        # connectivity: an "active"/"connected" agent shows "Active now",
        # otherwise the relative last-scan time.
        is_connected = dev["status"] in ("active", "connected")
        last_seen_text = "Active now" if is_connected else _format_relative(dev["last_keep"])
        customtkinter.CTkLabel(
            row_frame, text=last_seen_text, text_color=text_secondary,
            font=fonts["size_12"], anchor="w",
        ).grid(row=0, column=2, sticky="w", padx=(0, 12), pady=8)
        # Agent ID — col 3
        customtkinter.CTkLabel(
            row_frame, text=str(dev["agent_id"]), text_color=text_secondary,
            font=fonts["size_12"], anchor="w",
        ).grid(row=0, column=3, sticky="w", padx=(0, 12), pady=8)
        # IP — col 4
        customtkinter.CTkLabel(
            row_frame, text=dev["ip"], text_color=text_secondary,
            font=fonts["size_12"], anchor="w",
        ).grid(row=0, column=4, sticky="w", pady=8)

    def _inventory_row(self, parent, dev, row, fonts, divider_color):
        hover_bg = self._hover_bg
        text_secondary = self._theme("text_secondary", default=_DEFAULT_TEXT_SECONDARY)

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

        self._inventory_common_columns(row_frame, dev, fonts, text_secondary)
        self._bind_row_hover(row_frame, hover_bg)

    def _inventory_counts_row(self, parent, dev, row, fonts):
        """Row renderer for Processes/Ports/Network views. Same DEVICE /
        LAST SEEN / IP columns as _inventory_row, but the lead column is
        a bold count instead of a severity badge."""
        hover_bg = self._hover_bg
        text_secondary = self._theme("text_secondary", default=_DEFAULT_TEXT_SECONDARY)

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

        self._inventory_common_columns(row_frame, dev, fonts, text_secondary)
        self._bind_row_hover(row_frame, hover_bg)

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
        # Refresh repaint ticks, button-restore, prebuild chain, and the two
        # search debounces — these fire on the app window and would otherwise
        # run against destroyed widgets after teardown.
        for _aid_attr in (
            "_prebuild_after_id", "_refresh_button_after_id",
            "_event_search_after_id", "_vuln_search_after_id",
        ):
            _aid = getattr(self, _aid_attr, None)
            if _aid:
                try:
                    self.app.after_cancel(_aid)
                except Exception:
                    pass
                setattr(self, _aid_attr, None)
        for _aid in self._refresh_repaint_after_ids:
            try:
                self.app.after_cancel(_aid)
            except Exception:
                pass
        self._refresh_repaint_after_ids = []
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
        if self._vuln_resize_after_id:
            try:
                self.app.after_cancel(self._vuln_resize_after_id)
            except Exception:
                pass
            self._vuln_resize_after_id = None
        if self._vuln_resize_handler_id:
            try:
                self.app.unbind("<Configure>", self._vuln_resize_handler_id)
            except Exception:
                pass
            self._vuln_resize_handler_id = None
        if self._events_resize_after_id:
            try:
                self.app.after_cancel(self._events_resize_after_id)
            except Exception:
                pass
            self._events_resize_after_id = None
        if self._events_resize_handler_id:
            try:
                self.app.unbind("<Configure>", self._events_resize_handler_id)
            except Exception:
                pass
            self._events_resize_handler_id = None
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
