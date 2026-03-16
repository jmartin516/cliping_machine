# LocalClipper - Informe de Auditoría de Seguridad y Crítica de Código

## Fecha: 2026-02-26
## Auditor: Análisis Exhaustivo de Código

---

## RESUMEN EJECUTIVO

Se ha identificado el **PROBLEMA CRÍTICO DE DOBLE APERTURA** y múltiples problemas de seguridad y estabilidad que deben resolverse antes del lanzamiento al mercado.

### Problema Principal: Doble Apertura desde DMG

**CAUSA RAÍZ IDENTIFICADA:** La combinación de tres factores causa que la app se abra dos veces:

1. **argv_emulation=True** en PyInstaller (línea 162 de LocalClipper.spec)
2. **Wrapper script de bash + pty_launcher** sin manejo adecuado de señales
3. **Single-instance lock vulnerable a race conditions**

---

## LISTA DETALLADA DE PROBLEMAS

### 🔴 CRÍTICOS (Bloqueantes para lanzamiento)

#### 1. DOBLE APERTURA - argv_emulation + Wrapper Script
**Archivo:** `LocalClipper.spec` (línea 162)
**Severidad:** CRÍTICA

```python
# PROBLEMA:
argv_emulation=True,  # En combinación con el wrapper de shell script
```

**Explicación:**
- `argv_emulation` intercepta eventos de Apple Events de macOS
- Cuando la app se abre desde un DMG, macOS envía múltiples eventos de apertura
- El wrapper script de bash ejecuta el pty_launcher que hace execv()
- Esto crea una condición de carrera donde se pueden iniciar dos procesos

**Solución:**
```python
# En LocalClipper.spec - DESACTIVAR argv_emulation
exe = EXE(
    ...
    argv_emulation=False,  # Cambiar a False
    ...
)
```

---

#### 2. DOBLE APERTURA - Single Instance Lock Inseguro
**Archivo:** `main.py` (líneas 43-81)
**Severidad:** CRÍTICA

```python
# PROBLEMAS EN _try_single_instance_lock():

def _try_single_instance_lock() -> bool:
    global _lock_file_handle
    # PROBLEMA 1: El lock se adquiere DESPUÉS de que el proceso ya está corriendo
    # PROBLEMA 2: No hay protección contra múltiples instancias simultáneas
    # PROBLEMA 3: Si el lock falla, retorna True igualmente (línea 81)
    
    if str(_ROOT) not in sys.path:
        sys.path.insert(0, str(_ROOT))
    from src.utils.paths import get_app_data_dir
    lock_file = get_app_data_dir() / ".single_instance.lock"
    try:
        # ...
    except Exception:
        # PROBLEMA CRÍTICO: Si hay cualquier error, permite la ejecución
        return True  # <- Esto es MUY peligroso
```

**Solución:** Implementar un lock robusto con timeout y verificación de proceso
```python
import psutil
import atexit

def _try_single_instance_lock() -> bool:
    """Single instance lock con verificación de proceso activo."""
    global _lock_file_handle
    
    from src.utils.paths import get_app_data_dir
    lock_dir = get_app_data_dir()
    lock_file = lock_dir / ".single_instance.lock"
    pid_file = lock_dir / ".instance.pid"
    
    try:
        # Verificar si hay otra instancia activa
        if pid_file.exists():
            try:
                old_pid = int(pid_file.read_text().strip())
                if psutil.pid_exists(old_pid):
                    # Verificar que sea realmente nuestra app
                    proc = psutil.Process(old_pid)
                    if "LocalClipper" in proc.name() or any("LocalClipper" in cmd for cmd in proc.cmdline()):
                        logger.warning(f"Another instance already running (PID: {old_pid})")
                        return False
            except (ValueError, psutil.NoSuchProcess, psutil.AccessDenied):
                pass
        
        # Adquirir lock de archivo
        import fcntl
        _lock_file_handle = open(lock_file, "w")
        fcntl.lockf(_lock_file_handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        
        # Escribir PID actual
        pid_file.write_text(str(os.getpid()))
        
        # Limpiar al salir
        atexit.register(_cleanup_lock, lock_file, pid_file)
        return True
        
    except (IOError, OSError) as e:
        logger.error(f"Could not acquire single instance lock: {e}")
        return False
    except Exception as e:
        logger.error(f"Unexpected error in single instance lock: {e}")
        return False  # <- Fallar CERRADO, no abierto

def _cleanup_lock(lock_file: Path, pid_file: Path) -> None:
    """Limpiar archivos de lock al salir."""
    global _lock_file_handle
    try:
        if _lock_file_handle:
            _lock_file_handle.close()
        pid_file.unlink(missing_ok=True)
    except Exception:
        pass
```

