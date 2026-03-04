# -*- mode: python ; coding: utf-8 -*-
# CustosAI Clipper — PyInstaller spec para deployment (CORREGIDO)
#
# FIXES aplicados:
# 1. argv_emulation=False (evita doble apertura en macOS)
# 2. Agregado psutil a hiddenimports (necesario para single instance lock)

import platform
import sys
from pathlib import Path

block_cipher = None

# Project paths
SPEC_DIR = Path(SPECPATH)
PROJECT_ROOT = SPEC_DIR
ASSETS = PROJECT_ROOT / "assets"

# Platform key for FFmpeg bundle
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

# Data files to bundle
datas = []
if (ASSETS).exists():
    datas.append((str(ASSETS), "assets"))
if (PROJECT_ROOT / ".env").exists():
    datas.append((str(PROJECT_ROOT / ".env"), "."))
if FFMPEG_BUNDLE.exists() and (FFMPEG_BUNDLE / "installed.crumb").exists():
    datas.append((str(FFMPEG_BUNDLE), str(Path("ffmpeg_bundle") / PLATFORM_KEY)))

# Bundle faster_whisper assets
for _p in sys.path:
    fw_assets = Path(_p) / "faster_whisper" / "assets"
    if fw_assets.exists() and (fw_assets / "silero_vad.onnx").exists():
        datas.append((str(fw_assets), "faster_whisper/assets"))
        break

# Bundle OpenCV haarcascades
for _p in sys.path:
    cv2_data = Path(_p) / "cv2" / "data"
    if cv2_data.exists() and (cv2_data / "haarcascade_frontalface_default.xml").exists():
        datas.append((str(cv2_data), "cv2/data"))
        break

# Bundle llama-cpp-python native libraries
try:
    import llama_cpp
    _llama_pkg = Path(llama_cpp.__file__).parent
    _llama_lib = _llama_pkg / "lib"
    if _llama_lib.exists():
        for _f in _llama_lib.iterdir():
            if _f.suffix in (".dylib", ".so", ".dll"):
                datas.append((str(_f), "llama_cpp/lib"))
except Exception:
    pass

# FIX: Agregado psutil para single instance lock robusto
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
    "psutil",  # FIX: Necesario para verificar procesos
]

# Collect submodules for packages that use dynamic imports
try:
    from PyInstaller.utils.hooks import collect_submodules, collect_data_files
    try:
        hiddenimports += collect_submodules("ctranslate2")
    except Exception:
        pass
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
    # FIX: Incluir datos de psutil
    try:
        datas += collect_data_files("psutil")
    except Exception:
        pass
except ImportError:
    pass

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
    # macOS: onedir + BUNDLE → LocalClipper.app
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
        # FIX CRÍTICO: Desactivar argv_emulation para evitar doble apertura
        # argv_emulation causa que macOS lance múltiples procesos cuando
        # la app se abre desde Finder o DMG
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
    # Windows: onedir → LocalClipper folder
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
        console=False,
        disable_windowed_traceback=False,
        argv_emulation=False,
        target_arch=None,
        codesign_identity=None,
        entitlements_file=None,
        icon=icon_ico,
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
