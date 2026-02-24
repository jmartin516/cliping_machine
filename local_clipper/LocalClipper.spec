# -*- mode: python ; coding: utf-8 -*-
# CustosAI Clipper — PyInstaller spec for deployment
#
# Build: python -m PyInstaller LocalClipper.spec
# Output macOS: dist/LocalClipper.app (proper .app bundle)
# Output Windows: dist/LocalClipper.exe (onefile)

import sys
from pathlib import Path

block_cipher = None

# Project paths
SPEC_DIR = Path(SPECPATH)
PROJECT_ROOT = SPEC_DIR
ASSETS = PROJECT_ROOT / "assets"

# Data files to bundle (assets for icons; .env for license validation)
datas = []
if (ASSETS).exists():
    datas.append((str(ASSETS), "assets"))
# Bundle .env so the app can validate Whop licenses (required for distribution)
if (PROJECT_ROOT / ".env").exists():
    datas.append((str(PROJECT_ROOT / ".env"), "."))

# Hidden imports for faster-whisper, ctranslate2, moviepy, etc.
hiddenimports = [
    "faster_whisper",
    "ctranslate2",
    "moviepy",
    "moviepy.editor",
    "imageio",
    "imageio_ffmpeg",
    "PIL",
    "PIL.Image",
    "PIL.ImageDraw",
    "PIL.ImageFont",
    "cv2",
    "numpy",
    "yt_dlp",
    "static_ffmpeg",
    "static_ffmpeg.run",
    "requests",
    "dotenv",
]

# Collect submodules for packages that use dynamic imports
try:
    from PyInstaller.utils.hooks import collect_submodules, collect_data_files
    hiddenimports += collect_submodules("ctranslate2")
    hiddenimports += collect_submodules("faster_whisper")
    try:
        datas += collect_data_files("static_ffmpeg")
    except Exception:
        pass
except ImportError:
    pass  # PyInstaller hooks not available during spec parsing

a = Analysis(
    [str(PROJECT_ROOT / "main.py")],
    pathex=[str(PROJECT_ROOT)],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        "matplotlib",
        "scipy",
        "pandas",
    ],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

# Icon paths
icon_icns = str(ASSETS / "icon.icns") if (ASSETS / "icon.icns").exists() else None
icon_ico = str(ASSETS / "icon.ico") if (ASSETS / "icon.ico").exists() else None

if sys.platform == "darwin":
    # macOS: onedir + BUNDLE → LocalClipper.app (proper app bundle)
    exe = EXE(
        pyz,
        a.scripts,
        [],
        exclude_binaries=True,
        name="LocalClipper",
        debug=False,
        bootloader_ignore_signals=False,
        strip=False,
        upx=True,
        upx_exclude=[],
        runtime_tmpdir=None,
        console=False,
        disable_windowed_traceback=False,
        argv_emulation=True,
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
        name="LocalClipper",
    )
    app = BUNDLE(
        coll,
        name="LocalClipper.app",
        icon=icon_icns,
        bundle_identifier="com.custosai.clipper",
        info_plist={
            "NSPrincipalClass": "NSApplication",
            "NSHighResolutionCapable": True,
        },
    )
else:
    # Windows: onefile → LocalClipper.exe
    exe = EXE(
        pyz,
        a.scripts,
        a.binaries,
        a.zipfiles,
        a.datas,
        [],
        name="LocalClipper",
        debug=False,
        bootloader_ignore_signals=False,
        strip=False,
        upx=True,
        upx_exclude=[],
        runtime_tmpdir=None,
        console=False,
        disable_windowed_traceback=False,
        argv_emulation=False,
        target_arch=None,
        codesign_identity=None,
        entitlements_file=None,
        icon=icon_ico,
    )
