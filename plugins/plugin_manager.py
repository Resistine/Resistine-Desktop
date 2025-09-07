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
import pkgutil
from utils.paths import resource_path

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

    def get_plugins_path(self):
        return resource_path("plugins")

    def load_plugins(self):
        """
        Load all plugins from the plugins package (pkgutil), with filesystem fallback.
        """
        modules = []
        # Package-based discovery (preferred for PyInstaller)
        try:
            import plugins
            for _, name, ispkg in pkgutil.iter_modules(plugins.__path__, prefix="plugins."):
                #if ispkg and os.path.basename(name) not in ("__pycache__", "plugin_manager"):
                if ispkg:
                    modules.append(f"{name}.main")  # plugins.<name>.main
        except Exception as e:
            print(f"Package discovery failed: {e}")
            traceback.print_exc()

        # Filesystem fallback (dev runs)
        if not modules:
            plugins_path = self.get_plugins_path()
            if os.path.isdir(plugins_path):
                for d in os.listdir(plugins_path):
                    full = os.path.join(plugins_path, d)
                    if os.path.isdir(full) and d not in ("__pycache__", "plugin_manager") and not d.startswith("_"):
                        if os.path.exists(os.path.join(full, "main.py")):
                            modules.append(f"plugins.{d}.main")

        loaded = []
        for module_name in modules:
            try:
                module = importlib.import_module(module_name)
                if hasattr(module, "Plugin"):
                    loaded.append(module.Plugin(self.app))
                else:
                    print(f"Module {module_name} has no Plugin class; skipping")
            except Exception as e:
                print(f"Failed to load plugin {module_name}: {e}")
                traceback.print_exc()
                continue
        return loaded
