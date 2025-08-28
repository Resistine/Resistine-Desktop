from plugins.base_plugin import BasePlugin
import customtkinter
import os
import json

class Plugin(BasePlugin):
    """
    @brief Plugin class for the Settings plugin.
    Plugin class for the Settings plugin, that allows user to configure their account settings.
    """
    def __init__(self, app):
        """
        @brief Initialize the Settings plugin.
        Initialize the Settings plugin with the specified parameters.
        :param app: Main application object.
        """
        super().__init__(
            id="010",
            order=10,
            name="Settings",
            status="OK",
            description="This plugin allows you to configure your account settings.",
            supported_systems=["Windows", "Linux", "Mac"],
            translations={"US": "Settings", "ES": "Configuracion", "FR": "Paramètres"},
            icon_light_path=os.path.join(os.path.dirname(os.path.realpath(__file__)), "settings_light.png"),
            icon_dark_path=os.path.join(os.path.dirname(os.path.realpath(__file__)), "settings_dark.png"),
        )
        self.app = app
        self.user_data_path = os.path.join(os.path.dirname(__file__), "user_data.json")
        
        # Load user data (name, email)
        self.user_data = self.load_user_data()

    def load_user_data(self):
        """
        Load the user data (name and email) from the JSON file.
        If the file does not exist, return default values.
        """
        if os.path.exists(self.user_data_path):
            with open(self.user_data_path, "r") as file:
                return json.load(file)  # Load the user data from the JSON file
        return {"name": "", "email": ""}  # Return default values if no data is found

    def create_main_screen(self):
        """
        @brief Create the main screen for the Settings plugin.
        Create the main screen for the Settings plugin.
        """
        self.frame_5 = customtkinter.CTkFrame(self.app, corner_radius=0, fg_color="transparent")
        self.frame_5.grid_columnconfigure(0, weight=1)
        self.frame_5.grid_rowconfigure((0, 1, 2), weight=1)

        # Create a frame to combine both the label and entry
        self.name_frame = customtkinter.CTkFrame(self.frame_5, corner_radius=10, fg_color="white")  # Rounded frame
        self.name_frame.grid(row=0, column=0, columnspan=2, pady=20, padx=20)

        # Profile name label (initial value from user data)
        self.profile_name_label = customtkinter.CTkLabel(self.name_frame, text=f"Name: {self.user_data.get('name', '_')}", font=customtkinter.CTkFont(size=20))
        self.profile_name_label.grid(row=0, column=0, padx=(0, 10))

        # Name Entry (hidden by default)
        self.profile_name_entry = customtkinter.CTkEntry(self.name_frame, font=customtkinter.CTkFont(size=20), width=200)
        self.profile_name_entry.grid(row=0, column=1, padx=10, pady=10)
        self.profile_name_entry.grid_forget()  # Hide entry by default

        # Edit Button to toggle between label and entry
        self.edit_button = customtkinter.CTkButton(self.name_frame, text="Edit", command=self.toggle_edit_mode)
        self.edit_button.grid(row=0, column=2, padx=10, pady=10)

        # Save Button to save the name when editing
        self.save_button = customtkinter.CTkButton(self.name_frame, text="Save", command=self.save_name, width=80)
        self.save_button.grid(row=0, column=3, padx=10, pady=10)
        self.save_button.grid_forget()  # Hide save button by default

        # Profile email (read from file)
        email_file_path = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.realpath(__file__)))), "utils", "email-settings.txt")
        with open(email_file_path, 'r') as file:
            email = file.read().strip()

        self.profile_email_label = customtkinter.CTkLabel(self.frame_5, text=f"Email: {email}", font=customtkinter.CTkFont(size=20))
        self.profile_email_label.grid(row=1, column=0, padx=20, pady=10, columnspan=2)

        return self.frame_5

    def save_name(self):
        """
        Save the updated name to the JSON file and update the label.
        """
        # Get the new name from the entry widget
        new_name = self.profile_name_entry.get()

        # Update user data
        self.user_data["name"] = new_name

        # Save the updated user data to the JSON file
        with open(self.user_data_path, "w") as file:
            json.dump(self.user_data, file, indent=4)

        # Update the profile name label to show the new name
        self.profile_name_label.configure(text=f"Name: {new_name}")

        # Switch back to display mode
        self.toggle_edit_mode()

        # Force UI update
        self.after(100, self.update_ui)  # Adding a brief delay to force the UI refresh

    def toggle_edit_mode(self):
        """
        Toggle between display mode and edit mode.
        """
        # Hide the name label, show the entry, and show the save button
        if self.profile_name_label.winfo_ismapped():  # If the label is shown, switch to edit mode
            self.profile_name_label.grid_forget()
            self.profile_name_entry.grid(row=0, column=1, padx=10, pady=10)  # Make the entry visible
            self.save_button.grid(row=0, column=3, padx=10, pady=10)  # Show save button
            self.edit_button.config(text="Cancel", command=self.cancel_edit_mode)  # Change button to cancel
        else:  # If in edit mode, revert to the label
            self.profile_name_entry.grid_forget()
            self.save_button.grid_forget()
            self.profile_name_label.grid(row=0, column=0, padx=(0, 10))  # Show label again
            self.edit_button.config(text="Edit", command=self.toggle_edit_mode)  # Change button back to "Edit"

    def update_ui(self):
        """
        Manually trigger a UI update to reflect changes immediately.
        """
        self.frame_5.update_idletasks()  # Force the update of the UI components


    def cancel_edit_mode(self):
        """
        Cancel the editing mode and revert to the display mode.
        """
        # Hide the entry and save button, show the label again
        self.profile_name_entry.grid_forget()
        self.save_button.grid_forget()
        self.profile_name_label.grid(row=0, column=0, padx=(0, 10))  # Show label again

        # Change button back to "Edit"
        self.edit_button.config(text="Edit", command=self.toggle_edit_mode)
