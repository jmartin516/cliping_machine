# CustosAI Clipper — Guía de empaquetado para Whop

Pasos para empaquetar la app y distribuirla a usuarios que compran en Whop.

---

## ⚠️ Importante: El usuario final NO necesita terminal ni instalar nada

Todo está incluido en el paquete:
- **Python, Tk, CustomTkinter** → empaquetados en el ejecutable
- **FFmpeg** → se descarga automáticamente la primera vez que abre la app
- **Modelo Whisper** → se descarga automáticamente la primera vez
- **Licencia** → el usuario solo pega la key que recibe en Whop

El usuario: descarga → abre → pega licencia → espera ~2–5 min (solo primera vez) → usa la app.

---

## 1. Requisitos previos (solo para quien empaqueta)

- **macOS:** Python 3.11+ con Tk 8.6+ (instalar: `brew install python@3.11 python-tk@3.11`)
- **Windows:** Python 3.10+
- `.env` con `WHOP_API_KEY` configurado

---

## 2. Empaquetar la app

### macOS

**Opción A: Script automático (recomendado)**

```bash
cd local_clipper
chmod +x build.sh
./build.sh
```

El script verifica Python 3.11+ y Tk 8.6+ antes de construir.

**Opción B: Manual**

```bash
cd local_clipper
python3.11 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt pyinstaller
python -m PyInstaller LocalClipper.spec
```

**Crear DMG y ZIP para distribución:**
```bash
# ZIP (equivalente a Comprimir en Finder)
cd dist && zip -r ../CustosAI-Clipper-macOS.zip LocalClipper.app

# DMG (instalador tipo Mac)
hdiutil create -volname "CustosAI Clipper" -srcfolder dist/LocalClipper.app -ov -format UDZO CustosAI-Clipper-macOS.dmg
```

### Windows

**Opción A: GitHub Actions (sin tener Windows)**

1. Añade `WHOP_API_KEY` como secret: repo → Settings → Secrets and variables → Actions
2. Push a `main` o ejecuta manualmente: Actions → Build Windows → Run workflow
3. Descarga `CustosAI-Clipper-Windows.zip` desde los artifacts

**Opción B: En una máquina Windows**

```cmd
cd local_clipper
build.bat
```

O manualmente:
```cmd
python -m venv .venv
.venv\Scripts\activate.bat
pip install -r requirements.txt pyinstaller
python -m PyInstaller LocalClipper.spec
```

**Crear ZIP para distribución:**
```powershell
Compress-Archive -Path dist\LocalClipper.exe -DestinationPath CustosAI-Clipper-Windows.zip
```

**Resultado:**
- **Windows:** `dist/LocalClipper.exe` → empaquetar en `CustosAI-Clipper-Windows.zip`
- **macOS:** `dist/LocalClipper.app` → DMG o `CustosAI-Clipper-macOS.zip`

El `.env` se incluye automáticamente para validar licencias.

---

## 3. Configurar License Keys en Whop

1. Entra a tu producto en [Whop Dashboard](https://whop.com/dashboard)
2. Ve a **Settings** → **License Keys** (o similar)
3. Activa **License Keys** para el producto
4. Configura el formato si lo permite (ej. `XXXX-XXXX-XXXX-XXXX`)

Así los compradores verán su licencia en el área de miembros y podrán copiarla.

---

## 4. Subir el ejecutable a Whop

**Opción A: Descarga directa**
- Sube `LocalClipper.exe` (Windows) o `LocalClipper.app` (macOS) como archivo descargable. En macOS, el usuario puede hacer doble clic para abrir.
- En la descripción del producto indica: "Descarga el ejecutable, ábrelo, pega tu licencia y activa"

**Opción B: Dos builds (Windows + macOS)**
- Haz un build en Windows → `LocalClipper.exe`
- Haz un build en macOS → `LocalClipper.app`
- Ofrece ambos como descargas según el sistema del usuario

**Opción C: ZIP/DMG con instrucciones**
- **Windows:** `CustosAI-Clipper-Windows.zip` (contiene LocalClipper.exe)
- **macOS:** `CustosAI-Clipper-macOS.dmg` (recomendado) o `CustosAI-Clipper-macOS.zip`
- El README puede decir:
  ```
  1. Extrae el ZIP
  2. Abre CustosAI Clipper
  3. Pega tu licencia (la que recibiste al comprar)
  4. Clic en Activate
  5. Espera la descarga de componentes (primera vez)
  6. ¡Listo!
  ```

---

## 5. Flujo del usuario final

1. Compra en Whop → recibe acceso al producto
2. Entra al área de miembros → copia su licencia
3. Descarga el ejecutable desde Whop
4. Abre la app → pega la licencia → Activate
5. Primera vez: descarga FFmpeg + modelo Whisper (~2–5 min)
6. Usa el Dashboard para generar clips

---

## 6. Notas de seguridad

- El `.env` (con `WHOP_API_KEY`) va dentro del ejecutable. Es lo habitual en apps de escritorio.
- Si alguien extrae la key del binario, podría validar licencias falsas. Mitigaciones:
  - Whop tiene rate limits
  - Puedes regenerar la API key en Whop si sospechas abuso
  - El HWID limita una licencia por máquina

---

## 7. Build por plataforma

| Plataforma | Método | Salida |
|------------|--------|--------|
| Windows | GitHub Actions (sin Windows) o `build.bat` en Windows | `CustosAI-Clipper-Windows.zip` |
| macOS | `./build.sh` + comandos DMG/ZIP | `CustosAI-Clipper-macOS.dmg` o `.zip` |

**macOS:** El output es `LocalClipper.app` — una app nativa que el usuario puede abrir con doble clic, arrastrar a Aplicaciones, etc.

**Windows:** GitHub Actions compila en la nube; añade `WHOP_API_KEY` como secret para que la validación de licencias funcione.

**Importante:** En macOS debes construir con Python 3.11+ de Homebrew, no con el Python del sistema, para que Tk 8.6+ se empaquete correctamente.
