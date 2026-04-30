"""Events tab for the Wazuh plugin.

Renders severity summary pills, a 30-minute stacked bar chart of event
volume, and an event-stream list + selected-event detail. The chart bars
are click-toggle filters that scope the list to a 30-minute bucket.

Author: Resistine Team
Copyright (c) Resistine 2025
Licensed under the GNU General Public License v2 or later
"""

import json
import os
import tkinter as tk
from datetime import datetime, timedelta

import customtkinter

import matplotlib
matplotlib.use("TkAgg")
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
from matplotlib.figure import Figure

from utils.logger import logger

from plugins.endpoint2._helpers import (
    LEGEND_KEYS,
    format_relative,
    format_timestamp,
)

_PLUGIN_DIR = os.path.dirname(os.path.realpath(__file__))
_EVENTS_FILE = os.path.join(_PLUGIN_DIR, "data", "events.json")

_SEVERITY_LEVELS = ("critical", "high", "medium", "low")
# Severity name → status_badge_* theme key.
_SEVERITY_THEME_KEY = {
    "critical": "critical",
    "high": "high",
    "medium": "warning",
    "low": "ok",
}


def _load_events_data():
    try:
        with open(_EVENTS_FILE, "r", encoding="utf-8") as f:
            payload = json.load(f)
        events = payload.get("events", []) if isinstance(payload, dict) else []
        # Sort newest first by timestamp; events without a timestamp sort to the end.
        events.sort(
            key=lambda e: e.get("timestamp") or "",
            reverse=True,
        )
        return events
    except Exception as e:
        logger.error(f"Wazuh plugin: failed to load events sample ({_EVENTS_FILE}): {e}")
        return []


_EVENTS = _load_events_data()


class EventsTabMixin:
    """Mixin providing the Events-tab UI for the Wazuh plugin.

    Expects the host class to provide:
      - self.app
      - self._hover_bg
      - self._theme(*keys, default=...)
    """

    # ----- state init -----

    def _init_events_state(self):
        """Initialize Events-pane instance state. Called from Plugin.__init__."""
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

    # ----- pane orchestration -----

    def _build_events_pane(self, parent):
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

    # ----- severity helpers -----

    def _severity_palette(self, level):
        """Return (bg, text) tuple for a severity level, theme-resolved."""
        key = _SEVERITY_THEME_KEY.get(level, "info")
        bg = self._theme("status_badge_bg", key, default=["#F3F4F6", "#1F2937"])
        fg = self._theme("status_badge_text", key, default=["#6B7280", "#9CA3AF"])
        return bg, fg

    def _severity_counts(self):
        counts = {lvl: 0 for lvl in _SEVERITY_LEVELS}
        for ev in _EVENTS:
            sev = (ev.get("severity") or "").lower()
            if sev in counts:
                counts[sev] += 1
        return counts

    # ----- severity pills row -----

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
        if not _EVENTS:
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

    def _resolve_severity_color(self, level, is_dark):
        # Pull text color (more saturated than the badge bg) for the bar fill.
        key = _SEVERITY_THEME_KEY.get(level, "info")
        pair = self._theme("status_badge_text", key, default=["#6B7280", "#9CA3AF"])
        return pair[1] if is_dark else pair[0]

    def _build_event_chart(self, parent, row):
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
            font=customtkinter.CTkFont(size=14),
        )
        labeled(
            1, str(ev.get("rule_id", "—")),
            font=customtkinter.CTkFont(family="Inter", size=12, weight="bold"),
        )
        labeled(
            2, ev.get("description", "—"),
            font=customtkinter.CTkFont(size=12),
            anchor="w",
        )
        metric = (ev.get("mitre") or [None])[0] or ev.get("ip") or "—"
        labeled(
            3, metric,
            text_color=text_secondary,
            font=customtkinter.CTkFont(size=11),
        )
        labeled(
            4, format_timestamp(ev.get("timestamp")),
            text_color=text_secondary,
            font=customtkinter.CTkFont(size=11),
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
            text=format_relative(ev.get("timestamp")),
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
        logger.info(f"Wazuh plugin: Acknowledge clicked for {event_id} (placeholder)")

    def _on_view_in_manager(self, event_id):
        logger.info(f"Wazuh plugin: View in manager clicked for {event_id} (placeholder)")

    # ----- cleanup -----

    def _destroy_events(self):
        """Tear down the matplotlib figure. Called from Plugin.destroy()."""
        if self._event_chart_figure is not None:
            try:
                import matplotlib.pyplot as _plt
                _plt.close(self._event_chart_figure)
            except Exception:
                pass
            self._event_chart_figure = None
            self._event_chart_canvas = None
