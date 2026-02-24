#!/usr/bin/env bash
# CustosAI Clipper — Firma y notarización para macOS
# Para que los usuarios puedan abrir la app sin "desarrollador no identificado"
#
# OPCIONES:
# 1) Ad-hoc (gratis): CODESIGN_IDENTITY="" ./sign_and_notarize.sh
#    - Firma básica. En macOS recientes puede seguir mostrando advertencia.
#    - Los usuarios pueden: clic derecho → Abrir
#
# 2) Developer ID (Apple Developer $99/año): Necesario para distribución sin advertencias
#    export CODESIGN_IDENTITY="Developer ID Application: Tu Nombre (TEAM_ID)"
#    export APPLE_ID="tu@email.com"
#    export APP_SPECIFIC_PASSWORD="xxxx-xxxx-xxxx-xxxx"  # Crea en appleid.apple.com
#    ./sign_and_notarize.sh

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
APP_PATH="$PROJECT_ROOT/dist/LocalClipper.app"

if [ ! -d "$APP_PATH" ]; then
    echo "ERROR: No existe $APP_PATH. Ejecuta ./build.sh primero."
    exit 1
fi

echo "=== Firma de LocalClipper.app ==="

# Firma con Developer ID si está configurado, si no ad-hoc
IDENTITY="${CODESIGN_IDENTITY:--}"
echo "Firmando con identidad: $IDENTITY"

# Firma: Developer ID usa --options runtime (requerido para notarización)
# Ad-hoc ("-") no puede usar runtime, usamos firma básica
if [ "$IDENTITY" = "-" ]; then
    codesign --force --deep --sign - "$APP_PATH"
else
    codesign --force --deep --sign "$IDENTITY" \
        --options runtime \
        --timestamp \
        "$APP_PATH"
fi

echo "Firma completada."
echo ""

# Notarización (solo si tenemos credenciales Apple Developer)
if [ -n "$APPLE_ID" ] && [ -n "$APP_SPECIFIC_PASSWORD" ] && [ "$IDENTITY" != "-" ]; then
    echo "=== Notarización (envío a Apple) ==="
    
    # Crear ZIP para notarización
    NOTARIZE_ZIP="$PROJECT_ROOT/notarize_submit.zip"
    rm -f "$NOTARIZE_ZIP"
    ditto -c -k --keepParent "$APP_PATH" "$NOTARIZE_ZIP"
    
    # Enviar a Apple
    xcrun notarytool submit "$NOTARIZE_ZIP" \
        --apple-id "$APPLE_ID" \
        --password "$APP_SPECIFIC_PASSWORD" \
        --team-id "${TEAM_ID:-}" \
        --wait
    
    # Grapar el ticket de notarización
    xcrun stapler staple "$APP_PATH"
    
    rm -f "$NOTARIZE_ZIP"
    echo "Notarización completada. La app ya no mostrará advertencias."
else
    echo "Para notarización (eliminar advertencia en macOS):"
    echo "  1. Cuenta Apple Developer (\$99/año)"
    echo "  2. export CODESIGN_IDENTITY=\"Developer ID Application: Tu Nombre (TEAM_ID)\""
    echo "  3. export APPLE_ID=\"tu@email.com\""
    echo "  4. export APP_SPECIFIC_PASSWORD=\"xxxx\"  # appleid.apple.com → App-Specific Passwords"
    echo "  5. Ejecuta este script de nuevo"
    echo ""
    echo "Sin notarización, los usuarios pueden abrir con: clic derecho → Abrir"
fi

echo ""
echo "=== Listo ==="