---

#### 3. DOBLE APERTURA - pty_launcher sin Manejo de Señales
**Archivo:** `scripts/pty_launcher.c` (líneas 12-23)
**Severidad:** CRÍTICA

```c
// PROBLEMA: No maneja señales ni verifica que el proceso hijo esté corriendo
int main(int argc, char *argv[]) {
    if (argc < 2) return 1;
    int master, slave;
    if (openpty(&master, &slave, NULL, NULL, NULL) != 0) return 1;
    dup2(slave, 0);
    dup2(slave, 1);
    dup2(slave, 2);
    if (slave > 2) close(slave);
    close(master);
    execv(argv[1], argv + 1);  // <- Si esto falla, no hay manejo de error
    _exit(127);  // <- No limpia recursos
}
```

**Solución:**
```c
/*
 * LocalClipper — Pty launcher para macOS con manejo de instancia única
 */
#include <stdlib.h>
#include <unistd.h>
#include <util.h>
#include <signal.h>
#include <sys/types.h>
#include <sys/wait.h>
#include <fcntl.h>
#include <string.h>
#include <stdio.h>

#define LOCK_FILE "/tmp/LocalClipper.lock"

static volatile sig_atomic_t child_pid = -1;

static void signal_handler(int sig) {
    if (child_pid > 0) {
        kill(child_pid, sig);
    }
}

int main(int argc, char *argv[]) {
    if (argc < 2) return 1;
    
    // Verificar si ya hay una instancia corriendo (simplificado)
    int lock_fd = open(LOCK_FILE, O_RDWR | O_CREAT, 0666);
    if (lock_fd < 0) return 1;
    
    struct flock fl = {
        .l_type = F_WRLCK,
        .l_whence = SEEK_SET,
        .l_start = 0,
        .l_len = 0
    };
    
    if (fcntl(lock_fd, F_SETLK, &fl) < 0) {
        // Otra instancia está corriendo
        close(lock_fd);
        return 0;  // Salir silenciosamente
    }
    
    // Configurar manejo de señales
    signal(SIGTERM, signal_handler);
    signal(SIGINT, signal_handler);
    
    // Crear pseudo-tty
    int master, slave;
    if (openpty(&master, &slave, NULL, NULL, NULL) != 0) {
        close(lock_fd);
        return 1;
    }
    
    dup2(slave, STDIN_FILENO);
    dup2(slave, STDOUT_FILENO);
    dup2(slave, STDERR_FILENO);
    if (slave > STDERR_FILENO) close(slave);
    
    // Fork para poder esperar al hijo y limpiar
    pid_t pid = fork();
    if (pid < 0) {
        close(master);
        close(lock_fd);
        return 1;
    }
    
    if (pid == 0) {
        // Proceso hijo
        close(master);
        close(lock_fd);  // El hijo no necesita el lock
        execv(argv[1], argv + 1);
        _exit(127);
    }
    
    // Proceso padre
    child_pid = pid;
    close(master);
    
    // Esperar al hijo
    int status;
    waitpid(pid, &status, 0);
    
    // Cleanup
    close(lock_fd);
    unlink(LOCK_FILE);
    
    if (WIFEXITED(status)) {
        return WEXITSTATUS(status);
    }
    return 1;
}
```

---

#### 4. SEGURIDAD - API Key Expuesta en Binario
**Archivo:** `LocalClipper.spec` (línea 41-42)
**Severidad:** CRÍTICA

```python
# PROBLEMA: El .env con WHOP_API_KEY se incluye en el binario
if (PROJECT_ROOT / ".env").exists():
    datas.append((str(PROJECT_ROOT / ".env"), "."))
```

**Impacto:**
- Cualquiera puede extraer la API key del binario
- `strings dist/LocalClipper.app/Contents/MacOS/LocalClipper.real | grep -i whop`

**Mitigación:** (No hay solución perfecta para apps de escritorio)
1. Implementar ofuscación básica
2. Rotar API keys regularmente
3. Implementar rate limiting en Whop
4. Usar HWID para limitar abuso

---

#### 5. SEGURIDAD - Exfiltración de Datos de Usuario
**Archivo:** `src/auth/hwid.py` (líneas 93-121)
**Severidad:** CRÍTICA

