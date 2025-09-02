"""
This script is used to manage the loading and downloading of plugins.
Author: Peres J.
Copyright (c) Resistine 2025
Licensed under the Apache License 2.0
"""

import importlib
import os
import requests
import zipfile
import io
import sys
import traceback

class PluginManager:
    """
    A class to manage the loading and downloading of plugins.
    """
    def __init__(self, app):
        """
        Initialize the PluginManager with the given application instance.
        
        :param app: The application instance to which the plugins will be attached.
        """
        self.app = app
        self.plugins = sorted(self.load_plugins(), key=lambda x: getattr(x, "order", 0))

    def download_plugin(self, url):
        """
        Download a plugin from the specified URL and extract it to the plugins directory.
        
        :param url: The URL from which to download the plugin.
        :return: A message indicating the success or failure of the download and extraction process.
        """
        plugins_path = os.path.join(os.path.dirname(os.path.realpath(__file__)))
        try:
            response = requests.get(url, allow_redirects=True)
            response.raise_for_status()
            with zipfile.ZipFile(io.BytesIO(response.content)) as zip_ref:
                zip_ref.extractall(os.path.join(plugins_path))
            self.plugins = sorted(self.load_plugins(), key=lambda x: getattr(x, "order", 0))
            self.app.create_dashboard()
            return "Plugin downloaded and extracted successfully."
        except requests.RequestException as e:
            return f"Failed to download plugin from {url}: {e}"
        except zipfile.BadZipFile as e:
            return f"Failed to extract plugin: {e}"

    def load_plugins(self):
        """
        Load all plugins from the plugins directory.
        :return: A list of loaded plugin instances.
        """
        plugins_path = self.get_plugins_path()
        plugin_dirs = [
            d for d in os.listdir(plugins_path)
            if os.path.isdir(os.path.join(plugins_path, d))
            and not d.startswith('_')
            and d != "plugin_manager"
        ]

        # Build module names only if a main.py exists
        module_names = []
        for d in plugin_dirs:
            if os.path.exists(os.path.join(plugins_path, d, "main.py")):
                module_names.append(f"plugins.{d}.main")

        plugins = []
        for module_name in module_names:
            try:
                module = importlib.import_module(module_name)
                if hasattr(module, "Plugin"):
                    instance = module.Plugin(self.app)
                    plugins.append(instance)
                else:
                    print(f"Module {module_name} has no Plugin class; skipping")
            except Exception as e:
                print(f"Failed to load plugin {module_name}: {e}")
                traceback.print_exc()
                continue

        return plugins
        '''
        for plugin_dir in plugin_dirs:
            module_name = f"plugins.{plugin_dir}.main"
            try:
                module = importlib.import_module(module_name)
                plugin_class = getattr(module, "Plugin")  # Adjust this if your plugin class names are different
                plugin_instance = plugin_class(self.app)
                plugins.append(plugin_instance)
                plugin_instance.set_status("Ok")  # Set the status of the plugin to "Ok"
            except Exception as e:
                plugin_instance.set_status("Error")  # Set the status of the plugin to "Error"
                print(f"Failed to load plugin {module_name}: {e}")
        return plugins
        '''

    def get_plugins_path(self):
        """
        Get the path to the plugins directory.
        
        :return: The path to the plugins directory.
        """
        if getattr(sys, 'frozen', False):
            # If the application is run as a bundle, the PyInstaller bootloader
            # sets the sys._MEIPASS attribute to the path of the temporary directory
            return os.path.join(sys._MEIPASS, 'plugins')
        else:
            # If the application is run normally, use the original path
            return os.path.join(os.path.dirname(os.path.realpath(__file__)))
