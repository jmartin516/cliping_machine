#!/usr/bin/env bash
# CustosAI Clipper — Crea ZIPs listos para subir a Whop
# Ejecutar DESPUÉS de ./build.sh
# Uso: ./package_for_whop.sh

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

echo "=== Empaquetando para Whop ==="

if [ ! -d "dist" ]; then
    echo "ERROR: No existe dist/. Ejecuta primero: ./build.sh"
    exit 1
fi

# macOS
if [ -d "dist/LocalClipper.app" ]; then
    echo "Creando CustosAI-Clipper-macOS.zip..."
    zip -r -y CustosAI-Clipper-macOS.zip dist/LocalClipper.app
    echo "  → CustosAI-Clipper-macOS.zip"
fi

# Windows
if [ -f "dist/LocalClipper.exe" ]; then
    echo "Creando CustosAI-Clipper-Windows.zip..."
    zip -y CustosAI-Clipper-Windows.zip dist/LocalClipper.exe
    echo "  → CustosAI-Clipper-Windows.zip"
fi

echo ""
echo "=== Listo ==="
echo "Sube los ZIP a Whop en Files/Downloads de tu producto."
