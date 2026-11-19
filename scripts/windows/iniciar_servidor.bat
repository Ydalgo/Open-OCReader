@echo off
title Open OCReader - Servidor API REST
cd /d "%~dp0..\.."

set PYTHON_EXE=
if exist "D:\anaconda\python.exe" (
    set PYTHON_EXE=D:\anaconda\python.exe
) else (
    where python >nul 2>nul && set PYTHON_EXE=python
)

if exist "dist\Open_OCReader_Server\Open_OCReader_Server.exe" (
    "dist\Open_OCReader_Server\Open_OCReader_Server.exe" --host 0.0.0.0 --port 8000
) else (
    "%PYTHON_EXE%" src\ocr_server.py --host 0.0.0.0 --port 8000
)
pause
