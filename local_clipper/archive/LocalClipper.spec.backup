# -*- mode: python ; coding: utf-8 -*-
# CustosAI Clipper — PyInstaller Spec (Windows Fixes v1.1.0)

import platform
import sys
from pathlib import Path

block_cipher = None

SPEC_DIR = Path(SPECPATH)
PROJECT_ROOT = SPEC_DIR
ASSETS = PROJECT_ROOT / "assets"
LEGAL_DOCS = PROJECT_ROOT / "legal_docs"

APP_VERSION = "1.0.0"

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

datas = []
binaries = []  # Ahora usaremos esto para las DLLs en Windows

if ASSETS.exists():
    datas.append((str(ASSETS), "assets"))

if LEGAL_DOCS.exists():
    datas.append((str(LEGAL_DOCS), "legal_docs"))

if (PROJECT_ROOT / ".env").exists():
    datas.append((str(PROJECT_ROOT / ".env"), "."))

if FFMPEG_BUNDLE.exists() and (FFMPEG_BUNDLE / "installed.crumb").exists():
    datas.append((str(FFMPEG_BUNDLE), str(Path("ffmpeg_bundle") / PLATFORM_KEY)))

# Faster-whisper assets (silero_vad.onnx)
for _p in sys.path:
    fw_assets = Path(_p) / "faster_whisper" / "assets"
    if fw_assets.exists() and (fw_assets / "silero_vad.onnx").exists():
        datas.append((str(fw_assets), "faster_whisper/assets"))
        break

# CV2 data files
for _p in sys.path:
    cv2_data = Path(_p) / "cv2" / "data"
    if cv2_data.exists():
        datas.append((str(cv2_data), "cv2/data"))
        break

# ============================================================================
# BINARIOS NATIVOS - CRÍTICO PARA WINDOWS
# ============================================================================

try:
    from PyInstaller.utils.hooks import collect_dynamic_libs, collect_submodules, collect_data_files
    
    # 1. LLAMA-CPP-PYTHON - Librerías nativas
    try:
        import llama_cpp
        _llama_pkg = Path(llama_cpp.__file__).parent
        
        # En Windows, las DLLs pueden estar en varias ubicaciones
        # Buscar en lib/ y en el directorio raíz del paquete
        _llama_lib_paths = [_llama_pkg / "lib", _llama_pkg]
        
        for _lib_path in _llama_lib_paths:
            if _lib_path.exists():
                for _f in _lib_path.iterdir():
                    if _f.suffix in (".dylib", ".so", ".dll"):
                        # Usar binaries para DLLs en Windows
                        if sys.platform == "win32":
                            binaries.append((str(_f), "llama_cpp/lib" if "lib" in str(_f) else "."))
                        else:
                            datas.append((str(_f), "llama_cpp/lib"))
        
        # También intentar collect_dynamic_libs como respaldo
        if sys.platform == "win32":
            try:
                llama_bins = collect_dynamic_libs("llama_cpp")
                binaries.extend(llama_bins)
            except Exception:
                pass
                
    except Exception as e:
        print(f"Warning: Could not collect llama_cpp binaries: {e}")
    
    # 2. CTRANSLATE2 - Binarios nativos para faster-whisper
    try:
        ctranslate2_bins = collect_dynamic_libs("ctranslate2")
        binaries.extend(ctranslate2_bins)
    except Exception as e:
        print(f"Warning: Could not collect ctranslate2 binaries: {e}")
    
    # 3. ONNXRUNTIME - Usado por faster-whisper para VAD
    try:
        onnx_bins = collect_dynamic_libs("onnxruntime")
        binaries.extend(onnx_bins)
    except Exception as e:
        print(f"Warning: Could not collect onnxruntime binaries: {e}")
    
    # 4. PSUTIL - Binarios nativos
    try:
        psutil_bins = collect_dynamic_libs("psutil")
        binaries.extend(psutil_bins)
    except Exception as e:
        print(f"Warning: Could not collect psutil binaries: {e}")
    
    # 5. NUMPY - Binarios nativos (pueden ser necesarios en algunos casos)
    try:
        numpy_bins = collect_dynamic_libs("numpy")
        binaries.extend(numpy_bins)
    except Exception:
        pass
    
    # 6. CV2 (OpenCV) - Binarios nativos
    try:
        cv2_bins = collect_dynamic_libs("cv2")
        binaries.extend(cv2_bins)
    except Exception:
        pass
    
    # 7. PIL/Pillow - Binarios de imagen
    try:
        pil_bins = collect_dynamic_libs("PIL")
        binaries.extend(pil_bins)
    except Exception:
        pass
        
