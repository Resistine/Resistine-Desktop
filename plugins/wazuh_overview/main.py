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
import tkinter as tk
from datetime import datetime, timedelta, timezone

import customtkinter
from customtkinter import ThemeManager

from plugins.base_plugin import BasePlugin
from utils.logger import logger

# matplotlib is imported lazily via _ensure_matplotlib() — see below. Pulling it
# at module load adds ~200–500 ms to plugin discovery on the first run of the
# app; deferring it means the Vulnerabilities/Events charts only pay that cost
# the first time they're built.
_Figure = None
_FigureCanvasTkAgg = None


def _ensure_matplotlib():
    global _Figure, _FigureCanvasTkAgg
    if _Figure is None:
        import matplotlib
        matplotlib.use("TkAgg")
        from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg as _FCA
        from matplotlib.figure import Figure as _F
        _Figure, _FigureCanvasTkAgg = _F, _FCA
    return _Figure, _FigureCanvasTkAgg

_PLUGIN_DIR = os.path.dirname(os.path.realpath(__file__))
_WAZUH_DIR = os.path.join(os.path.dirname(_PLUGIN_DIR), "wazuh")
_DATA_FILE = os.path.join(_PLUGIN_DIR, "data", "agent.013.json")
_EVENTS_FILE = os.path.join(_PLUGIN_DIR, "data", "log_events.json")
_VULNS_FILE = os.path.join(_PLUGIN_DIR, "data", "vulnerabilities.json")

