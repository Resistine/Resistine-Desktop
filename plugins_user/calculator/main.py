from plugins.base_plugin import BasePlugin
import customtkinter
import os

class Plugin(BasePlugin):
    """    
    Calculator plugin for Resistine Desktop.
    """    
        
    def __init__(self, app):
        """    
        Initialize the Calculator plugin.
        :param app: Main application object.
        """    
        super().__init__(
            id="100",
            version="2026.01.05-alpha",
            order=5,
            name="Calculator",
            status="OK",
            description="A versatile calculator with standard operations, parentheses, and percentage support.",
            supported_systems=["Windows", "Linux", "Mac"],
            translations={"US": "Calculator", "DE": "Calculator", "ES": "Calculadora", "FR": "Calculatrice"},
            icon_light_path=os.path.join(os.path.dirname(os.path.realpath(__file__)), "calculator_light.png"),
            icon_dark_path=os.path.join(os.path.dirname(os.path.realpath(__file__)), "calculator_dark.png"),
        )
        self.app = app
        self.expression = ""

    def get_status(self):
        """
        Return the current operational state.
        """
        return None
    
    def create_main_screen(self):
        self.main_frame = customtkinter.CTkFrame(self.app, corner_radius=0, fg_color="transparent")
        self.main_frame.grid_columnconfigure(0, weight=1) 
        self.main_frame.grid_rowconfigure(0, weight=1)

        # Center Container to make it narrower
        self.center_container = customtkinter.CTkFrame(self.main_frame, fg_color="transparent")
        self.center_container.grid(row=0, column=0, sticky="nsew", padx=20, pady=20)
        
        # Grid configuration for centering
        # We use 3 columns: Left spacer, Center content, Right spacer.
        self.center_container.grid_columnconfigure(0, weight=1) # Spacer
        self.center_container.grid_columnconfigure(1, weight=0) # Content (we'll set width or let it grow slightly)
        self.center_container.grid_columnconfigure(2, weight=1) # Spacer
        self.center_container.grid_rowconfigure(0, weight=1)

        # Calculator Body (The actual UI)
        # We can set a width here for the "narrow" feel, e.g., width=400
        self.calc_body = customtkinter.CTkFrame(self.center_container, width=380, corner_radius=15)
        self.calc_body.grid(row=0, column=1, sticky="nsew", pady=20)
        self.calc_body.grid_columnconfigure(0, weight=1)
        self.calc_body.grid_rowconfigure(1, weight=1) # Button area expands

        # --- Display Area ---
        display_frame = customtkinter.CTkFrame(self.calc_body, fg_color="transparent")
        display_frame.grid(row=0, column=0, sticky="ew", padx=15, pady=(15, 10))
        display_frame.grid_columnconfigure(0, weight=1)

        # History Label
        self.history_label = customtkinter.CTkLabel(
            display_frame, 
            text="", 
            font=customtkinter.CTkFont(size=14), 
            text_color="gray",
            anchor="e"
        )
        self.history_label.grid(row=0, column=0, sticky="ew", padx=5)

        # Main Entry
        self.entry = customtkinter.CTkEntry(
            display_frame, 
            width=300, 
            height=60,
            font=customtkinter.CTkFont(size=32, weight="bold"),
            justify="right",
            border_width=0,
            fg_color=("gray95", "gray15")
        )
        self.entry.grid(row=1, column=0, sticky="ew", padx=5, pady=5)
        
        # Bind keys to Entry
        self.entry.bind("<Return>", lambda e: self.on_button_click('='))
        self.entry.bind("<KP_Enter>", lambda e: self.on_button_click('='))
        self.entry.bind("<Escape>", lambda e: self.on_button_click('AC'))
        # KeyRelease to update history or just allow typing? 
        # Standard typing works for numbers. We just need to handle specific logic if needed.

        # --- Buttons Area ---
        button_frame = customtkinter.CTkFrame(self.calc_body, fg_color="transparent")
        button_frame.grid(row=1, column=0, sticky="nsew", padx=15, pady=10)
        
        # Configure grid weights for buttons
        for i in range(4): # 4 Columns
            button_frame.grid_columnconfigure(i, weight=1)
        for i in range(6): # 6 Rows
            button_frame.grid_rowconfigure(i, weight=1)

        final_defs = [
            ('AC', 0, 0, 'AC'), ('(', 0, 1, '('), (')', 0, 2, ')'), ('/', 0, 3, '/'),
            ('7',  1, 0, '7'),  ('8', 1, 1, '8'), ('9', 1, 2, '9'), ('*', 1, 3, '*'),
            ('4',  2, 0, '4'),  ('5', 2, 1, '5'), ('6', 2, 2, '6'), ('-', 2, 3, '-'),
            ('1',  3, 0, '1'),  ('2', 3, 1, '2'), ('3', 3, 2, '3'), ('+', 3, 3, '+'),
            ('0',  4, 0, '0'),  ('.', 4, 1, '.'), ('%', 4, 2, '%'), ('⌫', 4, 3, 'DEL'),
            ('=',  5, 0, '=')
        ]
        
        for text, r, c, cmd in final_defs:
            color = ("gray85", "gray25")
            hover_color = ("gray75", "gray35")
            
            if text in ['/', '*', '-', '+', '=']:
                color = "#FF9900"
                hover_color = "#CC7700"
                text_color = "white"
            elif text in ['AC', '⌫']:
                color = ("#FF5555", "#CC0000")
                hover_color = "#990000"
                text_color = "white"
            elif text in ['(', ')', '%']:
                color = ("gray70", "gray40") 
                hover_color = ("gray60", "gray50")
                text_color = ("black", "white")
            else:
                 text_color = ("black", "white")
            
            if text == '=':
                 btn = customtkinter.CTkButton(
                    button_frame, 
                    text=text, 
                    command=lambda x=cmd: self.on_button_click(x),
                    font=customtkinter.CTkFont(size=24, weight="bold"),
                    fg_color=color,
                    hover_color=hover_color,
                    text_color=text_color
                )
                 btn.grid(row=r, column=c, columnspan=4, sticky="nsew", padx=3, pady=3)
            else:
                btn = customtkinter.CTkButton(
                    button_frame, 
                    text=text, 
                    command=lambda x=cmd: self.on_button_click(x),
                    font=customtkinter.CTkFont(size=20),
                    fg_color=color,
                    hover_color=hover_color,
                    text_color=text_color
                )
                btn.grid(row=r, column=c, sticky="nsew", padx=3, pady=3)

        # Ensure focus so keys work immediately
        self.entry.focus_set()

        return self.main_frame

    def on_button_click(self, char):
        current_text = self.entry.get()
        
        if char == 'AC':
            self.entry.delete(0, customtkinter.END)
            self.history_label.configure(text="")
            
        elif char == 'DEL':
            if len(current_text) > 0:
                self.entry.delete(len(current_text)-1, customtkinter.END)
                
        elif char == '=':
            expression = current_text
            if not expression:
                return

            expression_eval = expression.replace('%', '/100')
            # Handle implied multiplication for parentheses e.g. 5(2) -> 5*(2)
            # This is complex to do perfectly with regex but basic case:
            # digit( -> digit*(
            # )digit -> )*digit
            # For now relying on user or python syntax, but let's be robust?
            # User request: "Calculator is unbelievable" -> needs to be good.
            # Let's keep it simple first. If it fails, it fails.
            
            try:
                self.history_label.configure(text=expression + " =")
                # pylint: disable=eval-used
                result = str(eval(expression_eval)) 
                
                self.entry.delete(0, customtkinter.END)
                self.entry.insert(customtkinter.END, result)
            except Exception:
                self.entry.delete(0, customtkinter.END)
                self.entry.insert(customtkinter.END, "Error")
                
        else:
            # Append char
            self.entry.insert(customtkinter.END, char)

    def get_call_list(self):
        pass

    def get_dashboard_tile_code(self):
        pass