except ImportError:
    print("Warning: PyInstaller hooks not available")

# ============================================================================
# HIDDEN IMPORTS
# ============================================================================

hiddenimports = [
    "faster_whisper",
    "ctranslate2",
    "moviepy",
    "moviepy.editor",
    "moviepy.video.fx.all",
    "moviepy.audio.fx.all",
    "imageio",
    "imageio_ffmpeg",
    "imageio.plugins.ffmpeg",
    "PIL",
    "PIL.Image",
    "PIL.ImageDraw",
    "PIL.ImageFont",
    "PIL.ImageTk",
    "cv2",
    "cv2.data",
    "numpy",
    "numpy.core._dtype_ctypes",
    "yt_dlp",
    "yt_dlp.extractor",
    "yt_dlp.postprocessor",
    "static_ffmpeg",
    "static_ffmpeg.run",
    "requests",
    "requests.adapters",
    "requests.packages.urllib3",
    "dotenv",
    "llama_cpp",
    "llama_cpp.lib",
    "huggingface_hub",
    "huggingface_hub.file_download",
    "src.engine.ai_clip_selector",
    "src.engine.ai_transcriber",
    "src.engine.clip_selector",
    "src.engine.video_processor",
    "src.engine.yt_downloader",
    "src.auth.whop_api",
    "src.auth.hwid",
    "src.auth.license_storage",
    "src.gui.app",
    "src.gui.components",
    "src.utils.paths",
    "src.utils.ytdlp_updater",
    "psutil",
    "psutil._pswindows" if sys.platform == "win32" else "psutil._psposix",
    "customtkinter",
    "customtkinter.windows" if sys.platform == "win32" else "customtkinter.macOS",
    "onnxruntime",
    "certifi",
    "charset_normalizer",
    "idna",
    "urllib3",
    "packaging",
    "packaging.version",
    "pkg_resources",
    "pkg_resources.py31compat" if sys.platform == "win32" else "pkg_resources.py2_warn",
]

# Recolectar submódulos adicionales
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
        hiddenimports += collect_submodules("moviepy")
    except Exception:
        pass
    try:
        hiddenimports += collect_submodules("PIL")
    except Exception:
        pass
    try:
        hiddenimports += collect_submodules("cv2")
    except Exception:
        pass
    try:
        hiddenimports += collect_submodules("yt_dlp")
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
    try:
        datas += collect_data_files("certifi")
    except Exception:
        pass
    try:
        datas += collect_data_files("customtkinter")
    except Exception:
        pass
except ImportError:
    pass

# Eliminar duplicados
hiddenimports = list(set(hiddenimports))

# ============================================================================
# ANALYSIS
# ============================================================================

a = Analysis(
    [str(PROJECT_ROOT / "main.py")],
    pathex=[str(PROJECT_ROOT)],
    binaries=binaries,  # Ahora incluye las DLLs
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        "matplotlib",
        "scipy",
        "pandas",
        "tkinter.test",
        "tkinter.ttk.test",
        "unittest",
        "pytest",
        "pydoc",
        "doctest",
    ],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

icon_icns = str(ASSETS / "icon.icns") if (ASSETS / "icon.icns").exists() else None
icon_ico = str(ASSETS / "icon.ico") if (ASSETS / "icon.ico").exists() else None

if sys.platform == "darwin":
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
        version=APP_VERSION,
        info_plist={
            "NSPrincipalClass": "NSApplication",
            "NSHighResolutionCapable": True,
            "LSMultipleInstancesProhibited": True,
            "CFBundleIconFile": "icon",
            "CFBundleVersion": APP_VERSION,
            "CFBundleShortVersionString": APP_VERSION,
        },
    )
else:
    # Windows (y Linux) - Modo onedir para alto rendimiento y estabilidad IA
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
