@echo off
REM CustosAI Clipper — Crea ZIP listo para subir a Whop
REM Ejecutar DESPUÉS de build.bat
REM Uso: package_for_whop.bat

cd /d "%~dp0"

echo === Empaquetando para Whop ===

if not exist "dist\LocalClipper.exe" (
    echo ERROR: No existe dist\LocalClipper.exe. Ejecuta primero: build.bat
    pause
    exit /b 1
)

echo Creando CustosAI-Clipper-Windows.zip...
powershell -Command "Compress-Archive -Path dist\LocalClipper.exe -DestinationPath CustosAI-Clipper-Windows.zip -Force"

echo.
echo === Listo ===
echo Archivo: CustosAI-Clipper-Windows.zip
echo Sube este ZIP a Whop en Files/Downloads de tu producto.
echo.
pause
