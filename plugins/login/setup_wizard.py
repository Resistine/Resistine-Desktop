# -*- coding: utf-8 -*-
# @file plugins/login/setup_wizard.py
# Description: Unified post-login customer setup wizard.
#
# One screen, one guided flow. After sign-in the user lands here and a single
# "Get Protected" button walks them through every permission and installation
# their operating system needs — macOS VPN extension approval, antivirus +
# Full Disk Access, endpoint monitoring; the Windows/Linux equivalents — so
# they never have to hunt through the app enabling things by hand. A Skip
# button is always available.
#
# The wizard is intentionally plugin-agnostic: all platform specifics live in
# setup_steps.py. This module only sequences steps and renders their state.
#
# Author: Resistine Team
# Copyright: Resistine (c) 2025
# Licensed under the GNU General Public License v2 or later

import os

import customtkinter
from PIL import Image

from plugins.login.setup_steps import build_steps
from utils import settings
from utils.functions import get_resource_path
from utils.logger import logger

_BLUE = "#0D5394"
_BLUE_HOVER = "#0A4275"
_GREEN = "#1E8E3E"
_GREEN_HOVER = "#177B33"
_POLL_MS = 2000


def _font(size, weight="normal"):
    return customtkinter.CTkFont(family="Inter", size=size, weight=weight)


