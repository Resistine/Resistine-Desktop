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
def clean_previous_builds():
    """Clean previous builds"""
    print("🧹 Cleaning previous builds...")
    if os.path.exists("dist"):
        shutil.rmtree("dist")
    if os.path.exists("build"):
        shutil.rmtree("build")
def main():
    print("🚀 Building Resistine AI with simplified signing...")
    
    # Load configuration from build_config.env
    load_build_config()
    clean_previous_builds()
    
    # Install PyInstaller
    if not run_command(["pip3", "install", "pyinstaller"], "Installing PyInstaller"):
        sys.exit(1)
    
    # Check if WireGuard is installed (required for bundling)
    print("🔍 Checking for WireGuard installation...")
    wg_check = subprocess.run(["which", "wg"], capture_output=True)
    if wg_check.returncode != 0:
        print("⚠️  WireGuard not found! Installing via Homebrew...")
        if not run_command(["brew", "install", "wireguard-tools"], "Installing WireGuard tools"):
            print("❌ Failed to install WireGuard. Please install manually: brew install wireguard-tools")
            sys.exit(1)
    else:
        print("✅ WireGuard already installed")
    
    # Build with PyInstaller
    if not run_command(["pyinstaller", "resistine_simple.spec"], "Building with PyInstaller"):
        sys.exit(1)
    
    app_path = "dist/Resistine AI.app"
    print("📦 Adding helper components to app bundle...")
    
    # Create LaunchDaemons directory and place the plist there
    os.makedirs(os.path.join(app_path, "Contents", "Library", "LaunchDaemons"), exist_ok=True)
    shutil.copy("apple_helper/com.resistine.plist", os.path.join(app_path, "Contents", "Library", "LaunchDaemons", "com.resistine.plist"))
    
    #create Helper directory
    os.makedirs(os.path.join(app_path, "Contents", "Library", "LaunchServices"), exist_ok=True)
    shutil.copy("apple_helper/ResistineHelper", os.path.join(app_path, "Contents", "Library", "LaunchServices", "ResistineHelper"))
    shutil.copy("apple_helper/cli/ResistCli", os.path.join(app_path, "Contents", "Library", "LaunchServices", "ResistCli"))
    
    # Bundle WireGuard binaries INTO the app bundle
    print("📦 Bundling WireGuard binaries into app...")
    bin_dir = os.path.join(app_path, "Contents", "Resources", "bin")
    os.makedirs(bin_dir, exist_ok=True)
    
    wg_locations = [
        ("/opt/homebrew/bin/wg", "/opt/homebrew/bin/wg-quick"),  # Apple Silicon
        ("/usr/local/bin/wg", "/usr/local/bin/wg-quick"),        # Intel Mac
    ]
    
    wg_bundled = False
    for wg_path, wg_quick_path in wg_locations:
        if os.path.exists(wg_path) and os.path.exists(wg_quick_path):
            shutil.copy(wg_path, os.path.join(bin_dir, "wg"))
            shutil.copy(wg_quick_path, os.path.join(bin_dir, "wg-quick"))
            os.chmod(os.path.join(bin_dir, "wg"), 0o755)
            os.chmod(os.path.join(bin_dir, "wg-quick"), 0o755)
            print(f"✅ Bundled WireGuard from {wg_path}")
            wg_bundled = True
            break
    
    if not wg_bundled:
        print("❌ ERROR: WireGuard not found for bundling!")
        print("   Install via: brew install wireguard-tools")
        sys.exit(1)
    
    # Signing approach
    print("🔐 Signing with Developer ID Application certificate...")
    
    
    # Get signing identity from environment variable
    signing_identity = os.environ.get('SIGNING_IDENTITY')
    if not signing_identity:
        print("⚠️  Warning: SIGNING_IDENTITY environment variable not set.")
        print("   Set it with: export SIGNING_IDENTITY='your-certificate-id'")
        print("   Or add it to build_config.env file")
        print("   Skipping code signing...")
    else:
        print(f"🔐 Using signing identity: {signing_identity}")
        
        
        # Sign helper tool
        helper_path = os.path.join(app_path, "Contents", "Library", "LaunchServices", "ResistineHelper")
        if os.path.exists(helper_path):
            if not run_command([
                "codesign", "--force", "--options", "runtime", "--timestamp",
                "--entitlements", "apple_helper/ResistineHelper.entitlements",
                "--sign", signing_identity, helper_path
            ], "Signing helper tool"):
                sys.exit(1)
        else:
            print(f"⚠️ Warning: Helper not found at {helper_path}")
        
        # Sign CLI tool
        cli_path = os.path.join(app_path, "Contents", "Library", "LaunchServices", "ResistCli")
        if os.path.exists(cli_path):
            if not run_command([
                "codesign", "--force", "--options", "runtime", "--timestamp",
                "--entitlements", "apple_helper/cli/ResistCli.entitlements",
                "--sign", signing_identity, cli_path
            ], "Signing CLI tool"):
                sys.exit(1)
        else:
            print(f"⚠️ Warning: CLI tool not found at {cli_path}")
        
        # Sign bundled WireGuard binaries
        print("✍️ Signing bundled WireGuard binaries...")
        wg_bin_dir = os.path.join(app_path, "Contents", "Resources", "bin")
        for binary in ["wg", "wg-quick"]:
            binary_path = os.path.join(wg_bin_dir, binary)
            if os.path.exists(binary_path):
                if not run_command([
                    "codesign", "--force", "--options", "runtime", "--timestamp",
                    "--sign", signing_identity, binary_path
                ], f"Signing {binary} binary"):
                    sys.exit(1)
            else:
                print(f"⚠️ Warning: {binary} not found at {binary_path}")
        
        # Sign main executable
        if not run_command([
            "codesign", "--force", "--sign", signing_identity,
            "--timestamp", "--options", "runtime", "--entitlements", "Resistine.entitlements",
            f"{app_path}/Contents/MacOS/Resistine AI"
        ], "Signing main executable"):
            sys.exit(1)
        
        # Sign entire app bundle
        if not run_command([
            "codesign", "--force", "--deep", "--sign", signing_identity,
            "--timestamp", "--options", "runtime", "--entitlements", "Resistine.entitlements",
            app_path
        ], "Signing app bundle"):
            sys.exit(1)
    
    # Create DMG
    print("💿 Creating DMG...")
    with tempfile.TemporaryDirectory() as temp_dir:
        shutil.copytree(app_path, os.path.join(temp_dir, "Resistine AI.app"))
        os.symlink("/Applications", os.path.join(temp_dir, "Applications"))
        

        if not run_command([
            "hdiutil", "create", "-volname", "Resistine AI Installer",
            "-srcfolder", temp_dir, "-ov", "-format", "UDZO",
            "Resistine AI-1.0.0.dmg"
        ], "Creating installer DMG"):
            sys.exit(1)
        


if __name__ == "__main__":
    main() 