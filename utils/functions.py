import math
import os
import sys

import customtkinter

# Centralized SOC Theme Configuration
SOC_THEME = {
    "colors": {
        "background": ("#f0eff6", "#1a1a1a"),
        "card_bg": ("#ffffff", "#242424"),
        "card_border": ("#dddddd", "#333333"),
        "accent_blue": "#3a7ebf",
        "accent_green": "#2ecc71",
        "text_primary": ("#000000", "#ffffff"),
        "text_secondary": ("#666666", "#aaaaaa"),
        "sidebar_bg": ("#f0eff6", "#141414"),
        "hover_bg": ("#EAEAEA", "#2a2a2a")
    },
    "fonts": {
        "primary": "Inter",
        "title_size": 16,
        "body_size": 13,
        "small_size": 11
    },
    "layout": {
        "card_radius": 15,
        "card_padding": 15,
        "sidebar_width": 200
    }
}



def _effective_appearance_mode() -> str:
    """
    Return effective appearance: 'Light' or 'Dark' (resolves System on macOS).
    Mirrors UI_Dev behavior so colors can be updated on appearance switches.
    """
    mode = customtkinter.get_appearance_mode()
    if mode != "System":
        return mode

    if sys.platform == "darwin":
        try:
            import subprocess

            result = subprocess.run(
                ["defaults", "read", "-g", "AppleInterfaceStyle"],
                capture_output=True,
                text=True,
            )
            return "Dark" if result.returncode == 0 and "Dark" in result.stdout else "Light"
        except Exception:
            return "Light"

    return "Light"





def create_plugin_card(row, column, container_frame, plugin):
    """
    Create a professional SOC-style plugin card with fixed hover highlighting.
    """
    card_bg = SOC_THEME["colors"]["card_bg"]
    border_color = SOC_THEME["colors"]["card_border"]
    accent_green = SOC_THEME["colors"]["accent_green"]
    text_primary = SOC_THEME["colors"]["text_primary"]
    
    # Main card frame
    frame = customtkinter.CTkFrame(
        container_frame,
        corner_radius=SOC_THEME["layout"]["card_radius"],
        fg_color=card_bg,
        border_width=1,
        border_color=border_color
    )
    frame.grid(row=row, column=column, padx=15, pady=15, sticky="nsew")
    frame.grid_columnconfigure(0, weight=1)
    
    # Center container for icon and labels
    content_container = customtkinter.CTkFrame(frame, fg_color="transparent")
    content_container.grid(row=0, column=0, padx=20, pady=20, sticky="nsew")
    content_container.grid_columnconfigure(0, weight=1)

    # 1. Centered Icon
    icon_image = plugin.get_icon()
    icon_label = None
    if icon_image:
        icon_label = customtkinter.CTkLabel(
            content_container,
            image=icon_image,
            text=""
        )
        icon_label.grid(row=0, column=0, pady=(0, 10))

    # 2. Module Name (Bold Title)
    title_label = customtkinter.CTkLabel(
        content_container,
        text=plugin.get_name(),
        font=customtkinter.CTkFont(family=SOC_THEME["fonts"]["primary"], size=SOC_THEME["fonts"]["title_size"], weight="bold"),
        text_color=text_primary
    )
    title_label.grid(row=1, column=0, pady=(0, 5))

    # 3. Circular Status Indicator
    status_container = customtkinter.CTkFrame(content_container, fg_color="transparent")
    status_container.grid(row=2, column=0)
    
    status_dot = customtkinter.CTkFrame(
        status_container,
        width=10,
        height=10,
        corner_radius=5,
        fg_color=accent_green
    )
    status_dot.pack(side="left", padx=(0, 5))
    
    status_text = "Protected" if plugin.get_status().lower() == "ok" else plugin.get_status()
    status_label = customtkinter.CTkLabel(
        status_container,
        text=status_text,
        font=customtkinter.CTkFont(family=SOC_THEME["fonts"]["primary"], size=SOC_THEME["fonts"]["small_size"]),
        text_color=SOC_THEME["colors"]["text_secondary"]
    )
    status_label.pack(side="left")

    # Navigation logic
    def on_click(_event=None):
        # Find the main app instance to call select_frame_by_name
        curr = container_frame
        while curr and not hasattr(curr, "select_frame_by_name"):
            curr = curr.master
        
        if curr:
            curr.select_frame_by_name(f"frame_{plugin.get_name()}")
        else:
            plugin.create_main_screen().grid(row=0, column=1, sticky="nsew")

    # Highlighting logic
    def on_enter(_e):
        frame.configure(border_color=SOC_THEME["colors"]["accent_blue"], fg_color=SOC_THEME["colors"]["hover_bg"])
    def on_leave(_e):
        frame.configure(border_color=border_color, fg_color=card_bg)

    # Bind to frame AND all child widgets recursively
    def bind_recursive(widget):
        widget.bind("<Button-1>", on_click)
        widget.bind("<Enter>", on_enter)
        widget.bind("<Leave>", on_leave)
        for child in widget.winfo_children():
            bind_recursive(child)

    bind_recursive(frame)

    return frame


