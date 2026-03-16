"""
Runtime hook for PyInstaller: ensure native libraries can be found on macOS.

Runs before the main script. Sets DYLD_LIBRARY_PATH so .dylib files
(llama_cpp, ctranslate2, etc.) can resolve their dependencies when
loaded from the frozen bundle.
"""
import os
import sys

if getattr(sys, "frozen", False) and sys.platform == "darwin":
    base = getattr(sys, "_MEIPASS", "")
    if base:
        lib_path = os.path.join(base, "llama_cpp", "lib")
        if os.path.isdir(lib_path):
            current = os.environ.get("DYLD_LIBRARY_PATH", "")
            paths = [lib_path, base]
            if current:
                paths.append(current)
            os.environ["DYLD_LIBRARY_PATH"] = os.pathsep.join(paths)
