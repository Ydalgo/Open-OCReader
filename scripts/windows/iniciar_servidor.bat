@echo off
title Open OCReader - Servidor API REST
cd /d "%~dp0..\.."

set SERVER_PORT=%1
if "%SERVER_PORT%"=="" (
    if not "%OPEN_OCREADER_PORT%"=="" (
        set SERVER_PORT=%OPEN_OCREADER_PORT%
    ) else (
        set SERVER_PORT=8000
    )
)

set PYTHON_EXE=
if exist "D:\anaconda\python.exe" (
    set PYTHON_EXE=D:\anaconda\python.exe
) else (
    where python >nul 2>nul && set PYTHON_EXE=python
)

echo Iniciando Open OCReader API Server en el puerto %SERVER_PORT%...
if exist "dist\Open_OCReader_Server\Open_OCReader_Server.exe" (
    "dist\Open_OCReader_Server\Open_OCReader_Server.exe" --host 0.0.0.0 --port %SERVER_PORT%
) else (
    "%PYTHON_EXE%" src\ocr_server.py --host 0.0.0.0 --port %SERVER_PORT%
)
pause
