"""
Login Plugin for Resistine Desktop
Handles OTP authentication with Odoo backend
Author: Peres J.
Copyright (c) Resistine 2025
Licensed under the Apache License 2.0
"""

import customtkinter
import requests
import json
import secrets
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
import os
import re
from PIL import Image
from plugins.base_plugin import BasePlugin
from .config import *

class Plugin(BasePlugin):
    def __init__(self, app):
        
       
        self.app = app
        self.otp = None
        self.email = None
        
        # Odoo API Configuration
        self.odoo_url = ODOO_URL
        self.odoo_db = ODOO_DB
        self.odoo_username = ODOO_USERNAME
        self.odoo_password = ODOO_PASSWORD
        
        # SMTP Configuration
        self.smtp_server = SMTP_SERVER
        self.smtp_port = SMTP_PORT
        self.smtp_username = SMTP_USERNAME
        self.smtp_password = SMTP_PASSWORD

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
        
        # Single input field that transforms from email to OTP
        self.input_entry = customtkinter.CTkEntry(self.registration_frame, placeholder_text="Enter your email")
        self.input_entry.grid(row=3, column=1, padx=20, pady=20, sticky="ew")

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

    def authenticate_with_odoo(self):
        """Authenticate with Odoo and get session info"""
        try:
            auth_url = f"{self.odoo_url}/web/session/authenticate"
            auth_data = {
                "jsonrpc": "2.0",
                "method": "call",
                "params": {
                    "db": self.odoo_db,
                    "login": self.odoo_username,
                    "password": self.odoo_password
                },
                "id": 1
            }
            
            response = requests.post(auth_url, json=auth_data)
            if response.status_code == 200:
                result = response.json()
                if "error" not in result:
                    return response.cookies
            return None
        except Exception as e:
            print(f"Odoo authentication error: {e}")
            return None

    def check_customer_exists(self, email):
        """Check if customer exists in Odoo"""
        try:
            cookies = self.authenticate_with_odoo()
            if not cookies:
                return False

            search_url = f"{self.odoo_url}/web/dataset/call_kw"
            search_data = {
                "jsonrpc": "2.0",
                "method": "call",
                "params": {
                    "model": "res.partner",
                    "method": "search_read",
                    "args": [[["email", "=", email]]],
                    "kwargs": {"fields": ["email", "name", "is_company"]}
                },
                "id": 1
            }
            
            response = requests.post(search_url, json=search_data, cookies=cookies)
            if response.status_code == 200:
                result = response.json()
                return len(result.get("result", [])) > 0
            return False
        except Exception as e:
            print(f"Error checking customer: {e}")
            return False

    def generate_otp(self):
        """Generate a 6-digit OTP"""
        return str(secrets.randbelow(10**OTP_LENGTH - 10**(OTP_LENGTH-1)) + 10**(OTP_LENGTH-1))

    def send_otp_email(self, email, otp):
        """Send OTP via email"""
        try:
            if not self.smtp_password:
                # For testing, just show the OTP
                self.update_status(f"OTP for testing: {otp}", "orange")
                return True

            msg = MIMEMultipart()
            msg['From'] = self.smtp_username
            msg['To'] = email
            msg['Subject'] = "Resistine Login Verification Code"
            
            body = f"""
            Your Resistine login verification code is: {otp}
            
            This code will expire in {OTP_EXPIRY_MINUTES} minutes.
            
            If you didn't request this code, please ignore this email.
            """
            
            msg.attach(MIMEText(body, 'plain'))
            
            server = smtplib.SMTP(self.smtp_server, self.smtp_port)
            server.starttls()
            server.login(self.smtp_username, self.smtp_password)
            text = msg.as_string()
            server.sendmail(self.smtp_username, email, text)
            server.quit()
            
            return True
        except Exception as e:
            print(f"Error sending email: {e}")
            return False

    def send_otp(self):
        """Send OTP to customer email"""
        email = self.input_entry.get().strip()
        
        # Validate email format
        email_regex = r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$'
        if not email:
            self.update_status("Please enter an email address", "red")
            return
        elif not re.match(email_regex, email):
            self.update_status("Please enter a valid email address", "red")
            return

        self.update_status("Checking customer status...", "blue")
        
        # Check if customer exists
        if not self.check_customer_exists(email):
            self.update_status("Email not found in our customer database", "red")
            return

        # Generate and send OTP
        self.otp = self.generate_otp()
        self.email = email
        
        # OTP generated and stored successfully
        
        if self.send_otp_email(email, self.otp):
            self.update_status("OTP sent successfully! Check your email.", "green")
            self.transform_to_otp_input()
        else:
            self.update_status("Failed to send OTP. Please try again.", "red")

    def transform_to_otp_input(self):
        """Transform the email input to OTP input for better UX"""
        # Update the subtitle
        self.subtitle_label.configure(text="Enter the 6-digit code sent to your email")
        
        # Clear the input field once
        self.input_entry.delete(0, 'end')
        
        # Reconfigure the input field for OTP with proper placeholder
        self.input_entry.configure(
            placeholder_text="Enter 6-digit OTP",
            show="*"  # Hide the OTP as user types for security
        )
        
        # Update the button
        self.action_button.configure(text="Verify OTP", command=self.verify_otp)

    def verify_otp(self):
        """Verify the entered OTP"""
        entered_otp = self.input_entry.get().strip()
        print(entered_otp)
        print(self.input_entry.get().strip())
        if not entered_otp:
            self.update_status("Please enter the OTP", "red")
            return
        
        # Verify OTP match
        
        if entered_otp == self.otp:
            self.update_status("Login successful!", "green")
            # No need to save email settings - Odoo handles customer data
            self.app.destroy_login_screen()
            self.app.create_dashboard()
        else:
            self.update_status("Invalid OTP. Please try again.", "red")

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
