@echo off
title Compilando Open OCReader
echo ================================================================
echo   Compilador de Open OCReader a archivo ejecutable (.exe)
echo ================================================================
echo.

set PYTHON_EXE=

if exist "D:\anaconda\python.exe" (
    set PYTHON_EXE=D:\anaconda\python.exe
) else (
    where python >nul 2>nul
    if %errorlevel% equ 0 (
        set PYTHON_EXE=python
    )
)

if "%PYTHON_EXE%"=="" (
    echo [ERROR] No se ha encontrado Python ni Anaconda en el sistema.
    pause
    exit /b 1
)

echo Usando Python: %PYTHON_EXE%
echo.
"%PYTHON_EXE%" build_exe.py %*

echo.
echo Presiona cualquier tecla para cerrar esta ventana...
pause > nul
