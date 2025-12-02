from plugins.base_plugin import BasePlugin
import customtkinter
import os 

class Plugin(BasePlugin):
    def __init__(self, app):
        super().__init__(
            id="005",
            order=5,
            name="Calculator",
            status="OK",
            translations={"US": "Calculator", "ES": "Calculadora", "FR": "Calculatrice"},
            icon_light_path=os.path.join(os.path.dirname(os.path.realpath(__file__)), "calculator_light.png"),
            icon_dark_path=os.path.join(os.path.dirname(os.path.realpath(__file__)), "calculator_dark.png"),
        )
        self.app = app

    def create_main_screen(self):
        self.main_frame = customtkinter.CTkFrame(self.app, corner_radius=0, fg_color="transparent")
        self.main_frame.grid_columnconfigure(0, weight=1)
        self.main_frame.grid_rowconfigure((0, 1, 2), weight=1)

        self.profile_name_label = customtkinter.CTkLabel(self.main_frame, text="Plugin_2 Downloaded", font=customtkinter.CTkFont(size=20))
        self.profile_name_label.grid(row=0, column=0, padx=20, pady=10)
        self.entry = customtkinter.CTkEntry(self.main_frame, width=200, font=customtkinter.CTkFont(size=20))
        self.entry.grid(row=1, column=0, padx=20, pady=10)

        button_frame = customtkinter.CTkFrame(self.main_frame)
        button_frame.grid(row=2, column=0, padx=20, pady=10)

        buttons = [
            '7', '8', '9', '/',
            '4', '5', '6', '*',
            '1', '2', '3', '-',
            '0', '.', '=', '+'
        ]

        row_val = 0
        col_val = 0
        for button in buttons:
            action = lambda x=button: self.on_button_click(x)
            b = customtkinter.CTkButton(button_frame, text=button, command=action, width=50, height=50)
            b.grid(row=row_val, column=col_val, padx=5, pady=5)
            col_val += 1
            if col_val > 3:
                col_val = 0
            row_val += 1

        def on_button_click(self, char):
            if char == '=':
                try:
                    result = str(eval(self.entry.get()))
                    self.entry.delete(0, customtkinter.END)
                    self.entry.insert(customtkinter.END, result)
                except Exception as e:
                    self.entry.delete(0, customtkinter.END)
                    self.entry.insert(customtkinter.END, "Error")
            else:
                current_text = self.entry.get()
                self.entry.delete(0, customtkinter.END)
                self.entry.insert(customtkinter.END, current_text + char)
 

        return self.main_frame

    def get_call_list(self):
        pass

    def get_dashboard_tile_code(self):
        pass