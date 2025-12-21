# -*- mode: python ; coding: utf-8 -*-

block_cipher = None

a = Analysis(
    ['main.py'],
    pathex=[],
    binaries=[
        
    ],
    datas=[
        ('resources', 'resources'),
        ('plugins', 'plugins'),
        ('utils', 'utils'),
    ],
    hiddenimports=[
        'tkinter', 'tkinter.ttk', 'tkinter.messagebox', 'tkinter.filedialog',
        'PIL', 'PIL._tkinter_finder', 'customtkinter', 'darkdetect',
        'keyring', 'cryptography', 'cryptography.fernet', 'markdown', 'openai', 'requests',
        'objc', 'Foundation','ServiceManagement', 
        'html2text', 'html2text.html2text', 'plugins.plugin_manager', 'utils.functions',
        'tkinterweb', 'tkinterweb_tkhtml'
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
    name='Resistine',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file='Resistine.entitlements',
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='Resistine',
)

app = BUNDLE(
    coll,
    name='Resistine.app',
    icon='resources/icons/icon.ico',
    bundle_identifier='com.resistine',
    info_plist={
        'CFBundleName': 'Resistine',
        'CFBundleDisplayName': 'Resistine',
        'CFBundleIdentifier': 'com.resistine',
        'CFBundleVersion': '1.0.0',
        'CFBundleShortVersionString': '1.0.0',
        'NSHighResolutionCapable': True,
        'LSMinimumSystemVersion': '10.15.0',
        'NSAppleEventsUsageDescription': 'Resistine needs to access system features for VPN management.',
        'NSNetworkVolumesUsageDescription': 'Resistine needs network access for VPN functionality.',
        'SMPrivilegedExecutables': {
            'com.resistine.helper': 'identifier "com.resistine.helper" and anchor apple generic and certificate 1[field.1.2.840.113635.100.6.2.6] /* exists */ and certificate leaf[field.1.2.840.113635.100.6.1.13] /* exists */ and certificate leaf[subject.OU] = C7KSRZC3Q9'
        },
    },
)
