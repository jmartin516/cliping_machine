# Instrucciones para Corregir el Problema de Doble Apertura

## PROBLEMA
La app se abre 2 veces cuando se lanza desde el DMG en macOS.

## CAUSA RAÍZ
1. `argv_emulation=True` en PyInstaller causa múltiples eventos de apertura
2. El single instance lock tiene race conditions
3. El wrapper script no verifica procesos existentes

---

## PASOS PARA APLICAR LOS FIXES

### Paso 1: Instalar psutil (necesario para el lock robusto)

```bash
cd /Users/juanmartingonzalez/Documents/GitHub/cliping_machine/local_clipper
source .venv/bin/activate
pip install psutil
```

### Paso 2: Reemplazar main.py con la versión corregida

```bash
# Hacer backup del original
cp main.py main.py.backup

# Reemplazar con versión corregida
cp main_fixed.py main.py
```

### Paso 3: Reemplazar LocalClipper.spec con versión corregida

```bash
# Hacer backup
cp LocalClipper.spec LocalClipper.spec.backup

# Reemplazar
cp LocalClipper_fixed.spec LocalClipper.spec
```

### Paso 4: Reemplazar apply_macos_tk_fix.sh con versión corregida

```bash
# Hacer backup
cp scripts/apply_macos_tk_fix.sh scripts/apply_macos_tk_fix.sh.backup

# Reemplazar
cp scripts/apply_macos_tk_fix_fixed.sh scripts/apply_macos_tk_fix.sh
```

### Paso 5: Limpiar builds anteriores y reconstruir

```bash
# Limpiar completamente
rm -rf build dist __pycache__
rm -rf ~/Library/Application\ Support/CustosAI-Clipper

# Reconstruir
./build.sh
```

### Paso 6: Crear nuevo DMG y probar

```bash
# Crear DMG
hdiutil create -volname "CustosAI Clipper" -srcfolder dist/LocalClipper.app -ov -format UDZO CustosAI-Clipper-macOS-fixed.dmg

# Probar: Montar DMG y hacer doble clic en la app múltiples veces
open CustosAI-Clipper-macOS-fixed.dmg
```

---

## CAMBIOS CLAVE REALIZADOS

### 1. main.py
- ✅ `multiprocessing.set_start_method('spawn')` para macOS
- ✅ Single instance lock con verificación de proceso activo (psutil)
- ✅ Fail-closed: retorna False en errores (no True)
- ✅ Delay inicial de 50ms para prevenir race conditions

### 2. LocalClipper.spec
- ✅ `argv_emulation=False` (crítico para evitar doble apertura)
- ✅ Agregado `psutil` a hiddenimports

### 3. apply_macos_tk_fix.sh
- ✅ Verificación de procesos existentes antes de lanzar
- ✅ Limpieza de procesos zombie
- ✅ Wrapper script con single-instance protection

---

## VERIFICACIÓN

Después de aplicar los fixes, verificar:

```bash
# 1. Verificar que solo hay una instancia
pgrep -f "LocalClipper" | wc -l  # Debe mostrar 1 (o 2 si hay wrapper + real)

# 2. Intentar abrir la app múltiples veces desde el Finder
# Solo debe abrirse una ventana

# 3. Verificar que el lock funciona
ls ~/Library/Application\ Support/CustosAI-Clipper/
# Debe mostrar: .single_instance.lock .instance.pid
```

---

## SI LOS PROBLEMAS PERSISTEN

### Opción A: Desactivar completamente el pty_launcher (test)

Editar `scripts/apply_macos_tk_fix.sh` y comentar la sección del launcher:

```bash
# COMENTAR ESTO:
# cc -o "$LAUNCHER" "$SCRIPT_DIR/pty_launcher.c"
# mv "$REAL_BIN" "$MACOS_DIR/LocalClipper.real"
# cat > "$WRAPPER" << 'EOF'
# ...

# USAR EN SU LUGAR (sin pty_launcher):
# cp "$REAL_BIN" "$MACOS_DIR/LocalClipper.real"
# ln -sf "$MACOS_DIR/LocalClipper.real" "$WRAPPER"
```

### Opción B: Usar single instance basado en socket

Si el file lock no funciona, implementar un lock basado en socket TCP local (puerto fijo).

### Opción C: Verificar con PyInstaller onefile

Probar si el problema ocurre con modo `onefile` en lugar de `onedir`:

```python
# En LocalClipper.spec, cambiar a:
exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name="LocalClipper",
    console=False,
    argv_emulation=False,
)
# (sin COLLECT ni BUNDLE)
```

---

## NOTAS IMPORTANTES

1. **El fix requiere psutil**: Asegúrate de instalarlo antes de construir
2. **argv_emulation=False**: Esto es crítico, no revertir a True
3. **Testing**: Probar en macOS limpio (sin procesos previos de LocalClipper)
4. **DMG**: Siempre crear DMG nuevo, no reutilizar uno viejo

---

## ROLLBACK (si es necesario)

```bash
cd /Users/juanmartingonzalez/Documents/GitHub/cliping_machine/local_clipper
cp main.py.backup main.py
cp LocalClipper.spec.backup LocalClipper.spec
cp scripts/apply_macos_tk_fix.sh.backup scripts/apply_macos_tk_fix.sh
rm -rf build dist
./build.sh
```
