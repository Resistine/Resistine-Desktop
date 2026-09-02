"""
Debug Plugin — test bench for widget rendering, scroll artifacts, and
other platform-specific issues.

Visible only when the app is launched with ``--debug`` / ``-d`` or
detected running inside an IDE (mirrors ``main.py``'s DEBUG gate).
"""

import os
import sys
import tkinter as tk

import customtkinter

from plugins.base_plugin import BasePlugin
from utils import functions


def _is_debug_mode() -> bool:
    """Mirror ``main.py``'s DEBUG detection."""
    if any(a in ("-d", "--debug") for a in sys.argv[1:]):
        return True
    try:
        return bool(functions.is_running_in_ide())
    except Exception:
        return False


class Plugin(BasePlugin):
    def __init__(self, app):
        if not _is_debug_mode():
            raise RuntimeError(
                "Debug page hidden. Launch with --debug to enable."
            )
        super().__init__(
            id="999",
            version="2025.01.01",
            order=9999,
            name="Debug",
            status=None,
            description="Debug test bench",
            supported_systems=["Windows", "Darwin", "Linux"],
            translations={"US": "Debug"},
            icon_light_path=os.path.join(
                os.path.dirname(os.path.realpath(__file__)), "..", "help", "help_light.png"
            ),
            icon_dark_path=os.path.join(
                os.path.dirname(os.path.realpath(__file__)), "..", "help", "help_dark.png"
            ),
            uninstall_enabled=True,
        )
        self.app = app

    def create_main_screen(self):
        self.main_container = customtkinter.CTkScrollableFrame(
            self.app, corner_radius=0, fg_color="transparent",
        )
        self.main_container.grid_columnconfigure(0, weight=1)

        colors = {
            "blue": "#1a73e8",
            "green": "#22c55e",
            "red": "#ef4444",
            "dark": "#1e1e1e",
            "light": "#f0f0f0",
        }

        row = 0

        def add_section(title):
            nonlocal row
            customtkinter.CTkLabel(
                self.main_container, text=f"── {title} ──",
                font=customtkinter.CTkFont(size=16, weight="bold"),
            ).grid(row=row, column=0, padx=20, pady=(20, 5), sticky="w")
            row += 1

        def add_spacer(h=40):
            nonlocal row
            customtkinter.CTkFrame(
                self.main_container, height=h, fg_color="transparent",
            ).grid(row=row, column=0, sticky="ew")
            row += 1

        # === 1. tk.Text widgets (known good) ===
        add_section("tk.Text (known artifact-free)")
        for name, color in colors.items():
            f = tk.Text(
                self.main_container, bg=color, height=2, width=40,
                highlightthickness=0, bd=0, padx=10, pady=10,
                cursor="", insertwidth=0, state="disabled",
            )
            f.grid(row=row, column=0, padx=20, pady=3, sticky="ew")
            row += 1

        add_spacer()

        # === 2. tk.Frame widgets ===
        add_section("tk.Frame")
        for name, color in colors.items():
            f = tk.Frame(
                self.main_container, bg=color, height=44, highlightthickness=0, bd=0,
            )
            f.grid(row=row, column=0, padx=20, pady=3, sticky="ew")
            f.grid_propagate(False)
            row += 1

        add_spacer()

        # === 3. tk.Canvas widgets ===
        add_section("tk.Canvas")
        for name, color in colors.items():
            c = tk.Canvas(
                self.main_container, bg=color, height=44, highlightthickness=0, bd=0,
            )
            c.grid(row=row, column=0, padx=20, pady=3, sticky="ew")
            row += 1

        add_spacer()

        # === 4. tk.Label widgets ===
        add_section("tk.Label")
        for name, color in colors.items():
            l = tk.Label(
                self.main_container, bg=color, text=f"tk.Label ({name})",
                fg="white" if name != "light" else "black",
                height=2, anchor="center",
            )
            l.grid(row=row, column=0, padx=20, pady=3, sticky="ew")
            row += 1

        add_spacer()

        # === 5. tk.Entry widgets ===
        add_section("tk.Entry")
        for name, color in colors.items():
            e = tk.Entry(
                self.main_container, bg=color,
                fg="white" if name != "light" else "black",
                highlightthickness=0, bd=0,
                font=("Inter", 14),
            )
            e.insert(0, f"tk.Entry ({name})")
            e.grid(row=row, column=0, padx=20, pady=3, sticky="ew")
            row += 1

        add_spacer()

        # === 6. tk.Listbox widgets ===
        add_section("tk.Listbox")
        for name, color in colors.items():
            lb = tk.Listbox(
                self.main_container, bg=color,
                fg="white" if name != "light" else "black",
                height=2, highlightthickness=0, bd=0,
            )
            lb.insert(0, f"tk.Listbox ({name})")
            lb.grid(row=row, column=0, padx=20, pady=3, sticky="ew")
            row += 1

        add_spacer()

        # === 7. tk.Message widgets ===
        add_section("tk.Message")
        for name, color in colors.items():
            m = tk.Message(
                self.main_container, bg=color,
                fg="white" if name != "light" else "black",
                text=f"tk.Message ({name})", width=400,
            )
            m.grid(row=row, column=0, padx=20, pady=3, sticky="ew")
            row += 1

        add_spacer()

        # === 8. tk.Button widgets ===
        add_section("tk.Button")
        for name, color in colors.items():
            b = tk.Button(
                self.main_container, bg=color,
                fg="white" if name != "light" else "black",
                text=f"tk.Button ({name})",
                highlightthickness=0, bd=0,
                activebackground=color,
            )
            b.grid(row=row, column=0, padx=20, pady=3, sticky="ew")
            row += 1

        add_spacer()

        # === 9. tk.Scale widgets ===
        add_section("tk.Scale")
        for name, color in colors.items():
            s = tk.Scale(
                self.main_container, bg=color, orient="horizontal",
                from_=0, to=100, highlightthickness=0, bd=0,
                troughcolor=color,
            )
            s.grid(row=row, column=0, padx=20, pady=3, sticky="ew")
            row += 1

        add_spacer()

        # === 10. tk.Spinbox ===
        add_section("tk.Spinbox")
        for name, color in colors.items():
            sb = tk.Spinbox(
                self.main_container, bg=color,
                fg="white" if name != "light" else "black",
                from_=0, to=100, highlightthickness=0, bd=0,
            )
            sb.grid(row=row, column=0, padx=20, pady=3, sticky="ew")
            row += 1

        add_spacer()

        # === 11. CTkFrame widgets ===
        add_section("CTkFrame (Cairo-rendered)")
        for name, color in colors.items():
            f = customtkinter.CTkFrame(
                self.main_container, fg_color=color, height=44, corner_radius=12,
            )
            f.grid(row=row, column=0, padx=20, pady=3, sticky="ew")
            row += 1

        add_spacer()

        # === 12. CTkButton widgets ===
        add_section("CTkButton (Cairo-rendered)")
        for name, color in colors.items():
            b = customtkinter.CTkButton(
                self.main_container, fg_color=color,
                text=f"CTkButton ({name})", corner_radius=12,
            )
            b.grid(row=row, column=0, padx=20, pady=3, sticky="ew")
            row += 1

        add_spacer()

        # === 13. CTkLabel widgets ===
        add_section("CTkLabel")
        for name, color in colors.items():
            l = customtkinter.CTkLabel(
                self.main_container, fg_color=color,
                text=f"CTkLabel ({name})", corner_radius=8,
                text_color="white" if name != "light" else "black",
            )
            l.grid(row=row, column=0, padx=20, pady=3, sticky="ew")
            row += 1

        add_spacer()

        # === 14. CTkEntry widgets ===
        add_section("CTkEntry")
        for name, color in colors.items():
            e = customtkinter.CTkEntry(
                self.main_container, fg_color=color,
                text_color="white" if name != "light" else "black",
                corner_radius=8, border_width=0,
            )
            e.insert(0, f"CTkEntry ({name})")
            e.grid(row=row, column=0, padx=20, pady=3, sticky="ew")
            row += 1

        add_spacer()

        # === 15. CTkTextbox widgets ===
        add_section("CTkTextbox")
        for name, color in colors.items():
            t = customtkinter.CTkTextbox(
                self.main_container, fg_color=color, height=44,
                text_color="white" if name != "light" else "black",
                corner_radius=8,
            )
            t.insert("1.0", f"CTkTextbox ({name})")
            t.configure(state="disabled")
            t.grid(row=row, column=0, padx=20, pady=3, sticky="ew")
            row += 1

        add_spacer()

        # === 16. CTkProgressBar ===
        add_section("CTkProgressBar")
        for i, (name, color) in enumerate(colors.items()):
            p = customtkinter.CTkProgressBar(
                self.main_container, progress_color=color,
            )
            p.set((i + 1) / len(colors))
            p.grid(row=row, column=0, padx=20, pady=6, sticky="ew")
            row += 1

        add_spacer()

        # === 17. CTkSwitch ===
        add_section("CTkSwitch")
        for name, color in colors.items():
            s = customtkinter.CTkSwitch(
                self.main_container, text=f"CTkSwitch ({name})",
                progress_color=color,
            )
            s.grid(row=row, column=0, padx=20, pady=3, sticky="w")
            row += 1

        add_spacer()

        # === 18. CTkCheckBox ===
        add_section("CTkCheckBox")
        for name, color in colors.items():
            cb = customtkinter.CTkCheckBox(
                self.main_container, text=f"CTkCheckBox ({name})",
                fg_color=color,
            )
            cb.grid(row=row, column=0, padx=20, pady=3, sticky="w")
            row += 1

        add_spacer()

        # === 19. tk.Canvas with create_window embedding a tk.Text ===
        add_section("tk.Canvas + embedded tk.Text (hybrid)")
        for name, color in colors.items():
            c = tk.Canvas(
                self.main_container, height=44, highlightthickness=0, bd=0,
                bg=self.main_container.cget("fg_color") if self.main_container.cget("fg_color") != "transparent" else "#1a1a1a",
            )
            t = tk.Text(c, bg=color, highlightthickness=0, bd=0,
                        padx=10, pady=10, cursor="", insertwidth=0,
                        state="disabled", height=1)
            c.create_window(0, 0, anchor="nw", window=t, width=600, height=44)
            c.grid(row=row, column=0, padx=20, pady=3, sticky="ew")
            row += 1

        add_spacer()

        # === 20. PhotoImage on canvas (like Cairo) ===
        add_section("tk.Canvas + PhotoImage (simulates Cairo)")
        for name, color in colors.items():
            from PIL import Image, ImageTk, ImageDraw
            img = Image.new("RGBA", (600, 44), color)
            draw = ImageDraw.Draw(img)
            # No rounding, just solid color
            photo = ImageTk.PhotoImage(img)
            c = tk.Canvas(
                self.main_container, height=44, highlightthickness=0, bd=0,
            )
            c.create_image(0, 0, anchor="nw", image=photo)
            c._photo_ref = photo  # prevent GC
            c.grid(row=row, column=0, padx=20, pady=3, sticky="ew")
            row += 1

        add_spacer()

        # === 21. Nested CTkFrames (heavy — simulates settings cards) ===
        add_section("Nested CTkFrame cards (simulates Settings page)")
        for i in range(20):
            card = customtkinter.CTkFrame(
                self.main_container, corner_radius=12,
            )
            card.grid(row=row, column=0, padx=20, pady=6, sticky="ew")
            card.grid_columnconfigure(0, weight=1)

            customtkinter.CTkLabel(
                card, text=f"Card {i+1} — Section Title",
                font=customtkinter.CTkFont(size=15, weight="bold"),
            ).grid(row=0, column=0, padx=16, pady=(12, 4), sticky="w")

            customtkinter.CTkLabel(
                card, text="This simulates a settings card with multiple nested widgets.",
                font=customtkinter.CTkFont(size=13),
            ).grid(row=1, column=0, padx=16, pady=(0, 4), sticky="w")

            customtkinter.CTkButton(
                card, text="Action Button", corner_radius=8, height=34,
            ).grid(row=2, column=0, padx=16, pady=(4, 12), sticky="w")

            row += 1

        add_spacer()

        # === 22. MarkdownBubble (exactly what help page uses) ===
        add_section("MarkdownBubble (same renderer as Help page)")
        try:
            from plugins.chat.markdown_bubble import MarkdownBubble
            for i in range(5):
                md = MarkdownBubble(
                    self.main_container,
                    f"## Markdown Section {i+1}\n\n"
                    f"This is a **MarkdownBubble** with some content.\n\n"
                    f"- List item one\n- List item two\n- List item three\n\n"
                    f"```python\ndef hello():\n    print('world')\n```\n\n"
                    f"Some more text after the code block to add height.",
                )
                md.grid(row=row, column=0, padx=20, pady=6, sticky="ew")
                row += 1
        except Exception as e:
            customtkinter.CTkLabel(
                self.main_container, text=f"MarkdownBubble failed: {e}",
            ).grid(row=row, column=0, padx=20, pady=6, sticky="w")
            row += 1

        add_spacer(80)

        return self.main_container
