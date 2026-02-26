# -*- mode: python ; coding: utf-8 -*-
# CustosAI Clipper — PyInstaller spec for deployment
#
# Build: python -m PyInstaller LocalClipper.spec
# Output macOS: dist/LocalClipper.app (proper .app bundle)
# Output Windows: dist/LocalClipper.exe (onefile)
#
# Run scripts/setup_ffmpeg_bundle.py and scripts/setup_icons.py before building.

import platform
import sys
from pathlib import Path

block_cipher = None

# Project paths
SPEC_DIR = Path(SPECPATH)
PROJECT_ROOT = SPEC_DIR
ASSETS = PROJECT_ROOT / "assets"

# Platform key for FFmpeg bundle (darwin, darwin_arm64, win32, linux, linux_arm64)
def _get_platform_key():
    m = platform.machine().lower()
    arm = m in ("arm64", "aarch64")
    if sys.platform == "win32":
        return "win32"
    if sys.platform == "darwin":
        return "darwin_arm64" if arm else "darwin"
    if sys.platform == "linux":
        return "linux_arm64" if arm else "linux"
    return sys.platform

PLATFORM_KEY = _get_platform_key()
FFMPEG_BUNDLE = PROJECT_ROOT / "ffmpeg_bundle" / PLATFORM_KEY

# Data files to bundle (assets for icons; .env for license validation; FFmpeg)
datas = []
if (ASSETS).exists():
    datas.append((str(ASSETS), "assets"))
# Bundle .env so the app can validate Whop licenses (required for distribution)
if (PROJECT_ROOT / ".env").exists():
    datas.append((str(PROJECT_ROOT / ".env"), "."))
# Bundle pre-downloaded FFmpeg (no download on first launch)
if FFMPEG_BUNDLE.exists() and (FFMPEG_BUNDLE / "installed.crumb").exists():
    datas.append((str(FFMPEG_BUNDLE), str(Path("ffmpeg_bundle") / PLATFORM_KEY)))

# Bundle faster_whisper assets (silero_vad.onnx for VAD) — required for transcription
for _p in sys.path:
    fw_assets = Path(_p) / "faster_whisper" / "assets"
    if fw_assets.exists() and (fw_assets / "silero_vad.onnx").exists():
        datas.append((str(fw_assets), "faster_whisper/assets"))
        break

# Bundle OpenCV haarcascades for face detection (smart crop)
for _p in sys.path:
    cv2_data = Path(_p) / "cv2" / "data"
    if cv2_data.exists() and (cv2_data / "haarcascade_frontalface_default.xml").exists():
        datas.append((str(cv2_data), "cv2/data"))
        break

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
    "llama_cpp",
    "huggingface_hub",
    "src.engine.ai_clip_selector",
]

# Collect submodules for packages that use dynamic imports
try:
    from PyInstaller.utils.hooks import collect_submodules, collect_data_files
    try:
        hiddenimports += collect_submodules("ctranslate2")
    except Exception:
        pass  # ctranslate2 can segfault when collecting submodules on some systems
    try:
        hiddenimports += collect_submodules("faster_whisper")
    except Exception:
        pass
    try:
        datas += collect_data_files("static_ffmpeg")
    except Exception:
        pass
    try:
        datas += collect_data_files("faster_whisper")
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
            "LSMultipleInstancesProhibited": True,
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