def create_tab_button(frame, name, icon, command=None, row=0, col=0):
    """Create a sleek SOC-style tab button."""
    mode = _effective_appearance_mode()
    text_primary = SOC_THEME["colors"]["text_primary"] if mode == "Dark" else "#000000"
    hover_bg = SOC_THEME["colors"]["hover_bg"]
    accent_blue = SOC_THEME["colors"]["accent_blue"]

    frame_button = customtkinter.CTkButton(
        frame,
        corner_radius=10,
        height=45,
        border_spacing=12,
        text=name,
        fg_color="transparent",
        text_color=text_primary,
        hover_color=hover_bg,
        border_width=0,
        border_color=accent_blue,
        image=icon,
        anchor="w",
        font=customtkinter.CTkFont(family=SOC_THEME["fonts"]["primary"], size=14, weight="normal"),
        command=command,
    )

    def on_enter(_e):
        frame_button.configure(border_width=1)
    def on_leave(_e):
        if frame_button.cget("fg_color") == "transparent": # only remove if not active
            frame_button.configure(border_width=0)
        frame_button.update_idletasks()

    frame_button.bind("<Enter>", on_enter)
    frame_button.bind("<Leave>", on_leave)

    frame_button.grid(row=row, column=col, sticky="ew", padx=10, pady=2)

    return frame_button


def apply_tab_button_theme(button: customtkinter.CTkButton):
    """Update theme-dependent colors (text/hover) after appearance switches."""
    mode = _effective_appearance_mode()
    text_color = "#ffffff" if mode == "Dark" else "#000000"
    hover_bg = "#2A2A2A" if mode == "Dark" else "#F5F5F5"
    button.configure(text_color=text_color, hover_color=hover_bg)



def apply_tab_button_state(button: customtkinter.CTkButton, is_active: bool):
    """Apply active/inactive styling using SOC theme."""
    if is_active:
        button.configure(
            fg_color=SOC_THEME["colors"]["hover_bg"],
            border_width=1,
            border_color=SOC_THEME["colors"]["accent_blue"]
        )
    else:
        button.configure(
            fg_color="transparent",
            border_width=0
        )


def create_grid(frame, row, column, plugins, color, sticky="nsew"):
    """
    Create a grid layout for the plugins with the specified color and sticky option.

    :param frame: The parent frame to contain this grid.
    :param row: The row position in the grid.
    :param column: The column position in the grid.
    :param plugins: The list of plugins to display in the grid.
    :param color: The background color of the grid.
    :param sticky: The sticky option for the grid.
    :return: The created grid frame.
    """
    rows_tuple, cols_tuple = calculate_rows_cols(len(plugins))
    frame = customtkinter.CTkFrame(frame, corner_radius=0, fg_color=color)
    frame.grid(row=row, column=column, sticky=sticky)
    frame.grid_columnconfigure(rows_tuple, weight=1)
    frame.grid_rowconfigure(cols_tuple, weight=1)

    # Create the grid and color the columns
    for r in rows_tuple:
        for c in cols_tuple:
            cell_frame = customtkinter.CTkFrame(
                frame, corner_radius=0, fg_color="transparent"
            )
            cell_frame.grid(row=r, column=c, sticky="nsew")
            frame.grid_columnconfigure(c, weight=1)
            frame.grid_rowconfigure(r, weight=1)
    return frame


def calculate_rows_cols(num_plugins):
    """
    Calculate the number of rows and columns needed to display the plugins in a grid.

    :param num_plugins: The total number of plugins.
    :return: A tuple containing the range of rows and columns.
    """
    cols = math.ceil(math.sqrt(num_plugins))
    rows = math.ceil(num_plugins / cols)
    return tuple(range(rows)), tuple(range(cols))


def is_running_in_ide():
    """
    Check if the application is running within an IDE (VS Code, PyCharm, etc.)
    or if a debugger is attached.

    :return: True if running in an IDE or debugger, False otherwise.
    """
    # 1. Check for VS Code
    if (
        os.environ.get("TERM_PROGRAM") == "vscode"
        or "VSCODE_PID" in os.environ
        or "VSCODE_CWD" in os.environ
    ):
        return "VSCode"

    # 2. Check for PyCharm / JetBrains
    if "PYCHARM_HOSTED" in os.environ or "JETBRAINS_IDE" in os.environ:
        return "JetBrains"

    # 3. Check for general debugger attachment
    if sys.gettrace() is not None:
        return "Debugger"

    return None
