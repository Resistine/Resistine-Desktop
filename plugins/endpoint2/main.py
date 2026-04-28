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
from datetime import datetime, timezone

import customtkinter
from customtkinter import ThemeManager

from plugins.base_plugin import BasePlugin
from utils.logger import logger

_PLUGIN_DIR = os.path.dirname(os.path.realpath(__file__))
_WAZUH_DIR = os.path.join(os.path.dirname(_PLUGIN_DIR), "wazuh")
_DATA_FILE = os.path.join(_PLUGIN_DIR, "data", "agent.013.json")

_TAB_NAMES = ("Overview", "Events", "Vulnerabilities")
_LEGEND_KEYS = ("critical", "error", "warning", "info")


def _load_agent_data():
    try:
        with open(_DATA_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        logger.error(f"Endpoint 2: failed to load sample data ({_DATA_FILE}): {e}")
        return {}


_AGENT_DATA = _load_agent_data()


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


def _short_benchmark_name(name):
    """Tidy a CIS-style policy name like CIS_Apple_macOS_15.0_Sequoia_Benchmark_v1.0.0."""
    if not name:
        return ""
    cleaned = name.replace("_", " ").replace("Apple ", "")
    return cleaned


class Plugin(BasePlugin):
    """Endpoint 2 plugin — second sidebar entry, redesigned-architecture skeleton."""

    def __init__(self, app):
        super().__init__(
            id="013",
            version="2026.01.04-alpha",
            order=5.5,
            name="Endpoint 2",
            status=None,
            description="Placeholder for the redesigned endpoint page.",
            supported_systems=["Darwin", "Linux", "Windows"],
            translations={"US": "Endpoint 2", "ES": "Endpoint 2", "FR": "Endpoint 2"},
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

    def check_status(self):
        return None

    # ----- screen scaffold ---------------------------------------------------

    def create_main_screen(self):
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

        self._build_tab_strip()
        self._build_content_area()
        self._switch_tab("Overview")

        return self.main_container

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
            pane = customtkinter.CTkFrame(self._tab_content_holder, fg_color="transparent")
            pane.grid_columnconfigure(0, weight=1)
            pane.grid_rowconfigure(0, weight=1)
            self._tab_panes[name] = pane

        self._build_overview_pane(self._tab_panes["Overview"])

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
        self._tab_panes[name].grid(row=0, column=0, sticky="nsew")

        new_btn = self._tab_buttons[name]
        new_btn.configure(
            text_color=self._accent_color,
            font=customtkinter.CTkFont(size=14, weight="bold"),
        )
        col = _TAB_NAMES.index(name)
        self._tab_underline.grid(row=1, column=col, sticky="ew", padx=(0, 24), pady=(0, 0))

    def _on_tab_click(self, name):
        if self._active_tab == name:
            return
        self._switch_tab(name)
        if hasattr(self.app, "record_page_state"):
            self.app.record_page_state(name)

    def apply_state(self, state):
        target = state if state in _TAB_NAMES else "Overview"
        self._switch_tab(target)

    # ----- theme helpers -----------------------------------------------------

    def _theme(self, *keys, default=None):
        node = ThemeManager.theme.get("Theme", {})
        for k in keys:
            if not isinstance(node, dict):
                return default
            node = node.get(k)
            if node is None:
                return default
        return node

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
        parent.grid_columnconfigure(0, weight=1)
        parent.grid_rowconfigure(0, weight=0)
        parent.grid_rowconfigure(1, weight=0)
        parent.grid_rowconfigure(2, weight=0)
        parent.grid_rowconfigure(3, weight=1)

        self._build_top_device_widget(parent, row=0)
        self._build_alert_bar(parent, row=1)
        self._build_modules_header(parent, row=2)
        self._build_module_grid(parent, row=3)

    # ----- section 1: top device widget --------------------------------------

    def _build_top_device_widget(self, parent, row):
        text_secondary = self._theme("text_secondary", default=["#6B7280", "#9CA3AF"])
        divider_color = self._theme("divider_color", default=["#E5E7EB", "#2A2A2A"])

        bi = _AGENT_DATA.get("basic_info", {}) or {}
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
        critical_bg = self._theme("status_badge_bg", "critical", default=["#FEE2E2", "#7F1D1D"])
        critical_text = self._theme("status_badge_text", "critical", default=["#991B1B", "#F87171"])

        bi = _AGENT_DATA.get("basic_info", {}) or {}
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
                fg_color=critical_text,
                hover_color=critical_bg,
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
        bi = _AGENT_DATA.get("basic_info", {}) or {}

        # Security Alerts — no source in sample JSON
        cards.append({
            "title": "Security Alerts",
            "status": "INFO",
            "description": "Threats and security incidents detected",
            "stats": (("No data available", "muted"),),
        })

        # Vulnerabilities — vulnerabilities object is empty
        vulns = _AGENT_DATA.get("vulnerabilities") or {}
        if vulns:
            cards.append({
                "title": "Vulnerabilities",
                "status": "WARNING",
                "description": "CVEs across installed packages",
                "stats": ((str(len(vulns)) + " items", "warning"),),
            })
        else:
            cards.append({
                "title": "Vulnerabilities",
                "status": "INFO",
                "description": "CVEs across installed packages",
                "stats": (("No scan results", "muted"),),
            })

        # Compliance · SCA
        sca_items = (_AGENT_DATA.get("sca", {}) or {}).get("affected_items") or []
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
        syscheck = _AGENT_DATA.get("syscheck") or {}
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
        rc = _AGENT_DATA.get("rootcheck") or {}
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
        sc = _AGENT_DATA.get("syscollector", {}) or {}
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

        card = customtkinter.CTkFrame(parent, corner_radius=12, border_width=1)
        card.grid(row=row, column=column, sticky="nsew", padx=6, pady=6)
        card.grid_columnconfigure(0, weight=1)
        card.grid_columnconfigure(1, weight=0)
        card.grid_rowconfigure(2, weight=1)

        customtkinter.CTkLabel(
            card,
            text=card_data["title"],
            font=customtkinter.CTkFont(family="Inter", size=14, weight="bold"),
            anchor="w",
        ).grid(row=0, column=0, sticky="w", padx=14, pady=(12, 0))

        bg, fg = self._badge_colors(card_data["status"])
        customtkinter.CTkLabel(
            card,
            text=f"  ●  {card_data['status']}  ",
            fg_color=bg,
            text_color=fg,
            corner_radius=6,
            font=customtkinter.CTkFont(size=10, weight="bold"),
        ).grid(row=0, column=1, sticky="ne", padx=(0, 14), pady=(12, 0))

        customtkinter.CTkLabel(
            card,
            text=card_data["description"],
            text_color=text_secondary,
            font=customtkinter.CTkFont(size=11),
            anchor="w",
        ).grid(row=1, column=0, columnspan=2, sticky="w", padx=14, pady=(2, 8))

        stats = customtkinter.CTkFrame(card, fg_color="transparent")
        stats.grid(row=2, column=0, sticky="sw", padx=14, pady=(0, 12))
        for i, (text, color_key) in enumerate(card_data["stats"]):
            color = self._segment_color(color_key)
            weight = "bold" if color_key not in ("muted",) else "normal"
            customtkinter.CTkLabel(
                stats,
                text=text,
                text_color=color,
                font=customtkinter.CTkFont(size=12, weight=weight),
            ).grid(row=0, column=i, sticky="w")

        customtkinter.CTkLabel(
            card,
            text="›",
            text_color=text_secondary,
            font=customtkinter.CTkFont(size=18),
        ).grid(row=2, column=1, sticky="se", padx=(0, 14), pady=(0, 12))

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

    def destroy(self):
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
        super().destroy()
