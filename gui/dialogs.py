import customtkinter
from typing import Callable, Optional

class SafeDialog(customtkinter.CTkToplevel):
    """
    A custom dialog system that avoids native macOS NSAlert calls 
    to prevent Bus Error crashes on Python 3.14/ARM64.
    """
    def __init__(
        self, 
        master, 
        title: str, 
        message: str, 
        icon: str = "info",
        options: list = ["OK"],
        callback: Optional[Callable[[str], None]] = None
    ):
        super().__init__(master)
        
        self.title(title)
        self.lift()  # Bring to front
        self.attributes("-topmost", True)
        self.protocol("WM_DELETE_WINDOW", self._on_close)
        
        self.callback = callback
        self.result = None

        # Design
        self.grid_columnconfigure(0, weight=1)
        self.configure(padx=20, pady=20)
        
        # Message Label
        self.label = customtkinter.CTkLabel(
            self, 
            text=message, 
            wraplength=350,
            font=customtkinter.CTkFont(size=14)
        )
        self.label.grid(row=0, column=0, pady=(0, 20), sticky="nsew")
        
        # Buttons Frame
        self.button_frame = customtkinter.CTkFrame(self, fg_color="transparent")
        self.button_frame.grid(row=1, column=0, sticky="ew")
        
        for i, option in enumerate(options):
            self.button_frame.grid_columnconfigure(i, weight=1)
            btn = customtkinter.CTkButton(
                self.button_frame,
                text=option,
                command=lambda opt=option: self._on_button_click(opt)
            )
            btn.grid(row=0, column=i, padx=5)

        # Center on screen
        self.after(10, self._center_window)

    def _center_window(self):
        self.update_idletasks()
        width = self.winfo_width()
        height = self.winfo_height()
        x = (self.winfo_screenwidth() // 2) - (width // 2)
        y = (self.winfo_screenheight() // 2) - (height // 2)
        self.geometry(f"{width}x{height}+{x}+{y}")

    def _on_button_click(self, option: str):
        self.result = option
        if self.callback:
            self.callback(option)
        self.destroy()

    def _on_close(self):
        self._on_button_click(None)

def ask_yes_no(master, title: str, message: str, callback: Callable[[bool], None]):
    """Safe replacement for messagebox.askyesno"""
    def _internal_callback(result):
        callback(result == "Yes")
        
    SafeDialog(
        master, 
        title, 
        message, 
        options=["Yes", "No"], 
        callback=_internal_callback
    )

def show_info(master, title: str, message: str):
    """Safe replacement for messagebox.showinfo"""
    SafeDialog(master, title, message, options=["OK"])

class CTkPasswordDialog(customtkinter.CTkToplevel):
    def __init__(self, title: str, text: str, **kwargs):
        super().__init__(**kwargs)
        self.title(title)
        self.lift()
        self.attributes("-topmost", True)
        self.protocol("WM_DELETE_WINDOW", self._on_cancel)
        self.result = None

        self.grid_columnconfigure(0, weight=1)
        self.configure(padx=20, pady=20)

        self.label = customtkinter.CTkLabel(self, text=text, wraplength=350, font=customtkinter.CTkFont(size=14))
        self.label.grid(row=0, column=0, pady=(0, 20), sticky="nsew", columnspan=2)

        self.entry = customtkinter.CTkEntry(self, show="*")
        self.entry.grid(row=1, column=0, columnspan=2, pady=(0, 20), sticky="ew")
        self.entry.bind("<Return>", lambda event: self._on_ok())

        self.button_ok = customtkinter.CTkButton(self, text="OK", command=self._on_ok)
        self.button_ok.grid(row=2, column=0, padx=5, sticky="e")

        self.button_cancel = customtkinter.CTkButton(self, text="Cancel", fg_color="transparent", border_width=1, command=self._on_cancel)
        self.button_cancel.grid(row=2, column=1, padx=5, sticky="w")

        # Center on screen
        self.after(10, self._center_window)

    def _center_window(self):
        self.update_idletasks()
        width = self.winfo_width()
        height = self.winfo_height()
        x = (self.winfo_screenwidth() // 2) - (width // 2)
        y = (self.winfo_screenheight() // 2) - (height // 2)
        self.geometry(f"{width}x{height}+{x}+{y}")
        self.entry.focus()

    def _on_ok(self):
        self.result = self.entry.get()
        self.destroy()

    def _on_cancel(self):
        self.result = None
        self.destroy()

    def get_input(self):
        self.wait_window()
        return self.result