```python
# PROBLEMA: El HWID puede ser usado para rastrear usuarios
# El HWID es un UUID persistente del hardware
# Si se filtra la base de datos de Whop, se puede rastrear a los usuarios

def _get_hwid_macos() -> str:
    result = subprocess.run(
        ["ioreg", "-rd1", "-c", "IOPlatformExpertDevice"],
        ...
    )
    # Extrae IOPlatformUUID que es único por máquina
```

**Impacto:**
- Identificación única de dispositivos
- Rastreo cross-app si otras apps usan el mismo método
- No hay consentimiento explícito del usuario

**Recomendación:**
- Añadir diálogo de consentimiento en primera ejecución
- Documentar en política de privacidad
- Permitir revocación de licencia

---

### 🟠 MAYORES (Deben resolverse antes del lanzamiento)

#### 6. RENDIMIENTO - Carga de Modelos AI sin Control
**Archivo:** `src/gui/app.py` (líneas 340-349)

```python
# PROBLEMA: Se carga el modelo Whisper en thread sin manejo de errores robusto
try:
    from src.engine.ai_transcriber import load_model
    load_model("base", on_progress=None)  # Sin timeout ni control de memoria
except Exception as exc:
    logger.warning("Whisper pre-cache failed (non-fatal): %s", exc)
    # Non-fatal pero puede dejar la app en estado inconsistente
```

---

#### 7. RENDIMIENTO - Uso de Disco sin Límites
**Archivo:** `src/engine/video_processor.py` (líneas 227-241)

```python
# PROBLEMA: Archivos temporales sin limpieza garantizada
def extract_audio(...) -> Path:
    video = VideoFileClip(str(video_path))
    tmp = Path(tempfile.mktemp(suffix=".wav", prefix="lc_audio_"))
    video.audio.write_audiofile(str(tmp), ...)
    # Si hay excepción aquí, el archivo temporal no se limpia
    video.close()
    return tmp
```

---

#### 8. ESTABILIDAD - Multiprocessing sin Configuración Adecuada
**Archivo:** `main.py` (línea 162-163)

```python
# PROBLEMA: No se configura el método de inicio para macOS
import multiprocessing
multiprocessing.freeze_support()
# Falta: multiprocessing.set_start_method('spawn')
```

**Impacto:** En macOS, `fork` puede causar:
- Duplicación de procesos
- Problemas con objetos de Cocoa/Tk
- Deadlocks

---

### 🟡 MENORES (Mejoras recomendadas)

#### 9. UX - Mensajes de Error Genéricos
**Archivo:** `src/gui/app.py` (varias líneas)

Muchos errores muestran mensajes genéricos que no ayudan al usuario a resolver el problema.

#### 10. UX - No hay Indicador de Progreso en Descarga FFmpeg
**Archivo:** `src/gui/app.py` (líneas 324-330)

La descarga de FFmpeg puede tardar varios minutos sin feedback visual.

#### 11. CÓDIGO - Dependencias Sin Versiones Fijas
**Archivo:** `requirements.txt` (líneas 25, 29)

```
llama-cpp-python>=0.2.0  # Puede cambiar API
yt-dlp>=2024.1.0         # Puede cambiar comportamiento
```

#### 12. CÓDIGO - Uso de `subprocess` sin Validación de Entrada
**Archivo:** `src/auth/hwid.py` (varias líneas)

```python
# Aunque no es vulnerable directamente, es mala práctica
subprocess.run(["ioreg", "-rd1", "-c", "IOPlatformExpertDevice"], ...)
```

---

## ANÁLISIS ESPECÍFICO DEL PROBLEMA DE DOBLE APERTURA

### Escenario de Reproducción

1. Usuario monta el DMG `CustosAI-Clipper-macOS.dmg`
2. Usuario hace doble clic en `LocalClipper.app`
3. macOS:
   - Lanza el proceso principal
   - Envía evento de Apple Event de apertura
   - `argv_emulation=True` intercepta el evento
   - Puede lanzar un segundo proceso de validación

### Flujo de Ejecución Problemático

```
[Finder/DMG] 
    ↓
[LaunchServices] → Abre LocalClipper.app
    ↓
[Info.plist] → CFBundleExecutable = "LocalClipper"
    ↓
[LocalClipper - script bash]
    ↓
[pty_launcher] → execv() → [LocalClipper.real]
    ↓
[Python/PyInstaller] → main.py
    ↓
[_try_single_instance_lock()] → Verifica lock (¡race condition!)
    ↓
[GUI inicializa]
```

### Problemas en el Flujo

