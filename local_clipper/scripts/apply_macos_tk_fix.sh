#!/usr/bin/env bash
# CustosAI Clipper — macOS Tk Crash Fix Script (FIXED VERSION)
#
# This script applies a fix for Tk crashes when launching from Finder on macOS.
# It creates a PTY launcher wrapper that ensures proper terminal handling.
#
# CRITICAL FIXES APPLIED:
# 1. Single-instance verification before launching
# 2. Cleanup of stale/zombie processes
# 3. Better error handling
#
# Run automatically by build.sh on macOS after PyInstaller build.

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
MACOS_DIR="$PROJECT_ROOT/dist/LocalClipper.app/Contents/MacOS"
REAL_BIN="$MACOS_DIR/LocalClipper"
WRAPPER="$MACOS_DIR/LocalClipper"
LAUNCHER="$MACOS_DIR/pty_launcher"

# Verify the built app exists
if [ ! -f "$REAL_BIN" ]; then
    echo "ERROR: $REAL_BIN not found. Run build first."
    exit 1
fi

# Check if fix was already applied
if [ -f "$MACOS_DIR/LocalClipper.real" ] && [ -f "$MACOS_DIR/pty_launcher" ]; then
    echo "macOS Tk fix already applied."
    exit 0
fi

echo "Applying macOS Tk crash fix with single-instance protection..."

# =============================================================================
# CRITICAL FIX: Clean up any zombie processes from previous launches
# This prevents conflicts with stale lock files
# =============================================================================
if pgrep -f "LocalClipper.real" > /dev/null 2>&1; then
    echo "WARNING: LocalClipper processes already running. Killing stale processes..."
    pkill -f "LocalClipper.real" 2>/dev/null || true
    sleep 0.5
fi

# =============================================================================
# Compile the PTY launcher
# This wrapper ensures proper terminal handling for Tk/CustomTkinter
# =============================================================================
cc -o "$LAUNCHER" "$SCRIPT_DIR/pty_launcher.c" || {
    echo "ERROR: Failed to compile pty_launcher. Need Xcode Command Line Tools."
    exit 1
}
chmod +x "$LAUNCHER"

# =============================================================================
# Move the real binary and create wrapper script
# The wrapper provides single-instance protection
# =============================================================================
mv "$REAL_BIN" "$MACOS_DIR/LocalClipper.real"

# Create wrapper with single-instance verification
cat > "$WRAPPER" << 'WRAPPER_EOF'
#!/bin/bash
# LocalClipper macOS Launcher with Single-Instance Protection
#
# This wrapper prevents multiple app instances by checking for existing
# processes before launching the real binary.

# =============================================================================
# CRITICAL FIX: Check if another instance is already running
# Compare PIDs to ensure we're not detecting ourselves
# =============================================================================
if pgrep -f "LocalClipper.real" > /dev/null 2>&1; then
    # Get parent PID to avoid false positive
    PARENT_PID=$(ps -p $$ -o ppid= | tr -d ' ')
    LOCAL_CLIPPER_PIDS=$(pgrep -f "LocalClipper.real" | tr '\n' ' ')
    
    for PID in $LOCAL_CLIPPER_PIDS; do
        if [ "$PID" != "$PARENT_PID" ] && [ "$PID" != "$$" ]; then
            # Another instance is actually running
            echo "LocalClipper is already running." >&2
            exit 0
        fi
    done
fi

# Change to script directory and launch with PTY wrapper
dir="$(cd "$(dirname "$0")" && pwd)"
exec "$dir/pty_launcher" "$dir/LocalClipper.real" "$@"
WRAPPER_EOF

chmod +x "$WRAPPER"

echo "Done. LocalClipper uses PTY launcher with single-instance protection."
