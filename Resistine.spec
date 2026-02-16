# -*- mode: python ; coding: utf-8 -*-
"""
PyInstaller spec file for Resistine Desktop Application
This bundles the Python Tkinter UI with all dependencies
Swift components (CLI, XPC, Network Extension) are added by build script
"""

import os
import sys
from PyInstaller.utils.hooks import collect_data_files, collect_dynamic_libs

block_cipher = None

# Application metadata
APP_NAME = 'Resistine'
BUNDLE_ID = 'com.resistine.desktop'
VERSION = '1.0.2'

# Paths
base_path = os.path.abspath('.')

# Collect data files
datas = [
    ('resources', 'resources'),
    ('plugins', 'plugins'),
    ('plugins_user', 'plugins_user'),
    ('gui', 'gui'),
    ('utils', 'utils'),
    ('docs', 'docs'),
    ('ResistineLogoWhiteText.png', '.'),
    ('ResistineSheild.png', '.'),
]

# Hidden imports (modules not auto-detected)
hiddenimports = [
    'tkinter',
    'tkinter.ttk',
    'customtkinter',
    'PIL',
    'PIL._tkinter_finder',
    'cryptography',
    'keyring',
    'keyring.backends',
    'keyring.backends.macOS',
    'pyobjc',
    'Foundation',
    'ServiceManagement',
    'AppKit',
    'Cocoa',
    'objc',
    'httpx',
    'openai',
    'markdown',
    'tkinterweb',
    'html2text',
    'loguru',
]

# Analysis
a = Analysis(
    ['main.py'],
    pathex=[base_path],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        'matplotlib',
        'numpy',
        'pandas',
        'scipy',
        'pytest',
        'setuptools',
    ],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

# Remove duplicate files
pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

# Create executable
exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name=APP_NAME,
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,  # No console window
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,  # Use native architecture (arm64 on Apple Silicon, x86_64 on Intel)
    codesign_identity=None,
    entitlements_file='Resistine.entitlements',
)

# Collect all files
coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name=APP_NAME,
)

# Create .app bundle
app = BUNDLE(
    coll,
    name=f'{APP_NAME}.app',
    icon='ResistineSheild.png',  # Will be converted to .icns
    bundle_identifier=BUNDLE_ID,
    version=VERSION,
    info_plist={
        # Basic app info
        'CFBundleName': APP_NAME,
        'CFBundleDisplayName': 'Resistine',
        'CFBundleExecutable': APP_NAME,
        'CFBundleIdentifier': BUNDLE_ID,
        'CFBundleVersion': VERSION,
        'CFBundleShortVersionString': VERSION,
        'CFBundleInfoDictionaryVersion': '6.0',
        'CFBundlePackageType': 'APPL',
        'CFBundleSignature': '????',

        # UI settings
        'NSHighResolutionCapable': True,
        'NSRequiresAquaSystemAppearance': False,
        'LSMinimumSystemVersion': '10.15.0',

        # Permissions (will be expanded with actual entitlements)
        'NSNetworkClient': True,
        'NSSystemAdministrationUsageDescription': 'Resistine needs admin access to manage VPN connections.',

        # XPC Services (will be populated by build script)
        'NSXPCServices': ['ResistineVPNXPC'],

        # Helper registration for privileged operations
        'SMPrivilegedExecutables': {
            'com.resistine.vpn.xpc': 'identifier "com.resistine.vpn.xpc" and anchor apple generic and certificate leaf[subject.CN] = "Resistine" and certificate 1[field.1.2.840.113635.100.6.2.1] /* exists */'
        },

        # URL schemes (if needed for OAuth, deep links, etc.)
        'CFBundleURLTypes': [
            {
                'CFBundleURLName': BUNDLE_ID,
                'CFBundleURLSchemes': ['resistine'],
            }
        ],

        # Document types (if you want to open .conf files)
        'CFBundleDocumentTypes': [
            {
                'CFBundleTypeName': 'WireGuard Configuration',
                'CFBundleTypeRole': 'Editor',
                'LSItemContentTypes': ['com.resistine.wireguard-config'],
                'LSHandlerRank': 'Owner',
            }
        ],

        # Export type for .conf files
        'UTExportedTypeDeclarations': [
            {
                'UTTypeIdentifier': 'com.resistine.wireguard-config',
                'UTTypeConformsTo': ['public.data', 'public.content'],
                'UTTypeDescription': 'WireGuard Configuration File',
                'UTTypeTagSpecification': {
                    'public.filename-extension': ['conf'],
                    'public.mime-type': 'text/plain',
                }
            }
        ],

        # Sparkle Auto-Update
        'SUFeedURL': 'https://resistine.github.io/appcast.xml',
        'SUPublicEDKey': '2eiUHVoMgl+qqhEWO8iix5SUcRAKfkWYESh9F7jG6ls=',
        'SUEnableAutomaticChecks': True,
        'SUScheduledCheckInterval': 14400,  # 4 hours (base; Python scheduler adds jitter)
    },
)
