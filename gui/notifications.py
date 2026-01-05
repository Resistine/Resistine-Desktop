import customtkinter
from customtkinter import ThemeManager
from utils.logger import logger


class ToastNotification(customtkinter.CTkFrame):
    """
    Non-blocking, animated toast notification that overlays the main window.
    """

    def __init__(self, master, text, icon_color="green", **kwargs):
        super().__init__(
            master,
            corner_radius=20,
            fg_color=("gray90", "gray20"),
            border_width=1,
            border_color=("gray80", "gray30"),
            **kwargs,
        )

        # Icon (color dot)
        self.icon = customtkinter.CTkFrame(
            self, width=15, height=15, corner_radius=10, fg_color=icon_color
        )
        self.icon.pack(side="left", padx=(15, 10), pady=10)

        # Text
        text_color = ThemeManager.theme["CTkLabel"]["text_color"]
        self.label = customtkinter.CTkLabel(
            self, text=text, font=customtkinter.CTkFont(size=14), text_color=text_color,
            wraplength=400
        )
        self.label.pack(side="left", padx=(0, 20), pady=10)

        # Animation state
        self.y_pos = -0.1  # Start above screen
        self.target_y = 0.05
        self.master = master
        self.is_destroying = False

    def show(self):
        # Place relative to the top of the master window
        self.master.update_idletasks()
        
        # Force a width for centering if content is small
        self.configure(width=400)
        
        self.place(relx=0.5, rely=self.y_pos, anchor="n")
        
        # Lift above everything
        self.lift()
        self.attributes('-topmost', True) if isinstance(self, customtkinter.CTkToplevel) else None
        
        logger.info(f"Showing notification: '{self.label.cget('text')[:20]}...' at relx=0.5, rely={self.y_pos}")
        self.animate_in()

    def animate_in(self):
        if self.is_destroying:
            return
        if self.y_pos < self.target_y:
            self.y_pos += 0.01 # Faster animation
            self.place(relx=0.5, rely=self.y_pos, anchor="n")
            self.master.after(10, self.animate_in)
        else:
            self.master.after(3000, self.animate_out) # Show for 3 seconds

    def animate_out(self):
        self.is_destroying = True
        if self.y_pos > -0.2:
            self.y_pos -= 0.01
            self.place(relx=0.5, rely=self.y_pos, anchor="n")
            self.master.after(10, self.animate_out)
        else:
            self.destroy()
