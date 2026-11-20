@echo off
chcp 65001 >nul
cd /d "%~dp0..\.."
echo ============================================================
echo   Open OCReader - Instalacion 100%% Offline (sin Internet)
echo ============================================================

set "WHEELS_DIR=%~dp0..\..\offline_repo\wheels"
if not exist "%WHEELS_DIR%" (
    echo [ERROR] No se encontro la carpeta offline_repo\wheels.
    echo Ejecuta primero en un PC con Internet:
    echo   python scripts\windows\prepare_offline_repo.py --output offline_repo
    pause
    exit /b 1
)

set "PY_EXE=python"
if exist "D:\anaconda\python.exe" set "PY_EXE=D:\anaconda\python.exe"

echo [1/2] Instalando paquetes Python (incluyendo PySide6 / Qt 6) desde wheels locales...
"%PY_EXE%" -m pip install --no-index --find-links="%WHEELS_DIR%" -r requirements.txt
if errorlevel 1 (
    echo [ERROR] Fallo la instalacion offline de paquetes Python.
    pause
    exit /b 1
)

echo [2/2] Todo listo. Iniciando Open OCReader...
"%PY_EXE%" src\ocr_tool.py
