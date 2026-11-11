# -*- mode: python ; coding: utf-8 -*-
"""
kya-ray.spec - Modern PyInstaller specification for Kya-Ray.

Packages the native PySide6 desktop companion together with the embedded
FastAPI cloud backend, GroqCloud provider, and system tray/hotkey listeners.
"""

from PyInstaller.utils.hooks import collect_data_files, collect_submodules

# Synchronize Windows PE executable metadata with authoritative version
try:
    from desktop.version import sync_file_version_info
    sync_file_version_info()
except Exception:
    pass

block_cipher = None

# Comprehensive collection of submodules required for runtime dynamic imports
hiddenimports = [
    # Global hotkey and clipboard
    'pynput',
    'pynput.keyboard',
    'pynput.keyboard._win32',
    'pynput.mouse',
    'pynput.mouse._win32',
    'pyperclip',

    # Windows native integration
    'ctypes',
    'ctypes.wintypes',
    'winreg',

    # PySide6 GUI framework
    'PySide6',
    'PySide6.QtCore',
    'PySide6.QtGui',
    'PySide6.QtWidgets',

    # Networking & Utilities
    'http',
    'http.client',
    'json',
    'threading',
    'subprocess',
    'multiprocessing',
]

# Collect all dynamic submodules for API framework and LLM client
hiddenimports += collect_submodules('uvicorn')
hiddenimports += collect_submodules('fastapi')
hiddenimports += collect_submodules('starlette')
hiddenimports += collect_submodules('groq')
hiddenimports += collect_submodules('httpx')
hiddenimports += collect_submodules('pydantic')
hiddenimports += collect_submodules('pydantic_core')
hiddenimports += collect_submodules('dotenv')
hiddenimports += collect_submodules('backend')
hiddenimports += collect_submodules('desktop')
hiddenimports.append('version')

# Remove duplicate imports while preserving order
hiddenimports = list(dict.fromkeys(hiddenimports))

# Static assets and template configurations (NO private keys or .env with secrets)
datas = [
    ('assets', 'assets'),
    ('.env.example', '.'),
]

a = Analysis(
    ['desktop/app.py'],
    pathex=['.'],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        'tkinter',      # Legacy prototype UI not used
        'unittest',
        'pytest',
    ],
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
    name='Kya-Ray',
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
    icon='assets/icon.ico',
    version='file_version_info.txt',
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='Kya-Ray',
)
