@echo off
title Open OCReader - Limpiar y Reinstalar
cd /d "%~dp0..\.."
echo ================================================================
echo   Open OCReader - Limpieza completa y reinstalacion limpia
echo   (Cierra procesos zombies, elimina build/, dist/, *.spec,
echo    caches y actualiza llama.cpp + librerias Python)
echo ================================================================
echo.

echo [1/2] Cerrando posibles procesos en segundo plano (Open_OCReader, llama-server)...
taskkill /F /T /IM Open_OCReader.exe >nul 2>nul
taskkill /F /T /IM Open_OCReader_Server.exe >nul 2>nul
taskkill /F /T /IM llama-server.exe >nul 2>nul
timeout /t 1 /nobreak >nul

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

echo [2/2] Ejecutando limpieza profunda y reinstalacion...
"%PYTHON_EXE%" src\ocr_tool.py --clean-reinstall
echo.
echo Listo! Si quieres volver a generar el .exe, ejecuta scripts\windows\compilar.bat
pause
