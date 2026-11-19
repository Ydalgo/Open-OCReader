@echo off
cd /d "%~dp0..\.."

if exist "dist\Open_OCReader\Open_OCReader.exe" (
    start "" "dist\Open_OCReader\Open_OCReader.exe"
) else if exist "D:\anaconda\pythonw.exe" (
    start "" "D:\anaconda\pythonw.exe" "src\Open_OCReader.pyw"
) else (
    start "" pythonw "src\Open_OCReader.pyw"
)
