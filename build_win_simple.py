#!/usr/bin/env python3
import os
import sys
import subprocess
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parent

def load_build_config():
    """Load KEY=VALUE pairs from build_config.env into os.environ"""
    cfg = ROOT / "build_config.env"
    if cfg.exists():
        print(f"📋 Loading configuration from {cfg.name}...")
        try:
            for line in cfg.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                k, v = line.split("=", 1)
                v = v.strip().strip('"').strip("'")
                os.environ[k.strip()] = v
                print(f"   Loaded: {k.strip()}")
            print("✅ Configuration loaded successfully")
        except Exception as e:
            print(f"❌ Error loading {cfg.name}: {e}")
            print("⚠️  Continuing with environment variables only")
    else:
        print(f"⚠️  {cfg.name} not found. Using environment variables only.")

def run_command(cmd, description):
    print(f"Running: {' '.join(map(str, cmd))}")
    try:
        subprocess.check_call(cmd)
        print(f"✅ {description} completed")
        return True
    except subprocess.CalledProcessError as e:
        print(f"❌ {description} failed: {e}")
        return False

def clean_previous_builds():
    print("🧹 Cleaning previous builds...")
    for d in ("dist", "build"):
        shutil.rmtree(ROOT / d, ignore_errors=True)
    for f in ROOT.glob("*.spec"):
        try:
            f.unlink()
        except Exception:
            pass

def ensure_package_markers():
    """Ensure packages exist so pkgutil discovery works."""
    needed = [
        "plugins/__init__.py",
        "plugins/dashboard/__init__.py",
        "plugins/help/__init__.py",
        "plugins/settings/__init__.py",
        "plugins/vpn/__init__.py",
        "plugins/vpn/wireguard/__init__.py",
        "utils/__init__.py",
    ]
    for rel in needed:
        p = ROOT / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        if not p.exists():
            p.write_text("", encoding="utf-8")

def write_spec():
    """Generate a robust onefile spec that includes all assets and plugin code."""
    name = os.environ.get("APP_NAME", "ResistineAI")
    icon = os.environ.get("ICON", str(ROOT / "resources" / "icons" / "icon.ico"))
    console = os.environ.get("CONSOLE", "0") in ("1", "true", "True")
    include_chat = os.environ.get("INCLUDE_CHAT", "0") in ("1", "true", "True")

    hidden_openai = """
hiddenimports += ['openai','httpx','httpcore','anyio','sniffio','pydantic','pydantic_core','typing_extensions']
""" if include_chat else ""

    spec = f"""# -*- mode: python ; coding: utf-8 -*-
import os, sys
from PyInstaller.utils.hooks import collect_submodules, collect_data_files
from PyInstaller.building.build_main import Analysis, PYZ, EXE
from PyInstaller.building.datastruct import Tree

# Robust project root (works when __file__ is unset)
spec_path = globals().get('__file__') or (sys.argv[0] if sys.argv else os.getcwd())
project_dir = os.path.abspath(os.path.dirname(spec_path)) if os.path.isfile(spec_path) else os.getcwd()

hiddenimports = []
# Pull in all plugin modules so pkgutil discovery can import them
hiddenimports += collect_submodules('plugins')
# 3rd-party modules and plugins your app uses
hiddenimports += collect_submodules('tkinterweb')
hiddenimports += collect_submodules('PIL')
hiddenimports += collect_submodules('nacl')
hiddenimports += collect_submodules('keyring')
{hidden_openai}
hiddenimports += [
    'tkinter','tkinter.ttk','tkinter.messagebox','tkinter.filedialog',
    'PIL._tkinter_finder','customtkinter','darkdetect',
    'requests','markdown',
    'nacl.public','nacl.bindings',
    'win32ctypes.core','win32ctypes.pywin32',
    'plugins.plugin_manager','utils.functions',
]

datas = []
# Force-copy your project trees so .png/.json/.conf/.md and .py files are present
for folder in ['resources','libraries','utils','plugins']:
    p = os.path.join(project_dir, folder)
    if os.path.isdir(p):
        datas += Tree(p, prefix=folder).toc

# Third-party package data (native binaries, cert bundle, libsodium DLLs)
datas += collect_data_files('tkinterweb')
datas += collect_data_files('certifi')
datas += collect_data_files('nacl')

a = Analysis(
    ['main.py'],
    pathex=[project_dir],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={{}},
    runtime_hooks=[],
    excludes=[],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=None,
    noarchive=True,  # keep modules unpacked under _MEIPASS so pkgutil and __file__ paths work
)

pyz = PYZ(a.pure, a.zipped_data, cipher=None)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    name='{name}',
    icon=os.path.join(project_dir, r'{icon.replace("\\\\","/")}'),
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console={str(console)},
    disable_windowed_traceback=False,
)
"""
    out = ROOT / "final_resistine.spec"
    out.write_text(spec, encoding="utf-8")
    print(f"📝 Wrote spec: {out}")
    return out

def ensure_pyinstaller():
    return run_command([sys.executable, "-m", "pip", "install", "--upgrade", "pyinstaller"], "Installing/Upgrading PyInstaller")

def install_requirements():
    req = ROOT / "requirements_windows.txt"
    if req.exists():
        return run_command([sys.executable, "-m", "pip", "install", "-r", str(req)], "Installing app requirements")
    return True

def sign_exe_if_configured():
    if os.environ.get("SIGN", "0") not in ("1","true","True"):
        print("🔑 Code signing skipped (set SIGN=1 in build_config.env to enable).")
        return True
    exe = ROOT / "dist" / (os.environ.get("APP_NAME","ResistineAI") + ".exe")
    if not exe.exists():
        print(f"❌ Cannot sign; missing {exe}")
        return False
    signtool = os.environ.get("SIGNTOOL", "signtool.exe")
    pfx = os.environ.get("CERT_PATH", "")
    pwd = os.environ.get("CERT_PASSWORD", "")
    ts = os.environ.get("TIMESTAMP_URL", "http://timestamp.digicert.com")
    if not pfx or not Path(pfx).exists():
        print("⚠️  CERT_PATH missing/invalid. Skipping signing.")
        return True
    cmd = [signtool, "sign", "/f", pfx, "/p", pwd, "/tr", ts, "/td", "sha256", "/fd", "sha256", str(exe)]
    return run_command(cmd, "Code signing EXE")

def main():
    print("🚀 Building Resistine AI (Windows onefile)…")
    os.chdir(str(ROOT))
    load_build_config()
    clean_previous_builds()
    ensure_package_markers()
    if not ensure_pyinstaller(): sys.exit(1)
    if not install_requirements(): sys.exit(1)
    spec_path = write_spec()
    if not run_command(["pyinstaller", "-y", str(spec_path)], "Building with PyInstaller"):
        sys.exit(1)
    if not sign_exe_if_configured():
        sys.exit(1)
    print(f"🎉 Build complete: {ROOT / 'dist' / (os.environ.get('APP_NAME','ResistineAI') + '.exe')}")

if __name__ == "__main__":
    main()