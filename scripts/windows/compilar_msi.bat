@echo off
title Open OCReader - Generador de Instalador Empresarial (.msi)
cd /d "%~dp0..\.."
echo ====================================================================
echo   Open OCReader - Kit de Despliegue Empresarial (.msi + offline_repo)
echo ====================================================================
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

echo Usando Python: %PYTHON_EXE%
echo.
"%PYTHON_EXE%" scripts\windows\build_msi.py --with-offline-repo %*
echo.
pause
