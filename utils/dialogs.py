import customtkinter as ctk

from utils.i18n import get_text


class CTkPasswordDialog(ctk.CTkToplevel):
    """
    A themed password dialog using CustomTkinter.
    Usage:
        dialog = CTkPasswordDialog(title="Password Required", text="Enter sudo password:")
        password = dialog.get_input()
    """

    def __init__(self, title=None, text=None, parent=None):
        super().__init__(parent)

        if title is None:
            title = get_text("dialog.password.title")
        if text is None:
            text = get_text("dialog.password.text")

        self.title(title)
        self.geometry("500x200")
        self.resizable(False, False)

        # Center the window
        self.update_idletasks()
        if parent:
            x = parent.winfo_x() + (parent.winfo_width() // 2) - (500 // 2)
            y = parent.winfo_y() + (parent.winfo_height() // 2) - (200 // 2)
        else:
            x = (self.winfo_screenwidth() // 2) - (500 // 2)
            y = (self.winfo_screenheight() // 2) - (200 // 2)
        self.geometry(f"+{x}+{y}")

        self.attributes("-topmost", True)
        self.grab_set()  # Make it modal

        self.result = None

        self.label = ctk.CTkLabel(self, text=text, font=ctk.CTkFont(size=14))
        self.label.pack(pady=(20, 10), padx=20)

        self.entry = ctk.CTkEntry(self, show="*", width=400)
        self.entry.pack(pady=10, padx=20)
        self.entry.focus_set()
        self.entry.bind("<Return>", lambda e: self.on_ok())

        self.button_frame = ctk.CTkFrame(self, fg_color="transparent")
        self.button_frame.pack(pady=(10, 20), padx=20, fill="x")

        self.ok_button = ctk.CTkButton(
            self.button_frame,
            text=get_text("dialog.password.button.ok"),
            command=self.on_ok,
            width=100,
        )
        self.ok_button.pack(side="right", padx=5)

        self.cancel_button = ctk.CTkButton(
            self.button_frame,
            text=get_text("dialog.password.button.cancel"),
            command=self.on_cancel,
            width=100,
            fg_color="gray30",
            hover_color="gray40",
        )
        self.cancel_button.pack(side="right", padx=5)

    def on_ok(self):
        self.result = self.entry.get()
        self.destroy()

    def on_cancel(self):
        self.result = None
        self.destroy()

    def get_input(self):
        self.wait_window()
        return self.result
