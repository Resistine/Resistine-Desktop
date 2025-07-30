#!/usr/bin/env python3
import os
import sys
import subprocess
import tempfile
import shutil

def load_build_config():
    """Load configuration from build_config.env file"""
    config_file = "build_config.env"
    if os.path.exists(config_file):
        print(f"📋 Loading configuration from {config_file}...")
        try:
            with open(config_file, 'r') as f:
                for line in f:
                    line = line.strip()
                    # Skip comments and empty lines
                    if line and not line.startswith('#'):
                        if '=' in line:
                            key, value = line.split('=', 1)
                            # Remove quotes if present
                            value = value.strip().strip('"').strip("'")
                            os.environ[key] = value
                            print(f"   Loaded: {key}")
            print("✅ Configuration loaded successfully")
            
            # Check for required configuration
            signing_identity = os.environ.get('SIGNING_IDENTITY')
            if signing_identity:
                print(f"🔐 Using signing identity: {signing_identity}")
            else:
                print("⚠️  No SIGNING_IDENTITY found in config")
                
        except Exception as e:
            print(f"❌ Error loading configuration: {e}")
            print("⚠️  Continuing with environment variables only")
    else:
        print(f"⚠️  Warning: {config_file} not found. Using environment variables.")
        print("   Create build_config.env with your signing credentials")

def run_command(cmd, description):
    print(f"Running: {' '.join(cmd)}")
    try:
        result = subprocess.run(cmd, check=True, capture_output=True, text=True)
        print(f"✅ {description} completed")
        return True
    except subprocess.CalledProcessError as e:
        print(f"❌ Error: {e}")
        if e.stdout:
            print(f"stdout: {e.stdout}")
        if e.stderr:
            print(f"stderr: {e.stderr}")
        return False

def main():
    print("🚀 Building Resistine AI with simplified signing...")
    
    # Load configuration from build_config.env
    load_build_config()
    
    # Clean previous builds
    print("🧹 Cleaning previous builds...")
    if os.path.exists("dist"):
        shutil.rmtree("dist")
    if os.path.exists("build"):
        shutil.rmtree("build")
    for file in os.listdir("."):
        if file.endswith(".spec"):
            os.remove(file)
    
    # Install PyInstaller
    if not run_command(["pip3", "install", "pyinstaller"], "Installing PyInstaller"):
        sys.exit(1)
    
    # Create PyInstaller spec
    spec_content = '''# -*- mode: python ; coding: utf-8 -*-

block_cipher = None

a = Analysis(
    ['main.py'],
    pathex=[],
    binaries=[],
    datas=[
        ('resources', 'resources'),
        ('plugins', 'plugins'),
        ('utils', 'utils'),
    ],
    hiddenimports=[
        'tkinter', 'tkinter.ttk', 'tkinter.messagebox', 'tkinter.filedialog',
        'PIL', 'PIL._tkinter_finder', 'customtkinter', 'darkdetect',
        'keyring', 'cryptography', 'cryptography.fernet', 'markdown', 'openai', 'requests',
        'html2text', 'html2text.html2text', 'plugins.plugin_manager', 'utils.functions'
    ],
    
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='Resistine AI',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='Resistine AI',
)

app = BUNDLE(
    coll,
    name='Resistine AI.app',
    info_plist={
        'CFBundleName': 'Resistine AI',
        'CFBundleDisplayName': 'Resistine AI',
        'CFBundleIdentifier': 'com.resistine.ai',
        'CFBundleVersion': '1.0.0',
        'CFBundleShortVersionString': '1.0.0',
        'NSHighResolutionCapable': True,
        'LSMinimumSystemVersion': '10.15.0',
        'NSAppleEventsUsageDescription': 'Resistine AI needs to access system features.',
    },
)
'''
    
    with open('resistine_simple.spec', 'w') as f:
        f.write(spec_content)
    
    # Build with PyInstaller
    if not run_command(["pyinstaller", "resistine_simple.spec"], "Building with PyInstaller"):
        sys.exit(1)
    
    # Signing approach
    print("🔐 Signing with Developer ID Application certificate...")
    app_path = "dist/Resistine AI.app"
    
    # Get signing identity from environment variable
    signing_identity = os.environ.get('SIGNING_IDENTITY')
    if not signing_identity:
        print("⚠️  Warning: SIGNING_IDENTITY environment variable not set.")
        print("   Set it with: export SIGNING_IDENTITY='your-certificate-id'")
        print("   Or add it to build_config.env file")
        print("   Skipping code signing...")
    else:
        print(f"🔐 Using signing identity: {signing_identity}")
        # Sign main executable
        if not run_command([
            "codesign", "--force", "--sign", signing_identity,
            "--timestamp", "--options", "runtime", f"{app_path}/Contents/MacOS/Resistine AI"
        ], "Signing main executable"):
            sys.exit(1)
        
        # Sign entire app bundle
        if not run_command([
            "codesign", "--force", "--deep", "--sign", signing_identity,
            "--timestamp", "--options", "runtime", app_path
        ], "Signing app bundle"):
            sys.exit(1)
    
    # Create DMG
    print("💿 Creating DMG...")
    with tempfile.TemporaryDirectory() as temp_dir:
        shutil.copytree(app_path, os.path.join(temp_dir, "Resistine AI.app"))
        os.symlink("/Applications", os.path.join(temp_dir, "Applications"))
        
        # Set restrictive permissions on the app bundle to require sudo
        print("🔐 Setting restrictive permissions for sudo access...")
        if not run_command([
            "chmod", "-R", "700", os.path.join(temp_dir, "Resistine AI.app")
        ], "Setting restrictive permissions on app bundle"):
            sys.exit(1)
        
        if not run_command([
            "hdiutil", "create", "-volname", "Resistine AI Installer",
            "-srcfolder", temp_dir, "-ov", "-format", "UDZO",
            "Resistine AI-1.0.0.dmg"
        ], "Creating installer DMG"):
            sys.exit(1)
        
        # Set restrictive permissions on the DMG itself
        if not run_command([
            "chmod", "600", "Resistine AI-1.0.0.dmg"
        ], "Setting restrictive permissions on DMG"):
            sys.exit(1)
    
    print("🎉 Build completed successfully!")
    print("📁 App location: dist/Resistine AI.app")
    print("💿 DMG location: Resistine AI-1.0.0.dmg")
    print("🔐 Ready for notarization!")

if __name__ == "__main__":
    main() 