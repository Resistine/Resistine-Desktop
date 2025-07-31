#!/bin/bash

# Simple bundled app simulator
# This is a quick way to test your app as if it were bundled

echo "=== Simple Bundled App Test ==="

# Set environment to simulate bundled app
export PYTHONPATH="$(pwd):$PYTHONPATH"

# Create a simple wrapper that sets sys.frozen
python3 -c "
import sys
import os

# Simulate bundled app environment
sys.frozen = True
sys._MEIPASS = os.getcwd()

print('=== Simulating Bundled App ===')
print(f'sys.frozen: {sys.frozen}')
print(f'sys._MEIPASS: {sys._MEIPASS}')
print(f'Current directory: {os.getcwd()}')
print('=' * 30)

# Import and run the app
try:
    from main import App
    import customtkinter
    
    customtkinter.set_appearance_mode('system')
    
    # Try to load theme
    theme_path = os.path.join(os.getcwd(), 'resources', 'themes', 'custom_theme.json')
    if os.path.exists(theme_path):
        customtkinter.set_default_color_theme(theme_path)
        print(f'Theme loaded: {theme_path}')
    
    app = App()
    app.mainloop()
    
except Exception as e:
    print(f'Error: {e}')
    import traceback
    traceback.print_exc()
" 