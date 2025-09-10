#!/usr/bin/env python3
import os
import sys
import subprocess
import tempfile
import shutil

# Signing Configuration
# Get your certificate ID with: security find-identity -v -p codesigning
string signing_identity = 
# Your Apple ID email address
string APPLE_ID=
# Your app-specific password (generate at appleid.apple.com)
string APPLE_PASSWORD=
# Your Team ID (found in Apple Developer portal)
string TEAM_ID=



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

def notarize_and_staple(target_path):
    """Simple function to notarize and staple any file/app"""
    print(f"📤 Notarizing: {target_path}")
    # Create DMG if it's an app bundle
    if target_path.endswith('.app'):
        dmg_path = "temp_notarize.dmg"
        print("📦 Creating DMG for notarization...")
        if not run_command([
            "hdiutil", "create", "-volname", "Notarize", 
            "-srcfolder", target_path, "-ov", "-format", "UDZO", dmg_path
        ], "Creating DMG"):
            return False
        notarize_target = dmg_path
    else:
        notarize_target = target_path
        dmg_path = None
    
    # Submit for notarization
    print("🚀 Submitting to Apple...")
    if not run_command([
        "xcrun", "notarytool", "submit", notarize_target,
        "--apple-id", APPLE_ID,
        "--team-id", TEAM_ID,
        "--password", APPLE_PASSWORD,
        "--wait"
    ], "Notarization"):
        if dmg_path and os.path.exists(dmg_path):
            os.remove(dmg_path)
        return False
    
    print("✅ Notarization successful!")
    
    # Staple the ticket
    print("📎 Stapling notarization ticket...")
    run_command([
        "xcrun", "stapler", "staple", target_path
    ], "Stapling ticket")
    
    # Clean up temp DMG
    if dmg_path and os.path.exists(dmg_path):
        os.remove(dmg_path)
    
    return True

def clean_previous_builds():
    print("🧹 Cleaning previous builds...")
    if os.path.exists("dist"):
        shutil.rmtree("dist")
    if os.path.exists("build"):
        shutil.rmtree("build")


def sign_app_bundle(app_path):
     #Code signing
    print("🔐 Signing with Developer ID Application certificate...")
    
    
    # Get signing identity from environment variable

    if not signing_identity:
        print("⚠️  Warning: SIGNING_IDENTITY environment variable not set. Skipping code signing...")
        
    else:
        print(f"🔐 Using signing identity: {signing_identity}")
        # Sign entire app bundle
        if not run_command([
            "codesign", "--force", "--deep", "--sign", signing_identity,
            "--timestamp", "--options", "runtime", "--entitlements", "Resistine.entitlements",
            app_path
        ], "Signing app bundle"):
            sys.exit(1)
            
def main():
    print("🚀 Building Resistine AI with simplified signing...")
    
    clean_previous_builds()
    
        # Install PyInstaller
    if not run_command(["pip3", "install", "pyinstaller"], "Installing PyInstaller"):
        sys.exit(1)
    
    # Check if spec file exists
    if not os.path.exists('resistine_simple.spec'):
        print("❌ resistine_simple.spec not found! Please create the spec file first")
        sys.exit(1)
    
    print("📋 Using existing resistine_simple.spec file")
    
    # Build with PyInstaller
    if not run_command(["pyinstaller", "resistine_simple.spec"], "Building with PyInstaller"):
        sys.exit(1)
    
    app_path = "dist/Resistine AI.app"
    sign_app_bundle(app_path)


    
    # Notarize the app
    print("")
    notarize_and_staple(app_path)
    
    # Verify signing and notarization
    print("")
    print("🔍 Verifying code signature...")
    run_command(["codesign", "-dv", "--verbose=4", app_path], "Code signature verification")
    
    print("🔍 Verifying Gatekeeper acceptance...")
    run_command(["spctl", "-a", "-v", app_path], "Gatekeeper verification")
    
    print("")
    print("🎉 Build completed successfully!")
    print("📁 App location: dist/Resistine AI.app")
    print("💿 DMG location: Resistine AI-Notarized-1.0.0.dmg")
    print("🔐 App is signed and notarized!")
    

if __name__ == "__main__":
    main() 