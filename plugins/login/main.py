import customtkinter
import requests
import json
import os
import re
from PIL import Image
from plugins.base_plugin import BasePlugin

class Plugin(BasePlugin):
    def __init__(self, app):
        self.app = app
        self.email = None
        
        # API endpoint
        self.api_base_url = "https://validate.resistine.work"
        
        # Reference to the currently active input field
        self.active_input_entry = None 

    def create_main_screen(self):
        """
        Initial login screen with centered "Login" button, "Resistine" name, and logo.
        """
        print("🔐 Login plugin: Creating main screen...")
        self.login_frame = customtkinter.CTkFrame(self.app, corner_radius=0, fg_color=self.app.cget("fg_color"))
        self.login_frame.grid(row=0, column=0, sticky="nsew")
        print("✅ Login plugin: Main screen created")

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
            print(f"Logo load failed: {e}")
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
        self.login_button.grid(row=1, column=0, padx=20, pady=20, sticky="n")

        return self.login_frame

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

        for i in range(8):  # Adjusted for more rows
            self.registration_frame.grid_rowconfigure(i, weight=1)
        for i in range(3):
            self.registration_frame.grid_columnconfigure(i, weight=1)

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
        try:
            api_url = f"{self.api_base_url}/send-otp"
            payload = {
                "email": email
            }
            
            self.update_status("Sending OTP...", "blue")
            
            response = requests.post(api_url, json=payload, timeout=90)
            
            if response.status_code in range(200, 300):
                # Success status code - treat as success
                try:
                    result = response.json()
                    # Get message from API response if available
                    message = result.get("message", "") if isinstance(result, dict) else ""
                    status = result.get("status", "").lower() if isinstance(result, dict) else ""
                    
                    # Check if there's an explicit error status
                    if status in ["error", "failed", "failure"]:
                        error_msg = message or result.get("error", "Failed to send OTP")
                        self.update_status(f"Error: {error_msg}", "red")
                    else:
                        # Success - use API message if available, otherwise use default
                        success_msg = message if message else "OTP sent successfully! Check your email."
                        self.update_status(success_msg, "green")
                        self.transform_to_otp_input()
                except (ValueError, KeyError, json.JSONDecodeError):
                    # If response is not valid JSON, assume success if status is 200-299
                    self.update_status("OTP sent successfully! Check your email.", "green")
                    self.transform_to_otp_input()
            else:
                # Error status code
                try:
                    result = response.json()
                    error_msg = result.get("message") or result.get("error", f"Server error {response.status_code}")
                    self.update_status(f"Error: {error_msg}", "red")
                except (ValueError, KeyError, json.JSONDecodeError):
                    self.update_status(f"Failed to send OTP: Server error {response.status_code}", "red")
                
        except requests.exceptions.RequestException as e:
            self.update_status(f"Network error: {str(e)}", "red")
        except Exception as e:
            self.update_status(f"Error sending OTP: {str(e)}", "red")

    def verify_otp(self):
        """Verify the entered OTP with Resistine API"""
        entered_otp = self.active_input_entry.get().strip()
        
        if not entered_otp:
            self.update_status("Please enter the OTP", "red")
            return
        
        self.update_status("Verifying OTP with server...", "blue")
        
        try:
            import sys
            import base64
            
            # Import keychain utilities and VPN functions
            sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))
            from utils.keychain_darwin import (
                save_wireguard_keys, 
                delete_wireguard_keys,
                get_wireguard_private_key,
                get_wireguard_public_key
            )
            from plugins.vpn.wireguard import vpn_functions_darwin as vpn_funcs
            
            # Step 1: Regenerate fresh keys for this sign-in session
            # Delete old keys (if they exist) to ensure fresh key pair
            delete_wireguard_keys()
            
            # Generate new key pair
            keys = vpn_funcs.generate_wireguard_keys()
            if not keys:
                self.update_status("Failed to generate keys", "red")
                return
            
            # Save both private and public keys to Keychain with iOS-compatible service names
            if not save_wireguard_keys(keys['private_key'], keys['public_key']):
                self.update_status("Failed to save keys securely", "red")
                return
            
            # Get base64-encoded public key for API transmission
            public_key_b64 = keys['public_key_b64']
            
            if not public_key_b64:
                self.update_status("Failed to get public key", "red")
                return
            
            api_url = f"{self.api_base_url}/verify-otp"
            payload = {
                "email": self.email,
                "otp": entered_otp,
                "host_url": "rfr1.resisti.net",
                "vpn_name": "testVPNapi",
                "client_public_key": public_key_b64
            }
            
            response = requests.post(api_url, json=payload, timeout=90)
            
            if response.status_code in range(200, 300):
                try:
                    result = response.json()
                except Exception as e:
                    print(f"❌ Error parsing JSON: {e}")
                    result = {}
                
                # Check for success - handle different response formats
                status = result.get("status", "").lower() if isinstance(result, dict) else ""
                message = result.get("message", "") if isinstance(result, dict) else ""
                
                # Check if verification was successful (status="success" or "verified" OR message contains "success" or "verified")
                if status == "success" or status == "verified" or "success" in message.lower() or "verified" in message.lower():
                    self.update_status("OTP verified successfully!", "green")
                    
                    # Parse and create VPN config if provided
                    vpn_config_json = result.get("vpn_config", "") if isinstance(result, dict) else ""
                    if vpn_config_json:
                        try:
                            from plugins.vpn.wireguard import vpn_functions_darwin as vpn_funcs
                            config_path = vpn_funcs.parse_and_create_vpn_config(vpn_config_json, config_name="wg0")
                            if config_path:
                                print(f"✅ VPN configuration saved successfully")
                            else:
                                print(f"⚠️  Warning: Failed to create VPN config")
                        except Exception as e:
                            print(f"⚠️  Warning: Error creating VPN config: {e}")
                    
                    # Small delay to show success message, then transition
                    def transition_to_dashboard():
                        self.app.destroy_login_screen()
                        self.app.create_dashboard()
                    
                    self.app.after(500, transition_to_dashboard)
                else:
                    self.update_status(f"OTP verification failed: {message or 'Unknown error'}", "red")
                    
            else:
                self.update_status(f"Server error: {response.status_code}", "red")
                
        except requests.exceptions.RequestException as e:
            self.update_status(f"Network error: {str(e)}", "red")
        except Exception as e:
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