1. **El script bash wrapper** (`LocalClipper`) no reemplaza completamente el proceso
2. **pty_launcher** hace `execv()` pero puede fallar silenciosamente
3. **argv_emulation** puede causar que PyInstaller lance dos veces el proceso
4. **El single-instance lock** tiene una ventana de race condition

---

## RECOMENDACIONES CONCRETAS

### Fix Inmediato para Doble Apertura

#### Paso 1: Desactivar argv_emulation
```python
# LocalClipper.spec - línea 162
exe = EXE(
    ...
    argv_emulation=False,  # Cambiar a False
    ...
)
```

#### Paso 2: Mejorar el Single Instance Lock
Usar el código mejorado proporcionado arriba con `psutil`.

#### Paso 3: Agregar delay en inicialización
```python
# main.py - al inicio de main()
def main() -> None:
    # Delay para evitar race condition en apertura rápida
    import time
    time.sleep(0.1)
    
    if not _try_single_instance_lock():
        sys.exit(0)
    ...
```

#### Paso 4: Mejorar el apply_macos_tk_fix.sh
```bash
# Agregar verificación de proceso existente antes de lanzar
if pgrep -f "LocalClipper.real" > /dev/null; then
    echo "LocalClipper already running"
    exit 0
fi
```

---

## CHECKLIST DE PREPARACIÓN PARA LANZAMIENTO

### Seguridad
- [ ] Implementar ofuscación de API key
- [ ] Añadir diálogo de consentimiento de HWID
- [ ] Revisar política de privacidad
- [ ] Implementar rate limiting

### Estabilidad
- [ ] **CORREGIR: Doble apertura (argv_emulation=False)**
- [ ] **CORREGIR: Single instance lock robusto**
- [ ] **CORREGIR: Multiprocessing set_start_method('spawn')**
- [ ] Implementar manejo de errores en carga de modelos
- [ ] Agregar timeouts en operaciones de red

### UX
- [ ] Mejorar mensajes de error
- [ ] Añadir progress bar en descarga FFmpeg
- [ ] Implementar auto-update
- [ ] Añadir opción de "Abrir en carpeta" para clips generados

### Testing
- [ ] Test en macOS 12, 13, 14 (Intel y Apple Silicon)
- [ ] Test en Windows 10, 11
- [ ] Test de apertura desde DMG 10 veces consecutivas
- [ ] Test de licencia expirada
- [ ] Test sin conexión a internet

### Legal
- [ ] Añadir EULA
- [ ] Política de privacidad
- [ ] Términos de servicio
- [ ] Mecanismo de desactivación de licencia

---

## CÓDIGO CORREGIDO

### main.py - Versión Corregida

