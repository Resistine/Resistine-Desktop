import customtkinter
import requests
import json
import os
import re
import logging
from PIL import Image
from plugins.base_plugin import BasePlugin
from plugins.login import config
from plugins.login.api import LoginAPI
from utils import config_manager

# Set up logger for this module
logger = logging.getLogger(__name__)

class Plugin(BasePlugin):
    REGISTRATION_GRID_ROWS = 8
    REGISTRATION_GRID_COLS = 3
    
    def __init__(self, app):
        self.app = app
        self.email = None
        
        # API endpoint
        self.api_base_url = "https://validate.resistine.work"
        self.api = LoginAPI(self.api_base_url)
        
        # Reference to the currently active input field
        self.active_input_entry = None 

    def create_main_screen(self):
        """
        Initial login screen with centered "Login" button, "Resistine" name, and logo.
        """
        logger.debug("Login plugin: Creating main screen...")
        self.login_frame = customtkinter.CTkFrame(self.app, corner_radius=0, fg_color=self.app.cget("fg_color"))
        self.login_frame.grid(row=0, column=0, sticky="nsew")
        logger.debug("Login plugin: Main screen created")

        # Grid config for centering the sub-frame
        self.login_frame.grid_rowconfigure(0, weight=1)  # Top spacer
        self.login_frame.grid_rowconfigure(1, weight=0)  # Center row for sub-frame
        self.login_frame.grid_rowconfigure(2, weight=1)  # Bottom spacer
        self.login_frame.grid_columnconfigure(0, weight=1)

        # Sub-frame for centering logo/name and button together
        self.center_frame = customtkinter.CTkFrame(self.login_frame, corner_radius=0, fg_color=self.login_frame.cget("fg_color"))
        self.center_frame.grid(row=1, column=0, sticky="n")  # Center horizontally, top of row

        # Grid inside sub-frame: logo/name on top, button below
        self.center_frame.grid_rowconfigure(0, weight=0)
        self.center_frame.grid_rowconfigure(1, weight=0)
        self.center_frame.grid_columnconfigure(0, weight=1)

        # Load logo
        logo_path = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.realpath(__file__)))), "resources", "icons", "icon.ico")
        try:
            logo_image = Image.open(logo_path)
            logo_image = logo_image.resize((60, 60))
            logo = customtkinter.CTkImage(logo_image, size=(60, 60))
        except Exception as e:
            logger.warning(f"Logo load failed: {e}")
            logo = None

        # Resistine label with logo (top of sub-frame)
        self.resistine_label = customtkinter.CTkLabel(
            self.center_frame, 
            text=" Resistine", 
            image=logo, 
            compound="left", 
            font=("Arial", 32)
        )
        self.resistine_label.grid(row=0, column=0, padx=20, pady=10, sticky="n")

        # Centered login button (below logo in sub-frame)
        self.login_button = customtkinter.CTkButton(
            self.center_frame, 
            text="Login", 
            command=self.show_registration_screen, 
            font=("Arial", 20)
        )
        self.login_button.grid(row=1, column=1, padx=10, pady=20, sticky="n")

        # Skip button (left of Login button)
        self.skip_button = customtkinter.CTkButton(
            self.center_frame,
            text="Skip",
            command=self.skip_login,
            font=("Arial", 20),
            fg_color="transparent",
            border_width=2,
            text_color=("gray10", "gray90")
        )
        self.skip_button.grid(row=1, column=0, padx=10, pady=20, sticky="n")

        return self.login_frame

    def skip_login(self):
        """
        Skip the login process and go directly to the dashboard.
        """
        logger.info("User skipped login")
        self.app.destroy_login_screen()
        self.app.create_dashboard()

    def show_registration_screen(self):
        """
        Show the email entry screen after clicking Login.
        """
        self.login_frame.destroy()  # Remove the login button
        self.create_registration_screen()

    def create_registration_screen(self):
        """
        Create the registration screen where the user can enter their email and register.
        """
        self.registration_frame = customtkinter.CTkFrame(self.app, corner_radius=0, fg_color=self.app.cget("fg_color"))
        self.registration_frame.grid(row=0, column=0, sticky="nsew")

        for i in range(self.REGISTRATION_GRID_ROWS):
            self.registration_frame.grid_rowconfigure(i, weight=1)
        for i in range(self.REGISTRATION_GRID_COLS):
            self.registration_frame.grid_columnconfigure(i, weight=1)
            
        # Back button (top left)
        self.back_button = customtkinter.CTkButton(
            self.registration_frame,
            text="← Back",
            command=self.go_back,
            width=80,
            height=30,
            fg_color="transparent",
            text_color=("gray10", "gray90"),
            anchor="w"
        )
        self.back_button.grid(row=0, column=0, padx=20, pady=20, sticky="nw")

        self.welcome_label = customtkinter.CTkLabel(self.registration_frame, text="Welcome to Resistine", font=("Arial", 24))
        self.welcome_label.grid(row=1, column=1, padx=20, pady=20, sticky="nsew")
        self.subtitle_label = customtkinter.CTkLabel(self.registration_frame, text="Please enter your email to receive an OTP", font=("Arial", 16))
        self.subtitle_label.grid(row=2, column=1, padx=20, pady=10, sticky="ew")
        
        # Initial Email Input Field
        self.email_entry = customtkinter.CTkEntry(self.registration_frame, placeholder_text="Enter your email")
        self.email_entry.grid(row=3, column=1, padx=20, pady=20, sticky="ew")
        
        # Set the active input to the email entry initially
        self.active_input_entry = self.email_entry

        # Single button that transforms from Send OTP to Verify OTP
        self.action_button = customtkinter.CTkButton(self.registration_frame, text="Send OTP", command=self.send_otp)
        self.action_button.grid(row=4, column=1, padx=20, pady=20, sticky="nsew")

        # Status Label
        self.status_label = customtkinter.CTkLabel(
            self.registration_frame, 
            text="", 
            font=("Arial", 12)
        )
        self.status_label.grid(row=7, column=1, padx=20, pady=10)

    def go_back(self):
        """
        Handle back button click.
        If in OTP mode, go back to email entry.
        If in Email mode, go back to main login screen.
        """
        if hasattr(self, 'otp_entry') and self.otp_entry.winfo_exists():
            # In OTP mode, go back to email entry
            self.otp_entry.destroy()
            self.subtitle_label.configure(text="Please enter your email to receive an OTP")
            
            # Recreate email entry
            self.email_entry = customtkinter.CTkEntry(self.registration_frame, placeholder_text="Enter your email")
            self.email_entry.grid(row=3, column=1, padx=20, pady=20, sticky="ew")
            if self.email:
                self.email_entry.insert(0, self.email)
            
            self.active_input_entry = self.email_entry
            self.action_button.configure(text="Send OTP", command=self.send_otp)
            self.status_label.configure(text="")
        else:
            # In Email mode, go back to main login screen
            self.registration_frame.destroy()
            self.create_main_screen()

    def send_otp(self):
        """Send OTP to customer email via Resistine API"""
        email = self.email_entry.get().strip()
        
        # Validate email format
        email_regex = r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$'
        if not email:
            self.update_status("Please enter an email address", "red")
            return
        elif not re.match(email_regex, email):
            self.update_status("Please enter a valid email address", "red")
            return

        # Store email
        self.email = email
        
        # Send OTP via API - API handles all validation
        self.send_otp_api(email)

    def send_otp_api(self, email):
        """Send OTP via Resistine API (server generates and validates the OTP)"""
        self.update_status("Sending OTP...", "blue")
        
        success, message, result = self.api.send_otp(email)
        
        if success:
            self.update_status(message, "green")
            self.transform_to_otp_input()
        else:
            self.update_status(f"Error: {message}", "red")

    def verify_otp(self):
        """Verify the entered OTP with Resistine API"""
        entered_otp = self.active_input_entry.get().strip()
        
        if not entered_otp:
            self.update_status("Please enter the OTP", "red")
            return
        
        self.update_status("Verifying OTP with server...", "blue")
        
        try:
            import sys
            
            # Dynamic import based on platform
            if sys.platform == "darwin":
                from plugins.login import login_darwin as platform_login
            elif sys.platform == "linux":
                from plugins.login import login_linux as platform_login
            else:
                self.update_status(f"Unsupported platform: {sys.platform}", "red")
                return

            # Step 1: Setup VPN keys (Generate/Save/Get Public Key)
            public_key = platform_login.setup_vpn_keys()
            if not public_key:
                self.update_status("Failed to setup VPN keys", "red")
                return
            
            # Log key validation without exposing sensitive data
            logger.debug(f"WireGuard Public Key Validated: Length={len(public_key)} characters")
            
            # Step 2: Verify OTP with API
            success, message, result = self.api.verify_otp(self.email, entered_otp, public_key)
            
            if success:
                self.update_status(message, "green")
                
                # Log API response status
                safe_result = {
                    "status": result.get("status", ""),
                    "message": result.get("message", ""),
                    "vpn_config_received": bool(result.get("vpn_config", "")),
                }
                logger.info(f"API Response Status: {json.dumps(safe_result)}")
                
                # Step 3: Save VPN Configuration
                vpn_config_json = result.get("vpn_config", "")
                if vpn_config_json:
                    config_path = platform_login.save_vpn_configuration(vpn_config_json)
                    if config_path:
                        logger.info(f"VPN configuration saved to {config_path}")
                    else:
                        logger.warning("Failed to save VPN configuration")
                
                # Save login state
                config_manager.save_login_state(self.email)
                
                # Small delay to show success message, then transition
                def transition_to_dashboard():
                    self.app.destroy_login_screen()
                    self.app.create_dashboard()
                
                self.app.after(500, transition_to_dashboard)
            else:
                self.update_status(f"Error: {message}", "red")
                self.active_input_entry.delete(0, 'end')
                
        except Exception as e:
            logger.exception("Verification error")
            self.update_status(f"Verification error: {str(e)}", "red")

    def on_otp_key_press(self, event):
        """Only allow digits in the OTP field"""
        # Allow digits, backspace, delete, and navigation keys
        allowed_keys = ['BackSpace', 'Delete', 'Left', 'Right', 'Home', 'End', 'Tab']
        if event.char and not event.char.isdigit() and event.keysym not in allowed_keys:
            return 'break'

    def update_status(self, message, color="white"):
        """Update status label with message and color"""
        self.status_label.configure(text=message, text_color=color)
        self.status_label.update()

    def get_name(self):
        return self.name

    def get_icon(self):
        return self.icon

    def get_button(self):
        return self.button

    def set_button(self, button):
        self.button = button

    def transform_to_otp_input(self):
        """Destroy the email entry and create a fresh OTP entry field."""
        
        # 1. Destroy the old email entry
        self.email_entry.destroy()
        
        # 2. Update the subtitle
        self.subtitle_label.configure(text=f"Enter the 6-digit code sent to {self.email}")
        
        # 3. Create the new OTP input field
        self.otp_entry = customtkinter.CTkEntry(
            self.registration_frame, 
            placeholder_text="Enter OTP",
            show="*" # Crucial for masking input
        )
        
        # 4. Grid the new entry in the same spot
        self.otp_entry.grid(row=3, column=1, padx=20, pady=20, sticky="ew")
        
        # 5. Update the active input reference
        self.active_input_entry = self.otp_entry
        
        # 6. Bind the key press event for validation
        self.otp_entry.bind("<KeyPress>", self.on_otp_key_press)
        
        # 7. Focus on the new input field
        self.otp_entry.focus_set()
        
        # 8. Update the button
        self.action_button.configure(text="Verify OTP", command=self.verify_otp)
