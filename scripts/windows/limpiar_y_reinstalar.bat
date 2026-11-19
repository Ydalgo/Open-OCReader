@echo off
title Open OCReader - Limpiar y Reinstalar
cd /d "%~dp0..\.."
echo ================================================================
echo   Open OCReader - Limpieza completa y reinstalacion limpia
echo   (Elimina build/, dist/, *.spec, caches y actualiza llama.cpp)
echo ================================================================
echo.

set PYTHON_EXE=
if exist "D:\anaconda\python.exe" (
    set PYTHON_EXE=D:\anaconda\python.exe
) else (
    where python >nul 2>nul && set PYTHON_EXE=python
)

if "%PYTHON_EXE%"=="" (
    echo [ERROR] No se encontro Python ni Anaconda.
    pause
    exit /b 1
)

"%PYTHON_EXE%" src\ocr_tool.py --clean-reinstall
echo.
echo Listo! Si quieres volver a generar el .exe, ejecuta scripts\windows\compilar.bat
pause