class SetupWizardScreen:
    """Full-window wizard shown once, right after first sign-in."""

    def __init__(self, app, on_complete_callback):
        self.app = app
        self.on_complete = on_complete_callback
        self.frame = None
        self.steps = build_steps(app)
        self.index = -1                 # current step (-1 = welcome)
        self._poll_id = None
        self._active = False            # a step's work is running / polling
        self.results = {}               # step.key -> "done" | "skipped"

    # ── Lifecycle ───────────────────────────────────────────────────

    def show(self):
        self.frame = customtkinter.CTkFrame(
            self.app, corner_radius=0, fg_color=self.app.cget("fg_color")
        )
        self.frame.grid(row=0, column=0, sticky="nsew")
        self.app.grid_rowconfigure(0, weight=1)
        self.app.grid_columnconfigure(0, weight=1)
        self.frame.lift()

        if not self.steps:
            # Nothing to set up on this platform — go straight through.
            logger.info("[SETUP] No applicable steps; finishing wizard.")
            self._finish()
            return
        self._build_welcome()

    def destroy(self):
        self._cancel_poll()
        if self.frame is not None:
            self.frame.destroy()
            self.frame = None

    # ── Welcome ─────────────────────────────────────────────────────

    def _build_welcome(self):
        c = self._new_container()
        self._add_shield(c, row=0, size=96)

        customtkinter.CTkLabel(
            c, text="Let's finish setting up Resistine",
            font=_font(22, "bold"), text_color=("#333333", "#FFFFFF"),
        ).grid(row=1, column=0, pady=(0, 8))

        customtkinter.CTkLabel(
            c,
            text="We'll turn on your protection in a few quick, guided steps.\n"
                 "You can skip anything and set it up later.",
            font=_font(14), text_color=("#666666", "#AAAAAA"), justify="center",
        ).grid(row=2, column=0, pady=(0, 22))

        checklist = customtkinter.CTkFrame(
            c, corner_radius=12, fg_color=("#F5F5F5", "#1E1E1E"),
            border_width=1, border_color=("#E0E0E0", "#333333"),
        )
        checklist.grid(row=3, column=0, pady=(0, 24), sticky="ew")
        checklist.grid_columnconfigure(0, weight=1)

        for i, step in enumerate(self.steps):
            done = self._safe(step.is_complete, False)
            self._checklist_row(checklist, i, step, done)

        customtkinter.CTkButton(
            c, text="Get Protected", command=self._start_flow,
            width=400, height=46, corner_radius=23,
            fg_color=_BLUE, hover_color=_BLUE_HOVER, font=_font(16, "bold"),
        ).grid(row=4, column=0, pady=(0, 10))

        customtkinter.CTkButton(
            c, text="Skip for now", command=self._skip_all,
            fg_color="transparent", hover_color=("gray90", "gray20"),
            text_color=("#0D5394", "#3a7ebf"), font=_font(13),
        ).grid(row=5, column=0)

    def _checklist_row(self, parent, i, step, done):
        row = customtkinter.CTkFrame(parent, fg_color="transparent")
        pady = (14 if i == 0 else 6, 14 if i == len(self.steps) - 1 else 6)
        row.grid(row=i, column=0, padx=18, pady=pady, sticky="ew")
        row.grid_columnconfigure(1, weight=1)

        customtkinter.CTkLabel(
            row, text=step.icon, font=_font(20), width=32,
        ).grid(row=0, column=0, rowspan=2, padx=(0, 12))

        customtkinter.CTkLabel(
            row, text=step.title, font=_font(14, "bold"),
            text_color=("#333333", "#EEEEEE"), anchor="w",
        ).grid(row=0, column=1, sticky="w")

        customtkinter.CTkLabel(
            row, text=step.subtitle, font=_font(12),
            text_color=("#777777", "#999999"), anchor="w",
        ).grid(row=1, column=1, sticky="w")

        customtkinter.CTkLabel(
            row, text="✓ Ready" if done else "•",
            font=_font(12, "bold" if done else "normal"),
            text_color=(_GREEN, "#2CC985") if done else ("#BBBBBB", "#666666"),
        ).grid(row=0, column=2, rowspan=2, padx=(12, 0))

    # ── Flow control ────────────────────────────────────────────────

    def _start_flow(self):
        self.index = -1
        self._advance()

    def _advance(self):
        """Move to the next step that is both applicable and not yet complete."""
        self._cancel_poll()
        self._active = False
        self.index += 1
        while self.index < len(self.steps):
            step = self.steps[self.index]
            if self._safe(step.is_complete, False):
                self.results.setdefault(step.key, "done")
                self.index += 1
                continue
            self._build_step(step)
            return
        self._build_success()

    # ── Step screen ─────────────────────────────────────────────────

    def _build_step(self, step):
        c = self._new_container()

        # Progress indicator (Step X of N + dots)
        header = customtkinter.CTkFrame(c, fg_color="transparent")
        header.grid(row=0, column=0, pady=(0, 18))
        customtkinter.CTkLabel(
            header, text=f"Step {self.index + 1} of {len(self.steps)}",
            font=_font(12, "bold"), text_color=("#999999", "#888888"),
        ).grid(row=0, column=0, pady=(0, 8))
        dots = customtkinter.CTkFrame(header, fg_color="transparent")
        dots.grid(row=1, column=0)
        for i in range(len(self.steps)):
            done = i < self.index or self.results.get(self.steps[i].key)
            color = (_BLUE, "#3a7ebf") if i == self.index else (
                (_GREEN, "#2CC985") if done else ("#DDDDDD", "#444444"))
            customtkinter.CTkFrame(
                dots, width=22, height=6, corner_radius=3, fg_color=color,
            ).grid(row=0, column=i, padx=3)

        customtkinter.CTkLabel(
            c, text=step.icon, font=_font(46),
        ).grid(row=1, column=0, pady=(0, 6))

        customtkinter.CTkLabel(
            c, text=step.title, font=_font(20, "bold"),
            text_color=("#333333", "#FFFFFF"),
        ).grid(row=2, column=0, pady=(0, 8))

        customtkinter.CTkLabel(
            c, text=step.detail, font=_font(14), wraplength=440,
            text_color=("#666666", "#AAAAAA"), justify="center",
        ).grid(row=3, column=0, pady=(0, 18))

        # Instructions card (optional)
        if getattr(step, "instructions", None):
            self._instructions_card(c, step.instructions, row=4)

        # Progress bar (hidden until work starts)
        self._bar = customtkinter.CTkProgressBar(c, width=400, mode="indeterminate")
        self._bar.grid(row=5, column=0, pady=(6, 6))
        self._bar.grid_remove()

        # Status line
        self._status = customtkinter.CTkLabel(
            c, text="", font=_font(12), text_color=("#888888", "#888888"),
            wraplength=440, justify="center",
        )
        self._status.grid(row=6, column=0, pady=(0, 14))

        # Primary action
        self._primary = customtkinter.CTkButton(
            c, text=step.primary_label, command=self._on_primary,
            width=400, height=46, corner_radius=23,
            fg_color=_BLUE, hover_color=_BLUE_HOVER, font=_font(16, "bold"),
        )
        self._primary.grid(row=7, column=0, pady=(0, 10))

        # Skip this step
        self._skip_btn = customtkinter.CTkButton(
            c, text="Skip this step", command=self._skip_step,
            fg_color="transparent", hover_color=("gray90", "gray20"),
            text_color=("#0D5394", "#3a7ebf"), font=_font(13),
        )
        self._skip_btn.grid(row=8, column=0)

    def _instructions_card(self, parent, instructions, row):
        card = customtkinter.CTkFrame(
            parent, corner_radius=12, fg_color=("#F5F5F5", "#1E1E1E"),
            border_width=1, border_color=("#E0E0E0", "#333333"),
        )
        card.grid(row=row, column=0, pady=(0, 16), sticky="ew")
        card.grid_columnconfigure(0, weight=1)
        for i, text in enumerate(instructions):
            line = customtkinter.CTkFrame(card, fg_color="transparent")
            pad = (14 if i == 0 else 5, 14 if i == len(instructions) - 1 else 5)
            line.grid(row=i, column=0, padx=18, pady=pad, sticky="w")
            customtkinter.CTkLabel(
                line, text=str(i + 1), width=26, height=26, corner_radius=13,
                fg_color=_BLUE, text_color="#FFFFFF", font=_font(12, "bold"),
            ).pack(side="left", padx=(0, 12))
            customtkinter.CTkLabel(
                line, text=text, font=_font(13),
                text_color=("#444444", "#CCCCCC"), justify="left", wraplength=360,
            ).pack(side="left")

    # ── Step actions ────────────────────────────────────────────────

    def _on_primary(self):
        if self._active:
            return
        step = self.steps[self.index]
        self._active = True
        step._failed = None
        self._primary.configure(state="disabled", text=step.working_label)
        self._skip_btn.configure(text="Skip this step")
        self._bar.grid()
        self._bar.start()
        self._set_status(step.working_label)

        # on_status is called from worker threads — marshal to the UI thread.
        def on_status(text):
            try:
                self.app.after(0, self._set_status, text)
            except Exception:  # noqa: BLE001
                pass

        try:
            step.begin(on_status)
        except Exception as e:  # noqa: BLE001
            logger.error(f"[SETUP] begin() failed for {step.key}: {e}")
            step._failed = "Something went wrong. You can try again or skip."
        self._schedule_poll()

    def _schedule_poll(self):
        self._cancel_poll()
        self._poll_id = self.app.after(_POLL_MS, self._poll)

    def _poll(self):
        if self.frame is None or self.index >= len(self.steps):
            return
        step = self.steps[self.index]

        if self._safe(step.is_complete, False):
            self.results[step.key] = "done"
            self._on_step_done()
            return

        failure = self._safe(step.check_failed, None)
        if failure:
            self._show_failure(failure)
            return

        self._schedule_poll()

    def _on_step_done(self):
        self._cancel_poll()
        self._active = False
        try:
            self._bar.stop()
            self._set_status("✓ Done")
        except Exception:  # noqa: BLE001
            pass
        # Brief beat so the checkmark registers, then advance.
        self.app.after(600, self._advance)

    def _show_failure(self, message):
        self._cancel_poll()
        self._active = False
        try:
            self._bar.stop()
            self._bar.grid_remove()
            self._status.configure(text=message, text_color=("#C0392B", "#E74C3C"))
            self._primary.configure(state="normal", text="Try Again")
            self._skip_btn.configure(text="Skip this step")
        except Exception:  # noqa: BLE001
            pass

    def _skip_step(self):
        if self.index < len(self.steps):
            self.results[self.steps[self.index].key] = "skipped"
        self._advance()

    # ── Success ─────────────────────────────────────────────────────

    def _build_success(self):
        c = self._new_container()
        self._add_shield(c, row=0, size=96)

        any_done = any(v == "done" for v in self.results.values())
        title = "You're protected!" if any_done else "Setup complete"
        customtkinter.CTkLabel(
            c, text=title, font=_font(24, "bold"),
            text_color=(_GREEN, "#2CC985"),
        ).grid(row=1, column=0, pady=(0, 8))

        customtkinter.CTkLabel(
            c, text="Here's what's set up on your device.",
            font=_font(14), text_color=("#666666", "#AAAAAA"),
        ).grid(row=2, column=0, pady=(0, 20))

        summary = customtkinter.CTkFrame(
            c, corner_radius=12, fg_color=("#F5F5F5", "#1E1E1E"),
            border_width=1, border_color=("#E0E0E0", "#333333"),
        )
        summary.grid(row=3, column=0, pady=(0, 24), sticky="ew")
        summary.grid_columnconfigure(0, weight=1)
        for i, step in enumerate(self.steps):
            done = self.results.get(step.key) == "done" or self._safe(
                step.is_complete, False)
            line = customtkinter.CTkFrame(summary, fg_color="transparent")
            pad = (14 if i == 0 else 6, 14 if i == len(self.steps) - 1 else 6)
            line.grid(row=i, column=0, padx=18, pady=pad, sticky="ew")
            line.grid_columnconfigure(1, weight=1)
            customtkinter.CTkLabel(line, text=step.icon, font=_font(18), width=30).grid(
                row=0, column=0, padx=(0, 12))
            customtkinter.CTkLabel(
                line, text=step.title, font=_font(13, "bold"),
                text_color=("#333333", "#EEEEEE"), anchor="w",
            ).grid(row=0, column=1, sticky="w")
            customtkinter.CTkLabel(
                line, text="✓ Enabled" if done else "Skipped",
                font=_font(12, "bold" if done else "normal"),
                text_color=(_GREEN, "#2CC985") if done else ("#999999", "#888888"),
            ).grid(row=0, column=2, padx=(12, 0))

        customtkinter.CTkButton(
            c, text="Go to Dashboard", command=self._finish,
            width=400, height=46, corner_radius=23,
            fg_color=_GREEN, hover_color=_GREEN_HOVER, font=_font(16, "bold"),
        ).grid(row=4, column=0)

    # ── Completion ──────────────────────────────────────────────────

    def _skip_all(self):
        logger.info("[SETUP] User skipped setup wizard")
        self._finish()

    def _finish(self):
        if self.frame is None:
            return
        settings.set("setup", "complete", True)
        settings.set("auth", "logged_in", True)
        # Keep the legacy flag satisfied so the old VPN-only onboarding branch
        # never re-triggers.
        settings.set("vpn", "onboarding_complete", True)
        logger.info("[SETUP] Setup wizard complete")
        self.destroy()
        if self.on_complete:
            self.on_complete()

    # ── UI helpers ──────────────────────────────────────────────────

    def _set_status(self, text):
        try:
            if self._status.winfo_exists():
                self._status.configure(text=text, text_color=("#888888", "#888888"))
        except Exception:  # noqa: BLE001
            pass

    def _cancel_poll(self):
        if self._poll_id:
            try:
                self.app.after_cancel(self._poll_id)
            except Exception:  # noqa: BLE001
                pass
            self._poll_id = None

    def _new_container(self):
        for w in self.frame.winfo_children():
            w.destroy()
        self.frame.grid_rowconfigure(0, weight=1)
        self.frame.grid_rowconfigure(1, weight=0)
        self.frame.grid_rowconfigure(2, weight=1)
        self.frame.grid_columnconfigure(0, weight=1)
        container = customtkinter.CTkFrame(
            self.frame, corner_radius=0, fg_color="transparent", width=520,
        )
        container.grid(row=1, column=0, sticky="n")
        container.grid_columnconfigure(0, weight=1)
        return container

    def _add_shield(self, parent, row=0, size=96):
        path = get_resource_path(os.path.join("resources", "icons", "ResistineShield.png"))
        try:
            img = customtkinter.CTkImage(Image.open(path), size=(size, size))
            customtkinter.CTkLabel(parent, text="", image=img).grid(
                row=row, column=0, pady=(0, 20))
        except Exception as e:  # noqa: BLE001
            logger.warning(f"[SETUP] Shield logo load failed: {e}")

    @staticmethod
    def _safe(fn, default):
        try:
            return fn()
        except Exception as e:  # noqa: BLE001
            logger.warning(f"[SETUP] check failed: {e}")
            return default
