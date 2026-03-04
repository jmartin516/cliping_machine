#!/usr/bin/env bash
# CustosAI Clipper — Fix Tk crash on macOS (CORREGIDO)
#
# FIXES aplicados:
# 1. Verificación de proceso existente antes de lanzar
# 2. Mejor manejo de errores
# 3. Limpieza de archivos stale

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
MACOS_DIR="$PROJECT_ROOT/dist/LocalClipper.app/Contents/MacOS"
REAL_BIN="$MACOS_DIR/LocalClipper"
WRAPPER="$MACOS_DIR/LocalClipper"
LAUNCHER="$MACOS_DIR/pty_launcher"

if [ ! -f "$REAL_BIN" ]; then
    echo "ERROR: $REAL_BIN not found. Run build first."
    exit 1
fi

# Already applied?
if [ -f "$MACOS_DIR/LocalClipper.real" ] && [ -f "$MACOS_DIR/pty_launcher" ]; then
    echo "macOS Tk fix already applied."
    exit 0
fi

echo "Applying macOS Tk crash fix..."

# FIX: Limpiar procesos zombie si existen
if pgrep -f "LocalClipper.real" > /dev/null 2>&1; then
    echo "WARNING: LocalClipper processes already running. Killing stale processes..."
    pkill -f "LocalClipper.real" 2>/dev/null || true
    sleep 0.5
fi

# 1. Compile pty_launcher
cc -o "$LAUNCHER" "$SCRIPT_DIR/pty_launcher.c" || {
    echo "ERROR: Failed to compile pty_launcher. Need Xcode Command Line Tools."
    exit 1
}
chmod +x "$LAUNCHER"

# 2. Move real binary to LocalClipper.real
mv "$REAL_BIN" "$MACOS_DIR/LocalClipper.real"

# 3. Create wrapper with verificación de instancia única
cat > "$WRAPPER" << 'WRAPPER_EOF'
#!/bin/bash
# LocalClipper macOS Launcher (CORREGIDO)

# FIX: Verificar si ya hay una instancia corriendo
if pgrep -f "LocalClipper.real" > /dev/null 2>&1; then
    # Verificar que no seamos nosotros mismos (mismo PID padre)
    PARENT_PID=$(ps -p $$ -o ppid= | tr -d ' ')
    LOCAL_CLIPPER_PIDS=$(pgrep -f "LocalClipper.real" | tr '\n' ' ')
    
    for PID in $LOCAL_CLIPPER_PIDS; do
        if [ "$PID" != "$PARENT_PID" ] && [ "$PID" != "$$" ]; then
            # Otra instancia realmente está corriendo
            echo "LocalClipper is already running." >&2
            exit 0
        fi
    done
fi

dir="$(cd "$(dirname "$0")" && pwd)"
exec "$dir/pty_launcher" "$dir/LocalClipper.real" "$@"
WRAPPER_EOF

chmod +x "$WRAPPER"

echo "Done. LocalClipper uses pty launcher with single-instance protection."
