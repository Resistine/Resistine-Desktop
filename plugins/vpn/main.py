## @file plugins/vpn/main.py
## @package vpn_plugin
## @namespace vpn_plugin
## @class vpn_plugin::Plugin
"""
This module contains the main plugin class for the VPN plugin.
The VPN plugin displays VPN information and allows the user to manage VPN tunnels.
Author: Javier Perez and Jacqueline Edoro 
Copyright (c) Resistine 2025
Licensed under the Apache License 2.0
"""

from plugins.base_plugin import BasePlugin
import customtkinter
import os 
import tkinter as tk
import platform
from utils.encryption import *  # Ensure this module is correctly installed or replace with the correct one
from tkinter import filedialog
from PIL import Image
import subprocess
import ctypes
import sys
from utils.keys import write_demo_config_if_absent

# Function to get writable WireGuard directory
def get_writable_wireguard_dir():
    """Get a writable directory for WireGuard configuration files"""
    if platform.system() == "Darwin":
        # Use ~/Library/Application Support/Resistine AI/wireguard for macOS
        home_dir = os.path.expanduser("~")
        app_support_dir = os.path.join(home_dir, "Library", "Application Support", "Resistine AI")
        wireguard_dir = os.path.join(app_support_dir, "wireguard")
        os.makedirs(wireguard_dir, exist_ok=True)
        return wireguard_dir
    elif platform.system() == "Windows":
        # Use %APPDATA%/Resistine AI/wireguard for Windows
        appdata_dir = os.environ.get('APPDATA', os.path.expanduser("~"))
        wireguard_dir = os.path.join(appdata_dir, "Resistine AI", "wireguard")
        os.makedirs(wireguard_dir, exist_ok=True)
        return wireguard_dir
    else:
        # Use ~/.config/resistine-ai/wireguard for Linux
        home_dir = os.path.expanduser("~")
        config_dir = os.path.join(home_dir, ".config", "resistine-ai")
        wireguard_dir = os.path.join(config_dir, "wireguard")
        os.makedirs(wireguard_dir, exist_ok=True)
        return wireguard_dir

# Define the global variable and initialize vpn status
active_client_name = None
existing_interfaces = []

if platform.system() == "Windows":
    from plugins.vpn.wireguard.vpn_functions_windows import *
    try:
        existing_interfaces = subprocess.run(
            ['wg', 'show', 'interfaces'], capture_output=True, text=True, check=True
        ).stdout.split()
    except Exception:
        existing_interfaces = []
elif platform.system() == "Linux":
    from plugins.vpn.wireguard.vpn_functions_linux import *
    from python_wireguard import Client, ServerConnection, Key
    existing_interfaces = os.popen('wg show interfaces').read().split()
elif platform.system() == "Darwin":
    from plugins.vpn.wireguard.vpn_functions_darwin import *
    #from python_wireguard import Client, ServerConnection, Key
    existing_interfaces = os.popen('wg show interfaces').read().split()
else:
    raise NotImplementedError("Unsupported platform")


for interface in existing_interfaces:
        status = check_service_status(interface, "10.49.64.53")
        if status == "Running":
            active_client_name = interface
            break

my_vpn_status = check_service_status(active_client_name, "10.49.64.53") if active_client_name else "Stopped"
print(f"VPN Status in the init function : {my_vpn_status}")

# Function to update listbox colors based on theme
def update_listbox_colors(listbox):
    if customtkinter.get_appearance_mode() == "Dark":
        listbox.config(fg="white", bg="#2e2e2e")
    else:
        listbox.config(fg="black", bg="lightgray")