```python
"""
CustosAI Clipper — Application Entry Point (CORREGIDO)
"""

from __future__ import annotations

import os
import sys
import tempfile
import warnings
from pathlib import Path

# CRITICAL FIX: Set multiprocessing start method ANTES de cualquier otra cosa
if sys.platform == "darwin":
    import multiprocessing
    try:
        multiprocessing.set_start_method('spawn', force=True)
    except RuntimeError:
        pass  # Ya configurado

# When running from a DMG/bundle, cwd may be the read-only mount.
if getattr(sys, "frozen", False):
    _writable_cwd = Path(tempfile.gettempdir()) / "CustosAI-Clipper"
    _writable_cwd.mkdir(parents=True, exist_ok=True)
    os.chdir(str(_writable_cwd))

# Suppress known warnings
warnings.filterwarnings("ignore", message=".*OpenSSL.*")
warnings.filterwarnings("ignore", message=".*LibreSSL.*")
os.environ.setdefault("TK_SILENCE_DEPRECATION", "1")

import logging
import platform
import atexit

# Ensure the project root is on sys.path
if getattr(sys, "frozen", False):
    _ROOT = Path(sys._MEIPASS)
else:
    _ROOT = Path(__file__).resolve().parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

_lock_file_handle = None
_pid_file_handle = None

def _try_single_instance_lock() -> bool:
    """
    Acquire a single-instance lock with process verification.
    CRITICAL FIX: Fail-closed (return False on error, not True)
    """
    global _lock_file_handle, _pid_file_handle
    
    if str(_ROOT) not in sys.path:
        sys.path.insert(0, str(_ROOT))
    
    from src.utils.paths import get_app_data_dir
    import psutil
    
    lock_dir = get_app_data_dir()
    lock_file = lock_dir / ".single_instance.lock"
    pid_file = lock_dir / ".instance.pid"
    
    try:
        # Check if another instance is actually running
        if pid_file.exists():
            try:
                old_pid = int(pid_file.read_text().strip())
                if old_pid != os.getpid() and psutil.pid_exists(old_pid):
                    proc = psutil.Process(old_pid)
                    cmdline = " ".join(proc.cmdline())
                    if "LocalClipper" in cmdline or "LocalClipper.real" in cmdline:
                        print("LocalClipper is already running.", file=sys.stderr)
                        return False
            except (ValueError, psutil.NoSuchProcess, psutil.AccessDenied):
                pass  # Stale lock file
        
        # Acquire file lock
        if sys.platform == "win32":
            import msvcrt
            _lock_file_handle = open(lock_file, "w")
            try:
                msvcrt.locking(_lock_file_handle.fileno(), msvcrt.LK_NBLCK, 1)
            except OSError:
                _lock_file_handle.close()
                return False
        else:
            import fcntl
            _lock_file_handle = open(lock_file, "w")
            try:
                fcntl.lockf(_lock_file_handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            except (IOError, OSError):
                _lock_file_handle.close()
                return False
        
        # Write current PID
        pid_file.write_text(str(os.getpid()))
        
        # Register cleanup
        atexit.register(_cleanup_lock, lock_file, pid_file)
        return True
        
    except Exception as e:
        print(f"Lock error: {e}", file=sys.stderr)
        # CRITICAL FIX: Fail closed
        return False

def _cleanup_lock(lock_file: Path, pid_file: Path) -> None:
    """Clean up lock files on exit."""
    global _lock_file_handle
    try:
        if _lock_file_handle:
            _lock_file_handle.close()
        pid_file.unlink(missing_ok=True)
    except Exception:
        pass

def _check_tk_version() -> bool:
    """CustomTkinter requires Tk 8.6+."""
    if platform.system() != "Darwin":
        return True
    try:
        import tkinter as tk
        if tk.Tcl().eval('info patchlevel').split('.')[:2] < ['8', '6']:
            return False
    except Exception:
        pass
    return True

def _configure_logging() -> None:
    logging.basicConfig(
        level=logging.DEBUG,
        format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
        datefmt="%H:%M:%S",
    )
    logging.getLogger("PIL").setLevel(logging.WARNING)
    logging.getLogger("PIL.PngImagePlugin").setLevel(logging.WARNING)

def main() -> None:
    # CRITICAL FIX: Small delay to prevent race condition
    import time
    time.sleep(0.05)
    
    if not _try_single_instance_lock():
        sys.exit(0)
    
    if not _check_tk_version():
        print("Error: Tk 8.6+ required")
        sys.exit(1)
    
    _configure_logging()
    logger = logging.getLogger("local_clipper")
    logger.info("Starting CustosAI Clipper")
    
    from src.gui.app import LocalClipperApp
    app = LocalClipperApp()
    app.mainloop()

if __name__ == "__main__":
    multiprocessing.freeze_support()
    main()
```

### LocalClipper.spec - Versión Corregida

```python
# -*- mode: python ; coding: utf-8 -*-

import platform
import sys
from pathlib import Path

block_cipher = None

SPEC_DIR = Path(SPECPATH)
PROJECT_ROOT = SPEC_DIR
ASSETS = PROJECT_ROOT / "assets"

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

# Data files
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

# Bundle llama-cpp-python libraries
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

hiddenimports = [
    "faster_whisper", "ctranslate2", "moviepy", "moviepy.editor",
    "imageio", "imageio_ffmpeg", "PIL", "PIL.Image", "PIL.ImageDraw",
    "PIL.ImageFont", "cv2", "numpy", "yt_dlp", "static_ffmpeg",
    "static_ffmpeg.run", "requests", "dotenv", "llama_cpp",
    "huggingface_hub", "src.engine.ai_clip_selector", "psutil",  # ADD psutil
]

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
    excludes=["matplotlib", "scipy", "pandas"],
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
        argv_emulation=False,  # CRITICAL FIX: Desactivado para evitar doble apertura
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
            # ADD: Prevenir apertura múltiple a nivel de sistema
            "LSUIElement": False,
        },
    )
else:
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
```

---

## CONCLUSIÓN

El problema de doble apertura es **resoluble** con los cambios propuestos. Los problemas críticos son:

1. **argv_emulation=True** - Desactivar inmediatamente
2. **Single instance lock** - Implementar versión robusta con psutil
3. **Multiprocessing** - Configurar método 'spawn' para macOS

Con estos cambios, la app debería abrirse correctamente desde el DMG sin duplicación.

**Prioridad:** Resolver los problemas CRÍTICOS antes de cualquier lanzamiento.
