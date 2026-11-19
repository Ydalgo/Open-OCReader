@echo off
title Compilando Open OCReader
chcp 65001 > nul
echo ================================================================
echo   Compilador de Open OCReader a archivo ejecutable (.exe)
echo ================================================================
echo.

where python >nul 2>nul
if %errorlevel% neq 0 (
    echo [ERROR] No se ha encontrado Python en el sistema.
    echo Asegúrate de tener Python o Anaconda en el PATH.
    pause
    exit /b 1
)

python build_exe.py %*

echo.
echo Presiona cualquier tecla para cerrar esta ventana...
pause > nul