#Define the plugin class
class Plugin(BasePlugin):
    """
    @brief Plugin class for the VPN plugin.
    Plugin class for the VPN plugin, that displays the VPN information and allows the user to manage VPN tunnels.
    """
    def __init__(self, app):
        """
        @brief Initialize the VPN plugin.
        Initialize the VPN plugin with the required attributes.
        Args:
            app (App): The main application object.
        """
        super().__init__(
            id="008",
            order=8,
            name="VPN",
            description="VPN for windows",
            supported_systems=["Windows"],
            status="OK",
            translations={"US": "VPN", "ES": "VPN", "FR": "VPN"},
            icon_light_path=os.path.join(os.path.dirname(os.path.realpath(__file__)), "vpn_light.png"),
            icon_dark_path=os.path.join(os.path.dirname(os.path.realpath(__file__)), "vpn_dark.png"),
        )
        self.app = app


    #Create the main screen
    def create_main_screen(self):
        """
        @brief create_main_screen vpn plugin.
        Create the main screen for the VPN plugin.
        This method displays the VPN information and allows the user to manage VPN tunnels.
        """        

        #Getting the list of configuration files
        conf_files = self.get_list_of_tunnels()

        if not conf_files:
            # Create a demo config so users see the expected format
            try:
                write_demo_config_if_absent()
            except Exception as e:
                print(f"Failed to create demo config: {e}")
            conf_files = self.get_list_of_tunnels()

        if not conf_files:
            print("No configuration files found in wireguard folder")
            main_view = self.display_button_tunnel()
        else:
            print(f"Found configuration files: {conf_files}")
            main_view = self.display_vpn_info(conf_files)

        return main_view

    #Main screen with the button to add a tunnel in case there is not conf file. 
    def display_button_tunnel(self):
        """
        @brief display_button_tunnel vpn plugin.
        Display the main screen for the VPN plugin when there are no configuration files.
        This method displays a button to add a VPN tunnel configuration file.
        """
        self.main_container = customtkinter.CTkFrame(self.app, corner_radius=0, fg_color="transparent")
        self.main_container.grid_columnconfigure(0, weight=1)
        self.main_container.grid_rowconfigure(0, weight=1)
        self.main_container.grid_rowconfigure(1, weight=4)
        #name 20% of the hight 
        self.profile_name_label = customtkinter.CTkLabel(self.main_container, text="VPN", font=customtkinter.CTkFont(size=20))
        self.profile_name_label.grid(row=0, column=0, padx=20, pady=10)

        #container 80% of the height
        self.sub_frame_container = customtkinter.CTkFrame(self.main_container, corner_radius=0, fg_color="transparent")
        self.sub_frame_container.grid(row=1, column=0, sticky="nsew")
        self.sub_frame_container.grid_columnconfigure(0, weight=1)  # 5% width
        self.sub_frame_container.grid_columnconfigure(1, weight=19)  # 95% width
        self.sub_frame_container.grid_rowconfigure(0, weight=95)  # 95% height
        self.sub_frame_container.grid_rowconfigure(1, weight=5)  # 5% height

        # First container in column 0 (95% height)
        self.first_container_col0 = customtkinter.CTkFrame(self.sub_frame_container, corner_radius=0, fg_color="lightgray")
        self.first_container_col0.grid(row=0, column=0, sticky="nsew", padx=10, pady=(10, 5))
        self.first_container_col0.grid_rowconfigure(0, weight=1)
        self.first_container_col0.grid_columnconfigure(0, weight=1)

        # Second container in column 0 (5% height)
        self.second_container_col0 = customtkinter.CTkFrame(self.sub_frame_container, corner_radius=0, fg_color="transparent")
        self.second_container_col0.grid(row=1, column=0, sticky="nsew", padx=10, pady=(5, 10))
        self.second_container_col0.grid_rowconfigure(0, weight=1)
        self.second_container_col0.grid_columnconfigure(0, weight=1)

        # Add Tunnel button
        self.add_tunnel_button = customtkinter.CTkButton(self.second_container_col0, text="Add Tunnel", command=self.add_tunnel)
        self.add_tunnel_button.grid(row=0, column=0, padx=10, pady=5, sticky="sew")

        # Delete button (disabled)
        self.delete_button = customtkinter.CTkButton(self.second_container_col0, text="Delete", command=self.delete_tunnel, state=tk.DISABLED)
        self.delete_button.grid(row=0, column=1, padx=10, pady=5, sticky="sew")

        # First container in column 1 (50% height)
        self.first_container_col1 = customtkinter.CTkFrame(self.sub_frame_container, corner_radius=0, fg_color="transparent")
        self.first_container_col1.grid(row=0, column=1, sticky="nsew", padx=10, pady=(10, 5))
        self.first_container_col1.grid_rowconfigure(0, weight=1)
        self.first_container_col1.grid_columnconfigure(0, weight=1)

        # Import Tunnels from File button
        self.import_tunnels_button = customtkinter.CTkButton(self.first_container_col1, text="Import Tunnels from File", command=self.add_tunnel)
        self.import_tunnels_button.grid(row=0, column=0, padx=10, pady=5, sticky="ew")

        # Second container in column 1 (5% height)
        self.second_container_col1 = customtkinter.CTkFrame(self.sub_frame_container, corner_radius=0, fg_color="transparent")
        self.second_container_col1.grid(row=1, column=1, sticky="nsew", padx=10, pady=(5, 10))
        self.second_container_col1.grid_rowconfigure(0, weight=1)
        self.second_container_col1.grid_columnconfigure(0, weight=1)

        # Settings button (disabled)
        self.settings_button = customtkinter.CTkButton(self.second_container_col1, text="Settings", command=self.open_settings, state=tk.DISABLED)
        self.settings_button.grid(row=0, column=0, padx=10, pady=5, sticky="se")

        return self.main_container


    #Main screen with the list of tunnels
    def display_vpn_info(self, conf_files):
        """
        @brief display_vpn_info vpn plugin.
        Display the VPN information for the selected tunnel.
        This method displays the VPN information and allows the user to manage VPN tunnels.
        Args:
            conf_files (list): A list of configuration file names.
        """
        self.main_container = customtkinter.CTkFrame(self.app, corner_radius=0, fg_color="transparent")
        self.main_container.grid_columnconfigure(0, weight=1)
        self.main_container.grid_rowconfigure(0, weight=1)
        self.main_container.grid_rowconfigure(1, weight=4)
        #name 20% of the hight 
        self.profile_name_label = customtkinter.CTkLabel(self.main_container, text="VPN", font=customtkinter.CTkFont(size=20))
        self.profile_name_label.grid(row=0, column=0, padx=20, pady=10)

        #container 80% of the height
        self.sub_frame_container = customtkinter.CTkFrame(self.main_container, corner_radius=0, fg_color="transparent")
        self.sub_frame_container.grid(row=1, column=0, sticky="nsew")
        self.sub_frame_container.grid_columnconfigure(0, weight=1)  # 10% width
        self.sub_frame_container.grid_columnconfigure(1, weight=9)  # 90% width
        self.sub_frame_container.grid_rowconfigure(0, weight=95)  # 95% height
        self.sub_frame_container.grid_rowconfigure(1, weight=5)  # 5% height

        # First container in column 0 (95% height)
        self.first_container_col0 = customtkinter.CTkFrame(self.sub_frame_container, corner_radius=0, fg_color="transparent")
        self.first_container_col0.grid(row=0, column=0, sticky="nsew", padx=10, pady=(10, 5))
        self.first_container_col0.grid_rowconfigure(0, weight=1)
        self.first_container_col0.grid_columnconfigure(0, weight=1)
        

        # Listbox to display configuration files with padding on the left side
        self.conf_files_listbox = tk.Listbox(self.first_container_col0, selectmode=tk.SINGLE, highlightthickness=0, font=16, bd=1, bg="lightgray", fg="black")
        self.conf_files_listbox.grid(row=0, column=0, sticky="nsew", padx=(20, 0), pady=10)
        
        # Call the function to set initial colors
        update_listbox_colors(self.conf_files_listbox)

        # Bind the theme change event to update colors dynamically
        self.app.bind("<<ThemeChanged>>", lambda e: update_listbox_colors(self.conf_files_listbox))


        # Populate the listbox with configuration files without the .conf extension
        for conf_file in conf_files:
            interface_name = os.path.splitext(conf_file)[0]
            self.conf_files_listbox.insert(tk.END, interface_name)

        # Select the first item by default if the listbox is not empty
        if conf_files:
            self.conf_files_listbox.select_set(0)

        # Function to get the selected configuration file
        def get_selected_conf_file():
            selected_index = self.conf_files_listbox.curselection()
            if selected_index:
                selected_file = self.conf_files_listbox.get(selected_index)
                return os.path.splitext(selected_file)[0]
            return None


        # Second container in column 0 (5% height)
        self.second_container_col0 = customtkinter.CTkFrame(self.sub_frame_container, corner_radius=0, fg_color="transparent")
        self.second_container_col0.grid(row=1, column=0, sticky="nsew", padx=10, pady=(5, 10))
        self.second_container_col0.grid_rowconfigure(0, weight=1)
        self.second_container_col0.grid_columnconfigure(0, weight=1)

        # Add Tunnel button
        self.add_tunnel_button = customtkinter.CTkButton(self.second_container_col0, text="Add Tunnel", command=self.add_tunnel)
        self.add_tunnel_button.grid(row=0, column=0, padx=10, pady=5, sticky="sew")

        # Delete button
        self.delete_button = customtkinter.CTkButton(self.second_container_col0, text="Delete", command=lambda: self.delete_tunnel(get_selected_conf_file()))
        self.delete_button.grid(row=0, column=1, padx=10, pady=5, sticky="sew")

        # First container in column 1 (50% height)
        self.first_container_col1 = customtkinter.CTkFrame(self.sub_frame_container, corner_radius=0, fg_color="transparent")
        self.first_container_col1.grid(row=0, column=1, sticky="nsew", padx=10, pady=(10, 5))
        self.first_container_col1.grid_rowconfigure((0,1), weight=1)
        self.first_container_col1.grid_columnconfigure(0, weight=1)

        # VPN Information Frame 1 (Interface, Status, Public Key, Addresses)
        self.vpn_info_frame = customtkinter.CTkFrame(self.first_container_col1, corner_radius=3, fg_color=("lightgray", "#2e2e2e"), border_color="darkgray", border_width=1)
        self.vpn_info_frame.grid(row=0, column=0, padx=10, pady=(10, 5), sticky="nsew")
        self.vpn_info_frame.grid_columnconfigure(0, weight=1)

        #getting information from the configuration file
        interface_name = get_selected_conf_file()
        print(f"Interface name: {interface_name}")
        selected_conf_file = get_selected_conf_file()
        data = self.get_configuration_values(selected_conf_file)
        global my_vpn_status
        print(f"VPN Status in display vpn info : {my_vpn_status}")

        self.interface_label = customtkinter.CTkLabel(self.vpn_info_frame, text=f"Interface: {interface_name}", justify="center")
        self.interface_label.grid(row=0, column=0, padx=10, pady=5, sticky="nw")

        shield_image_path = os.path.join(os.path.dirname(os.path.realpath(__file__)), "active_shield.png" if my_vpn_status == "Running" else "inactive_shield.png")
        status_text = "Active" if my_vpn_status == "Running" else "Inactive"
        
        self.status_frame = customtkinter.CTkFrame(self.vpn_info_frame, corner_radius=3, fg_color="transparent")
        self.status_frame.grid(row=1, column=0, padx=1, pady=0, sticky="nw")
        self.status_frame.grid_columnconfigure(0, weight=0)
        self.status_frame.grid_columnconfigure(1, weight=1)

        # Load images using PIL
        shield_image = Image.open(shield_image_path)
        self.shield_image = customtkinter.CTkImage(light_image=shield_image, dark_image=shield_image)
        self.status_label = customtkinter.CTkLabel(self.status_frame, text="Status: ", justify="left")
        self.status_label.grid(row=0, column=0, padx=10, pady=5, sticky="nw")
        self.status_image_label = customtkinter.CTkLabel(self.status_frame, image=self.shield_image, text=status_text, compound="left", justify="left")
        self.status_image_label.grid(row=0, column=1, padx=5, pady=5, sticky="nw")

        self.public_key_label = customtkinter.CTkLabel(self.vpn_info_frame, text=f"Public Key: {data.get('public_key')}", justify="left")
        self.public_key_label.grid(row=2, column=0, padx=10, pady=5, sticky="nw")

        self.addresses_label = customtkinter.CTkLabel(self.vpn_info_frame, text=f"Addresses: {data.get('client_ip_address')}", justify="left")
        self.addresses_label.grid(row=3, column=0, padx=10, pady=5, sticky="nw")

        # Activate/Deactivate Button
        button_text = "Deactivate" if my_vpn_status == "Running" else "Activate"
        button_color = "red" if my_vpn_status == "Running" else "green"
        self.activate_button = customtkinter.CTkButton(self.vpn_info_frame, text=button_text, fg_color=button_color, command=lambda: self.activate_tunnel(get_selected_conf_file()))
        self.activate_button.grid(row=4, column=0, padx=10, pady=5, sticky="nw")

        # Peer Information Frame 2
        self.vpn_info_frame_peer = customtkinter.CTkFrame(self.first_container_col1, corner_radius=3, fg_color=("lightgray", "#2e2e2e"), border_color="darkgray", border_width=1)
        self.vpn_info_frame_peer.grid(row=1, column=0, padx=10, pady=(5, 10), sticky="nswe")
        self.vpn_info_frame_peer.grid_columnconfigure(0, weight=1)

        self.peer_label = customtkinter.CTkLabel(self.vpn_info_frame_peer, text="Peer:", justify="center")
        self.peer_label.grid(row=0, column=0, padx=10, pady=5, sticky="nw")

        self.peer_public_key_label = customtkinter.CTkLabel(self.vpn_info_frame_peer, text=f"Public Key: {data.get('public_key')}", justify="left")
        self.peer_public_key_label.grid(row=1, column=0, padx=10, pady=5, sticky="nw")

        self.peer_allowed_ips_label = customtkinter.CTkLabel(self.vpn_info_frame_peer, text=f"Allowed IPs: {data.get('allowed_ips')}", justify="left")
        self.peer_allowed_ips_label.grid(row=2, column=0, padx=10, pady=5, sticky="nw")

        self.peer_endpoint_label = customtkinter.CTkLabel(self.vpn_info_frame_peer, text=f"Endpoint: {data.get('endpoint')}:{data.get('port')}", justify="left")
        self.peer_endpoint_label.grid(row=3, column=0, padx=10, pady=5, sticky="nw")

        # Second container in column 1 (5% height)
        self.second_container_col1 = customtkinter.CTkFrame(self.sub_frame_container, corner_radius=0, fg_color="transparent")
        self.second_container_col1.grid(row=1, column=1, sticky="nsew", padx=10, pady=(5, 10))
        self.second_container_col1.grid_rowconfigure(0, weight=1)
        self.second_container_col1.grid_columnconfigure(0, weight=1)

        # Settings button
        self.settings_button = customtkinter.CTkButton(self.second_container_col1, text="Settings", command=lambda: self.open_settings(get_selected_conf_file()))
        self.settings_button.grid(row=0, column=0, padx=10, pady=5, sticky="se")
        
        return self.main_container


    def add_tunnel(self):
        """
        Adds a WireGuard tunnel configuration by selecting a configuration file.
        A file dialog is used to select the configuration file.
        The selected configuration file is then copied to a 'wireguard' folder within the same directory
        as this script.
        Example usage:
            User selects the file using a file dialog.
        Prints:
            A message indicating the file has been saved to the destination path or that no file was selected.
        """
        file_path = filedialog.askopenfilename(filetypes=[("Config Files", "*.conf")])

        if file_path:
            # Save the file to the writable wireguard folder
            wireguard_folder = get_writable_wireguard_dir()
            destination_path = os.path.join(wireguard_folder, os.path.basename(file_path))
            print(f"Destination path: {destination_path}")
            try:
                with open(file_path, 'rb') as src_file:
                    with open(destination_path, 'wb') as dst_file:
                        dst_file.write(src_file.read())
                print(f"File {file_path} saved to {destination_path}")
                # Force update ONLY this plugin
                self.update_plugin(self.id)  # Ensure it reloads the VPN plugin
            except Exception as e:
                print(f"Error saving file: {e}")
        else:
            print("No file selected")

    #function to delete a tunnel by selecting the tunnel name
    def delete_tunnel(self, tunnel_name):
        selected_conf_file = tunnel_name
        if selected_conf_file:
            wireguard_folder = get_writable_wireguard_dir()
            conf_file_path = os.path.join(wireguard_folder, f"{selected_conf_file}.conf")
            if os.path.exists(conf_file_path):
                try:
                    os.remove(conf_file_path)
                    print(f"Deleted configuration file: {conf_file_path}")
                    # Force update ONLY this plugin
                    self.update_plugin(self.id)  # Ensure it reloads the VPN plugin
                except Exception as e:
                    print(f"Error deleting file: {e}")
            else:
                print(f"Configuration file not found: {conf_file_path}")
        else:
            print("No configuration file selected")
        print("Delete Tunnel")

    def open_settings(self, tunnel_name):
        """
        Open the settings of the specified tunnel and allow the user to edit the configuration.
        
        :param tunnel_name: The name of the tunnel whose settings are to be opened.
        """
        selected_conf_file = tunnel_name
        if selected_conf_file:
            wireguard_folder = get_writable_wireguard_dir()
            conf_file_path = os.path.join(wireguard_folder, f"{selected_conf_file}.conf")

            def save_changes():
                try:
                    with open(conf_file_path, 'w') as conf_file:
                        conf_file.write(text_area.get("1.0", tk.END))
                    settings_popup.destroy()
                except Exception as e:
                    print(f"Error saving changes: {e}")

            def cancel_changes():
                settings_popup.destroy()

            settings_popup = customtkinter.CTkToplevel(self.app)
            settings_popup.title(f"Settings for {selected_conf_file}")
            settings_popup.geometry("600x600")

            settings_frame = customtkinter.CTkFrame(settings_popup, corner_radius=0, fg_color="transparent")
            settings_frame.pack(fill="both", expand=True, padx=20, pady=20)

            with open(conf_file_path, 'r') as conf_file:
                config_content = conf_file.read()

            text_area = customtkinter.CTkTextbox(settings_frame, wrap=tk.WORD)
            text_area.insert(tk.END, config_content)
            text_area.pack(fill="both", expand=True, padx=10, pady=10)

            # Save and Cancel buttons
            button_frame = customtkinter.CTkFrame(settings_frame, corner_radius=0, fg_color="transparent")
            button_frame.pack(fill="x", padx=10, pady=10)

            save_button = customtkinter.CTkButton(button_frame, text="Save", command=save_changes)
            save_button.pack(side="left", padx=10, pady=10, expand=True)

            cancel_button = customtkinter.CTkButton(button_frame, text="Cancel", command=cancel_changes)
            cancel_button.pack(side="right", padx=10, pady=10, expand=True)

    def get_list_of_tunnels(self):
        """
        Retrieve the list of available VPN tunnel configuration files.
        
        :return: A list of configuration file names.
        """
        wireguard_folder = get_writable_wireguard_dir()
        if os.path.exists(wireguard_folder):
            conf_files = [f for f in os.listdir(wireguard_folder) if f.endswith('.conf')]
            return conf_files
        return []

    def update_plugin(self, plugin_id):
        """
        Refresh the view of the specified plugin by reloading its main screen.
        
        :param plugin_id: The ID of the plugin to be updated.
        """
        print(f"Updating plugin: {plugin_id}")  # Debugging
        # Ensure you're updating the correct plugin
        for plugin in self.app.plugin_list:
            if plugin.id == plugin_id:
                self.main_container.destroy()  # Remove old UI
                print(f"Reloading plugin: {plugin}")  # Debugging
                plugin.create_main_screen().grid(row=0, column=1, sticky="nsew")  # Create new UI
                return    

    def get_configuration_values(self, tunnel_name):
        """
        Retrieve the configuration values from the specified tunnel's configuration file.
        
        :param tunnel_name: The name of the tunnel whose configuration values are to be retrieved.
        :return: A dictionary containing the configuration values.
        """
        wireguard_folder = get_writable_wireguard_dir()
        conf_file_path = os.path.join(wireguard_folder, f"{tunnel_name}.conf")

        data = {
            'private_key': '',
            'client_ip_address': '',
            'public_key': '',
            'allowed_ips': '',
            'endpoint': '',
            'port': '',
            'dns': ''
        }

        if os.path.exists(conf_file_path):
            with open(conf_file_path, 'r') as conf_file:
                for line in conf_file:
                    if line.startswith('PrivateKey'):
                        data['private_key'] = line.split('=')[1].strip() + '='
                    elif line.startswith('Address'):
                        data['client_ip_address'] = line.split('=')[1].strip()
                    elif line.startswith('PublicKey'):
                        data['public_key'] = line.split('=')[1].strip() + '='
                    elif line.startswith('AllowedIPs'):
                        data['allowed_ips'] = line.split('=')[1].strip()
                    elif line.startswith('Endpoint'):
                        endpoint = line.split('=')[1].strip()
                        data['endpoint'], data['port'] = endpoint.split(':')
                    elif line.startswith('DNS'):
                        data['dns'] = line.split('=')[1].strip()
        else:
            print(f"Configuration file not found, values not created: {conf_file_path}")

        return data


    
    def activate_tunnel(self, tunnel_name):
        """
        Activates a VPN tunnel using WireGuard based on the provided tunnel name.
        This function handles the activation of a VPN tunnel for both Linux and Windows platforms.
        It checks if WireGuard is installed, configures the VPN tunnel, and starts or stops the VPN service
        based on the current status.
        Args:
            tunnel_name (str): The name of the VPN tunnel to be activated.
        Raises:
            NotImplementedError: If the platform is neither Linux nor Windows.
        """
        global my_vpn_status
        
        # Handle None or empty tunnel_name safely
        if not tunnel_name:
            print("❌ No tunnel name provided")
            return
            
        print(f"vpn status: {my_vpn_status} in activate_tunnel")
        interface_name = tunnel_name
        wireguard_folder = get_writable_wireguard_dir()
        config_path = os.path.join(wireguard_folder, f"{tunnel_name}.conf")
        
        print(f"Using config path: {config_path}")

        # Check if WireGuard is installed
        is_wg_installed = check_wireguard_installed()

        if platform.system() == "Linux":
            data = self.get_configuration_values(tunnel_name)
            print(f"Activating tunnel: {tunnel_name}")
            
            # Create Key objects
            private = Key(data.get("private_key"))
            srv_key = Key(data.get("public_key"))
            
            client_ip_address = data.get("client_ip_address")

            # Check if the interface already exists
            existing_interfaces = os.popen('wg show interfaces').read().split()
            if interface_name not in existing_interfaces:
                # Set up the client
                print(f"Creating interface {interface_name}...")
                client = Client(interface_name, private, client_ip_address)
                # Set up the server connection
                server_conn = ServerConnection(srv_key, data.get("endpoint"), data.get("port"))
                # Configure the client to connect to the server
                client.set_server(server_conn)
            else:
                print(f"Interface {interface_name} already exists.")
                client = Client(interface_name, private, client_ip_address)
                server_conn = ServerConnection(srv_key, data.get("endpoint"), data.get("port"))

            if is_wg_installed:
                if "Running" == my_vpn_status:
                    stop_vpn(config_path)
                    my_vpn_status = check_service_status(tunnel_name, "10.49.64.53")
                    self.update_plugin(self.id) 
                elif "Stopped" == my_vpn_status:
                    client.set_server(server_conn)
                    start_vpn(config_path)
                    my_vpn_status = check_service_status(tunnel_name, "10.49.64.53")
                    self.update_plugin(self.id) 
                else:
                    print("The service status is unknown.")    
            else:
                print("Wireguard not installed")
        elif platform.system() == "Darwin":
            data = self.get_configuration_values(tunnel_name)
            print(f"Activating tunnel: {tunnel_name}")

            if is_wg_installed:
                # Use system path for WireGuard operations
                
                
                if "Running" == my_vpn_status:
                    stop_vpn(config_path)
                    my_vpn_status = check_service_status(tunnel_name, "10.49.64.53")
                    self.update_plugin(self.id) 
                elif "Stopped" == my_vpn_status:
                    start_vpn(config_path)
                    my_vpn_status = check_service_status(tunnel_name, "10.49.64.53")
                    self.update_plugin(self.id) 
                else:
                    print("The service status is unknown.")    
            else:
                print("Wireguard not installed")
                   
        elif platform.system() == "Windows":
            if is_admin():
                try:
                    # Check if the interface already exists
                    if check_wireguard_interface(tunnel_name):
                        if my_vpn_status == "Running":
                            stop_vpn(config_path)
                            my_vpn_status = check_service_status(tunnel_name, "10.49.64.53")
                            self.update_plugin(self.id) 
                        else:
                            start_vpn(config_path)
                            my_vpn_status = check_service_status(tunnel_name, "10.49.64.53")
                            self.update_plugin(self.id) 
                    else:
                        install_tunnel(config_path)
                        self.update_plugin(self.id) 
                except Exception as e:
                    print("Error installing VPN service:", e)
            else:
                # Re-run the script with admin privileges
                ctypes.windll.shell32.ShellExecuteW(None, "runas", sys.executable, __file__, None, 1)
        else:
            #if there is no platform
            

            raise NotImplementedError("Unsupported platform")
            
        
 
 

  

