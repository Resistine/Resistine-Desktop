# -*- mode: python ; coding: utf-8 -*-


a = Analysis(
    ['main.py'],
    pathex=[],
    binaries=[],
    datas=[
        ('shares', 'shares'),   # Move 'shares' to _internal
        ('plugins', 'plugins'), # Move 'plugins' to _internal
        ('views', 'views'),    # Move 'views' to _internal
        ('images', 'images')   # Move 'images' to _internal
    ],
    hiddenimports=[
        'pkgutil',
        'zipimport',
        'struct',
        'unittest',
        'difflib',
        'PIL',
        'setuptools',
        'importlib',
        'json',
        'platform',
        'multiprocessing',
        'ctypes',
        'darkdetect',
        'charset_normalizer',
        'idna',
        'urllib3',
        'requests',
        'packaging',
        'olefile',
        'tkinter',                # Add tkinter
        'tkinter.ttk',            # Add ttk if you are using advanced widgets
        'tkinter.messagebox',     # Add messagebox for dialogs
        'tkinter.filedialog',     # Add filedialog for file selection
        'tkinter.colorchooser',   # Add colorchooser for color picker
        'tkinter.simpledialog',   # Add simpledialog for simple input dialogs
        'tkinter.scrolledtext',   # Add scrolledtext for text widgets
        'openai',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='resistine',
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
    icon=['images\\icon.ico'],
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='resistine',
)
