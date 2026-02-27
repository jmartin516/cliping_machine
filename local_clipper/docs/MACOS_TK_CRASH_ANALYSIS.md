# Análisis del crash de LocalClipper en macOS

**Fecha:** 26 Feb 2026  
**Sistema:** macOS 14.1.2 (Sonoma), ARM64 (Mac14,7)

---

## Resumen del diagnóstico

| Check | Resultado |
|-------|-----------|
| AppKit debug menu (`_NS_4445425547`) | No activado |
| Python en venv | 3.11.14 (Homebrew/Clang) |
| Tk/Tcl en venv | 8.6 |
| Tk en bundle | **8.6.17** (libtk8.6.dylib) |
| App en /Applications | ✅ Presente |
| Ejecución desde Terminal | No crashea en 3s (sandbox) |

---

## Causa del crash

El crash ocurre durante la **inicialización de Tk**, en la cadena:

```
Tk_CreateConsoleWindow → TkpSetMainMenubar → NSMenuItem initWithTitle
→ NSCalendarDate initWithCoder → NSAssertionHandler (assertion failed)
```

- **Tk 8.6.17** crea una ventana de consola interna al iniciar.
- Al configurar el menú nativo de macOS para esa ventana, usa APIs deprecadas (`NSCalendarDate`).
- En macOS 14+, esa ruta falla con una aserción y provoca `SIGABRT`.

**Diferencia clave:** Al lanzar desde **Terminal** (con TTY), Tk puede omitir o manejar distinto la creación de la consola. Al lanzar desde **Finder** (sin TTY), intenta crearla y se produce el crash.

---

## Solución implementada

Se añade un **wrapper script** que ejecuta el binario con un pseudo-TTY (`script -q`), de modo que Tk detecte un terminal y no intente crear la ventana de consola problemática.

El build aplica este wrapper en un paso post-PyInstaller para macOS.

---

## Alternativas si el fix no funciona

1. **Actualizar Tcl-Tk:** `brew upgrade tcl-tk` y reconstruir con ese Python.
2. **Probar Python de python.org:** A veces usa un Tcl/Tk compilado distinto.
3. **Cambiar de framework:** Migrar a PyQt/wxPython si Tk sigue fallando.
