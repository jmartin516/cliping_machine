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
LEGAL_DOCS = PROJECT_ROOT / "legal_docs"
if LEGAL_DOCS.exists():
    datas.append((str(LEGAL_DOCS), "legal_docs"))
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

# ── Native libraries & binaries ─────────────────────────────────────────────
binaries = []

# 1. llama-cpp-python: native .dylib/.so/.dll (required for AI clip selection)
try:
    import llama_cpp
    _llama_pkg = Path(llama_cpp.__file__).parent
    _llama_lib = _llama_pkg / "lib"
    if _llama_lib.exists():
        for _f in _llama_lib.iterdir():
            if _f.suffix in (".dylib", ".so", ".dll"):
                binaries.append((str(_f), "llama_cpp/lib"))
    # Apple Silicon: ggml-metal.metal for GPU acceleration
    _metal = _llama_pkg / "ggml-metal.metal"
    if _metal.exists():
        datas.append((str(_metal), "llama_cpp"))
except Exception:
    pass

# 2. ctranslate2: native libs for faster-whisper
try:
    from PyInstaller.utils.hooks import collect_dynamic_libs
    for _b in collect_dynamic_libs("ctranslate2"):
        binaries.append(_b)
except Exception:
    pass

# 3. onnxruntime: used by faster-whisper VAD
try:
    from PyInstaller.utils.hooks import collect_dynamic_libs
    for _b in collect_dynamic_libs("onnxruntime"):
        binaries.append(_b)
except Exception:
    pass

# 4. numpy: native extensions
try:
    from PyInstaller.utils.hooks import collect_dynamic_libs
    for _b in collect_dynamic_libs("numpy"):
        binaries.append(_b)
except Exception:
    pass

# ── Hidden imports: all packages and submodules ─────────────────────────────
hiddenimports = [
    "faster_whisper",
    "ctranslate2",
    "moviepy",
    "moviepy.editor",
    "moviepy.audio.AudioClip",
    "moviepy.video.VideoClip",
    "moviepy.video.io.VideoFileClip",
    "moviepy.video.fx.all",
    "moviepy.audio.fx.all",
    "imageio",
    "imageio_ffmpeg",
    "imageio.plugins.ffmpeg",
    "imageio.plugins.pillow",
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
    "urllib3",
    "certifi",
    "charset_normalizer",
    "idna",
    "dotenv",
    "llama_cpp",
    "huggingface_hub",
    "huggingface_hub.hf_api",
    "src.engine.ai_clip_selector",
    "psutil",
    "decorator",
    "proglog",
    "tqdm",
    "packaging",
    "packaging.version",
    "pkg_resources",
]

# Collect ALL submodules for packages with dynamic imports
try:
    from PyInstaller.utils.hooks import collect_submodules, collect_data_files
    for pkg in ("ctranslate2", "faster_whisper", "moviepy", "imageio", "PIL", "cv2", "yt_dlp", "huggingface_hub", "onnxruntime"):
        try:
            hiddenimports += collect_submodules(pkg)
        except Exception:
            pass
    # Data files
    for pkg in ("static_ffmpeg", "faster_whisper", "certifi", "customtkinter", "imageio", "psutil", "onnxruntime"):
        try:
            datas += collect_data_files(pkg)
        except Exception:
            pass
except ImportError:
    pass

# Deduplicate
hiddenimports = list(dict.fromkeys(hiddenimports))

_runtime_hook = PROJECT_ROOT / "scripts" / "runtime_hook_libs.py"
_runtime_hooks = [str(_runtime_hook)] if _runtime_hook.exists() else []

a = Analysis(
    [str(PROJECT_ROOT / "main.py")],
    pathex=[str(PROJECT_ROOT)],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=_runtime_hooks,
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