_TAB_NAMES = ("Overview", "Events", "Vulnerabilities")
_LEGEND_KEYS = ("critical", "error", "warning", "info")
_SEVERITY_LEVELS = ("critical", "high", "medium", "low")
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
        # Vulnerabilities pane state
        self._vuln_search_var = None
        self._vuln_count_label = None
        self._vuln_list_frame = None
        self._vuln_donut_figure = None
        self._vuln_donut_canvas = None
        self._vuln_cvss_figure = None
        self._vuln_cvss_canvas = None

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

        self._build_top_device_widget(parent, row=0)
        self._build_alert_bar(parent, row=1)
        self._build_modules_header(parent, row=2)
        self._build_module_grid(parent, row=3)

    # ----- section 1: top device widget --------------------------------------

    def _build_top_device_widget(self, parent, row):
        text_secondary = self._theme("text_secondary", default=["#6B7280", "#9CA3AF"])
        divider_color = self._theme("divider_color", default=["#E5E7EB", "#2A2A2A"])

        bi = _get_agent_data().get("basic_info", {}) or {}
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

        is_connected = (bi.get("status") or "").lower() == "connected"
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

        card = customtkinter.CTkFrame(parent, corner_radius=12, border_width=1)
        card.grid(row=row, column=0, sticky="ew", pady=(0, 12))
        card.grid_columnconfigure(0, weight=1)

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

    # ----- section 2: alert bar ----------------------------------------------

    def _build_alert_bar(self, parent, row):
        warn_bg = self._theme("protection_bg_warn", default=["#FEF3C7", "#2D1F05"])
        warn_text = self._theme("protection_text_warn", default=["#B45309", "#FBBF24"])
        ok_bg = self._theme("protection_bg_ok", default=["#DCFCE7", "#0A2F1A"])
        ok_text = self._theme("protection_text_ok", default=["#15803D", "#4ADE80"])
        # Reconnect-button colors come from the "error" theme key (red), not the
        # severity scheme. Buttons should never inherit severity colors —
        # Reconnect is an error-fix action, not a "critical-severity" indicator.
        err_bg = self._theme("status_badge_bg", "error", default=["#FEE2E2", "#7F1D1D"])
        err_text = self._theme("status_badge_text", "error", default=["#DC2626", "#F87171"])

        bi = _get_agent_data().get("basic_info", {}) or {}
        is_connected = (bi.get("status") or "").lower() == "connected"
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

        customtkinter.CTkLabel(
            bar,
            text=f"{icon}  {msg}",
            text_color=txt,
            font=customtkinter.CTkFont(size=12),
            anchor="w",
            justify="left",
            wraplength=720,
        ).grid(row=0, column=0, sticky="w", padx=(14, 12), pady=10)

        legend = customtkinter.CTkFrame(bar, fg_color="transparent")
        legend.grid(row=0, column=1, sticky="e", padx=(0, 12))
        for i, key in enumerate(_LEGEND_KEYS):
            color = self._segment_color(key)
            customtkinter.CTkLabel(
                legend,
                text=f"●  {key.capitalize()}",
                text_color=color,
                font=customtkinter.CTkFont(size=11, weight="bold"),
            ).grid(row=0, column=i, sticky="w", padx=(0, 10))

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
        """Compute module-card data from the loaded agent JSON."""
        cards = []
        bi = _get_agent_data().get("basic_info", {}) or {}

        # Security Alerts — no source in sample JSON
        cards.append({
            "title": "Security Alerts",
            "status": "INFO",
            "description": "Threats and security incidents detected",
            "stats": (("No data available", "muted"),),
            "target_tab": "Events",
        })

        # Vulnerabilities — vulnerabilities object is empty
        vulns = _get_agent_data().get("vulnerabilities") or {}
        if vulns:
            cards.append({
                "title": "Vulnerabilities",
                "status": "WARNING",
                "description": "CVEs across installed packages",
                "stats": ((str(len(vulns)) + " items", "warning"),),
                "target_tab": "Vulnerabilities",
            })
        else:
            cards.append({
                "title": "Vulnerabilities",
                "status": "INFO",
                "description": "CVEs across installed packages",
                "stats": (("No scan results", "muted"),),
                "target_tab": "Vulnerabilities",
            })

        # Compliance · SCA
        sca_items = (_get_agent_data().get("sca", {}) or {}).get("affected_items") or []
        if sca_items:
            sca = sca_items[0]
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
            cards.append({
                "title": "Compliance · SCA",
                "status": sca_status,
                "description": desc,
                "stats": tuple(stats),
            })
        else:
            cards.append({
                "title": "Compliance · SCA",
                "status": "INFO",
                "description": "OS signature checks and benchmarks",
                "stats": (("No scan results", "muted"),),
            })

        # File Integrity — syscheck is empty in the sample
        syscheck = _get_agent_data().get("syscheck") or {}
        if syscheck:
            cards.append({
                "title": "File Integrity",
                "status": "INFO",
                "description": "Created · added/modified · deleted",
                "stats": ((f"{len(syscheck)} entries", "muted"),),
            })
        else:
            cards.append({
                "title": "File Integrity",
                "status": "INFO",
                "description": "Created · added/modified · deleted",
                "stats": (("No data available", "muted"),),
            })

        # Rootcheck
        rc = _get_agent_data().get("rootcheck") or {}
        rc_items = rc.get("affected_items") or []
        rc_total = int(rc.get("total_affected_items") or len(rc_items))
        if rc_total:
            solved = sum(1 for r in rc_items if (r.get("status") or "").lower() == "solved")
            unsolved = rc_total - solved
            if unsolved == 0:
                rc_status = "OK"
                noun = "finding" if rc_total == 1 else "findings"
                rc_stats = ((f"{rc_total} {noun} · all solved", "ok"),)
            else:
                rc_status = "WARNING" if unsolved <= 3 else "CRITICAL"
                rc_stats = (
                    (f"{unsolved} open", "warning"),
                    ("  ·  ", "muted"),
                    (f"{solved} solved", "muted"),
                )
            cards.append({
                "title": "Rootcheck",
                "status": rc_status,
                "description": "Recent rootkit / process detection",
                "stats": rc_stats,
            })
        else:
            cards.append({
                "title": "Rootcheck",
                "status": "INFO",
                "description": "Recent rootkit / process detection",
                "stats": (("No findings", "muted"),),
            })

        # MITRE ATT&CK — no source in sample JSON
        cards.append({
            "title": "MITRE ATT&CK",
            "status": "INFO",
            "description": "Tactics observed in triggered rules",
            "stats": (("No data available", "muted"),),
        })

        # Inventory · Syscollector
        sc = _get_agent_data().get("syscollector", {}) or {}
        pkgs = int((sc.get("packages") or {}).get("total_affected_items") or 0)
        procs = int((sc.get("processes") or {}).get("total_affected_items") or 0)
        ports = int(((sc.get("network") or {}).get("ports") or {}).get("total_affected_items") or 0)
        ifaces = int(((sc.get("network") or {}).get("interfaces") or {}).get("total_affected_items") or 0)
        inv_segments = []
        for label, n in (
            ("packages", pkgs),
            ("processes", procs),
            ("ports", ports),
            ("interfaces", ifaces),
        ):
            if n:
                if inv_segments:
                    inv_segments.append(("  ·  ", "muted"))
                inv_segments.append((f"{n} {label}", "muted"))
        if not inv_segments:
            inv_segments = [("No data available", "muted")]
        cards.append({
            "title": "Inventory · Syscollector",
            "status": "INFO",
            "description": "Hardware, packages, ports, services",
            "stats": tuple(inv_segments),
        })

        # Agent Health
        is_connected = (bi.get("status") or "").lower() == "connected"
        if is_connected:
            cards.append({
                "title": "Agent Health",
                "status": "OK",
                "description": "Connectivity & configuration",
                "stats": (
                    (f"Connected · keep-alive {_format_relative(bi.get('lastKeepAlive'))}", "ok"),
                ),
            })
        else:
            cards.append({
                "title": "Agent Health",
                "status": "ERROR",
                "description": "Connectivity & configuration",
                "stats": (
                    (f"Disconnected · {_format_relative(bi.get('disconnection_time'))}", "error"),
                ),
            })

        # Manager
        manager = bi.get("manager") or ""
        node = bi.get("node_name") or ""
        config_synced = (bi.get("group_config_status") or "").lower() == "synced"
        mgr_segments = []
        if manager:
            mgr_segments.append((manager, "muted"))
        if node:
            if mgr_segments:
                mgr_segments.append(("  ·  ", "muted"))
            mgr_segments.append((node, "muted"))
        if config_synced:
            if mgr_segments:
                mgr_segments.append(("  ·  ", "muted"))
            mgr_segments.append(("synced", "ok"))
        if not mgr_segments:
            mgr_segments = [("No data available", "muted")]
        cards.append({
            "title": "Manager",
            "status": "OK" if config_synced else "INFO",
            "description": "Wazuh cluster reachable by node",
            "stats": tuple(mgr_segments),
        })

        return cards

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

    def _make_module_card(self, parent, row, column, card_data):
        text_secondary = self._theme("text_secondary", default=["#6B7280", "#9CA3AF"])
        target_tab = card_data.get("target_tab")

        card = customtkinter.CTkFrame(parent, corner_radius=12, border_width=1)
        card.grid(row=row, column=column, sticky="nsew", padx=6, pady=6)
        card.grid_columnconfigure(0, weight=1)
        card.grid_columnconfigure(1, weight=0)
        card.grid_rowconfigure(2, weight=1)

        title = customtkinter.CTkLabel(
            card,
            text=card_data["title"],
            font=customtkinter.CTkFont(family="Inter", size=14, weight="bold"),
            anchor="w",
        )
        title.grid(row=0, column=0, sticky="w", padx=14, pady=(12, 0))

        bg, fg = self._badge_colors(card_data["status"])
        badge = customtkinter.CTkLabel(
            card,
            text=f"  ●  {card_data['status']}  ",
            fg_color=bg,
            text_color=fg,
            corner_radius=6,
            font=customtkinter.CTkFont(size=10, weight="bold"),
        )
        badge.grid(row=0, column=1, sticky="ne", padx=(0, 14), pady=(12, 0))

        desc = customtkinter.CTkLabel(
            card,
            text=card_data["description"],
            text_color=text_secondary,
            font=customtkinter.CTkFont(size=11),
            anchor="w",
        )
        desc.grid(row=1, column=0, columnspan=2, sticky="w", padx=14, pady=(2, 8))

        stats = customtkinter.CTkFrame(card, fg_color="transparent")
        stats.grid(row=2, column=0, sticky="sw", padx=14, pady=(0, 12))
        stat_labels = []
        for i, (text, color_key) in enumerate(card_data["stats"]):
            color = self._segment_color(color_key)
            weight = "bold" if color_key not in ("muted",) else "normal"
            lbl = customtkinter.CTkLabel(
                stats,
                text=text,
                text_color=color,
                font=customtkinter.CTkFont(size=12, weight=weight),
            )
            lbl.grid(row=0, column=i, sticky="w")
            stat_labels.append(lbl)

        arrow = customtkinter.CTkLabel(
            card,
            text="›",
            text_color=text_secondary,
            font=customtkinter.CTkFont(size=18),
        )
        arrow.grid(row=2, column=1, sticky="se", padx=(0, 14), pady=(0, 12))

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
            text="EVENT STREAM",
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

    def _build_vulnerabilities_pane(self, parent):
        parent.grid_columnconfigure(0, weight=1)
        parent.grid_rowconfigure(0, weight=0)  # charts row
        parent.grid_rowconfigure(1, weight=0)  # table header
        parent.grid_rowconfigure(2, weight=1)  # table list

        self._build_vuln_charts_row(parent, row=0)
        self._build_vuln_table_header(parent, row=1)
        self._build_vuln_table(parent, row=2)

    def _vuln_severity_counts(self):
        vulns = _get_vulns()
        vulns_id = id(vulns)
        cache = self._vuln_severity_cache
        if cache is not None and cache[0] == vulns_id:
            return cache[1]
        counts = {lvl: 0 for lvl in _SEVERITY_LEVELS}
        for v in vulns:
            sev = (v.get("severity") or "").lower()
            if sev in counts:
                counts[sev] += 1
        self._vuln_severity_cache = (vulns_id, counts)
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
        Figure, FigureCanvasTkAgg = _ensure_matplotlib()
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

        # matplotlib donut on the left
        fig = Figure(figsize=(2.6, 2.2), dpi=100, facecolor=card_bg)
        self._vuln_donut_figure = fig
        ax = fig.add_subplot(111)
        ax.set_facecolor(card_bg)

        sizes = [counts[lvl] for lvl in _SEVERITY_LEVELS]
        colors = [
            self._resolve_severity_color(lvl, chart_theme["is_dark"])
            for lvl in _SEVERITY_LEVELS
        ]
        if total > 0:
            ax.pie(
                sizes,
                colors=colors,
                startangle=90,
                counterclock=False,
                wedgeprops={"width": 0.32, "edgecolor": card_bg},
            )
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
        else:
            ax.text(
                0,
                0,
                "No CVEs",
                ha="center",
                va="center",
                color=chart_theme["text"],
                fontsize=11,
            )
        ax.set_aspect("equal")

        canvas = FigureCanvasTkAgg(fig, master=card)
        widget = canvas.get_tk_widget()
        widget.configure(highlightthickness=0, bd=0, bg=card_bg)
        widget.grid(row=1, column=0, sticky="nsew", padx=(8, 4), pady=(0, 10))
        self._vuln_donut_canvas = canvas
        canvas.draw_idle()

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

    def _bucket_vulns_daily(self):
        """Group CVEs into 30 daily buckets ending today (UTC) by detection_date."""
        today = datetime.now(timezone.utc).date()
        vulns = _get_vulns()
        # Cache keyed on (vulns identity, today) so a day-boundary crossing
        # during a long-lived app session naturally invalidates the buckets.
        cache_key = (id(vulns), today)
        cache = self._bucket_vulns_cache
        if cache is not None and cache[0] == cache_key:
            return cache[1]
        buckets = [today - timedelta(days=29 - i) for i in range(30)]
        counts = {b: {lvl: 0 for lvl in _SEVERITY_LEVELS} for b in buckets}
        for v in vulns:
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
            text=f"{len(_get_vulns())} vulnerabilities",
            text_color=text_secondary,
            font=customtkinter.CTkFont(size=11),
        )
        self._vuln_count_label.grid(row=0, column=2, sticky="e", padx=(8, 0))

    # ----- table -----

    def _build_vuln_table(self, parent, row):
        wrapper = customtkinter.CTkFrame(parent, corner_radius=12, border_width=1)
        wrapper.grid(row=row, column=0, sticky="nsew")
        wrapper.grid_columnconfigure(0, weight=1)
        wrapper.grid_rowconfigure(1, weight=1)

        self._build_vuln_table_columns(wrapper, row=0)

        self._vuln_list_frame = customtkinter.CTkScrollableFrame(
            wrapper, fg_color="transparent"
        )
        self._vuln_list_frame.grid(row=1, column=0, sticky="nsew", padx=4, pady=(0, 4))
        self._vuln_list_frame.grid_columnconfigure(0, weight=1)

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
        labels = ("SEV", "CVE", "AFFECTED PACKAGE", "CVSS", "STATUS", "EPSS")
        for col, label in enumerate(labels):
            # SEV column rows render a badge with "  HIGH  " interior padding,
            # so nudge the SEV header right to land on the badge's visible text.
            left_pad = 8 if col == 0 else 0
            right_pad = 12 if col < 5 else 0
            customtkinter.CTkLabel(
                head, text=label, text_color=text_secondary, font=small_bold
            ).grid(row=0, column=col, sticky="w", padx=(left_pad, right_pad))

    @staticmethod
    def _configure_vuln_row_grid(frame):
        frame.grid_columnconfigure(0, weight=0, minsize=70)   # severity badge
        frame.grid_columnconfigure(1, weight=0, minsize=180)  # CVE id + modified
        frame.grid_columnconfigure(2, weight=1, minsize=200)  # package
        frame.grid_columnconfigure(3, weight=0, minsize=70)   # cvss
        frame.grid_columnconfigure(4, weight=0, minsize=100)  # status
        frame.grid_columnconfigure(5, weight=0, minsize=70)   # epss

    def _filter_vulns(self, query):
        q = (query or "").lower().strip()
        out = []
        for v in _get_vulns():
            if q:
                haystack = " ".join((
                    str(v.get("id", "")),
                    str(v.get("package_name", "")),
                    str(v.get("package_version", "")),
                    str(v.get("severity", "")),
                    str(v.get("status", "")),
                    str(v.get("description", "")),
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

        vulns = self._filter_vulns(query)
        if self._vuln_count_label:
            total = len(_get_vulns())
            shown = len(vulns)
            text = (
                f"{shown} vulnerabilities"
                if shown == total
                else f"{shown}/{total} vulnerabilities"
            )
            self._vuln_count_label.configure(text=text)

        for r, v in enumerate(vulns):
            self._vuln_row(self._vuln_list_frame, v, r)

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

    def _vuln_row(self, parent, vuln, row):
        fonts = self._ensure_fonts()
        text_secondary = self._theme(
            "text_secondary", default=["#6B7280", "#9CA3AF"]
        )
        hover_bg = self._theme(
            "sidebar_hover_bg", default=["#F0F0F5", "#1F1F22"]
        )

        sev = (vuln.get("severity") or "").lower()
        sev_bg, sev_fg = self._severity_palette(sev)
        sev_label = _SEVERITY_SHORT.get(sev, sev.upper() or "—")

        row_frame = customtkinter.CTkFrame(parent, fg_color="transparent", corner_radius=8)
        row_frame.grid(row=row, column=0, sticky="ew", padx=2, pady=1)
        self._configure_vuln_row_grid(row_frame)

        # SEV badge
        customtkinter.CTkLabel(
            row_frame,
            text=f"  {sev_label}  ",
            fg_color=sev_bg,
            text_color=sev_fg,
            corner_radius=6,
            font=fonts["bold_10"],
        ).grid(row=0, column=0, sticky="w", padx=(0, 12), pady=8)

        # CVE id + modified date
        cve_cell = customtkinter.CTkFrame(row_frame, fg_color="transparent")
        cve_cell.grid(row=0, column=1, sticky="w", padx=(0, 12), pady=4)
        cve_cell.grid_columnconfigure(0, weight=1)
        customtkinter.CTkLabel(
            cve_cell,
            text=vuln.get("id", "—"),
            font=fonts["inter_bold_12"],
            anchor="w",
        ).grid(row=0, column=0, sticky="w")
        modified = _format_relative(vuln.get("modified_date"))
        customtkinter.CTkLabel(
            cve_cell,
            text=f"modified {modified}",
            text_color=text_secondary,
            font=fonts["size_10"],
            anchor="w",
        ).grid(row=1, column=0, sticky="w")

        # Affected package + version
        pkg_cell = customtkinter.CTkFrame(row_frame, fg_color="transparent")
        pkg_cell.grid(row=0, column=2, sticky="w", padx=(0, 12), pady=4)
        pkg_cell.grid_columnconfigure(0, weight=1)
        customtkinter.CTkLabel(
            pkg_cell,
            text=vuln.get("package_name", "—"),
            font=fonts["inter_bold_12"],
            anchor="w",
        ).grid(row=0, column=0, sticky="w")
        customtkinter.CTkLabel(
            pkg_cell,
            text=str(vuln.get("package_version", "")),
            text_color=text_secondary,
            font=fonts["size_10"],
            anchor="w",
        ).grid(row=1, column=0, sticky="w")

        # CVSS
        try:
            cvss_text = f"{float(vuln.get('cvss_score') or 0.0):.1f}"
        except (TypeError, ValueError):
            cvss_text = "—"
        customtkinter.CTkLabel(
            row_frame,
            text=cvss_text,
            text_color=sev_fg,
            font=fonts["inter_bold_14"],
        ).grid(row=0, column=3, sticky="w", padx=(0, 12), pady=8)

        # Status badge — alias unknown values to a sensible theme key so the
        # color is never the muted fallback.
        status = (vuln.get("status") or "").lower()
        status_key = _VULN_STATUS_BADGE.get(status, status or "info")
        st_bg = self._theme(
            "status_badge_bg", status_key, default=["#F3F4F6", "#1F2937"]
        )
        st_fg = self._theme(
            "status_badge_text", status_key, default=["#6B7280", "#9CA3AF"]
        )
        customtkinter.CTkLabel(
            row_frame,
            text=f"  {(status or '—').capitalize()}  ",
            fg_color=st_bg,
            text_color=st_fg,
            corner_radius=6,
            font=fonts["bold_10"],
        ).grid(row=0, column=4, sticky="w", padx=(0, 12), pady=8)

        # EPSS
        epss = vuln.get("epss")
        epss_color_key = self._epss_color_key(epss)
        if epss_color_key == "muted":
            epss_color = text_secondary
        else:
            _, epss_color = self._severity_palette(
                "high" if epss_color_key == "high" else "medium"
            )
        try:
            epss_text = f"{float(epss) * 100:.0f}%"
        except (TypeError, ValueError):
            epss_text = "—"
        customtkinter.CTkLabel(
            row_frame,
            text=epss_text,
            text_color=epss_color,
            font=fonts["inter_bold_13"],
        ).grid(row=0, column=5, sticky="w", pady=8)

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
                import matplotlib.pyplot as _plt
                _plt.close(self._event_chart_figure)
            except Exception:
                pass
            self._event_chart_figure = None
            self._event_chart_canvas = None
        for attr in ("_vuln_donut_figure", "_vuln_cvss_figure"):
            fig = getattr(self, attr, None)
            if fig is not None:
                try:
                    import matplotlib.pyplot as _plt
                    _plt.close(fig)
                except Exception:
                    pass
                setattr(self, attr, None)
        self._vuln_donut_canvas = None
        self._vuln_cvss_canvas = None
        super().destroy()
