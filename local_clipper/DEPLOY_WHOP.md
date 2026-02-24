# Empaquetar CustosAI Clipper para Whop

Guía para crear los archivos que subirás a Whop para que los clientes descarguen e instalen la app.

---

## 1. Requisitos previos

- **macOS**: Python 3.11+ con Tk 8.6 (`brew install python@3.11 python-tk@3.11`)
- **Windows**: Python 3.10+ desde python.org
- **.env**: Copia `.env.example` a `.env` y añade tu `WHOP_API_KEY` (para validación de licencias)

---

## 2. Construir la app

### macOS

```bash
cd local_clipper
./build.sh
```

**Salida:** `dist/LocalClipper.app`

### Windows

```bash
cd local_clipper
build.bat
```

**Salida:** `dist/LocalClipper.exe`

---

## 3. Comprimir para subir a Whop

### macOS

```bash
cd local_clipper
zip -r CustosAI-Clipper-macOS.zip dist/LocalClipper.app
```

Archivo resultante: `CustosAI-Clipper-macOS.zip`

### Windows

```bash
cd local_clipper
# Opción A: Solo el .exe (más ligero)
Compress-Archive -Path dist/LocalClipper.exe -DestinationPath CustosAI-Clipper-Windows.zip

# Opción B: Con PowerShell en cualquier sistema
zip CustosAI-Clipper-Windows.zip dist/LocalClipper.exe
```

Archivo resultante: `CustosAI-Clipper-Windows.zip`

---

## 4. Subir a Whop

1. Entra en tu producto en [Whop](https://whop.com)
2. Ve a **Files** o **Downloads**
3. Sube:
   - `CustosAI-Clipper-macOS.zip` (para usuarios Mac)
   - `CustosAI-Clipper-Windows.zip` (para usuarios Windows)
4. Puedes crear dos archivos distintos (Mac vs Windows) o uno solo con ambos ZIPs

---

## 5. Firma y notarización (macOS — para que abra sin advertencias)

Por defecto macOS bloquea apps de "desarrolladores no identificados". Hay dos opciones:

### Opción A: Sin cuenta Apple Developer (gratis)

Los usuarios pueden abrir la app así:
- **Clic derecho** en `LocalClipper.app` → **Abrir** (solo la primera vez)
- O: Preferencias del Sistema → Privacidad y seguridad → "Abrir de todas formas"

### Opción B: Con Apple Developer ($99/año) — sin advertencias

1. Cuenta en [developer.apple.com](https://developer.apple.com)
2. Crear certificado "Developer ID Application" en Keychain
3. Contraseña específica para apps en [appleid.apple.com](https://appleid.apple.com)
4. Ejecutar después del build:

```bash
export CODESIGN_IDENTITY="Developer ID Application: Tu Nombre (TEAM_ID)"
export APPLE_ID="tu@email.com"
export APP_SPECIFIC_PASSWORD="xxxx-xxxx-xxxx-xxxx"
export TEAM_ID="tu_team_id"
./scripts/sign_and_notarize.sh
```

5. Volver a crear el ZIP: `./package_for_whop.sh`

---

## 6. Instrucciones para el cliente

Incluye en la descripción del producto o en un README:

**macOS:**
1. Descargar `CustosAI-Clipper-macOS.zip`
2. Descomprimir (doble clic)
3. Mover `LocalClipper.app` a Aplicaciones (opcional)
4. Abrir: **clic derecho** en `LocalClipper.app` → **Abrir** (primera vez; macOS puede mostrar advertencia)

**Windows:**
1. Descargar `CustosAI-Clipper-Windows.zip`
2. Descomprimir
3. Ejecutar `LocalClipper.exe` (si SmartScreen muestra advertencia: "Más información" → "Ejecutar de todas formas")

---

## 7. Notas importantes

- **FFmpeg**: Se incluye en el paquete gracias a `scripts/setup_ffmpeg_bundle.py`. No hace falta instalarlo aparte.
- **Modelos Whisper**: Se descargan automáticamente la primera vez que se usa.
- **.env**: El build incluye el `.env` si existe. Para producción, no incluyas la API key en el cliente; usa un backend proxy para validar licencias.
